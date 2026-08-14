"""JWT 解析: 只验签不签发。

令牌由 backend-blog 签发, 本服务共享同一个 SECRET_KEY 做本地验签,
因此「识别用户身份」这一步零网络开销 —— 这是 JWT 相比会话方案在微服务下的核心优势。
"""

# 导入类型注解
from typing import Any

# 导入 JWT 编解码库
from jose import JWTError, jwt

# 导入全局配置
from app.core.config import settings


# 解析并校验 JWT 令牌, 成功返回载荷字典, 失败返回 None
def decode_access_token(token: str) -> dict[str, Any] | None:
    # 捕获解码异常(过期/签名错误等)
    try:
        # 解码令牌, 自动校验签名与过期时间
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        # 校验失败返回 None, 由调用方处理为 401 或按匿名处理
        return None


# 从 Authorization 请求头中提取用户 ID; 无令牌/令牌无效均返回 None
def user_id_from_header(authorization: str) -> int | None:
    # 无 Bearer 令牌视为匿名访问
    if not authorization.startswith("Bearer "):
        # 匿名
        return None
    # 解析令牌载荷
    payload = decode_access_token(authorization[7:])
    # 载荷缺少用户标识同样按匿名处理
    if not payload or "sub" not in payload:
        # 匿名
        return None
    # 载荷中的 sub 可能是字符串, 统一转 int
    try:
        # 返回用户 ID
        return int(payload["sub"])
    except (TypeError, ValueError):
        # 载荷异常按匿名处理
        return None
