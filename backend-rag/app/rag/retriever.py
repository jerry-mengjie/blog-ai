"""检索: LlamaIndex VectorStoreIndex → VectorIndexRetriever → 相似度后处理。

经典读路径:
`VectorStoreIndex.from_vector_store()` 挂载既有 Milvus 集合(不重建索引),
`as_retriever()` 生成检索器, `aretrieve()` 完成「问题向量化 + 标量过滤 + TopK」。

检索范围与产品需求一一对应:
- article: 只检索当前文章的分块(filters: article_id == X)
- series : 检索当前分类(系列)下所有文章的分块(filters: category_id == X)

性能优化要点:
1. 相似度下限下推到引擎: search_params 带 radius, Milvus 侧就丢掉低分块,
   避免把无用结果传回进程再过滤; 框架侧 SimilarityPostprocessor 只作阈值兜底
2. 标量过滤命中倒排索引(article_id / category_id 已建 INVERTED)
3. ef 取 TopK 的数倍保证召回率, 由配置统一调节
4. 检索结果按 Redis TTL 缓存, 重复提问直接命中, 省下向量化 HTTP 调用
"""

# 导入 LlamaIndex 索引入口
from llama_index.core import VectorStoreIndex
# 导入相似度阈值后处理器
from llama_index.core.postprocessor import SimilarityPostprocessor
# 导入元数据过滤条件
from llama_index.core.vector_stores.types import (
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
)

# 导入检索结果缓存
from app.core import cache
# 导入全局配置
from app.core.config import settings
# 导入全局组件
from app.rag.models import get_embed_model
# 导入向量存储
from app.rag.vector_store import get_vector_store

# 模块级索引单例(仅是 Milvus 集合的读写视图, 构造开销极小但没必要重复创建)
_index: VectorStoreIndex | None = None


# 获取全局唯一的向量索引(挂载既有集合, 不做任何写操作)
def get_index() -> VectorStoreIndex:
    # 声明使用模块级变量
    global _index
    # 首次调用时挂载
    if _index is None:
        # from_vector_store 表示「数据已在向量库中」, 只建立查询视图
        _index = VectorStoreIndex.from_vector_store(
            vector_store=get_vector_store(),
            embed_model=get_embed_model(),
        )
    # 返回单例
    return _index


# 组装标量过滤条件: 文章优先, 其次分类; 都不传则全库检索
def _build_filters(
    article_id: int | None,
    category_id: int | None,
) -> MetadataFilters | None:
    # 逐个收集过滤项
    items: list[MetadataFilter] = []
    # 限定当前文章
    if article_id:
        # 等值过滤, 命中 article_id 倒排索引
        items.append(
            MetadataFilter(key="article_id", value=int(article_id), operator=FilterOperator.EQ)
        )
    # 限定当前分类(系列)
    if category_id:
        # 等值过滤, 命中 category_id 倒排索引
        items.append(
            MetadataFilter(key="category_id", value=int(category_id), operator=FilterOperator.EQ)
        )
    # 无过滤项返回 None, 检索器会跳过过滤表达式
    return MetadataFilters(filters=items) if items else None


# 组装 Milvus 检索参数: ef 控制召回率, radius 把相似度下限下推到引擎侧
def _build_search_config(min_score: float) -> dict:
    # COSINE 度量下 radius 是下界, range_filter 是上界(余弦相似度最大为 1)
    return {
        "ef": settings.MILVUS_SEARCH_EF,  # 检索候选队列
        "radius": min_score,              # 相似度下限(引擎侧过滤)
        "range_filter": 1.0,              # 相似度上限
    }


# 检索: 在指定范围内查询与问题最相关的分块, 返回 JSON 友好的字典列表
async def retrieve(
    query: str,
    article_id: int | None = None,
    category_id: int | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
) -> list[dict]:
    # 归一化 TopK, 缺省取配置值
    k = max(1, int(top_k or settings.RAG_TOP_K))
    # 归一化相似度下限, 缺省取配置值
    threshold = settings.RAG_SCORE_THRESHOLD if min_score is None else float(min_score)
    # 缓存 key 由全部影响结果的参数派生
    key = cache.make_key(
        {
            "q": query,
            "article_id": article_id,
            "category_id": category_id,
            "k": k,
            "min_score": threshold,
        }
    )

    # 回源闭包: 真 miss 时才向量化并检索 Milvus
    async def _factory() -> list[dict]:
        # 生成检索器: 过滤条件与检索参数按请求下发
        retriever = get_index().as_retriever(
            similarity_top_k=k,
            filters=_build_filters(article_id, category_id),
            vector_store_kwargs={"milvus_search_config": _build_search_config(threshold)},
        )
        # 异步检索: 内部完成 问题向量化 → Milvus 过滤检索 → 节点还原
        hits = await retriever.aretrieve(query)
        # 阈值兜底: 保证返回结果的语义与配置一致, 不依赖引擎实现细节
        hits = SimilarityPostprocessor(similarity_cutoff=threshold).postprocess_nodes(hits)
        # 整理为简单字典列表, 上层(backend-agent)据此拼提示词与来源引用
        return [
            {
                "article_id": int(h.node.metadata.get("article_id") or 0),  # 来源文章 ID
                "title": h.node.metadata.get("title") or "",                # 来源标题
                "chunk_index": int(h.node.metadata.get("chunk_index") or 0),  # 块序号
                "text": h.node.get_content(),                               # 分块原文
                "score": float(h.score or 0.0),                             # 余弦相似度
            }
            for h in hits
        ]

    # Redis 缓存 → 向量化 + Milvus 检索
    return await cache.get_or_set(key, _factory)
