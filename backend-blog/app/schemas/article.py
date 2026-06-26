"""文章相关请求/响应数据模型(Pydantic)。"""

# 导入日期时间类型
from datetime import datetime

# 导入 Pydantic 基类与字段
from pydantic import BaseModel, Field


# 发布文章请求体
class ArticleCreateReq(BaseModel):
    # 标题, 必填
    title: str = Field(min_length=1, max_length=200)
    # 封面图, 可选
    cover: str = Field(default="", max_length=255)
    # 正文, 必填
    content: str = Field(min_length=1)
    # 摘要, 可选
    summary: str = Field(default="", max_length=500)
    # 分类 ID
    category_id: int = 0
    # 是否置顶
    is_top: int = 0
    # 标签 ID 列表(多对多)
    tag_ids: list[int] = Field(default_factory=list)


# 编辑文章请求体, 字段均可选
class ArticleUpdateReq(BaseModel):
    # 标题
    title: str | None = Field(default=None, max_length=200)
    # 封面
    cover: str | None = Field(default=None, max_length=255)
    # 正文
    content: str | None = None
    # 摘要
    summary: str | None = Field(default=None, max_length=500)
    # 分类
    category_id: int | None = None
    # 置顶
    is_top: int | None = None
    # 状态
    status: int | None = None
    # 标签列表(传入则全量覆盖)
    tag_ids: list[int] | None = None


# 文章列表项响应体(不含正文大字段, 提升列表性能)
class ArticleListItem(BaseModel):
    # 文章 ID
    id: int
    # 标题
    title: str
    # 封面
    cover: str
    # 摘要
    summary: str
    # 分类 ID
    category_id: int
    # 浏览量
    view_count: int
    # 是否置顶
    is_top: int
    # 创建时间
    create_time: datetime
    # 允许从 ORM 读取
    model_config = {"from_attributes": True}


# 文章详情响应体(含正文)
class ArticleDetail(ArticleListItem):
    # 作者 ID
    user_id: int
    # 正文
    content: str
    # 更新时间
    update_time: datetime
    # 标签名称列表
    tags: list[str] = Field(default_factory=list)


# 通用分页响应体
class PageOut(BaseModel):
    # 总条数
    total: int
    # 当前页数据列表
    list: list[ArticleListItem]
