"""索引写入: LlamaIndex IngestionPipeline(文档 → 分块 → 向量化 → Milvus)。

经典管道形态: `transformations=[分块器, 自定义变换, 向量模型]` + `vector_store`,
`arun()` 会依次执行变换并把带向量的节点批量写入 Milvus。

幂等设计:
1. 分块后为每块生成确定性 ID(article:{id}:chunk:{i} 的 UUID5), 配合向量存储的
   upsert_mode, 同一文章重复索引只会覆盖而不会堆积重复块
2. 写入前先按 article_id 删除旧块, 覆盖正文变短导致的尾部残留

向量化成本控制:
1. 标题写进元数据并参与向量化(携带主题信息提升召回), 而 article_id / category_id /
   chunk_index 这类纯数字被排除在向量化文本之外, 避免污染语义
2. 单篇文章分块数超过上限时截断, 防止超长文章打爆向量模型配额
"""

# 导入 uuid 用于生成确定性节点 ID
import uuid
# 导入日志
import logging
# 导入类型注解
from collections.abc import Sequence
from typing import Any

# 导入 LlamaIndex 写入管道
from llama_index.core.ingestion import IngestionPipeline
# 导入文档/节点与变换组件基类
from llama_index.core.schema import BaseNode, Document, TransformComponent
# 导入元数据过滤条件(按文章删除)
from llama_index.core.vector_stores.types import (
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
)

# 导入全局配置
from app.core.config import settings
# 导入全局组件
from app.rag.models import get_embed_model, get_node_parser
# 导入向量存储
from app.rag.vector_store import get_vector_store

# 模块日志器
logger = logging.getLogger(__name__)

# 不参与向量化与提示词的元数据键(纯数字标识, 语义上是噪音)
_NON_SEMANTIC_KEYS = ["article_id", "category_id", "chunk_index"]


# 生成确定性节点 ID: 同一文章同一块序号恒定, 重复写入即覆盖
def _node_id(article_id: int, chunk_index: int) -> str:
    # 使用 UUID5 基于稳定字符串生成
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"article:{article_id}:chunk:{chunk_index}")
    )


# 自定义变换: 为分块编号并改写为确定性 ID(插在分块器与向量模型之间)
class ChunkStamper(TransformComponent):
    """给分块打上顺序号与确定性 ID, 并按上限截断。"""

    # LlamaIndex 变换组件的统一入口
    def __call__(self, nodes: Sequence[BaseNode], **kwargs: Any) -> Sequence[BaseNode]:
        # 超长文章截断, 保留前 N 块(正文越靠前信息密度通常越高)
        kept = list(nodes)[: settings.RAG_MAX_CHUNKS]
        # 截断时留下日志便于发现异常长文
        if len(kept) < len(nodes):
            # 记录被丢弃的块数
            logger.warning("分块数 %s 超过上限, 已截断至 %s", len(nodes), len(kept))
        # 按分块器输出顺序编号
        for index, node in enumerate(kept):
            # 块序号写入元数据, 检索后据此还原原文顺序
            node.metadata["chunk_index"] = index
            # 改写为确定性 ID, 使写入幂等
            node.id_ = _node_id(int(node.metadata["article_id"]), index)
        # 返回处理后的节点
        return kept

    # 组件名(LlamaIndex 序列化用)
    @classmethod
    def class_name(cls) -> str:
        # 返回稳定名称
        return "ChunkStamper"


# 模块级管道单例(无状态, 跨请求复用向量模型的 HTTP 连接池)
_pipeline: IngestionPipeline | None = None


# 获取全局唯一的写入管道
def get_pipeline() -> IngestionPipeline:
    # 声明使用模块级变量
    global _pipeline
    # 首次调用时组装管道
    if _pipeline is None:
        # 变换顺序: 分块 → 编号/定 ID → 向量化; 之后由管道写入 Milvus
        _pipeline = IngestionPipeline(
            transformations=[get_node_parser(), ChunkStamper(), get_embed_model()],
            vector_store=get_vector_store(),
            # 关闭 IngestionCache: 常驻服务里它只会无界增长, 幂等已由确定性 ID 保证
            disable_cache=True,
        )
    # 返回单例
    return _pipeline


# 构造文档对象: 正文入 text, 检索所需标识入 metadata
def _build_document(
    article_id: int,
    category_id: int,
    title: str,
    content: str,
) -> Document:
    # 组装 LlamaIndex 文档
    return Document(
        # 文档 ID 用业务语义标识, 会落到 Milvus 的 doc_id 列便于排查
        id_=f"article:{article_id}",
        # 正文(标题通过元数据参与向量化, 无需再拼进正文)
        text=content,
        # 元数据会被复制到每个分块上, 并提升为 Milvus 标量列
        metadata={
            "article_id": int(article_id),        # 文章 ID
            "category_id": int(category_id or 0),  # 分类 ID(无分类记 0)
            "title": title,                       # 标题
        },
        # 向量化文本里只保留标题, 排除纯数字标识
        excluded_embed_metadata_keys=list(_NON_SEMANTIC_KEYS),
        # 交给大模型的上下文同样排除纯数字标识
        excluded_llm_metadata_keys=list(_NON_SEMANTIC_KEYS),
    )


# 删除一篇文章的全部分块(下架/删除, 或重新索引前清理)
async def delete_article(article_id: int) -> None:
    # 按 article_id 等值过滤删除, 命中标量倒排索引
    await get_vector_store().adelete_nodes(
        filters=MetadataFilters(
            filters=[
                MetadataFilter(
                    key="article_id",
                    value=int(article_id),
                    operator=FilterOperator.EQ,
                )
            ]
        )
    )


# 索引一篇文章: 先清旧块再走管道写入, 返回写入的分块数
async def index_article(
    article_id: int,
    category_id: int,
    title: str,
    content: str,
) -> int:
    # 先删旧块, 避免正文变短后尾部块残留在检索结果里
    await delete_article(article_id)
    # 正文为空(草稿/占位文章)时只做清理
    if not (content or "").strip():
        # 无内容可索引
        return 0
    # 执行管道: 分块 → 编号 → 向量化 → 写入 Milvus
    nodes = await get_pipeline().arun(
        documents=[_build_document(article_id, category_id, title, content)]
    )
    # 返回实际写入的块数
    return len(nodes)
