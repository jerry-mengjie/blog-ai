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
