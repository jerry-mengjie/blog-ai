"""对话模型: LangChain ChatOpenAI 全局单例。

经典方案: langchain-openai 的 ChatOpenAI 通过 OpenAI 兼容协议对接阿里云百炼
(也可换 DeepSeek / OpenAI 等任意兼容服务), 只需改 .env 中的地址与模型名。

性能要点:
1. 进程级单例, 复用底层 httpx 连接池, 避免每次问答重新握手 TLS
2. streaming=True: 模型侧逐 token 返回, 配合 LangGraph 的 messages 流模式
   让首字延迟从「整段生成完」降到「模型吐出第一个 token」
3. 低温度 + 有限重试, 在稳定性与响应时间之间取平衡
"""

# 导入 LangChain 的 OpenAI 兼容对话模型
from langchain_openai import ChatOpenAI

# 导入全局配置
from app.core.config import settings

# 模块级对话模型单例
_chat_model: ChatOpenAI | None = None


# 判断 AI 能力是否可用(未配置 API Key 时前端隐藏问答入口)
def ai_enabled() -> bool:
    # 仅当配置了 API Key 才启用
    return bool(settings.AI_API_KEY)


# 获取全局唯一的对话模型
def get_chat_model() -> ChatOpenAI:
    # 声明使用模块级变量
    global _chat_model
    # 首次调用时创建实例
    if _chat_model is None:
        # 按配置初始化
        _chat_model = ChatOpenAI(
            model=settings.AI_CHAT_MODEL,        # 对话模型名称
            api_key=settings.AI_API_KEY,         # API Key
            base_url=settings.AI_BASE_URL,       # OpenAI 兼容接口地址
            temperature=settings.AI_TEMPERATURE,  # 低随机性, 减少编造
            timeout=settings.AI_TIMEOUT,         # 单次请求超时秒数
            max_retries=settings.AI_MAX_RETRIES,  # 网络抖动自动重试
            streaming=True,                      # 流式输出, 显著降低首字延迟
        )
    # 返回单例
    return _chat_model
