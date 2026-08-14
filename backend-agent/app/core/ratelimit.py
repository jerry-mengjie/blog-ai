"""提问限流: Redis 固定窗口计数, 无 Redis 时退化为进程内滑动窗口。

为什么用 Redis: 本服务可以多副本部署, 纯进程内限流会让实际上限变成
「配置值 × 副本数」, 起不到保护大模型配额的作用。

Redis 方案(经典固定窗口):
    INCR   ratelimit:ask:{ip}:{当前分钟}
    EXPIRE 同 key 70 秒 NX(略大于窗口, 且只在首次设置, 避免窗口被反复续期)
两条命令用 pipeline 一次发出, 每次请求固定一个 RTT。
"""

# 导入时间工具
import time
# 导入日志
import logging
# 导入 defaultdict/deque 存储进程内回退窗口
from collections import defaultdict, deque

# 导入全局配置
from app.core.config import settings
# 导入 Redis 客户端
from app.core.redis import get_redis

# 模块日志器
logger = logging.getLogger(__name__)

# 限流 key 前缀
_PREFIX = "ratelimit:ask:"
# 窗口长度(秒)
_WINDOW = 60
# 进程内回退窗口: IP → 最近请求时间戳队列
_local_buckets: dict[str, deque] = defaultdict(deque)
# 回退窗口的 IP 上限, 超过后清理已离开窗口的 IP, 避免长期运行内存只增不减
_LOCAL_MAX_IPS = 10000


# 内部工具: 清理窗口内已无记录的 IP(仅在桶数量超阈值时触发)
def _sweep_local(now: float) -> None:
    # 未超阈值不做无用功
    if len(_local_buckets) <= _LOCAL_MAX_IPS:
        # 直接返回
        return
    # 找出窗口内最后一次请求也已过期的 IP
    stale = [
        ip
        for ip, bucket in _local_buckets.items()
        if not bucket or now - bucket[-1] > _WINDOW
    ]
    # 逐个移除
    for ip in stale:
        # 删除该 IP 的桶
        _local_buckets.pop(ip, None)


# 进程内滑动窗口判定(仅在 Redis 不可用时使用)
def _allow_local(ip: str, limit: int) -> bool:
    # 当前单调时间
    now = time.monotonic()
    # 桶过多时先清理
    _sweep_local(now)
    # 取出该 IP 的时间戳队列
    bucket = _local_buckets[ip]
    # 移除窗口之前的旧记录
    while bucket and now - bucket[0] > _WINDOW:
        # 弹出过期时间戳
        bucket.popleft()
    # 窗口内已达上限则拒绝
    if len(bucket) >= limit:
        # 拒绝
        return False
    # 记录本次请求时间
    bucket.append(now)
    # 允许
    return True


# 判断某 IP 本次提问是否放行
async def allow_ask(ip: str) -> bool:
    # 上限取配置值; 非正数视为不限流
    limit = settings.AI_RATE_LIMIT
    # 关闭限流
    if limit <= 0:
        # 直通
        return True
    # 取 Redis 客户端
    client = get_redis()
    # 无 Redis 时用进程内窗口兜底
    if client is None:
        # 单机限流
        return _allow_local(ip, limit)
    # Redis 异常不应让用户无法提问, 失败时放行(fail-open)
    try:
        # 窗口 key 带上当前分钟, 到点自然切换
        key = f"{_PREFIX}{ip}:{int(time.time()) // _WINDOW}"
        # 计数与设 TTL 合并为一次往返(无需事务: 两条命令都是幂等的写)
        async with client.pipeline(transaction=False) as pipe:
            # 自增计数
            pipe.incr(key)
            # NX 只在无 TTL 时设置, 保证窗口不会被后续请求续期
            pipe.expire(key, _WINDOW + 10, nx=True)
            # 一次发送两条命令
            count, _ = await pipe.execute()
        # 未超上限则放行
        return int(count) <= limit
    except Exception:
        # 记录后放行, 保证可用性优先
        logger.warning("限流计数失败, 本次请求放行", exc_info=True)
        # fail-open
        return True
