"""backend-blog 内部接口客户端: 全量重建索引时回源拉取文章正文。

只在「全量重建」这条低频路径上使用; 日常的单篇索引由 backend-blog 主动推送,
不需要反向调用, 避免两个服务在写路径上互相依赖。

性能要点:
1. 进程级 AsyncClient 单例 + 连接池, 服务间调用复用 TCP 与 HTTP/1.1 keep-alive
2. 显式超时, 上游卡住时快速失败而不是拖垮重建任务
"""

# 导入日志
import logging

# 导入异步 HTTP 客户端
import httpx

# 导入全局配置
from app.core.config import settings

# 模块日志器
logger = logging.getLogger(__name__)

# 模块级客户端单例
_client: httpx.AsyncClient | None = None


# 获取全局唯一的 HTTP 客户端
def get_client() -> httpx.AsyncClient:
    # 声明使用模块级变量
    global _client
    # 首次调用时创建
    if _client is None:
        # 连接池与超时按配置设定
        _client = httpx.AsyncClient(
            base_url=settings.BLOG_BASE_URL.rstrip("/"),
            timeout=settings.HTTP_TIMEOUT,
            limits=httpx.Limits(
                max_connections=settings.HTTP_MAX_CONNECTIONS,
                max_keepalive_connections=settings.HTTP_MAX_CONNECTIONS // 2,
            ),
            # 服务间调用令牌, 由 backend-blog 的内部路由校验
            headers={"X-Internal-Token": settings.INTERNAL_TOKEN},
        )
    # 返回单例
    return _client


# 应用关闭时释放连接池
async def close_client() -> None:
    # 声明使用模块级变量
    global _client
    # 已创建则关闭
    if _client is not None:
        # 关闭连接池
        await _client.aclose()
        # 置空
        _client = None


# 内部工具: 取出统一信封中的 data 字段
def _unwrap(resp: httpx.Response) -> dict:
    # 非 2xx 直接抛出, 由调用方记录
    resp.raise_for_status()
    # 解析 {code, message, data}
    body = resp.json()
    # 业务码非 0 视为失败
    if body.get("code") != 0:
        # 抛出带业务信息的异常
        raise RuntimeError(f"backend-blog 返回业务错误: {body.get('message')}")
    # 返回数据体
    return body.get("data") or {}


# 拉取全部需要索引的文章 ID(仅已发布)
async def list_indexable_article_ids() -> list[int]:
    # 调用内部接口
    resp = await get_client().get("/internal/article/indexable-ids")
    # 解包后取 ID 列表
    return [int(i) for i in _unwrap(resp).get("ids", [])]


# 拉取单篇文章的索引用文档(标题 + 正文 + 分类)
async def fetch_article_document(article_id: int) -> dict | None:
    # 调用内部接口
    resp = await get_client().get(f"/internal/article/{article_id}/document")
    # 文章已删除时返回 404, 视为无文档
    if resp.status_code == 404:
        # 交由调用方清理索引
        return None
    # 解包返回文档
    return _unwrap(resp)
