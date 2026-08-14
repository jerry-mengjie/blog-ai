"""检索结果缓存: 仅用 Redis 单层, 不做进程内 L1。

为什么这里不要 L1:
检索 key 由「问题文本 + 过滤条件」哈希而来, 是典型长尾分布, 进程内 L1 命中率极低,
反而占内存并在多 Worker 间产生不一致。真正值钱的是跨 Worker 共享的 L2:
一次命中就省下 1 次向量化 HTTP 调用 + 1 次 Milvus 检索。

失效策略: TTL 过期 + 写路径整批失效。
key 是「问题 + 过滤条件」的哈希, 无法反查出「哪些 key 引用了某篇文章」, 而文章被删除
或下架后继续把它的片段喂给模型是不可接受的(会引用读者已经看不到的内容)。索引写入是
低频路径, 因此在其末尾按前缀清空整批检索缓存 —— 用一次 SCAN 换取「不会引用陈旧内容」。
"""

# 导入 JSON 编解码(Redis 存字符串)
import json
# 导入哈希算法(把长问题压成定长 key)
import hashlib
# 导入日志
import logging
# 导入类型注解
from collections.abc import Awaitable, Callable
from typing import Any

# 导入全局配置
from app.core.config import settings
# 导入 Redis 客户端获取函数
from app.core.redis import get_redis

# 模块日志器
logger = logging.getLogger(__name__)

# 缓存 key 前缀(版本号便于结构调整后整批作废)
_PREFIX = "rag:retrieve:v1:"


# 由检索参数生成定长缓存 key: 参数规范化后取 SHA1
def make_key(payload: dict[str, Any]) -> str:
    # sort_keys 保证同参数不同书写顺序命中同一 key
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    # SHA1 足够区分且比原文短得多(Redis key 越短内存越省)
    return f"{_PREFIX}{hashlib.sha1(raw.encode('utf-8')).hexdigest()}"


# 读缓存, 未启用/未命中/数据损坏均返回 None
async def get(key: str) -> Any | None:
    # 取客户端
    client = get_redis()
    # 未启用 Redis 直接 miss
    if client is None:
        # 无缓存
        return None
    # Redis 抖动不能影响主流程, 异常按 miss 处理
    try:
        # 读字符串
        raw = await client.get(key)
        # 空则 miss
        if raw is None:
            # 未命中
            return None
        # 反序列化
        return json.loads(raw)
    except Exception:
        # 记录一次告警后走回源
        logger.warning("检索缓存读取失败, 已回源", exc_info=True)
        # 视为未命中
        return None


# 写缓存(SET key value EX ttl), 失败静默
async def set(key: str, value: Any) -> None:
    # 取客户端
    client = get_redis()
    # 未启用则跳过
    if client is None:
        # 无缓存
        return
    # 写失败不影响已算好的结果返回
    try:
        # 序列化后带过期写入
        await client.set(
            key,
            json.dumps(value, ensure_ascii=False, default=str),
            ex=settings.RAG_RETRIEVE_CACHE_TTL,
        )
    except Exception:
        # 仅告警
        logger.warning("检索缓存写入失败", exc_info=True)


# 清空全部检索缓存(索引写入后调用, 保证不再返回已变更/已删除文章的片段)
async def invalidate_all() -> None:
    # 取客户端
    client = get_redis()
    # 未启用则无需处理
    if client is None:
        # 无缓存
        return
    # 失效失败时退化为 TTL 自然过期, 不影响索引结果
    try:
        # 批量收集待删 key, 减少往返次数
        batch: list[str] = []
        # SCAN 渐进式迭代, 不阻塞 Redis(KEYS 会阻塞)
        async for key in client.scan_iter(match=f"{_PREFIX}*", count=100):
            # 加入批次
            batch.append(key)
            # 满 100 删一次
            if len(batch) >= 100:
                # UNLINK 异步回收内存
                await client.unlink(*batch)
                # 清空批次
                batch.clear()
        # 尾批删除
        if batch:
            # 删剩余
            await client.unlink(*batch)
    except Exception:
        # 仅告警
        logger.warning("检索缓存失效失败, 将由 TTL 自然过期", exc_info=True)


# 读缓存, miss 时执行 factory 并回填
async def get_or_set(key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
    # 先查缓存
    cached = await get(key)
    # 命中直接返回
    if cached is not None:
        # 省下向量化与检索
        return cached
    # 回源计算
    value = await factory()
    # 回填缓存
    await set(key, value)
    # 返回新值
    return value
