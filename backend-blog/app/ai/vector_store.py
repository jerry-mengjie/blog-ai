"""Milvus 向量库模块: pymilvus 负责集合 DDL, LangChain Milvus 负责读写检索。

分工(经典组合):
- pymilvus MilvusClient: 启动期建集合, 精确控制 Schema/HNSW/标量倒排索引
- langchain-milvus Milvus: 运行期文档写入(内部自动向量化)与相似度检索

性能优化要点:
1. HNSW 图索引: M=16/efConstruction=128 平衡构建成本与召回率, 检索 ef=64
2. 标量倒排索引(INVERTED): article_id/category_id 过滤走索引而非全表暴力过滤
3. range search: 以相似度下限(radius)在引擎侧过滤低分结果, 减少无效返回
4. 向量存储单例: 复用 Milvus 连接与 embedding 客户端
"""

# 导入 uuid 用于生成确定性的主键
import uuid

# 导入 numpy 做向量均值聚合(pymilvus 自带依赖)
import numpy as np

# 导入 LangChain 文档对象(向量库读写的标准载体)
from langchain_core.documents import Document
# 导入 LangChain Milvus 向量存储集成
from langchain_milvus import Milvus
# 导入 pymilvus: 同步客户端做 DDL, connections 用于释放连接
from pymilvus import DataType, MilvusClient, connections

# 导入向量模型单例
from app.ai.llm import get_embeddings
# 导入全局配置
from app.core.config import settings

# 模块级向量存储单例, 复用连接与 embedding 客户端
_store: Milvus | None = None


# 获取全局唯一的 LangChain Milvus 向量存储
def get_vector_store() -> Milvus:
    # 声明使用模块级变量
    global _store
    # 首次调用时创建实例
    if _store is None:
        # 连接既有集合(由 ensure_collection 预建), 字段名与 Schema 一一对应
        _store = Milvus(
            embedding_function=get_embeddings(),          # 向量化交给 LangChain 内部完成
            collection_name=settings.MILVUS_COLLECTION,   # 集合名称
            connection_args={"uri": settings.MILVUS_URI}, # gRPC 连接地址
            primary_field="id",                           # 主键字段名
            text_field="text",                            # 原文字段名
            vector_field="vector",                        # 向量字段名
            auto_id=False,                                # 主键由业务生成(确定性 ID)
            search_params={
                "metric_type": "COSINE",                  # 与建索引时一致
                "params": {
                    "ef": 64,                             # 检索候选队列, 高于 TopK 数倍保证召回
                    "radius": settings.RAG_SCORE_THRESHOLD,  # 相似度下限, 引擎侧过滤低分结果
                },
            },
            drop_old=False,                               # 复用既有集合, 不重建
        )
    # 返回单例
    return _store


# 应用关闭时释放 Milvus 连接
async def close_vector_store() -> None:
    # 声明使用模块级变量
    global _store
    # 已创建则断开其连接别名
    if _store is not None:
        # langchain-milvus 为实例维护独立连接别名, 按别名断开
        connections.disconnect(_store.alias)
        # 置空便于重建
        _store = None


# 内部工具: 构建集合 Schema(显式字段, 关闭动态字段保证结构可控)
def _build_schema():
    # 创建 Schema, 主键由业务生成(确定性 ID), 不用自增
    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
    # 主键: 确定性字符串 ID "article:{id}:chunk:{idx}" 的 UUID5
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
    # 分块向量, 维度与 embedding 模型对齐
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=settings.AI_EMBED_DIM)
    # 文章 ID(过滤字段)
    schema.add_field("article_id", DataType.INT64)
    # 分类 ID(过滤字段, 系列检索用)
    schema.add_field("category_id", DataType.INT64)
    # 文章标题, 用于提示词中标注来源
    schema.add_field("title", DataType.VARCHAR, max_length=1024)
    # 块序号, 用于按原文顺序拼接上下文
    schema.add_field("chunk_index", DataType.INT64)
    # 分块原文, 检索后直接拼提示词
    schema.add_field("text", DataType.VARCHAR, max_length=4096)
    # 返回 Schema
    return schema


# 内部工具: 构建索引参数(向量 HNSW + 标量倒排)
def _build_index_params():
    # 创建索引参数容器
    index_params = MilvusClient.prepare_index_params()
    # 向量索引: HNSW + 余弦相似度, 文本语义检索经典组合
    index_params.add_index(
        field_name="vector",
        index_type="HNSW",
        metric_type="COSINE",
        params={
            "M": 16,               # 每个节点的边数, 召回率与内存的平衡点
            "efConstruction": 128, # 构建时候选队列, 略高于默认提升图质量
        },
    )
    # 标量倒排索引: "只检索当前文章" 的过滤条件走索引
    index_params.add_index(field_name="article_id", index_type="INVERTED")
    # 标量倒排索引: "检索当前系列(同分类)" 的过滤条件走索引
    index_params.add_index(field_name="category_id", index_type="INVERTED")
    # 返回索引参数
    return index_params


# 确保集合存在且维度正确, 应用启动时调用一次(启动期 DDL 用同步客户端即可)
async def ensure_collection() -> None:
    # 创建临时同步客户端执行 DDL
    client = MilvusClient(uri=settings.MILVUS_URI)
    # 异常时也要关闭连接
    try:
        # 检查集合是否已存在
        if client.has_collection(settings.MILVUS_COLLECTION):
            # 读取现有集合描述
            desc = client.describe_collection(settings.MILVUS_COLLECTION)
            # 取出向量字段的维度
            dim = next(
                f["params"]["dim"] for f in desc["fields"] if f["name"] == "vector"
            )
            # 维度一致则直接复用
            if int(dim) == settings.AI_EMBED_DIM:
                # 确保集合已 load 到内存, 避免检索前冷启动全量加载
                client.load_collection(settings.MILVUS_COLLECTION)
                # 无需重建
                return
            # 维度变化(更换向量模型)时删除旧集合重建
            client.drop_collection(settings.MILVUS_COLLECTION)
        # 创建集合: 传入 index_params 会同时建索引并自动加载(load)到内存
        client.create_collection(
            collection_name=settings.MILVUS_COLLECTION,
            schema=_build_schema(),
            index_params=_build_index_params(),
        )
        # 显式 load 一次, 保证检索路径零冷启动(幂等)
        client.load_collection(settings.MILVUS_COLLECTION)
    finally:
        # 释放临时连接
        client.close()


# 生成确定性的主键: 同一文章同一分块序号恒定, 重复写入即覆盖(天然幂等)
def _point_id(article_id: int, chunk_index: int) -> str:
    # 使用 UUID5 基于稳定字符串生成
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"article:{article_id}:chunk:{chunk_index}"))


# 写入(或覆盖)一篇文章的全部分块(向量化由 LangChain 内部完成)
async def upsert_article_chunks(
    article_id: int,
    category_id: int,
    title: str,
    chunks: list[str],
) -> None:
    # 获取向量存储
    store = get_vector_store()
    # 先删除该文章的旧分块, 防止正文变短后残留过期块
    await delete_article_chunks(article_id)
    # 无新分块(空文章)则到此结束
    if not chunks:
        # 仅做清理
        return
    # 将分块包装为 LangChain 文档: 原文 + 元数据(与集合标量字段一一对应)
    docs = [
        Document(
            page_content=chunk,                # 分块原文(写入 text 字段并向量化)
            metadata={
                "article_id": article_id,      # 文章 ID(过滤索引字段)
                "category_id": category_id,    # 分类 ID(过滤索引字段)
                "title": title,                # 标题, 用于提示词中标注来源
                "chunk_index": idx,            # 块序号, 用于按原文顺序排序
            },
        )
        for idx, chunk in enumerate(chunks)
    ]
    # 确定性主键列表, 与文档一一对应
    ids = [_point_id(article_id, idx) for idx in range(len(chunks))]
    # 批量写入: 内部先调 embedding 再插入 Milvus
    await store.aadd_documents(docs, ids=ids)


# 删除一篇文章的全部分块(文章删除或重建索引前调用)
async def delete_article_chunks(article_id: int) -> None:
    # 获取向量存储
    store = get_vector_store()
    # 按 article_id 表达式过滤删除, 命中倒排索引
    await store.adelete(expr=f"article_id == {article_id}")


# 推荐用: 批量取文章分块向量并按文章求均值, 作为文章级语义向量(画像原料)
async def fetch_article_mean_vectors(article_ids: list[int]) -> dict[int, list[float]]:
    # 空入参直接返回, 避免拼出非法表达式
    if not article_ids:
        # 无文章无向量
        return {}
    # 获取向量存储(复用其内部异步客户端连接)
    store = get_vector_store()
    # 标量过滤: article_id 命中倒排索引, 只捞目标文章的分块
    rows = await store.aclient.query(
        collection_name=settings.MILVUS_COLLECTION,          # 集合名称
        filter=f"article_id in {list(article_ids)}",         # ID 来自数据库主键, 无注入风险
        output_fields=["article_id", "vector"],              # 只取聚合所需字段, 减少传输
        limit=4096,                                          # 上限兜底(20 篇文章的分块远小于此)
    )
    # 按文章分桶收集分块向量
    buckets: dict[int, list[list[float]]] = {}
    # 逐行归桶
    for row in rows:
        # 追加该分块向量到所属文章
        buckets.setdefault(int(row["article_id"]), []).append(row["vector"])
    # 对每篇文章的分块向量取均值, 得到文章级语义向量
    return {
        aid: np.mean(np.asarray(vecs, dtype=np.float32), axis=0).tolist()
        for aid, vecs in buckets.items()
    }


# 推荐用: 按画像向量召回相似文章(分块级检索后聚合到文章级, 取每篇最高分)
async def search_article_ids_by_vector(
    vector: list[float],
    exclude_ids: list[int],
    limit: int,
) -> list[dict]:
    # 获取向量存储
    store = get_vector_store()
    # 排除已读/已收藏文章: not in 走倒排索引, 引擎侧完成过滤
    expr = f"article_id not in {list(exclude_ids)}" if exclude_ids else None
    # 分块级向量检索: 候选块数取目标文章数的 4 倍, 保证聚合后数量充足
    hits = await store.aclient.search(
        collection_name=settings.MILVUS_COLLECTION,          # 集合名称
        data=[vector],                                       # 画像向量(单条查询)
        anns_field="vector",                                 # 向量字段
        filter=expr,                                         # 排除表达式(可为 None)
        limit=min(limit * 4, 256),                           # TopK 缓冲, 封顶防止极端参数
        output_fields=["article_id"],                        # 聚合只需文章 ID
        search_params={"metric_type": "COSINE", "params": {"ef": 128}},  # ef 高于 TopK 保证召回率
    )
    # 文章级聚合: 同一文章取其最高分块得分
    best: dict[int, float] = {}
    # 遍历首条查询的命中块
    for hit in hits[0]:
        # 取块所属文章 ID
        aid = int(hit["entity"]["article_id"])
        # 保留该文章的最高得分
        best[aid] = max(best.get(aid, 0.0), float(hit["distance"]))
    # 按得分倒序输出前 limit 篇
    return [
        {"article_id": aid, "score": score}
        for aid, score in sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    ]


# 相似度检索: 在指定范围(当前文章 / 当前分类)内查询与问题最相关的分块
async def search_chunks(
    question: str,
    article_id: int | None = None,
    category_id: int | None = None,
) -> list[dict]:
    # 获取向量存储
    store = get_vector_store()
    # 组装标量过滤表达式(数值来自数据库主键, 无注入风险)
    conditions: list[str] = []
    # 限定当前文章
    if article_id is not None:
        # 追加文章过滤
        conditions.append(f"article_id == {article_id}")
    # 限定当前分类(系列)
    if category_id is not None:
        # 追加分类过滤
        conditions.append(f"category_id == {category_id}")
    # 执行检索: 问题向量化 + 标量过滤 + TopK + range search 均在存储内部完成
    results = await store.asimilarity_search_with_score(
        query=question,
        k=settings.RAG_TOP_K,
        expr=" and ".join(conditions) or None,
    )
    # 将命中文档整理为简单字典列表返回
    return [
        {
            "article_id": doc.metadata["article_id"],   # 来源文章 ID
            "title": doc.metadata["title"],             # 来源标题
            "chunk_index": doc.metadata["chunk_index"], # 块序号
            "text": doc.page_content,                   # 分块原文
            "score": score,                             # 余弦相似度得分
        }
        for doc, score in results
    ]
