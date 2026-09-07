"""全局配置模块: 通过 pydantic-settings 从 .env 读取配置。

本服务是纯检索服务, 不连 MySQL、不生成回答:
- 上游: backend-blog(写路径推送文档) 与 backend-agent(读路径检索)
- 下游: Milvus(向量) + 向量模型(OpenAI 兼容接口) + Redis(检索结果缓存)
"""

# 从 pydantic_settings 导入配置基类
from pydantic_settings import BaseSettings, SettingsConfigDict


# 定义配置类, 字段名与 .env 中的键(忽略大小写)对应
class Settings(BaseSettings):
    # ---------- 服务自身 ----------
    # 监听端口(uvicorn --port 时可覆盖, 这里主要供文档与健康检查展示)
    SERVICE_PORT: int = 8002
    # 日志级别
    LOG_LEVEL: str = "INFO"
    # 服务间调用令牌: 与 backend-blog / backend-agent 保持一致, 空则不校验(仅本地开发)
    INTERNAL_TOKEN: str = ""

    # ---------- 上游服务 ----------
    # backend-blog 基础地址(全量重建索引时回源拉取文章正文)
    BLOG_BASE_URL: str = "http://127.0.0.1:8000"
    # 服务间 HTTP 超时秒数
    HTTP_TIMEOUT: float = 10.0
    # 服务间 HTTP 连接池上限(复用 TCP, 避免每次握手)
    HTTP_MAX_CONNECTIONS: int = 100

    # ---------- 向量模型 ----------
    # OpenAI 兼容接口的 API Key, 为空则本服务所有 RAG 能力返回 503
    AI_API_KEY: str = ""
    # OpenAI 兼容接口基础地址, 默认阿里云百炼
    AI_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # 向量模型名称
    AI_EMBED_MODEL: str = "text-embedding-v4"
    # 向量维度, 须与向量模型输出一致; 修改后集合会按新维度重建
    AI_EMBED_DIM: int = 1024
    # 单次向量化的文本条数; 百炼兼容接口批量上限为 10
    AI_EMBED_BATCH: int = 10

    # ---------- Milvus 向量库 ----------
    # Milvus gRPC 地址(standalone 部署默认 19530 端口)
    MILVUS_URI: str = "http://127.0.0.1:19530"
    # 集合名称(LlamaIndex 节点结构与旧 LangChain 集合不同, 故用新集合名)
    MILVUS_COLLECTION: str = "blog_rag_nodes"
    # 一致性级别: Bounded 允许秒级陈旧, 免去每次检索等待数据同步, 吞吐显著优于 Strong/Session
    MILVUS_CONSISTENCY: str = "Bounded"
    # HNSW 每个节点的边数, 召回率与内存的平衡点
    MILVUS_HNSW_M: int = 16
    # HNSW 构建时候选队列, 略高于默认值提升图质量
    MILVUS_HNSW_EF_CONSTRUCTION: int = 128
    # HNSW 检索候选队列, 取 TopK 的数倍保证召回率
    MILVUS_SEARCH_EF: int = 64
    # 单次写入 Milvus 的实体条数, 批量插入摊薄 RPC 开销
    MILVUS_BATCH_SIZE: int = 128

    # ---------- 分块与检索参数 ----------
    # 单个文本块的目标字符数
    RAG_CHUNK_SIZE: int = 500
    # 相邻块的重叠字符数, 避免语义在边界被切断
    RAG_CHUNK_OVERLAP: int = 80
    # 检索返回的片段数量
    RAG_TOP_K: int = 6
    # 相似度下限, 过滤无关片段减少提示词噪音
    RAG_SCORE_THRESHOLD: float = 0.3
    # 单篇文章允许的最大分块数, 防止超长文章打爆向量化配额
    RAG_MAX_CHUNKS: int = 200
    # 全量重建的并发文章数, 受向量模型 QPS 限制不宜过大
    RAG_REINDEX_CONCURRENCY: int = 4
    # 构建用户画像时每篇行为文章取多少个开头分块作为该文章的代表向量。
    # 取全部分块做均值语义最准, 但要把成百上千条 1024 维向量传回进程(单次可达数十 MB);
    # 只取开头若干块(标题 + 开篇, 主题信息最集中)可把传输量压到千分之一, 召回质量几乎不变
    RAG_PROFILE_CHUNKS: int = 3
    # 画像召回的候选块数上限, 聚合到文章级后再截断
    RAG_PROFILE_CANDIDATES: int = 256

    # ---------- Redis(检索结果缓存) ----------
    # 主机; 为空则关闭 Redis, 检索每次都实时打向量模型 + Milvus
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
    # 检索结果缓存 TTL(秒): 同一问题重复提问时省下 embedding 与 Milvus 检索
    RAG_RETRIEVE_CACHE_TTL: int = 300

    # 指定读取 .env 文件、编码及忽略多余字段
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


# 实例化全局唯一配置对象, 供其他模块导入使用
settings = Settings()
