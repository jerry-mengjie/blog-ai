"""全局配置模块: 通过 pydantic-settings 从 .env 读取配置。

拆分为微服务后本服务只保留「业务」相关配置:
- MySQL / Redis / RocketMQ / JWT 归本服务
- 向量库、分块、检索参数归 backend-rag; 对话模型、推荐参数归 backend-agent
这里只需要知道两个下游服务的地址与共享的服务间令牌。
"""

# 从 pydantic_settings 导入配置基类
from pydantic_settings import BaseSettings, SettingsConfigDict


# 定义配置类, 字段名与 .env 中的键(忽略大小写)对应
class Settings(BaseSettings):
    # 数据库异步连接 URL (MySQL 9.7 + aiomysql)
    DATABASE_URL: str
    # 连接池常驻连接数
    DB_POOL_SIZE: int = 20
    # 连接池溢出上限
    DB_MAX_OVERFLOW: int = 10
    # 连接回收秒数, 略小于 MySQL wait_timeout(28800)
    DB_POOL_RECYCLE: int = 28000
    # 从池中获取连接的超时秒数
    DB_POOL_TIMEOUT: int = 30
    # 建立 TCP 连接超时秒数
    DB_CONNECT_TIMEOUT: int = 10
    # JWT 签名密钥
    SECRET_KEY: str
    # JWT 算法
    ALGORITHM: str = "HS256"
    # 令牌过期时间(分钟)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080
    # 允许跨域的来源, 字符串形式(逗号分隔), 读取后再切分
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:5174"

    # ---------- 服务间调用 ----------
    # 服务间调用令牌: 保护 /internal/* 接口, 三个后端服务必须一致; 空则不校验
    INTERNAL_TOKEN: str = ""
    # backend-rag 地址(文章变更后推送索引); 为空则关闭索引同步
    RAG_BASE_URL: str = "http://127.0.0.1:8002"
    # backend-agent 地址(文章变更后通知失效推荐缓存); 为空则关闭通知
    AGENT_BASE_URL: str = "http://127.0.0.1:8001"
    # 服务间 HTTP 超时秒数(全部为后台通知调用, 取较短值快速放弃)
    SERVICE_HTTP_TIMEOUT: float = 10.0
    # 服务间 HTTP 连接池上限
    SERVICE_HTTP_MAX_CONNECTIONS: int = 50

    # ---------- Redis(文章列表多级缓存 L2) ----------
    # 主机; 为空则关闭 Redis, 列表仅用进程内 L1
    REDIS_HOST: str = "127.0.0.1"
    # 端口(docker -p 6379:6379)
    REDIS_PORT: int = 6379
    # 密码(与 redis-server --requirepass 一致)
    REDIS_PASSWORD: str = "123456"
    # 逻辑库编号
    REDIS_DB: int = 0
    # 连接池上限, 避免瞬时打满 Redis
    REDIS_MAX_CONNECTIONS: int = 50
    # 建连/读写超时秒数, 超时快速失败走回源
    REDIS_SOCKET_TIMEOUT: float = 2.0
    # 文章列表第 1 页缓存 TTL(秒)
    ARTICLE_LIST_CACHE_TTL: int = 60
    # L1 本地缓存最大条目数
    ARTICLE_LIST_L1_MAXSIZE: int = 256

    # ---------- RocketMQ(浏览统计异步写) ----------
    # Proxy gRPC 地址; 为空则关闭 MQ, API 同步写库(本地无 MQ 也能跑)
    # Python 官方客户端 rocketmq-python-client 走 Proxy, 不是 NameServer 9876
    ROCKETMQ_ENDPOINTS: str = ""
    # 浏览统计 Topic(report/pv 共用, 用 Tag 区分)
    ROCKETMQ_TOPIC_BROWSE: str = "blog_browse"
    # 浏览统计消费组
    ROCKETMQ_GROUP_BROWSE: str = "blog_browse_consumer"

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
