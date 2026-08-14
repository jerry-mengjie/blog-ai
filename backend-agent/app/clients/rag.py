"""backend-rag 客户端: 本服务获取向量检索能力的唯一入口。

本服务不关心向量库是 Milvus 还是别的、分块策略如何、用哪个 embedding 模型 ——
这些细节全部封装在 backend-rag 内部, 这里只消费「问题 → 相关分块」与
「行为 → 相似文章」两个语义化接口。
"""

# 导入服务客户端基类
from app.clients.http import ServiceClient
# 导入全局配置
from app.core.config import settings

# backend-rag 客户端单例
_client = ServiceClient("backend-rag", settings.RAG_BASE_URL)


# 检索与问题相关的文章分块
async def retrieve(
    query: str,
    article_id: int | None = None,
    category_id: int | None = None,
    top_k: int | None = None,
) -> list[dict]:
    # 调用检索接口
    data = await _client.post(
        "/rag/retrieve",
        json={
            "query": query,                                       # 问题
            "article_id": article_id,                             # 限定文章(可为 None)
            "category_id": category_id,                           # 限定分类(可为 None)
            "top_k": top_k or settings.RAG_TOP_K,                 # 返回分块数
            "min_score": settings.RAG_SCORE_THRESHOLD,            # 相似度下限
        },
    )
    # 返回命中分块
    return (data or {}).get("chunks") or []


# 按用户行为画像召回相似文章
async def recall_similar(
    behaviors: list[dict],
    exclude_ids: list[int],
    limit: int,
) -> list[dict]:
    # 调用画像召回接口
    data = await _client.post(
        "/rag/similar",
        json={"behaviors": behaviors, "exclude_ids": exclude_ids, "limit": limit},
    )
    # 返回召回候选
    return (data or {}).get("items") or []


# 触发全量重建索引(管理操作, 耗时较长, 使用独立超时)
async def reindex() -> dict:
    # 调用重建接口
    data = await _client.post(
        "/rag/reindex", timeout=settings.HTTP_REINDEX_TIMEOUT
    )
    # 返回统计结果
    return data or {}
