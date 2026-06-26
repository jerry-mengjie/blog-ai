"""全局配置模块: 通过 pydantic-settings 从 .env 读取配置。"""

# 从 pydantic_settings 导入配置基类
from pydantic_settings import BaseSettings, SettingsConfigDict


# 定义配置类, 字段名与 .env 中的键(忽略大小写)对应
class Settings(BaseSettings):
    # 数据库异步连接 URL
    DATABASE_URL: str
    # JWT 签名密钥
    SECRET_KEY: str
    # JWT 算法
    ALGORITHM: str = "HS256"
    # 令牌过期时间(分钟)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080
    # 允许跨域的来源, 字符串形式(逗号分隔), 读取后再切分
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:5174"

    # 计算属性: 将逗号分隔的来源字符串转为列表, 供 CORS 中间件使用
    @property
    def cors_origins_list(self) -> list[str]:
        # 按逗号切分并去除首尾空白, 过滤空字符串
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    # 指定读取 .env 文件、编码及忽略多余字段
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


# 实例化全局唯一配置对象, 供其他模块导入使用
settings = Settings()
