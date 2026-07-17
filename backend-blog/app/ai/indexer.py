"""向量索引同步模块: 在文章发布/编辑/删除时同步 Milvus 中的分块向量。

设计要点: 索引同步通过 FastAPI BackgroundTasks 在响应返回后异步执行,
不阻塞文章接口的响应时间; 失败仅记录日志, 不影响主业务。
"""

# 导入日志模块
import logging

# 导入查询构造器
from sqlalchemy import select

# 导入独立会话工厂(后台任务在请求会话关闭后运行, 需自建会话)
from app.core.database import AsyncSessionLocal
# 导入文章模型
from app.models.article import Article
# 导入分块工具
from app.ai.chunker import split_text
# 导入向量化能力与开关
from app.ai.llm import ai_enabled, embed_texts
# 导入向量库操作
from app.ai.vector_store import delete_article_chunks, upsert_article_chunks

# 模块日志器
logger = logging.getLogger(__name__)


# 后台任务: 重建单篇文章的向量索引(发布/编辑后调用)
async def index_article(article_id: int) -> None:
    # 未配置 AI 则跳过
    if not ai_enabled():
        # 静默返回
        return
    # 异常兜底: 索引失败不影响主业务
    try:
        # 打开独立数据库会话
        async with AsyncSessionLocal() as db:
            # 查询文章最新内容
            result = await db.execute(select(Article).where(Article.id == article_id))
            # 取出文章
            article = result.scalar_one_or_none()
        # 文章不存在或未发布则清除其向量(下架即从检索中消失)
        if not article or article.status != 1:
            # 删除旧分块
            await delete_article_chunks(article_id)
            # 结束
            return
        # 将 "标题 + 正文" 作为索引文本, 标题携带主题信息提升召回
        chunks = split_text(f"{article.title}\n\n{article.content}")
        # 批量向量化全部分块
        vectors = await embed_texts(chunks) if chunks else []
        # 覆盖写入向量库
        await upsert_article_chunks(
            article_id=article.id,
            category_id=article.category_id,
            title=article.title,
            chunks=chunks,
            vectors=vectors,
        )
        # 记录成功日志
        logger.info("文章 %s 向量索引完成, 共 %s 块", article_id, len(chunks))
    except Exception:
        # 记录异常但不抛出, 保证主流程不受影响
        logger.exception("文章 %s 向量索引失败", article_id)


# 后台任务: 删除单篇文章的向量索引(文章删除后调用)
async def remove_article_index(article_id: int) -> None:
    # 未配置 AI 则跳过
    if not ai_enabled():
        # 静默返回
        return
    # 异常兜底
    try:
        # 删除该文章全部分块
        await delete_article_chunks(article_id)
        # 记录日志
        logger.info("文章 %s 向量索引已删除", article_id)
    except Exception:
        # 记录异常但不抛出
        logger.exception("文章 %s 向量索引删除失败", article_id)


# 全量重建: 遍历所有已发布文章重建索引(初始化或模型更换后手动触发)
async def reindex_all() -> int:
    # 打开独立会话
    async with AsyncSessionLocal() as db:
        # 查询全部已发布文章的 ID
        result = await db.execute(select(Article.id).where(Article.status == 1))
        # 取出 ID 列表
        ids = list(result.scalars().all())
    # 逐篇重建(串行执行, 避免 embedding 接口限流)
    for article_id in ids:
        # 复用单篇索引逻辑
        await index_article(article_id)
    # 返回处理的文章数
    return len(ids)
