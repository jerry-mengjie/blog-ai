"""索引写入路由: 单篇 upsert / 单篇删除 / 全量重建 (3 个接口)。

调用方:
- backend-blog: 文章发布/编辑/删除后推送单篇变更(响应后的后台任务, 不阻塞业务接口)
- backend-agent: 管理员触发全量重建时转发到这里
"""

# 导入并发原语(全量重建限流)
import asyncio
# 导入日志
import logging

# 导入路由与依赖工具
from fastapi import APIRouter, Depends

# 导入检索缓存(索引变更后失效)
from app.core import cache
# 导入统一响应
from app.core.response import Result, ok
# 导入全局配置
from app.core.config import settings
# 导入服务间令牌与可用性校验
from app.api.deps import require_rag_enabled, verify_internal_token
# 导入 backend-blog 客户端(全量重建回源)
from app.clients import blog as blog_client
# 导入索引写入能力
from app.rag.ingest import delete_article, index_article
# 导入请求/响应模型
from app.schemas.rag import ArticleDocumentReq, IndexResultOut, ReindexOut

# 模块日志器
logger = logging.getLogger(__name__)

# 创建索引路由, 前缀 /rag, 全局挂服务间令牌校验
router = APIRouter(
    prefix="/rag",
    tags=["索引写入"],
    dependencies=[Depends(verify_internal_token)],
)


# 1. 单篇索引 upsert: 覆盖写入一篇文章的全部分块
@router.post(
    "/documents",
    response_model=Result,
    summary="索引单篇文章(幂等覆盖)",
    dependencies=[Depends(require_rag_enabled)],
)
async def upsert_document(body: ArticleDocumentReq):
    # 覆盖写入: 内部先删旧块再分块向量化
    chunks = await index_article(
        article_id=body.article_id,
        category_id=body.category_id,
        title=body.title,
        content=body.content,
    )
    # 内容已变更, 清空检索缓存避免继续返回旧片段
    await cache.invalidate_all()
    # 记录日志便于观察索引同步是否跟上
    logger.info("文章 %s 索引完成, 共 %s 块", body.article_id, chunks)
    # 返回写入块数
    return ok(IndexResultOut(article_id=body.article_id, chunks=chunks))


# 2. 单篇索引删除: 文章删除或下架时调用
@router.delete(
    "/documents/{article_id}",
    response_model=Result,
    summary="删除单篇文章索引",
    dependencies=[Depends(require_rag_enabled)],
)
async def remove_document(article_id: int):
    # 按 article_id 删除全部分块
    await delete_article(article_id)
    # 文章已不可见, 必须同时清掉可能引用它的检索缓存
    await cache.invalidate_all()
    # 记录日志
    logger.info("文章 %s 索引已删除", article_id)
    # 返回结果
    return ok(IndexResultOut(article_id=article_id, chunks=0))


# 内部工具: 重建单篇文章索引, 返回 (块数, 是否成功)
async def _reindex_one(article_id: int) -> tuple[int, bool]:
    # 单篇失败不能中断整体重建
    try:
        # 回源拉取最新正文
        doc = await blog_client.fetch_article_document(article_id)
        # 文章已不可索引(删除/下架)则清理其向量
        if not doc:
            # 删除残留分块
            await delete_article(article_id)
            # 记 0 块但算成功
            return 0, True
        # 覆盖写入
        chunks = await index_article(
            article_id=int(doc["article_id"]),
            category_id=int(doc.get("category_id") or 0),
            title=doc.get("title") or "",
            content=doc.get("content") or "",
        )
        # 返回块数
        return chunks, True
    except Exception:
        # 记录异常并标记失败
        logger.exception("文章 %s 重建索引失败", article_id)
        # 失败计入结果便于人工重试
        return 0, False


# 3. 全量重建: 遍历所有已发布文章重新索引(初始化或更换向量模型后触发)
@router.post(
    "/reindex",
    response_model=Result,
    summary="全量重建向量索引",
    dependencies=[Depends(require_rag_enabled)],
)
async def reindex():
    # 从 backend-blog 拉取需要索引的文章 ID
    article_ids = await blog_client.list_indexable_article_ids()
    # 并发闸门: 向量模型有 QPS 限制, 不能无限并发
    gate = asyncio.Semaphore(settings.RAG_REINDEX_CONCURRENCY)

    # 受限并发的单篇任务
    async def _guarded(article_id: int) -> tuple[int, int, bool]:
        # 拿到令牌才执行
        async with gate:
            # 复用单篇重建逻辑
            chunks, success = await _reindex_one(article_id)
            # 返回三元组便于汇总
            return article_id, chunks, success

    # 并发执行全部文章(受闸门限制为 RAG_REINDEX_CONCURRENCY 路)
    results = await asyncio.gather(*(_guarded(aid) for aid in article_ids))
    # 汇总写入块数
    total_chunks = sum(chunks for _, chunks, success in results if success)
    # 汇总失败文章
    failed = [aid for aid, _, success in results if not success]
    # 全库内容都可能变了, 整批清空检索缓存(整个重建只清一次)
    await cache.invalidate_all()
    # 记录总览日志
    logger.info(
        "全量重建完成: 文章 %s 篇, 分块 %s 个, 失败 %s 篇",
        len(article_ids), total_chunks, len(failed),
    )
    # 返回统计结果
    return ok(
        ReindexOut(articles=len(article_ids), chunks=total_chunks, failed=failed),
        message="重建完成",
    )
