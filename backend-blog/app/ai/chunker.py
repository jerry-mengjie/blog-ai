"""文本分块模块: 将文章正文切分为带重叠的语义块, 供向量化与检索使用。"""

# 导入全局配置
from app.core.config import settings


# 将长文本切分为多个目标长度的块, 相邻块保留重叠以避免语义被边界切断
def split_text(
    text: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    # 未显式传参时使用全局配置
    chunk_size = chunk_size or settings.RAG_CHUNK_SIZE
    # 重叠长度同理
    overlap = overlap or settings.RAG_CHUNK_OVERLAP
    # 去除首尾空白
    text = text.strip()
    # 空文本直接返回空列表
    if not text:
        # 无内容可分
        return []
    # 优先按空行(段落)切分, 保持语义完整
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    # 结果块列表
    chunks: list[str] = []
    # 当前累积缓冲
    buffer = ""
    # 逐段落累积到目标长度
    for para in paragraphs:
        # 单段落超长时先冲出缓冲再按窗口硬切
        if len(para) > chunk_size:
            # 先保存已累积内容
            if buffer:
                # 写入结果
                chunks.append(buffer)
                # 清空缓冲
                buffer = ""
            # 滑动窗口硬切超长段落, 步长 = 块长 - 重叠
            step = chunk_size - overlap
            # 按步长切片
            for start in range(0, len(para), step):
                # 截取窗口内文本
                piece = para[start : start + chunk_size]
                # 忽略过短的尾部碎片(已被上一窗口的重叠覆盖)
                if len(piece) > overlap or start == 0:
                    # 写入结果
                    chunks.append(piece)
            # 处理下一段落
            continue
        # 缓冲加上本段后超限则先落块
        if buffer and len(buffer) + len(para) + 1 > chunk_size:
            # 写入结果
            chunks.append(buffer)
            # 新缓冲以上一块尾部作为重叠开头, 保持上下文连续
            buffer = buffer[-overlap:] + "\n" + para if overlap else para
        else:
            # 未超限则继续累积(段落间以换行连接)
            buffer = f"{buffer}\n{para}" if buffer else para
    # 收尾: 缓冲中剩余内容作为最后一块
    if buffer:
        # 写入结果
        chunks.append(buffer)
    # 返回全部块
    return chunks
