"""安全工具: 密码哈希校验 + JWT 令牌生成解析。"""

# 导入日期时间工具用于计算过期时间
from datetime import datetime, timedelta, timezone
# 导入类型注解
from typing import Any

# 导入 JWT 编解码库
from jose import JWTError, jwt
# 直接使用 bcrypt 库进行密码哈希(比 passlib 更稳定, 无版本兼容坑)
import bcrypt

# 导入全局配置
from app.core.config import settings


# bcrypt 单次最多处理 72 字节, 超出部分会被忽略, 这里统一截断保证一致性
def _to_bytes(password: str) -> bytes:
    # 将密码按 UTF-8 编码并截断到 72 字节
    return password.encode("utf-8")[:72]


# 对明文密码进行哈希加密
def hash_password(password: str) -> str:
    # 生成随机盐并计算哈希, 再解码为字符串存储
    return bcrypt.hashpw(_to_bytes(password), bcrypt.gensalt()).decode("utf-8")


# 校验明文密码与哈希是否匹配
def verify_password(plain: str, hashed: str) -> bool:
    # 捕获异常(如哈希格式非法)避免抛出 500
    try:
        # 使用 bcrypt 校验明文与哈希
        return bcrypt.checkpw(_to_bytes(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # 校验失败返回 False
        return False


# 生成 JWT 访问令牌, data 为要写入的载荷(如用户ID)
def create_access_token(data: dict[str, Any]) -> str:
    # 复制载荷, 避免修改原始字典
    to_encode = data.copy()
    # 计算过期时间点(当前 UTC 时间 + 配置的分钟数)
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    # 将过期时间写入标准声明 exp
    to_encode.update({"exp": expire})
    # 使用密钥与算法编码生成令牌字符串
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


# 解析并校验 JWT 令牌, 成功返回载荷字典, 失败返回 None
def decode_access_token(token: str) -> dict[str, Any] | None:
    # 捕获解码异常(过期/签名错误等)
    try:
        # 解码令牌, 自动校验签名与过期时间
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        # 校验失败返回 None, 由调用方处理为 401
        return None
