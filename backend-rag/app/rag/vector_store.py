"""Milvus 向量存储: LlamaIndex MilvusVectorStore 负责读写, pymilvus 负责索引 DDL。

分工(经典组合):
- MilvusVectorStore: 节点写入/删除/检索, 自动完成 Schema 建表与向量索引
- pymilvus MilvusClient: 补建标量倒排索引(框架只建向量索引), 并做维度校验

性能优化要点:
1. 标量字段独立成列: article_id / category_id / title / chunk_index 从元数据 JSON
   提升为真实列, 过滤表达式才能命中索引(留在动态字段里只能逐行解析 JSON)
2. 标量倒排索引(INVERTED): 「只看本文」「只看本系列」「排除已读」这三类过滤走索引
3. HNSW 图索引: M=16 / efConstruction=128 平衡构建成本与召回率, 检索 ef 可配
4. output_fields 白名单: 检索只回传标量列与正文, 不回传 LlamaIndex 的 `_node_content`
   (它是正文的 JSON 副本), 网络传输量约减半
5. consistency_level=Bounded: 检索不等待数据同步点, 吞吐远高于 Strong/Session,
   代价是新索引的文章有秒级可见延迟, 对博客问答完全可接受
6. upsert_mode + 确定性节点 ID: 重复索引同一文章天然幂等, 不产生重复块
"""

# 导入日志
import logging

# 导入 LlamaIndex Milvus 向量存储与索引管理策略
from llama_index.vector_stores.milvus import IndexManagement, MilvusVectorStore
# 导入 pymilvus 数据类型与同步客户端(仅用于索引 DDL 与维度校验)
from pymilvus import DataType, MilvusClient

# 导入全局配置
from app.core.config import settings

# 模块日志器
logger = logging.getLogger(__name__)

# 向量字段名(与 LlamaIndex 默认保持一致)
EMBEDDING_FIELD = "embedding"
# 正文字段名
TEXT_FIELD = "text"
# 提升为真实列的标量字段: 名称 → Milvus 类型
_SCALAR_FIELDS: dict[str, DataType] = {
    "article_id": DataType.INT64,    # 文章 ID: 「只看本文」过滤 + 推荐排除已读
    "category_id": DataType.INT64,   # 分类 ID: 「只看本系列」过滤
    "title": DataType.VARCHAR,       # 文章标题: 检索结果标注来源, 不参与过滤
    "chunk_index": DataType.INT64,   # 块序号: 拼接上下文时还原原文顺序
}
# 需要建倒排索引的过滤字段(title 只读不过滤, 无需索引)
_INDEXED_SCALAR_FIELDS = ("article_id", "category_id", "chunk_index")
# 检索时回传的字段白名单
_OUTPUT_FIELDS = list(_SCALAR_FIELDS.keys())

# 模块级向量存储单例, 复用 Milvus 连接
_store: MilvusVectorStore | None = None


# 获取全局唯一的 Milvus 向量存储(集合不存在时按 Schema + HNSW 自动创建)
def get_vector_store() -> MilvusVectorStore:
    # 声明使用模块级变量
    global _store
    # 首次调用时创建实例
    if _store is None:
        # 按配置初始化
        _store = MilvusVectorStore(
            uri=settings.MILVUS_URI,                        # gRPC 连接地址
            collection_name=settings.MILVUS_COLLECTION,     # 集合名称
            dim=settings.AI_EMBED_DIM,                      # 向量维度
            embedding_field=EMBEDDING_FIELD,                # 向量字段名
            text_key=TEXT_FIELD,                            # 正文字段名
            scalar_field_names=list(_SCALAR_FIELDS.keys()),  # 标量列名
            scalar_field_types=list(_SCALAR_FIELDS.values()),  # 标量列类型
            similarity_metric="COSINE",                     # 余弦相似度, 文本语义检索经典选择
            consistency_level=settings.MILVUS_CONSISTENCY,   # 一致性级别, 默认 Bounded
            overwrite=False,                                # 复用既有集合, 不重建
            upsert_mode=True,                               # 主键相同即覆盖, 重复索引幂等
            index_management=IndexManagement.CREATE_IF_NOT_EXISTS,  # 缺索引时自动补建
            index_config={
                "index_type": "HNSW",                       # 图索引
                "metric_type": "COSINE",                    # 与检索时一致
                "M": settings.MILVUS_HNSW_M,                # 每节点边数
                "efConstruction": settings.MILVUS_HNSW_EF_CONSTRUCTION,  # 构建候选队列
            },
            search_config={"ef": settings.MILVUS_SEARCH_EF},  # 检索候选队列
            output_fields=_OUTPUT_FIELDS,                   # 回传字段白名单, 省掉正文 JSON 副本
            batch_size=settings.MILVUS_BATCH_SIZE,          # 批量写入条数
            use_async_client=True,                          # 启用异步客户端, 检索不阻塞事件循环
        )
    # 返回单例
    return _store


# 内部工具: 补建标量倒排索引(框架只负责向量索引)
def _ensure_scalar_indexes(client: MilvusClient) -> None:
    # 已有索引名集合(创建时把 index_name 设为字段名, 便于比对)
    existing = set(client.list_indexes(collection_name=settings.MILVUS_COLLECTION))
    # 计算缺失的过滤字段
    missing = [f for f in _INDEXED_SCALAR_FIELDS if f not in existing]
    # 无缺失直接返回
    if not missing:
        # 已是最优状态
        return
    # Milvus 要求集合处于释放状态才能新建标量索引; 该操作仅在首次启动时发生一次
    client.release_collection(settings.MILVUS_COLLECTION)
    # 准备索引参数
    index_params = client.prepare_index_params()
    # 为每个缺失字段建倒排索引
    for field in missing:
        # 倒排索引: 等值/IN/NOT IN 过滤从全列扫描变为索引查找
        index_params.add_index(field_name=field, index_name=field, index_type="INVERTED")
    # 提交索引创建
    client.create_index(settings.MILVUS_COLLECTION, index_params)
    # 记录日志便于排查
    logger.info("已补建标量倒排索引: %s", ", ".join(missing))


# 确保集合与全部索引就绪, 应用启动时调用一次(启动期 DDL 用同步客户端即可)
def ensure_collection() -> None:
    # 创建临时同步客户端执行 DDL
    client = MilvusClient(uri=settings.MILVUS_URI)
    # 异常时也要关闭连接
    try:
        # 集合已存在时校验向量维度
        if client.has_collection(settings.MILVUS_COLLECTION):
            # 读取集合描述
            desc = client.describe_collection(settings.MILVUS_COLLECTION)
            # 取出向量字段维度
            dim = next(
                f["params"]["dim"]
                for f in desc["fields"]
                if f["name"] == EMBEDDING_FIELD
            )
            # 维度变化(更换向量模型)时删除旧集合, 由下一步重建
            if int(dim) != settings.AI_EMBED_DIM:
                # 旧向量与新模型不可比, 只能重建并重新索引
                logger.warning(
                    "向量维度由 %s 变为 %s, 重建集合 %s(需重新执行全量索引)",
                    dim, settings.AI_EMBED_DIM, settings.MILVUS_COLLECTION,
                )
                # 删除旧集合
                client.drop_collection(settings.MILVUS_COLLECTION)
        # 触发单例创建: 集合不存在时按 Schema 建表并创建 HNSW 向量索引
        get_vector_store()
        # 补建标量倒排索引(可能需要先释放集合)
        _ensure_scalar_indexes(client)
        # 显式加载到内存, 保证首次检索零冷启动(幂等)
        client.load_collection(settings.MILVUS_COLLECTION)
        # 记录就绪日志
        logger.info("Milvus 集合 %s 就绪", settings.MILVUS_COLLECTION)
    finally:
        # 释放临时连接
        client.close()


# 应用关闭时释放向量存储持有的 Milvus 连接
async def close_vector_store() -> None:
    # 声明使用模块级变量
    global _store
    # 未创建则无需处理
    if _store is None:
        # 空操作
        return
    # 关闭失败不应阻断进程退出
    try:
        # 关闭同步客户端
        _store.client.close()
        # 关闭异步客户端(构造参数 use_async_client=True 时存在)
        await _store.aclient.close()
    except Exception:
        # 仅记录
        logger.warning("释放 Milvus 连接时出现异常", exc_info=True)
    # 置空便于重建
    _store = None
