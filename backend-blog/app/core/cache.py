"""经典多级缓存: L1 进程内存 + L2 Redis。

读路径: L1 → L2 → 回源 factory → 回填 L2/L1
写失效: 清 L1 + 删 L2(SCAN 匹配前缀)
防击穿: 同 key 单飞(asyncio.Lock), 避免缓存击穿打穿 MySQL
"""

# 导入异步锁与时间工具
import asyncio
import time
# 导入 JSON 编解码(L2 存字符串)
import json
# 导入类型注解
from collections.abc import Awaitable, Callable
from typing import Any

# 导入 Redis 客户端获取函数
from app.core.redis import get_redis


# 多级缓存门面: 一个实例可服务一类业务 key
class MultiLevelCache:
    # 初始化: TTL、L1 容量、可选 key 前缀
    def __init__(self, ttl_seconds: int, l1_maxsize: int = 256, prefix: str = "") -> None:
        # L2/L1 统一过期秒数
        self._ttl = max(1, int(ttl_seconds))
        # L1 最大条目数, 超出则淘汰最旧
        self._l1_maxsize = max(1, int(l1_maxsize))
        # key 业务前缀, 便于 SCAN 批量失效
        self._prefix = prefix
        # L1: key → (过期时间戳, 值)
        self._l1: dict[str, tuple[float, Any]] = {}
        # 单飞锁表: 同 key 并发只回源一次
        self._locks: dict[str, asyncio.Lock] = {}
        # 保护 locks 字典本身的互斥
        self._locks_guard = asyncio.Lock()

    # 拼完整缓存 key
    def make_key(self, *parts: object) -> str:
        # 前缀 + 冒号拼接各段
        body = ":".join(str(p) for p in parts)
        # 有前缀则带上
        return f"{self._prefix}{body}" if self._prefix else body

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

    # 删除单个 L1 key
    def _l1_delete(self, key: str) -> None:
        # 弹出即可
        self._l1.pop(key, None)

    # 清空全部 L1
    def _l1_clear(self) -> None:
        # 清空字典
        self._l1.clear()

    # 获取(或创建)某 key 的单飞锁
    async def _lock_for(self, key: str) -> asyncio.Lock:
        # 快路径: 已有锁
        lock = self._locks.get(key)
        # 已有则直接返回
        if lock is not None:
            # 复用
            return lock
        # 慢路径: 加全局锁再建
        async with self._locks_guard:
            # 双重检查
            lock = self._locks.get(key)
            # 仍无则新建
            if lock is None:
                # 创建锁并登记
                lock = asyncio.Lock()
                # 写入表
                self._locks[key] = lock
            # 返回锁
            return lock

    # L2 读: Redis GET + JSON 反序列化
    async def _l2_get(self, key: str) -> Any | None:
        # 取客户端
        client = get_redis()
        # 未启用 Redis
        if client is None:
            # L2 miss
            return None
        # 读字符串
        raw = await client.get(key)
        # 空则 miss
        if raw is None:
            # 未命中
            return None
        # JSON 反序列化; 损坏则当 miss
        try:
            # 解析
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            # 坏数据删掉
            await client.delete(key)
            # 视为未命中
            return None

    # L2 写: SET key value EX ttl
    async def _l2_set(self, key: str, value: Any) -> None:
        # 取客户端
        client = get_redis()
        # 未启用则跳过
        if client is None:
            # 无 L2
            return
        # 序列化为 JSON 字符串
        raw = json.dumps(value, ensure_ascii=False, default=str)
        # 带过期写入(经典 SET EX)
        await client.set(key, raw, ex=self._ttl)

    # L2 按前缀批量删除(SCAN + UNLINK/DELETE)
    async def _l2_delete_prefix(self, match: str) -> None:
        # 取客户端
        client = get_redis()
        # 未启用则跳过
        if client is None:
            # 无操作
            return
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
            # 真正回源(通常打 MySQL)
            value = await factory()
            # 回填 L2
            await self._l2_set(key, value)
            # 回填 L1
            self._l1_set(key, value)
            # 返回新值
            return value

    # 删除单个 key(L1 + L2)
    async def delete(self, key: str) -> None:
        # 清本地
        self._l1_delete(key)
        # 取 Redis
        client = get_redis()
        # 有 Redis 则删远程
        if client is not None:
            # 删除远程键
            await client.delete(key)

    # 按前缀失效: 清全部 L1 + SCAN 删 L2
    async def invalidate_prefix(self, match: str | None = None) -> None:
        # 默认匹配本实例前缀下全部
        pattern = match if match is not None else f"{self._prefix}*"
        # 本地全清(前缀实例通常专用于一类业务)
        self._l1_clear()
        # 远程按模式删
        await self._l2_delete_prefix(pattern)
