"""AI 问答相关请求/响应数据模型(Pydantic)。"""

# 导入 Pydantic 基类与字段
from pydantic import BaseModel, Field


# AI 问答请求体(与拆分前的接口契约完全一致, 前端无需改动)
class AskReq(BaseModel):
    # 当前文章 ID, 必填
    article_id: int = Field(gt=0)
    # 用户问题, 限制长度防止提示词注入超长内容
    question: str = Field(min_length=1, max_length=500)
    # 检索范围: article=仅当前文章, series=当前系列(同分类)
    scope: str = Field(default="article", pattern="^(article|series)$")


# AI 问答配置响应
class AiConfigOut(BaseModel):
    # 功能是否可用(未配置对话模型 Key 时前端隐藏入口)
    enabled: bool
    # 预设引导问题
    preset_questions: list[str]


# 全量重建索引响应
class ReindexOut(BaseModel):
    # 处理的文章数
    articles: int = 0
    # 写入的分块总数
    chunks: int = 0
    # 失败的文章 ID
    failed: list[int] = []
