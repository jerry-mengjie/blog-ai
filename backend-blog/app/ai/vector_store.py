"""Milvus 向量库模块: 集合管理、分块写入与带过滤的相似度检索。

性能优化要点:
1. AsyncMilvusClient: 运行期读写全异步(gRPC), 与 FastAPI 事件循环无缝配合
2. HNSW 图索引: M=16/efConstruction=128 平衡构建成本与召回率, 检索 ef=64
3. 标量倒排索引(INVERTED): article_id/category_id 过滤走索引而非全表暴力过滤
4. range search: 以相似度下限(radius)在引擎侧过滤低分结果, 减少无效返回
"""

# 导入 uuid 用于生成确定性的主键
import uuid

# 导入 Milvus 客户端: 异步客户端负责运行期读写, 同步客户端仅用于启动期建集合
from pymilvus import AsyncMilvusClient, DataType, MilvusClient

# 导入全局配置
from app.core.config import settings

# 模块级异步客户端单例, 复用 gRPC 通道
_client: AsyncMilvusClient | None = None


# 获取全局唯一的 Milvus 异步客户端
def get_milvus() -> AsyncMilvusClient:
    # 声明使用模块级变量
    global _client
    # 首次调用时创建实例
    if _client is None:
        # 连接 standalone 的 gRPC 端口
        _client = AsyncMilvusClient(uri=settings.MILVUS_URI)
    # 返回单例
    return _client


# 应用关闭时释放客户端连接
async def close_milvus() -> None:
    # 声明使用模块级变量
    global _client
    # 已创建则关闭
    if _client is not None:
        # 关闭底层 gRPC 通道
        await _client.close()
        # 置空便于重建
        _client = None


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
    finally:
        # 释放临时连接
        client.close()


# 生成确定性的主键: 同一文章同一分块序号恒定, 重复写入即覆盖(天然幂等)
def _point_id(article_id: int, chunk_index: int) -> str:
    # 使用 UUID5 基于稳定字符串生成
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"article:{article_id}:chunk:{chunk_index}"))


# 写入(或覆盖)一篇文章的全部分块向量
async def upsert_article_chunks(
    article_id: int,
    category_id: int,
    title: str,
    chunks: list[str],
    vectors: list[list[float]],
) -> None:
    # 获取客户端
    client = get_milvus()
    # 先删除该文章的旧分块, 防止正文变短后残留过期块
    await delete_article_chunks(article_id)
    # 无新分块(空文章)则到此结束
    if not chunks:
        # 仅做清理
        return
    # 构造行数据: 主键 + 向量 + 标量字段
    rows = [
        {
            "id": _point_id(article_id, idx),   # 确定性主键, 幂等覆盖
            "vector": vector,                    # 分块向量
            "article_id": article_id,           # 文章 ID(过滤索引字段)
            "category_id": category_id,         # 分类 ID(过滤索引字段)
            "title": title,                     # 标题, 用于提示词中标注来源
            "chunk_index": idx,                 # 块序号, 用于按原文顺序排序
            "text": chunk,                      # 分块原文
        }
        for idx, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]
    # 批量 upsert, 主键相同即覆盖(Milvus 内部转为删旧插新)
    await client.upsert(collection_name=settings.MILVUS_COLLECTION, data=rows)


# 删除一篇文章的全部分块(文章删除或重建索引前调用)
async def delete_article_chunks(article_id: int) -> None:
    # 获取客户端
    client = get_milvus()
    # 按 article_id 表达式过滤删除, 命中倒排索引
    await client.delete(
        collection_name=settings.MILVUS_COLLECTION,
        filter=f"article_id == {article_id}",
    )


# 相似度检索: 在指定范围(当前文章 / 当前分类)内查询与问题最相关的分块
async def search_chunks(
    query_vector: list[float],
    article_id: int | None = None,
    category_id: int | None = None,
) -> list[dict]:
    # 获取客户端
    client = get_milvus()
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
    # 执行向量检索: 标量过滤 + TopK + range search(相似度下限)
    result = await client.search(
        collection_name=settings.MILVUS_COLLECTION,
        data=[query_vector],
        filter=" and ".join(conditions),
        limit=settings.RAG_TOP_K,
        output_fields=["article_id", "title", "chunk_index", "text"],
        search_params={
            "metric_type": "COSINE",  # 与建索引时一致
            "params": {
                "ef": 64,             # 检索时候选队列, 高于 TopK 数倍以保证召回
                "radius": settings.RAG_SCORE_THRESHOLD,  # 相似度下限, 引擎侧过滤低分结果
            },
        },
    )
    # 将命中点整理为简单字典列表返回(单条查询取首个结果集)
    return [
        {
            "article_id": hit["entity"]["article_id"],   # 来源文章 ID
            "title": hit["entity"]["title"],             # 来源标题
            "chunk_index": hit["entity"]["chunk_index"], # 块序号
            "text": hit["entity"]["text"],               # 分块原文
            "score": hit["distance"],                    # 余弦相似度得分
        }
        for hit in result[0]
    ]
