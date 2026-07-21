"""模型客户端模块: 基于 LangChain 提供对话模型与向量模型的全局单例。

经典方案: langchain-openai 的 ChatOpenAI / OpenAIEmbeddings,
通过 OpenAI 兼容协议对接阿里云百炼(也可换 DeepSeek 等兼容服务)。
"""

# 导入 LangChain 的 OpenAI 兼容对话模型与向量模型
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

# 导入全局配置
from app.core.config import settings

# 模块级对话模型单例, 复用底层 HTTP 连接池
_chat_model: ChatOpenAI | None = None
# 模块级向量模型单例
_embeddings: OpenAIEmbeddings | None = None


# 判断 AI 功能是否可用(未配置 API Key 时前端隐藏问答入口)
def ai_enabled() -> bool:
    # 仅当配置了 API Key 才启用
    return bool(settings.AI_API_KEY)


# 获取全局唯一的对话模型(LCEL 链的生成节点)
def get_chat_model() -> ChatOpenAI:
    # 声明使用模块级变量
    global _chat_model
    # 首次调用时创建实例
    if _chat_model is None:
        # 按配置初始化, 低温度保证回答贴近原文
        _chat_model = ChatOpenAI(
            model=settings.AI_CHAT_MODEL,      # 对话模型名称
            api_key=settings.AI_API_KEY,       # API Key
            base_url=settings.AI_BASE_URL,     # OpenAI 兼容接口地址
            temperature=0.3,                   # 低随机性, 减少编造
            timeout=60,                        # 单次请求超时秒数
            max_retries=2,                     # 网络抖动自动重试
        )
    # 返回单例
    return _chat_model


# 获取全局唯一的向量模型(交给 langchain-milvus 内部做文本向量化)
def get_embeddings() -> OpenAIEmbeddings:
    # 声明使用模块级变量
    global _embeddings
    # 首次调用时创建实例
    if _embeddings is None:
        # 按配置初始化, 参数适配百炼兼容接口
        _embeddings = OpenAIEmbeddings(
            model=settings.AI_EMBED_MODEL,     # 向量模型名称
            api_key=settings.AI_API_KEY,       # API Key
            base_url=settings.AI_BASE_URL,     # OpenAI 兼容接口地址
            dimensions=settings.AI_EMBED_DIM,  # 输出维度, 与 Milvus 集合对齐
            chunk_size=10,                     # 单批条数, 适配百炼 embedding 批量上限
            check_embedding_ctx_length=False,  # 关闭 tiktoken 预分词, 兼容非 OpenAI 官方端点
        )
    # 返回单例
    return _embeddings
