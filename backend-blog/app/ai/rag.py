"""RAG 问答模块: 检索文章分块构建提示词, 并流式生成回答。

检索范围仅两种(与产品需求一致):
- article: 只检索当前文章的分块
- series : 检索当前文章所属分类(系列)下所有文章的分块
"""

# 导入异步生成器类型注解
from typing import AsyncGenerator

# 导入对话与向量化能力
from app.ai.llm import chat_stream, embed_text
# 导入向量检索
from app.ai.vector_store import search_chunks

# 系统提示词: 约束模型只依据检索到的文章内容作答
_SYSTEM_PROMPT = (
    "你是一个博客网站的读者助手, 负责解答读者关于文章内容的疑问。\n"
    "要求:\n"
    "1. 只依据下面提供的文章片段回答, 不要编造片段之外的内容;\n"
    "2. 若片段不足以回答, 直接说明文章中没有提到, 可以给出简短的常识性提示;\n"
    "3. 回答使用中文, 简洁清晰, 适合在手机上阅读;\n"
    "4. 涉及多篇文章时, 用文章标题指明信息来源。"
)

# 每篇文章底部展示的预设问题(经典引导问法)
PRESET_QUESTIONS = [
    "这篇文章的核心内容是什么?",
    "能举个例子说明吗?",
    "有没有更简单的方法?",
    "和本系列其他文章有什么区别?",
]


# 检索阶段: 向量化问题并按范围过滤检索, 返回命中的分块列表
async def retrieve(
    question: str,
    article_id: int,
    category_id: int,
    scope: str,
) -> list[dict]:
    # 将用户问题向量化
    query_vector = await embed_text(question)
    # series 范围且文章有分类: 检索同分类(系列)下所有文章
    if scope == "series" and category_id:
        # 按分类过滤检索
        return await search_chunks(query_vector, category_id=category_id)
    # 默认范围: 仅检索当前文章
    return await search_chunks(query_vector, article_id=article_id)


# 从命中分块中提取去重后的来源文章列表(供前端展示引用)
def extract_sources(chunks: list[dict]) -> list[dict]:
    # 以 (id, title) 去重后按文章 ID 排序
    unique = sorted({(c["article_id"], c["title"]) for c in chunks})
    # 转为字典列表
    return [{"article_id": aid, "title": title} for aid, title in unique]


# 将检索到的分块拼装为提示词中的上下文文本
def _build_context(chunks: list[dict]) -> str:
    # 无命中时返回明确标记, 让模型知道无可用资料
    if not chunks:
        # 空上下文占位
        return "(未检索到相关文章片段)"
    # 按 "来源文章 + 原文顺序" 排序, 保持上下文连贯
    ordered = sorted(chunks, key=lambda c: (c["article_id"], c["chunk_index"]))
    # 每个片段标注来源标题, 便于模型引用
    return "\n\n".join(
        f"【片段 {i + 1} · 来自《{c['title']}》】\n{c['text']}"
        for i, c in enumerate(ordered)
    )


# 生成阶段: 基于检索结果构建提示词, 流式产出回答文本
async def answer_stream(
    question: str,
    article_title: str,
    chunks: list[dict],
) -> AsyncGenerator[str, None]:
    # 拼装检索上下文
    context = _build_context(chunks)
    # 组装对话消息: 系统约束 + 上下文 + 用户问题
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"读者正在阅读文章《{article_title}》。\n\n"
                f"检索到的文章片段:\n{context}\n\n"
                f"读者的问题: {question}"
            ),
        },
    ]
    # 流式产出模型回答
    async for delta in chat_stream(messages):
        # 逐段交给上层写入 SSE
        yield delta
