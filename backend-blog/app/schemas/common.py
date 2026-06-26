"""分类/标签/评论/收藏 的请求与响应数据模型。"""

# 导入日期时间类型
from datetime import datetime

# 导入 Pydantic 基类与字段
from pydantic import BaseModel, Field


# 新增分类请求体
class CategoryCreateReq(BaseModel):
    # 分类名称
    name: str = Field(min_length=1, max_length=50)
    # 排序值
    sort: int = 0


# 分类响应体
class CategoryOut(BaseModel):
    # 分类 ID
    id: int
    # 名称
    name: str
    # 排序
    sort: int
    # 允许从 ORM 读取
    model_config = {"from_attributes": True}


# 新增标签请求体
class TagCreateReq(BaseModel):
    # 标签名称
    name: str = Field(min_length=1, max_length=50)


# 标签响应体
class TagOut(BaseModel):
    # 标签 ID
    id: int
    # 名称
    name: str
    # 允许从 ORM 读取
    model_config = {"from_attributes": True}


# 发表评论请求体
class CommentCreateReq(BaseModel):
    # 文章 ID
    article_id: int
    # 评论内容
    content: str = Field(min_length=1, max_length=1000)
    # 父评论 ID, 0 为顶级评论
    parent_id: int = 0


# 评论响应体
class CommentOut(BaseModel):
    # 评论 ID
    id: int
    # 文章 ID
    article_id: int
    # 用户 ID
    user_id: int
    # 父评论 ID
    parent_id: int
    # 内容
    content: str
    # 创建时间
    create_time: datetime
    # 评论者昵称(联表查询填充)
    nickname: str = ""
    # 评论者头像
    avatar: str = ""


# 收藏/取消收藏请求体
class FavoriteReq(BaseModel):
    # 文章 ID
    article_id: int
