"""用户相关请求/响应数据模型(Pydantic)。"""

# 导入日期时间类型
from datetime import datetime

# 导入 Pydantic 基类与字段
from pydantic import BaseModel, Field


# 注册请求体
class RegisterReq(BaseModel):
    # 用户名, 长度 3-50
    username: str = Field(min_length=3, max_length=50)
    # 密码, 长度 6-50
    password: str = Field(min_length=6, max_length=50)
    # 昵称, 可选
    nickname: str = Field(default="", max_length=50)
    # 邮箱, 可选
    email: str = Field(default="", max_length=100)


# 登录请求体
class LoginReq(BaseModel):
    # 用户名
    username: str
    # 密码
    password: str


# 修改个人资料请求体, 字段均可选
class UpdateUserReq(BaseModel):
    # 昵称
    nickname: str | None = Field(default=None, max_length=50)
    # 头像
    avatar: str | None = Field(default=None, max_length=255)
    # 邮箱
    email: str | None = Field(default=None, max_length=100)


# 用户信息响应体
class UserOut(BaseModel):
    # 用户 ID
    id: int
    # 用户名
    username: str
    # 昵称
    nickname: str
    # 头像
    avatar: str
    # 邮箱
    email: str
    # 是否管理员
    is_admin: int
    # 创建时间
    create_time: datetime
    # 允许从 ORM 对象属性直接读取
    model_config = {"from_attributes": True}


# 登录成功响应体, 含令牌与用户信息
class LoginOut(BaseModel):
    # JWT 访问令牌
    token: str
    # 用户信息
    user: UserOut


# ---------- 管理端用户相关 schema ----------


# 标签简要信息(兴趣标签展示用)
class TagBrief(BaseModel):
    # 标签 ID
    id: int
    # 标签名称
    name: str


# 管理端用户详情响应(含状态与兴趣标签, 不含密码)
class AdminUserOut(BaseModel):
    # 用户 ID
    id: int
    # 用户名
    username: str
    # 昵称
    nickname: str
    # 头像
    avatar: str
    # 邮箱
    email: str
    # 状态: 1 正常 0 禁用
    status: int
    # 是否管理员
    is_admin: int
    # 创建时间
    create_time: datetime
    # 兴趣标签列表(复用文章标签)
    interest_tags: list[TagBrief] = Field(default_factory=list)


# 管理端用户分页响应
class AdminUserPageOut(BaseModel):
    # 总条数
    total: int
    # 当前页用户列表
    list: list[AdminUserOut]


# 管理端更新用户资料请求(字段均可选)
class AdminUpdateUserReq(BaseModel):
    # 昵称
    nickname: str | None = Field(default=None, max_length=50)
    # 邮箱
    email: str | None = Field(default=None, max_length=100)
    # 头像
    avatar: str | None = Field(default=None, max_length=255)
    # 状态: 1 正常 0 禁用
    status: int | None = Field(default=None, ge=0, le=1)
    # 是否管理员: 1 是 0 否
    is_admin: int | None = Field(default=None, ge=0, le=1)


# 管理端设置用户兴趣标签请求(全量替换)
class AdminSetUserTagsReq(BaseModel):
    # 标签 ID 列表(须为 tb_tag 中已存在的 ID)
    tag_ids: list[int] = Field(default_factory=list)
