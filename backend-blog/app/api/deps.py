"""路由依赖: 解析 JWT 获取当前用户, 以及管理员权限校验。"""

# 导入 FastAPI 依赖工具与异常
from fastapi import Depends, Header, HTTPException, status
# 导入异步会话类型
from sqlalchemy.ext.asyncio import AsyncSession
# 导入查询构造器
from sqlalchemy import select

# 导入数据库会话依赖
from app.core.database import get_db
# 导入令牌解析函数
from app.core.security import decode_access_token
# 导入用户模型
from app.models.user import User


# 依赖: 从请求头 Authorization 中解析 Bearer 令牌并返回当前用户对象
async def get_current_user(
    # 从请求头读取 Authorization 字段
    authorization: str = Header(default=""),
    # 注入数据库会话
    db: AsyncSession = Depends(get_db),
) -> User:
    # 校验请求头是否以 Bearer 开头
    if not authorization.startswith("Bearer "):
        # 缺失令牌返回 401
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或令牌缺失"
        )
    # 截取实际令牌字符串
    token = authorization[7:]
    # 解析令牌得到载荷
    payload = decode_access_token(token)
    # 校验载荷是否有效且包含用户 ID
    if not payload or "sub" not in payload:
        # 无效令牌返回 401
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌无效或已过期"
        )
    # 根据载荷中的用户 ID 查询用户
    result = await db.execute(select(User).where(User.id == int(payload["sub"])))
    # 取出唯一用户(可能为 None)
    user = result.scalar_one_or_none()
    # 用户不存在或被禁用返回 401
    if not user or user.status != 1:
        # 用户不可用
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已被禁用"
        )
    # 返回当前用户对象
    return user


# 依赖: 可选登录, 解析成功返回用户, 未登录/令牌无效返回 None(推荐等公开接口用)
async def get_current_user_optional(
    # 从请求头读取 Authorization 字段(允许为空)
    authorization: str = Header(default=""),
    # 注入数据库会话
    db: AsyncSession = Depends(get_db),
) -> User | None:
    # 无 Bearer 令牌视为匿名访问
    if not authorization.startswith("Bearer "):
        # 匿名返回 None, 不抛异常
        return None
    # 截取实际令牌字符串
    token = authorization[7:]
    # 解析令牌得到载荷
    payload = decode_access_token(token)
    # 令牌无效同样按匿名处理
    if not payload or "sub" not in payload:
        # 匿名返回 None
        return None
    # 根据载荷中的用户 ID 查询用户
    result = await db.execute(select(User).where(User.id == int(payload["sub"])))
    # 取出唯一用户(可能为 None)
    user = result.scalar_one_or_none()
    # 用户不存在或被禁用按匿名处理
    if not user or user.status != 1:
        # 匿名返回 None
        return None
    # 返回当前用户对象
    return user


# 依赖: 在登录基础上进一步校验是否为管理员(RBAC 后台权限控制)
async def require_admin(
    # 复用当前用户依赖
    current: User = Depends(get_current_user),
) -> User:
    # 校验管理员标识
    if current.is_admin != 1:
        # 非管理员返回 403 禁止访问
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限"
        )
    # 返回管理员用户对象
    return current
