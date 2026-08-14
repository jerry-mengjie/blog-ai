"""画像召回: 把用户行为文章聚合成偏好向量, 再做向量近邻召回。

供 backend-agent 的推荐图使用。这里只做「向量层」的事, 不碰任何业务库:
上游把「行为文章 ID + 权重」传进来, 本服务返回「相似文章 ID + 得分」。

流程:
1. 取行为文章的代表向量(每篇取开头若干块)
2. 按行为权重加权平均 → 用户偏好向量(画像向量)
3. 以画像向量在 Milvus 中近邻检索, 引擎侧排除已读/已收藏
4. 分块级命中聚合到文章级, 每篇取其最高分

性能优化要点:
1. 代表向量只取每篇文章开头 RAG_PROFILE_CHUNKS 块, 把回传的向量数据量压到千分之一级别
2. 取数与召回的过滤条件(article_id in / not in, chunk_index <)全部命中标量倒排索引
3. 候选块数取目标篇数的数倍并封顶, 保证聚合去重后仍有富余
4. 权重用 float32 矩阵一次性加权平均, 避免逐条 Python 循环
"""

# 导入日志
import logging

# 导入 numpy 做加权平均
import numpy as np
# 导入向量检索请求与过滤条件
from llama_index.core.vector_stores.types import (
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
    VectorStoreQuery,
)

# 导入全局配置
from app.core.config import settings
# 导入向量存储与字段名常量
from app.rag.vector_store import EMBEDDING_FIELD, get_vector_store

# 模块日志器
logger = logging.getLogger(__name__)


# 取一批文章的代表向量: 每篇取开头若干分块的均值
async def fetch_article_vectors(article_ids: list[int]) -> dict[int, list[float]]:
    # 空入参直接返回, 避免拼出非法表达式
    if not article_ids:
        # 无文章无向量
        return {}
    # 去重后的 ID 列表(数值来自数据库主键, 无注入风险)
    ids = sorted({int(a) for a in article_ids})
    # 过滤: 限定文章集合 + 只取开头若干块, 两个条件都走标量倒排索引
    expr = f"article_id in {ids} and chunk_index < {settings.RAG_PROFILE_CHUNKS}"
    # 直接用 pymilvus 异步客户端: 需要拿原始向量, 检索器接口不回传 embedding
    rows = await get_vector_store().aclient.query(
        collection_name=settings.MILVUS_COLLECTION,
        filter=expr,
        output_fields=["article_id", EMBEDDING_FIELD],   # 只取聚合所需字段
        limit=len(ids) * settings.RAG_PROFILE_CHUNKS,    # 精确上限, 不多取一条
    )
    # 按文章分桶收集分块向量
    buckets: dict[int, list[list[float]]] = {}
    # 逐行归桶
    for row in rows:
        # 追加该分块向量到所属文章
        buckets.setdefault(int(row["article_id"]), []).append(row[EMBEDDING_FIELD])
    # 每篇文章的分块向量取均值, 得到文章级代表向量
    return {
        aid: np.asarray(vecs, dtype=np.float32).mean(axis=0).tolist()
        for aid, vecs in buckets.items()
    }


# 由行为权重合成画像向量; 行为文章都没有向量时返回 None
async def build_profile_vector(behaviors: list[dict]) -> list[float] | None:
    # 无行为无画像
    if not behaviors:
        # 交给上层走其他召回策略
        return None
    # 取出行为文章的代表向量
    vectors = await fetch_article_vectors([b["article_id"] for b in behaviors])
    # 行为文章都未被索引(如刚清空向量库)时无法构建画像
    if not vectors:
        # 交给上层兜底
        return None
    # 保留有向量的行为及其权重
    pairs = [
        (vectors[int(b["article_id"])], float(b.get("weight") or 0.0))
        for b in behaviors
        if int(b["article_id"]) in vectors
    ]
    # 向量堆叠为矩阵
    matrix = np.asarray([v for v, _ in pairs], dtype=np.float32)
    # 权重数组
    weights = np.asarray([w for _, w in pairs], dtype=np.float32)
    # 加权平均得到画像向量(权重和过小时退化为等权, 避免除零)
    profile = (matrix * weights[:, None]).sum(axis=0) / max(float(weights.sum()), 1e-6)
    # 转为普通列表便于跨进程传输
    return profile.tolist()


# 按画像向量召回相似文章: 分块级检索后聚合到文章级, 每篇取最高分
async def recall_similar_articles(
    behaviors: list[dict],
    exclude_ids: list[int],
    limit: int,
) -> list[dict]:
    # 先合成画像向量
    profile = await build_profile_vector(behaviors)
    # 画像不可用则返回空, 由上层切换策略
    if profile is None:
        # 无候选
        return []
    # 排除已读/已收藏: not in 走 article_id 倒排索引, 引擎侧完成过滤
    filters = (
        MetadataFilters(
            filters=[
                MetadataFilter(
                    key="article_id",
                    value=sorted({int(a) for a in exclude_ids}),
                    operator=FilterOperator.NIN,
                )
            ]
        )
        if exclude_ids
        else None
    )
    # 候选块数取目标篇数的数倍(同一文章会占多个块), 并按配置封顶
    candidate_k = min(max(1, int(limit)) * 4, settings.RAG_PROFILE_CANDIDATES)
    # 执行向量检索(画像向量已是现成向量, 无需再过一次 embedding)
    result = await get_vector_store().aquery(
        VectorStoreQuery(
            query_embedding=profile,
            similarity_top_k=candidate_k,
            filters=filters,
        ),
        milvus_search_config={"ef": max(settings.MILVUS_SEARCH_EF, candidate_k)},
    )
    # 文章级聚合: 同一文章取其最高分块得分
    best: dict[int, float] = {}
    # 逐条命中归并(similarities 与 nodes 顺序一一对应)
    for node, score in zip(result.nodes or [], result.similarities or []):
        # 取块所属文章 ID
        aid = int(node.metadata.get("article_id") or 0)
        # 跳过异常数据
        if not aid:
            # 无效块
            continue
        # 保留该文章的最高得分
        best[aid] = max(best.get(aid, 0.0), float(score))
    # 按得分倒序输出前 limit 篇
    return [
        {"article_id": aid, "score": score}
        for aid, score in sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    ]
