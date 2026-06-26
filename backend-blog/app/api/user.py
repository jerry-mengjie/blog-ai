"""用户模块路由: 注册/登录/获取信息/修改资料/退出 (5 个接口)。"""

# 导入路由与依赖工具
from fastapi import APIRouter, Depends, HTTPException
# 导入查询构造器
from sqlalchemy import select
# 导入异步会话类型
from sqlalchemy.ext.asyncio import AsyncSession

# 导入数据库会话依赖
from app.core.database import get_db
# 导入密码工具与令牌生成
from app.core.security import create_access_token, hash_password, verify_password
# 导入统一响应
from app.core.response import Result, ok
# 导入当前用户依赖
from app.api.deps import get_current_user
# 导入用户模型
from app.models.user import User
# 导入用户相关 schema
from app.schemas.user import (
    LoginOut,
    LoginReq,
    RegisterReq,
    UpdateUserReq,
    UserOut,
)

# 创建用户路由, 统一前缀 /api/user, 文档标签为"用户模块"
router = APIRouter(prefix="/api/user", tags=["用户模块"])


# 1. 用户注册
@router.post("/register", response_model=Result, summary="用户注册")
async def register(body: RegisterReq, db: AsyncSession = Depends(get_db)):
    # 查询用户名是否已存在
    exists = await db.execute(select(User.id).where(User.username == body.username))
    # 已存在则报错
    if exists.scalar_one_or_none():
        # 用户名重复
        raise HTTPException(status_code=400, detail="用户名已存在")
    # 构造新用户对象, 密码哈希存储
    user = User(
        username=body.username,
        password=hash_password(body.password),
        nickname=body.nickname or body.username,
        email=body.email,
    )
    # 加入会话
    db.add(user)
    # 提交事务写入数据库
    await db.commit()
    # 刷新以获取自增 ID
    await db.refresh(user)
    # 返回用户信息
    return ok(UserOut.model_validate(user))


# 2. 用户登录
@router.post("/login", response_model=Result, summary="用户登录")
async def login(body: LoginReq, db: AsyncSession = Depends(get_db)):
    # 按用户名查询用户
    result = await db.execute(select(User).where(User.username == body.username))
    # 取出用户
    user = result.scalar_one_or_none()
    # 校验用户存在且密码正确
    if not user or not verify_password(body.password, user.password):
        # 凭证错误
        raise HTTPException(status_code=400, detail="用户名或密码错误")
    # 校验账号状态
    if user.status != 1:
        # 账号被禁用
        raise HTTPException(status_code=403, detail="账号已被禁用")
    # 生成 JWT 令牌, sub 存放用户 ID
    token = create_access_token({"sub": str(user.id), "is_admin": user.is_admin})
    # 返回令牌与用户信息
    return ok(LoginOut(token=token, user=UserOut.model_validate(user)))


# 3. 获取个人信息
@router.get("/info", response_model=Result, summary="获取个人信息")
async def get_info(current: User = Depends(get_current_user)):
    # 直接返回当前登录用户信息
    return ok(UserOut.model_validate(current))


# 4. 修改个人资料
@router.put("/info", response_model=Result, summary="修改个人资料")
async def update_info(
    body: UpdateUserReq,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 仅更新传入的非空字段
    if body.nickname is not None:
        # 更新昵称
        current.nickname = body.nickname
    if body.avatar is not None:
        # 更新头像
        current.avatar = body.avatar
    if body.email is not None:
        # 更新邮箱
        current.email = body.email
    # 提交修改
    await db.commit()
    # 刷新对象
    await db.refresh(current)
    # 返回更新后的信息
    return ok(UserOut.model_validate(current))


# 5. 退出登录
@router.post("/logout", response_model=Result, summary="退出登录")
async def logout(current: User = Depends(get_current_user)):
    # JWT 为无状态令牌, 退出由前端清除本地令牌即可, 此处仅返回成功
    return ok(message="已退出登录")
