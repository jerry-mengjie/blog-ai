"""经典多级缓存: L1 进程内存 + L2 Redis。

读路径: L1 → L2 → 回源 factory → 回填 L2/L1
写失效: 清 L1 + 删 L2(SCAN 匹配前缀)
防击穿: 同 key 单飞(asyncio.Lock), 避免热点 key 同时打穿下游
防雪崩: L2 TTL 附加随机抖动, 避免同一批 key 在同一秒集体过期

推荐结果是典型的「少量热点 key + 高频读」: 匿名请求共享一个 key,
登录用户各自一个 key, L1 命中率很高, 因此这里 L1/L2 都值得保留。
"""

# 导入异步锁与时间工具
import asyncio
import time
# 导入 JSON 编解码(L2 存字符串)
import json
# 导入随机数(TTL 抖动)
import random
# 导入日志
import logging
# 导入类型注解
from collections.abc import Awaitable, Callable
from typing import Any

# 导入 Redis 客户端获取函数
from app.core.redis import get_redis

# 模块日志器
logger = logging.getLogger(__name__)

# L2 TTL 抖动比例上限: 实际 TTL 取 [ttl, ttl * 1.2) 之间的随机值
_JITTER_RATIO = 0.2


# 多级缓存门面: 一个实例服务一类业务 key
class MultiLevelCache:
    # 初始化: TTL、L1 容量、可选 key 前缀
    def __init__(self, ttl_seconds: int, l1_maxsize: int = 256, prefix: str = "") -> None:
        # L2/L1 基准过期秒数
        self._ttl = max(1, int(ttl_seconds))
        # L1 最大条目数, 超出则淘汰最旧
        self._l1_maxsize = max(1, int(l1_maxsize))
        # key 业务前缀, 便于 SCAN 批量失效
        self._prefix = prefix
        # L1: key → (过期时间戳, 值)
        self._l1: dict[str, tuple[float, Any]] = {}
        # 单飞锁表: 同 key 并发只回源一次
        self._locks: dict[str, asyncio.Lock] = {}
        # 锁引用计数: 归零即回收, 防止 user 维度 key 让锁表无限增长
        self._lock_refs: dict[str, int] = {}
        # 保护 locks 字典本身的互斥
        self._locks_guard = asyncio.Lock()

    # 拼完整缓存 key
    def make_key(self, *parts: object) -> str:
        # 前缀 + 冒号拼接各段
        body = ":".join(str(p) for p in parts)
        # 有前缀则带上
        return f"{self._prefix}{body}" if self._prefix else body

    # 计算带抖动的 TTL, 打散过期时刻防止缓存雪崩
    def _jittered_ttl(self) -> int:
        # 在基准 TTL 上叠加 0~20% 的随机增量
        return int(self._ttl * (1 + random.random() * _JITTER_RATIO))

    # 读取 L1: 命中且未过期返回值, 否则 None
    def _l1_get(self, key: str) -> Any | None:
        # 取出条目
        item = self._l1.get(key)
        # 不存在
        if item is None:
            # 未命中
            return None
        # 解包过期时间与值
        expire_at, value = item
        # 已过期则删除并 miss
        if expire_at <= time.monotonic():
            # 清理过期项
            self._l1.pop(key, None)
            # 视为未命中
            return None
        # 命中返回
        return value

    # 写入 L1, 并做简易容量淘汰(删最早插入的键)
    def _l1_set(self, key: str, value: Any) -> None:
        # 容量满且是新 key 时淘汰一个最旧
        if key not in self._l1 and len(self._l1) >= self._l1_maxsize:
            # dict 保序(Py3.7+), 弹出第一个
            oldest = next(iter(self._l1))
            # 删除最旧
            self._l1.pop(oldest, None)
        # 写入带过期时间的条目
        self._l1[key] = (time.monotonic() + self._ttl, value)

    # 清空全部 L1
    def _l1_clear(self) -> None:
        # 清空字典
        self._l1.clear()

    # 获取(或创建)某 key 的单飞锁, 同时登记一次引用
    async def _lock_for(self, key: str) -> asyncio.Lock:
        # 取锁与改引用计数必须是同一个原子步骤, 因此统一走 guard
        async with self._locks_guard:
            # 复用同 key 的现有锁, 不存在则新建
            lock = self._locks.get(key)
            # 首个等待者负责创建
            if lock is None:
                # 创建锁并登记
                lock = asyncio.Lock()
                # 写入锁表
                self._locks[key] = lock
            # 引用 +1
            self._lock_refs[key] = self._lock_refs.get(key, 0) + 1
            # 返回锁
            return lock

    # 释放引用: 归零时把锁从表里摘除(同步执行, 事件循环内不会被打断)
    def _release_lock(self, key: str, lock: asyncio.Lock) -> None:
        # 引用 -1
        refs = self._lock_refs.get(key, 0) - 1
        # 仍有其他协程在用则只更新计数
        if refs > 0:
            # 保留锁供其复用
            self._lock_refs[key] = refs
            # 结束
            return
        # 归零, 清理计数
        self._lock_refs.pop(key, None)
        # 仅当表中仍是同一把锁时摘除, 避免误删后来新建的锁
        if self._locks.get(key) is lock:
            # 摘除
            self._locks.pop(key, None)

    # L2 读: Redis GET + JSON 反序列化
    async def _l2_get(self, key: str) -> Any | None:
        # 取客户端
        client = get_redis()
        # 未启用 Redis
        if client is None:
            # L2 miss
            return None
        # Redis 抖动不能影响主流程
        try:
            # 读字符串
            raw = await client.get(key)
            # 空则 miss
            if raw is None:
                # 未命中
                return None
            # JSON 反序列化
            return json.loads(raw)
        except json.JSONDecodeError:
            # 坏数据直接删掉, 下次重新回源
            await client.delete(key)
            # 视为未命中
            return None
        except Exception:
            # Redis 不可用时降级为仅 L1 + 回源
            logger.warning("推荐缓存 L2 读取失败, 已回源", exc_info=True)
            # 视为未命中
            return None

    # L2 写: SET key value EX ttl(带抖动)
    async def _l2_set(self, key: str, value: Any) -> None:
        # 取客户端
        client = get_redis()
        # 未启用则跳过
        if client is None:
            # 无 L2
            return
        # 写失败不影响已算好的结果返回
        try:
            # 序列化为 JSON 字符串并带过期写入
            await client.set(
                key,
                json.dumps(value, ensure_ascii=False, default=str),
                ex=self._jittered_ttl(),
            )
        except Exception:
            # 仅告警
            logger.warning("推荐缓存 L2 写入失败", exc_info=True)

    # L2 按前缀批量删除(SCAN + UNLINK)
    async def _l2_delete_prefix(self, match: str) -> None:
        # 取客户端
        client = get_redis()
        # 未启用则跳过
        if client is None:
            # 无操作
            return
        # 失效失败时靠 TTL 自然收敛, 不抛给调用方
        try:
            # 收集待删 key, 批量删除减少 RTT
            batch: list[str] = []
            # SCAN 迭代匹配键(不阻塞 Redis)
            async for key in client.scan_iter(match=match, count=100):
                # 加入批次
                batch.append(key)
                # 满 100 刷一次
                if len(batch) >= 100:
                    # 非阻塞删除
                    await client.unlink(*batch)
                    # 清空批次
                    batch.clear()
            # 尾批删除
            if batch:
                # 删剩余
                await client.unlink(*batch)
        except Exception:
            # 仅告警
            logger.warning("推荐缓存 L2 失效失败, 将由 TTL 自然过期", exc_info=True)

    # 核心 API: 读缓存或回源并回填
    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Awaitable[Any]],
    ) -> Any:
        # 1) L1 快路径
        hit = self._l1_get(key)
        # L1 命中直接返回
        if hit is not None:
            # 零网络开销
            return hit
        # 2) L2 快路径(无锁先试, 多数读可避免抢锁)
        remote = await self._l2_get(key)
        # L2 命中则回填 L1
        if remote is not None:
            # 晋升到本地
            self._l1_set(key, remote)
            # 返回
            return remote
        # 3) 单飞回源, 防缓存击穿
        lock = await self._lock_for(key)
        # 回源结束后无论成败都要回收锁, 否则 user 维度 key 会让锁表无限增长
        try:
            # 抢锁后双重检查
            async with lock:
                # 再查 L1
                hit = self._l1_get(key)
                # 其他协程已回填
                if hit is not None:
                    # 直接返回
                    return hit
                # 再查 L2
                remote = await self._l2_get(key)
                # L2 已有
                if remote is not None:
                    # 回填 L1
                    self._l1_set(key, remote)
                    # 返回
                    return remote
                # 真正回源(执行 LangGraph 图)
                value = await factory()
                # 回填 L2
                await self._l2_set(key, value)
                # 回填 L1
                self._l1_set(key, value)
                # 返回新值
                return value
        finally:
            # 只有确认没人持有/等待时才摘除, 避免误删仍在使用的锁
            self._release_lock(key, lock)

    # 按前缀失效: 清全部 L1 + SCAN 删 L2
    async def invalidate_prefix(self, match: str | None = None) -> None:
        # 默认匹配本实例前缀下全部
        pattern = match if match is not None else f"{self._prefix}*"
        # 本地全清(前缀实例专用于一类业务)
        self._l1_clear()
        # 远程按模式删
        await self._l2_delete_prefix(pattern)
