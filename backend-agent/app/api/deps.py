"""路由依赖: 身份识别、管理员校验、AI 可用性校验、服务间令牌校验。

身份识别只做本地 JWT 验签(零网络); 只有「管理员操作」这种低频高危动作
才额外向 backend-blog 核对账号的实时状态, 避免令牌签发后权限被回收却仍然生效。
"""

# 导入 FastAPI 依赖工具与异常
from fastapi import Header, HTTPException, status

# 导入 backend-blog 客户端
from app.clients import blog as blog_client
# 导入服务调用异常
from app.clients.http import ServiceError
# 导入全局配置
from app.core.config import settings
# 导入 JWT 解析
from app.core.security import user_id_from_header
# 导入 AI 开关
from app.llm.models import ai_enabled


# 依赖: 可选登录, 解析成功返回用户 ID, 未登录/令牌无效返回 None
async def current_user_id_optional(
    # 从请求头读取 Authorization 字段(允许为空)
    authorization: str = Header(default=""),
) -> int | None:
    # 本地验签, 不产生网络调用
    return user_id_from_header(authorization)


# 依赖: 要求管理员身份(先本地验签, 再向 blog 核对实时权限)
async def require_admin(
    # 从请求头读取 Authorization 字段
    authorization: str = Header(default=""),
) -> int:
    # 本地解析用户 ID
    user_id = user_id_from_header(authorization)
    # 无有效令牌返回 401
    if user_id is None:
        # 未登录
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或令牌无效"
        )
    # 向 backend-blog 核对账号状态与管理员标识
    try:
        # 查询用户实时状态
        state = await blog_client.get_user_state(user_id)
    except ServiceError as exc:
        # 无法核对权限时拒绝而非放行
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="无法校验用户权限"
        ) from exc
    # 账号不存在或已被禁用
    if not state or int(state.get("status") or 0) != 1:
        # 拒绝访问
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已被禁用"
        )
    # 非管理员返回 403
    if int(state.get("is_admin") or 0) != 1:
        # 权限不足
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限"
        )
    # 返回管理员用户 ID
    return user_id


# 依赖: 校验 AI 能力是否可用(未配置对话模型 Key 时返回 503)
async def require_ai_enabled() -> None:
    # 未启用返回 503
    if not ai_enabled():
        # 明确告知未配置
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AI 问答功能未启用"
        )


# 依赖: 校验服务间调用令牌(供 backend-blog 调用本服务的内部接口)
async def verify_internal_token(
    # 从请求头读取令牌
    x_internal_token: str = Header(default=""),
) -> None:
    # 未配置则不校验
    if not settings.INTERNAL_TOKEN:
        # 本地开发直通
        return
    # 令牌不匹配返回 401
    if x_internal_token != settings.INTERNAL_TOKEN:
        # 拒绝非法调用
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="服务间令牌无效"
        )
