"""全局配置模块: 通过 pydantic-settings 从 .env 读取配置。

本服务是 AI 编排层, 不连任何数据库:
- 业务数据向 backend-blog 的内部接口取
- 向量检索向 backend-rag 取
- 自己只持有 Redis(推荐结果缓存 + 分布式限流)与大模型连接
"""

# 从 pydantic_settings 导入配置基类
from pydantic_settings import BaseSettings, SettingsConfigDict


# 定义配置类, 字段名与 .env 中的键(忽略大小写)对应
class Settings(BaseSettings):
    # ---------- 服务自身 ----------
    # 监听端口(供文档与健康检查展示)
    SERVICE_PORT: int = 8001
    # 日志级别
    LOG_LEVEL: str = "INFO"
    # 允许跨域的来源, 字符串形式(逗号分隔); 前端直连本服务时需要
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:5174"
    # 服务间调用令牌: 与 backend-blog / backend-rag 保持一致
    INTERNAL_TOKEN: str = ""

    # ---------- JWT(与 backend-blog 共享密钥, 本地验签不产生网络调用) ----------
    # 签名密钥, 必须与 backend-blog 完全一致
    SECRET_KEY: str
    # 签名算法
    ALGORITHM: str = "HS256"

    # ---------- 下游服务 ----------
    # backend-blog 基础地址(业务数据来源)
    BLOG_BASE_URL: str = "http://127.0.0.1:8000"
    # backend-rag 基础地址(向量检索来源)
    RAG_BASE_URL: str = "http://127.0.0.1:8002"
    # 服务间 HTTP 超时秒数
    HTTP_TIMEOUT: float = 10.0
    # 全量重建索引是长任务, 单独放宽超时
    HTTP_REINDEX_TIMEOUT: float = 600.0
    # 服务间 HTTP 连接池上限(复用 TCP, 避免每次握手)
    HTTP_MAX_CONNECTIONS: int = 100

    # ---------- 对话模型 ----------
    # OpenAI 兼容接口的 API Key, 为空则问答功能返回 503
    AI_API_KEY: str = ""
    # OpenAI 兼容接口基础地址, 默认阿里云百炼
    AI_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # 对话模型名称
    AI_CHAT_MODEL: str = "qwen-plus"
    # 采样温度, 低温度减少编造
    AI_TEMPERATURE: float = 0.3
    # 单次请求超时秒数
    AI_TIMEOUT: float = 60.0
    # 网络抖动自动重试次数
    AI_MAX_RETRIES: int = 2
    # 单 IP 每分钟提问上限, 轻量防刷
    AI_RATE_LIMIT: int = 10

    # ---------- 检索参数(下发给 backend-rag) ----------
    # 问答检索返回的分块数
    RAG_TOP_K: int = 6
    # 相似度下限
    RAG_SCORE_THRESHOLD: float = 0.3

    # ---------- 推荐参数 ----------
    # 画像最多采用最近 N 条浏览行为
    REC_BEHAVIOR_LIMIT: int = 20
    # 收藏行为的固定加权(强偏好信号)
    REC_FAVORITE_WEIGHT: float = 2.0
    # 召回候选相对目标数量的缓冲倍数
    REC_RECALL_BUFFER: int = 2

    # ---------- Redis(推荐缓存 L2 + 分布式限流) ----------
    # 主机; 为空则关闭 Redis, 推荐仅用进程内 L1, 限流退化为单机内存
    REDIS_HOST: str = "127.0.0.1"
    # 端口
    REDIS_PORT: int = 6379
    # 密码(与 redis-server --requirepass 一致)
    REDIS_PASSWORD: str = "qwqwqw78"
    # 逻辑库编号
    REDIS_DB: int = 0
    # 连接池上限, 避免瞬时打满 Redis
    REDIS_MAX_CONNECTIONS: int = 50
    # 建连/读写超时秒数, 超时快速失败走回源
    REDIS_SOCKET_TIMEOUT: float = 2.0
    # 推荐结果缓存 TTL(秒); 个性化行为变动频繁, 取短 TTL
    REC_ARTICLE_CACHE_TTL: int = 30
    # 推荐结果 L1 本地缓存最大条目数(匿名 + 用户分 key)
    REC_ARTICLE_L1_MAXSIZE: int = 512

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
