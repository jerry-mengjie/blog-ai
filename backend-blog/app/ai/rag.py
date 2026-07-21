"""RAG 问答模块: LangChain LCEL 链(提示词模板 | 对话模型 | 输出解析)流式生成回答。

检索范围仅两种(与产品需求一致):
- article: 只检索当前文章的分块
- series : 检索当前文章所属分类(系列)下所有文章的分块
"""

# 导入异步生成器类型注解
from typing import AsyncGenerator

# 导入 LangChain 输出解析器(把模型消息流转为纯文本流)
from langchain_core.output_parsers import StrOutputParser
# 导入 LangChain 对话提示词模板
from langchain_core.prompts import ChatPromptTemplate
# 导入可运行链类型注解
from langchain_core.runnables import Runnable

# 导入对话模型单例
from app.ai.llm import get_chat_model
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

# 用户消息模板: 阅读场景 + 检索上下文 + 问题
_USER_TEMPLATE = (
    "读者正在阅读文章《{title}》。\n\n"
    "检索到的文章片段:\n{context}\n\n"
    "读者的问题: {question}"
)

# 每篇文章底部展示的预设问题(经典引导问法)
PRESET_QUESTIONS = [
    "这篇文章的核心内容是什么?",
    "能举个例子说明吗?",
    "有没有更简单的方法?",
    "和本系列其他文章有什么区别?",
]

# 模块级 LCEL 链单例(无状态, 可跨请求复用)
_chain: Runnable | None = None


# 获取全局唯一的问答链: 提示词模板 | 对话模型 | 字符串解析器
def get_chain() -> Runnable:
    # 声明使用模块级变量
    global _chain
    # 首次调用时组装链
    if _chain is None:
        # 由系统约束与用户模板构建对话提示词
        prompt = ChatPromptTemplate.from_messages(
            [("system", _SYSTEM_PROMPT), ("human", _USER_TEMPLATE)]
        )
        # LCEL 管道组合: 模板渲染 -> 模型生成 -> 文本解析
        _chain = prompt | get_chat_model() | StrOutputParser()
    # 返回单例
    return _chain


# 检索阶段: 按范围过滤检索, 返回命中的分块列表
async def retrieve(
    question: str,
    article_id: int,
    category_id: int,
    scope: str,
) -> list[dict]:
    # series 范围且文章有分类: 检索同分类(系列)下所有文章
    if scope == "series" and category_id:
        # 按分类过滤检索
        return await search_chunks(question, category_id=category_id)
    # 默认范围: 仅检索当前文章
    return await search_chunks(question, article_id=article_id)


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


# 生成阶段: 以 LCEL 链流式产出回答文本
async def answer_stream(
    question: str,
    article_title: str,
    chunks: list[dict],
) -> AsyncGenerator[str, None]:
    # 流式执行链: 传入模板变量, 逐段产出文本增量
    async for token in get_chain().astream(
        {
            "title": article_title,          # 当前文章标题
            "context": _build_context(chunks),  # 检索上下文
            "question": question,            # 用户问题
        }
    ):
        # 仅产出非空文本
        if token:
            # 逐段交给上层写入 SSE
            yield token
