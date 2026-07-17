"""LLM 客户端模块: 基于 OpenAI 兼容协议提供文本向量化与流式对话能力。"""

# 导入异步生成器类型注解
from typing import AsyncGenerator

# 导入 OpenAI 官方异步客户端(兼容百炼/DeepSeek 等 OpenAI 协议服务)
from openai import AsyncOpenAI

# 导入全局配置
from app.core.config import settings

# 模块级客户端单例, 懒加载以复用底层 HTTP 连接池
_client: AsyncOpenAI | None = None

# 百炼 embedding 接口单次请求的最大文本条数
_EMBED_BATCH_SIZE = 10


# 判断 AI 功能是否可用(未配置 API Key 时前端展示降级提示)
def ai_enabled() -> bool:
    # 仅当配置了 API Key 才启用
    return bool(settings.AI_API_KEY)


# 获取全局唯一的异步客户端
def get_client() -> AsyncOpenAI:
    # 声明使用模块级变量
    global _client
    # 首次调用时创建实例
    if _client is None:
        # 使用配置中的 Key 与兼容接口地址初始化
        _client = AsyncOpenAI(
            api_key=settings.AI_API_KEY,
            base_url=settings.AI_BASE_URL,
        )
    # 返回单例
    return _client


# 批量文本向量化: 输入文本列表, 返回等长的向量列表
async def embed_texts(texts: list[str]) -> list[list[float]]:
    # 获取客户端
    client = get_client()
    # 结果向量列表
    vectors: list[list[float]] = []
    # 按接口上限分批请求, 避免单次超限
    for i in range(0, len(texts), _EMBED_BATCH_SIZE):
        # 取出当前批次
        batch = texts[i : i + _EMBED_BATCH_SIZE]
        # 调用向量化接口, 指定输出维度与集合配置一致
        resp = await client.embeddings.create(
            model=settings.AI_EMBED_MODEL,
            input=batch,
            dimensions=settings.AI_EMBED_DIM,
        )
        # 按 index 排序保证与输入顺序一致
        ordered = sorted(resp.data, key=lambda d: d.index)
        # 追加本批向量
        vectors.extend(d.embedding for d in ordered)
    # 返回全部向量
    return vectors


# 单条文本向量化的便捷封装(用于用户提问)
async def embed_text(text: str) -> list[float]:
    # 复用批量接口并取首个结果
    return (await embed_texts([text]))[0]


# 流式对话: 输入消息列表, 逐段产出模型生成的文本增量
async def chat_stream(messages: list[dict]) -> AsyncGenerator[str, None]:
    # 获取客户端
    client = get_client()
    # 发起流式对话请求
    stream = await client.chat.completions.create(
        model=settings.AI_CHAT_MODEL,
        messages=messages,
        stream=True,
        temperature=0.3,
    )
    # 逐块读取流式响应
    async for chunk in stream:
        # 取出增量内容(可能为空块)
        delta = chunk.choices[0].delta.content if chunk.choices else None
        # 仅产出非空文本
        if delta:
            # 交给上层拼装 SSE
            yield delta
