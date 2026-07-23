"""用户文章浏览统计: 请求/响应数据模型(Pydantic)。"""

# 导入日期时间类型
from datetime import datetime

# 导入 Pydantic 基类与字段
from pydantic import BaseModel, Field


# 上报一次浏览会话(登录用户)
class BrowseReportReq(BaseModel):
    # 文章 ID
    article_id: int = Field(ge=1)
    # 本次停留秒数(0 也计一次打开; 上限由服务层裁剪防刷)
    duration: int = Field(default=0, ge=0, le=7200)


# 浏览记录条目(含文章摘要字段, 供列表展示)
class BrowseItemOut(BaseModel):
    # 记录 ID
    id: int
    # 用户 ID
    user_id: int
    # 文章 ID
    article_id: int
    # 文章标题(联表)
    title: str = ""
    # 文章封面(联表)
    cover: str = ""
    # 文章摘要(联表)
    summary: str = ""
    # 浏览总次数
    view_count: int
    # 总时长(秒)
    total_duration: int
    # 单次最长时长(秒)
    best_duration: int
    # 最好浏览时间
    best_browse_time: datetime | None = None
    # 最近浏览时间
    last_browse_time: datetime
    # 用户名(管理端展示, C 端可空)
    username: str = ""
    # 昵称(管理端展示)
    nickname: str = ""


# 浏览记录分页响应
class BrowsePageOut(BaseModel):
    # 总条数
    total: int
    # 当前页列表
    list: list[BrowseItemOut]
