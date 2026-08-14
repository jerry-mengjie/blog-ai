"""LlamaIndex 全局组件: 向量模型 + 分块器(经典 Settings 单例方案)。

LlamaIndex 的经典用法是把 embed_model / node_parser 注册到全局 `Settings`,
索引、管道、检索器都会自动取用, 避免层层透传参数。

选型说明:
- OpenAILikeEmbedding: 官方 OpenAIEmbedding 会校验模型名白名单, 拒绝 `text-embedding-v4`
  这类非 OpenAI 模型; OpenAILike 变体专为 OpenAI 兼容端点(阿里云百炼/DeepSeek 等)设计
- SentenceSplitter: LlamaIndex 默认分块器, 先按段落再按句子切, 内置中文句读正则,
  语义完整性优于纯字符硬切
- 本服务只做检索不做生成, 因此显式关闭 LLM(Settings.llm = None), 避免 LlamaIndex
  在构建索引时去解析默认 OpenAI 模型
"""

# 导入 LlamaIndex 全局设置
from llama_index.core import Settings as LlamaSettings
# 导入句子分块器
from llama_index.core.node_parser import SentenceSplitter
# 导入 OpenAI 兼容向量模型
from llama_index.embeddings.openai_like import OpenAILikeEmbedding

# 导入全局配置
from app.core.config import settings

# 标记全局组件是否已注册, 保证只初始化一次
_configured = False


# RAG 能力是否可用(未配置向量模型 API Key 时整个服务降级)
def rag_enabled() -> bool:
    # 仅当配置了 API Key 才启用
    return bool(settings.AI_API_KEY)


# 构建向量模型: OpenAI 兼容协议, 维度与 Milvus 集合对齐
def _build_embed_model() -> OpenAILikeEmbedding:
    # 按配置初始化
    return OpenAILikeEmbedding(
        model_name=settings.AI_EMBED_MODEL,          # 向量模型名称
        api_key=settings.AI_API_KEY,                 # API Key
        api_base=settings.AI_BASE_URL,               # OpenAI 兼容接口地址
        dimensions=settings.AI_EMBED_DIM,            # 输出维度, 与 Milvus 集合对齐
        embed_batch_size=settings.AI_EMBED_BATCH,    # 批量条数, 适配百炼上限 10
    )


# 构建分块器: 字符级计数 + 中文友好切分
def _build_node_parser() -> SentenceSplitter:
    # 按配置初始化
    return SentenceSplitter(
        chunk_size=settings.RAG_CHUNK_SIZE,          # 单块目标长度
        chunk_overlap=settings.RAG_CHUNK_OVERLAP,    # 相邻块重叠长度
        paragraph_separator="\n\n",                  # 博客正文以空行分段
        # 默认 tokenizer 是 tiktoken(按 token 计数, 且首次使用要联网下载词表);
        # 传入 list 即按「字符」计数, 与配置里的字符语义一致, 也省掉 tiktoken 开销
        tokenizer=list,
    )


# 注册全局组件(应用启动时调用一次, 幂等)
def configure_llama_index() -> None:
    # 声明使用模块级变量
    global _configured
    # 已注册直接返回
    if _configured:
        # 幂等
        return
    # 注册分块器: 写入管道与索引默认使用
    LlamaSettings.node_parser = _build_node_parser()
    # 本服务不生成回答, 显式关闭 LLM(LlamaIndex 会退化为 MockLLM)
    LlamaSettings.llm = None
    # 仅在配置了 Key 时注册向量模型, 否则保持未配置状态由上层返回 503
    if rag_enabled():
        # 注册向量模型: 写入与检索共用同一实例, 复用底层 HTTP 连接池
        LlamaSettings.embed_model = _build_embed_model()
    # 标记完成
    _configured = True


# 获取全局向量模型(供直接向量化场景使用)
def get_embed_model() -> OpenAILikeEmbedding:
    # 确保已注册
    configure_llama_index()
    # 返回全局实例
    return LlamaSettings.embed_model


# 获取全局分块器
def get_node_parser() -> SentenceSplitter:
    # 确保已注册
    configure_llama_index()
    # 返回全局实例
    return LlamaSettings.node_parser
