"""文本分块模块: 基于 LangChain RecursiveCharacterTextSplitter 的经典分块方案。

按分隔符优先级递归切分(段落 > 换行 > 中文句读 > 空格), 尽量保持语义完整,
相邻块保留重叠字符, 避免语义在块边界被切断。
"""

# 导入 LangChain 递归字符分块器
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 导入全局配置
from app.core.config import settings

# 模块级分块器单例(无状态, 可安全复用)
_splitter: RecursiveCharacterTextSplitter | None = None


# 获取全局唯一的分块器
def get_splitter() -> RecursiveCharacterTextSplitter:
    # 声明使用模块级变量
    global _splitter
    # 首次调用时创建实例
    if _splitter is None:
        # 分隔符按优先级排列: 优先按段落切, 再按行, 再按中文句读, 最后硬切
        _splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.RAG_CHUNK_SIZE,        # 单块目标字符数
            chunk_overlap=settings.RAG_CHUNK_OVERLAP,  # 相邻块重叠字符数
            separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
        )
    # 返回单例
    return _splitter


# 将长文本切分为语义块列表
def split_text(text: str) -> list[str]:
    # 去除首尾空白
    text = text.strip()
    # 空文本直接返回空列表
    if not text:
        # 无内容可分
        return []
    # 调用分块器切分并返回
    return get_splitter().split_text(text)
