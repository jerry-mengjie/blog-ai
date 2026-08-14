"""路由依赖: 服务间令牌校验与 RAG 可用性校验。

本服务只对内网暴露, 不面向浏览器, 因此鉴权用一个共享的服务间令牌即可,
不需要 JWT / 用户体系 —— 用户身份由 backend-blog 与 backend-agent 负责。
"""

# 导入 FastAPI 依赖工具与异常
from fastapi import Header, HTTPException, status

# 导入全局配置
from app.core.config import settings
# 导入 RAG 开关
from app.rag.models import rag_enabled


# 依赖: 校验服务间调用令牌(未配置令牌时跳过, 便于本地开发)
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


# 依赖: 校验 RAG 能力是否可用(未配置向量模型 Key 时整体降级)
async def require_rag_enabled() -> None:
    # 未启用返回 503, 由上游决定降级方案
    if not rag_enabled():
        # 明确告知未配置
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG 服务未启用(缺少向量模型 API Key)",
        )
