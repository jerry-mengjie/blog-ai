"""内部接口的请求/响应模型: backend-agent / backend-rag 调用本服务的契约。

这些模型只在服务之间使用, 不对浏览器暴露, 因此字段以「下游好用」为准,
不必迁就前端的展示结构。
"""

# 导入 Pydantic 基类与字段
from pydantic import BaseModel, Field


# ---------- 内容 ----------
# 文章元信息(问答前校验文章可用性)
class ArticleMetaOut(BaseModel):
    # 文章 ID
    article_id: int
    # 标题
    title: str = ""
    # 分类 ID(0 表示无分类)
    category_id: int = 0
    # 状态: 1 已发布
    status: int = 0


# 文章索引文档(检索服务全量重建时回源拉取)
class ArticleDocumentOut(BaseModel):
    # 文章 ID
    article_id: int
    # 标题
    title: str = ""
    # 分类 ID
    category_id: int = 0
    # 正文
    content: str = ""
    # 状态: 1 已发布
    status: int = 0


# 可索引文章 ID 列表
class IndexableIdsOut(BaseModel):
    # 全部已发布文章的 ID
    ids: list[int]


# 用户账号状态(管理操作前二次校验权限)
class UserStateOut(BaseModel):
    # 用户 ID
    user_id: int
    # 是否管理员: 1 是
    is_admin: int = 0
    # 状态: 1 正常
    status: int = 0


# ---------- 推荐取数 ----------
# 单条浏览行为
class BrowseRowOut(BaseModel):
    # 文章 ID
    article_id: int
    # 阅读次数
    view_count: int = 0
    # 累计停留秒数
    total_duration: int = 0


# 用户行为原始数据
class BehaviorOut(BaseModel):
    # 最近的浏览记录
    browses: list[BrowseRowOut]
    # 收藏文章 ID
    favorite_ids: list[int]


# 标签召回请求
class TagRecallReq(BaseModel):
    # 目标用户
    user_id: int = Field(gt=0)
    # 需要排除的文章 ID
    exclude_ids: list[int] = []
    # 召回数量
    limit: int = Field(default=12, ge=1, le=200)


# 兜底召回请求
class FallbackRecallReq(BaseModel):
    # 需要排除的文章 ID
    exclude_ids: list[int] = []
    # 召回数量
    limit: int = Field(default=12, ge=1, le=200)


# 单条召回候选
class RecallItemOut(BaseModel):
    # 文章 ID
    article_id: int
    # 召回得分(标签召回记热度, 兜底为 0)
    score: float = 0.0


# 召回结果
class RecallOut(BaseModel):
    # 候选列表
    items: list[RecallItemOut]


# 卡片批量查询请求
class CardsReq(BaseModel):
    # 目标文章 ID 列表
    article_ids: list[int] = Field(default=[], max_length=200)


# 单张文章卡片
class ArticleCardOut(BaseModel):
    # 文章 ID
    id: int
    # 标题
    title: str = ""
    # 封面
    cover: str = ""
    # 摘要
    summary: str = ""
    # 浏览量
    view_count: int = 0


# 卡片批量查询结果
class CardsOut(BaseModel):
    # 卡片列表(顺序由调用方按候选顺序重排)
    items: list[ArticleCardOut]
