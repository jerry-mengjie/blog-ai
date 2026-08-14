"""backend-rag 客户端: 文章变更后同步向量索引。

设计要点: 索引同步走「写路径主动推送」而不是让检索服务轮询数据库 ——
本服务在文章发布/编辑/删除后, 把最新文档推给 backend-rag, 检索服务因此完全
不需要访问 MySQL。全部调用都在响应返回后的 BackgroundTasks 中执行,
失败仅记录日志, 不影响文章接口的响应时间与事务结果。
"""

# 导入日志
import logging

# 导入全局配置
from app.core.config import settings
# 导入客户端工厂
from app.clients.base import get_client

# 模块日志器
logger = logging.getLogger(__name__)


# 内部工具: 获取 backend-rag 客户端
def _rag():
    # 复用单例
    return get_client("backend-rag", settings.RAG_BASE_URL)


# 是否启用索引同步(未配置检索服务地址时整条链路静默跳过)
def rag_enabled() -> bool:
    # 地址非空即启用
    return bool(settings.RAG_BASE_URL and settings.RAG_BASE_URL.strip())


# 后台任务: 推送单篇文章文档, 覆盖其向量索引
async def index_article(
    article_id: int,
    category_id: int,
    title: str,
    content: str,
) -> None:
    # 未启用则跳过
    if not rag_enabled():
        # 静默返回
        return
    # 索引失败不影响主业务
    try:
        # 推送文档(检索服务侧会先删旧块再写新块, 天然幂等)
        resp = await _rag().post(
            "/rag/documents",
            json={
                "article_id": article_id,        # 文章 ID
                "category_id": category_id or 0,  # 分类 ID
                "title": title or "",            # 标题
                "content": content or "",        # 正文
            },
        )
        # 非 2xx 记录状态码
        resp.raise_for_status()
        # 记录成功日志
        logger.info("文章 %s 索引同步完成", article_id)
    except Exception:
        # 记录异常但不抛出, 保证主流程不受影响
        logger.exception("文章 %s 索引同步失败", article_id)


# 后台任务: 删除单篇文章的向量索引
async def remove_article_index(article_id: int) -> None:
    # 未启用则跳过
    if not rag_enabled():
        # 静默返回
        return
    # 异常兜底
    try:
        # 调用删除接口
        resp = await _rag().delete(f"/rag/documents/{article_id}")
        # 非 2xx 记录状态码
        resp.raise_for_status()
        # 记录日志
        logger.info("文章 %s 索引已删除", article_id)
    except Exception:
        # 记录异常但不抛出
        logger.exception("文章 %s 索引删除失败", article_id)


# 后台任务: 按文章状态决定「写入索引」还是「删除索引」
async def sync_article_index(
    article_id: int,
    category_id: int,
    title: str,
    content: str,
    status: int,
) -> None:
    # 已发布才进检索库; 草稿/下架必须从库里清掉, 否则问答会引用不可见内容
    if status == 1:
        # 覆盖写入
        await index_article(article_id, category_id, title, content)
    else:
        # 清理残留
        await remove_article_index(article_id)
