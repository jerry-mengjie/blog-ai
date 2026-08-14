"""推荐模块 Pydantic 模型: 推荐文章卡片与列表响应。"""

# 导入 Pydantic 基类
from pydantic import BaseModel


# 单张推荐文章卡片
class RecArticleOut(BaseModel):
    # 文章 ID
    id: int
    # 标题
    title: str = ""
    # 封面图 URL
    cover: str = ""
    # 摘要
    summary: str = ""
    # 浏览量
    view_count: int = 0
    # 召回策略: profile 画像向量 / tag 兴趣标签 / fallback 兜底
    strategy: str = "fallback"


# 推荐列表响应
class RecListOut(BaseModel):
    # 推荐文章卡片列表(字段名与其他分页响应保持一致; 不设默认值以免类属性遮蔽 list 类型)
    list: list[RecArticleOut]
