"""Redis 异步客户端: ConnectionPool + redis.asyncio(经典方案)。

性能要点:
1. 进程级单例连接池, 避免每次请求新建 TCP
2. health_check_interval 探测僵死连接, 配合 socket 超时快速失败
3. decode_responses=True, 业务层直接用 str/JSON, 少一次编解码
4. REDIS_HOST 为空则关闭 Redis, 检索退化为每次实时计算
"""

# 导入异步 Redis 客户端与连接池
from redis.asyncio import ConnectionPool, Redis

# 导入全局配置
from app.core.config import settings

# 模块级连接池单例(进程内复用)
_pool: ConnectionPool | None = None
# 模块级 Redis 客户端单例
_client: Redis | None = None


# 是否启用 Redis(主机非空即启用)
def redis_enabled() -> bool:
    # 主机配置去空白后非空则认为启用
    return bool(settings.REDIS_HOST and settings.REDIS_HOST.strip())


# 获取全局 Redis 客户端; 未启用时返回 None
def get_redis() -> Redis | None:
    # 声明使用模块级变量
    global _pool, _client
    # 未启用直接返回
    if not redis_enabled():
        # 上层跳过缓存
        return None
    # 首次调用时建池与客户端
    if _client is None:
        # 创建连接池: 经典 ConnectionPool 参数调优
        _pool = ConnectionPool(
            host=settings.REDIS_HOST.strip(),                       # Redis 主机
            port=settings.REDIS_PORT,                               # 端口
            password=settings.REDIS_PASSWORD or None,               # 空串视为无密码
            db=settings.REDIS_DB,                                   # 逻辑库编号
            max_connections=settings.REDIS_MAX_CONNECTIONS,         # 池上限, 防打满
            decode_responses=True,                                  # 自动解码为 str
            socket_connect_timeout=settings.REDIS_SOCKET_TIMEOUT,   # 建连超时
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,           # 读写超时
            health_check_interval=30,                               # 空闲连接健康检查(秒)
        )
        # 基于池创建异步客户端
        _client = Redis(connection_pool=_pool)
    # 返回单例
    return _client


# 应用关闭时释放连接池
async def close_redis() -> None:
    # 声明使用模块级变量
    global _pool, _client
    # 已创建客户端则关闭
    if _client is not None:
        # 关闭客户端(归还连接)
        await _client.aclose()
        # 置空便于重启后重建
        _client = None
    # 已创建池则断开
    if _pool is not None:
        # 断开全部底层连接
        await _pool.disconnect()
        # 置空
        _pool = None
