"""提示词: 阅读助手的系统约束与用户消息模板。

提示词集中在一个模块里, 调整措辞不必翻动编排代码。
"""

# 导入 LangChain 对话提示词模板
from langchain_core.prompts import ChatPromptTemplate

# 系统提示词: 约束模型只依据检索到的文章内容作答
SYSTEM_PROMPT = (
    "你是一个博客网站的读者助手, 负责解答读者关于文章内容的疑问。\n"
    "要求:\n"
    "1. 只依据下面提供的文章片段回答, 不要编造片段之外的内容;\n"
    "2. 若片段不足以回答, 直接说明文章中没有提到, 可以给出简短的常识性提示;\n"
    "3. 回答使用中文, 简洁清晰, 适合在手机上阅读;\n"
    "4. 涉及多篇文章时, 用文章标题指明信息来源。"
)

# 用户消息模板: 阅读场景 + 检索上下文 + 问题
USER_TEMPLATE = (
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

# 未检索到任何片段时的上下文占位, 让模型明确知道无资料可依
EMPTY_CONTEXT = "(未检索到相关文章片段)"


# 构建问答提示词模板(模块级复用, 无状态)
def build_qa_prompt() -> ChatPromptTemplate:
    # 由系统约束与用户模板组合
    return ChatPromptTemplate.from_messages(
        [("system", SYSTEM_PROMPT), ("human", USER_TEMPLATE)]
    )
