"""服务间 HTTP 客户端: 统一连接池与令牌。

本服务对外只发出「通知类」调用(同步索引、失效缓存), 全部运行在响应返回后的
BackgroundTasks 里, 因此:
1. 失败只记日志, 绝不反向影响已经提交的业务事务
2. 超时设得较短, 下游卡住时快速放弃而不是占着后台任务不放

性能要点: 每个下游服务一个 AsyncClient 单例, 复用 TCP 与 keep-alive。
"""

# 导入日志
import logging

# 导入异步 HTTP 客户端
import httpx

# 导入全局配置
from app.core.config import settings

# 模块日志器
logger = logging.getLogger(__name__)

# 服务名 → 客户端 的单例表
_clients: dict[str, httpx.AsyncClient] = {}


# 获取(或创建)某个下游服务的客户端
def get_client(name: str, base_url: str) -> httpx.AsyncClient:
    # 首次使用时创建
    if name not in _clients:
        # 连接池与超时按配置设定
        _clients[name] = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=settings.SERVICE_HTTP_TIMEOUT,
            limits=httpx.Limits(
                max_connections=settings.SERVICE_HTTP_MAX_CONNECTIONS,
                max_keepalive_connections=settings.SERVICE_HTTP_MAX_CONNECTIONS // 2,
            ),
            # 服务间调用令牌, 由下游的内部路由校验
            headers={"X-Internal-Token": settings.INTERNAL_TOKEN},
        )
    # 返回单例
    return _clients[name]


# 应用关闭时释放全部下游连接池
async def close_clients() -> None:
    # 逐个关闭
    for name, client in list(_clients.items()):
        # 单个失败不影响其余
        try:
            # 关闭连接池
            await client.aclose()
        except Exception:
            # 仅告警
            logger.warning("释放 %s 连接池失败", name, exc_info=True)
        # 从表中移除
        _clients.pop(name, None)
