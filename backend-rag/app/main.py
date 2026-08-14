"""backend-rag 应用入口: RAG 检索微服务(FastAPI + LlamaIndex + Milvus)。

职责边界:
- 只做「索引 + 检索」, 不连 MySQL、不生成回答、不感知用户身份
- 向量库结构、分块策略、检索参数全部收敛在本服务内, 换向量库只改这里

启动顺序: 日志 → LlamaIndex 全局组件 → Milvus 集合与索引 → Redis 预热
"""

# 导入异步上下文管理器工具
from contextlib import asynccontextmanager

# 导入 FastAPI 核心类与异常
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# 导入全局配置
from app.core.config import settings
# 导入日志初始化
from app.core.logging import setup_logging
# 导入 Redis 预热与关闭
from app.core.redis import close_redis, get_redis, redis_enabled
# 导入 LlamaIndex 全局组件初始化与开关
from app.rag.models import configure_llama_index, rag_enabled
# 导入 Milvus 集合初始化与连接释放
from app.rag.vector_store import close_vector_store, ensure_collection
# 导入 backend-blog 客户端关闭
from app.clients.blog import close_client
# 导入业务路由
from app.api import index, retrieve


# 应用生命周期: 启动时装配 RAG 组件, 关闭时释放全部连接池
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 最早初始化日志, 保证后续启动步骤都有日志可看
    setup_logging()
    # 注册 LlamaIndex 全局组件(向量模型 + 分块器)
    configure_llama_index()
    # 启用 RAG 时初始化 Milvus 集合(Schema + HNSW 向量索引 + 标量倒排索引)
    if rag_enabled():
        # 幂等操作; Milvus 不可达时不阻断启动, 由请求路径报错
        try:
            # 建集合/补索引/加载到内存
            ensure_collection()
        except Exception:
            # 启动期 Milvus 未就绪属常见场景, 记录后继续
            import logging

            logging.getLogger(__name__).warning(
                "Milvus 初始化失败, 检索接口将在 Milvus 恢复后可用", exc_info=True
            )
    # 启用 Redis 时预热连接池
    if redis_enabled():
        # 取单例客户端
        client = get_redis()
        # 客户端存在则探测
        if client is not None:
            # 忽略瞬时不可达, 后续请求再连
            try:
                # 经典健康检查
                await client.ping()
            except Exception:
                # 启动期 Redis 不可用时静默, 检索退化为实时计算
                pass
    # yield 之前为启动逻辑, 之后为关闭逻辑
    yield
    # 关闭阶段: 释放 backend-blog HTTP 连接池
    await close_client()
    # 关闭阶段: 释放 Redis 连接池
    await close_redis()
    # 关闭阶段: 释放 Milvus 客户端连接
    await close_vector_store()


# 创建 FastAPI 应用实例
app = FastAPI(
    title="RAG 检索服务",                                 # 文档标题
    description="FastAPI + LlamaIndex + Milvus 检索增强微服务",  # 文档描述
    version="1.0.0",                                      # 版本号
    lifespan=lifespan,                                    # 绑定生命周期
)


# 统一处理 HTTP 异常, 返回 {code, message, data} 结构
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    # 以业务错误码 = HTTP 状态码 返回
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "message": exc.detail, "data": None},
    )


# 统一处理参数校验异常
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # 返回 422 与错误明细
    return JSONResponse(
        status_code=422,
        content={"code": 422, "message": "参数校验失败", "data": exc.errors()},
    )


# 健康检查接口: 同时暴露 RAG 开关与集合名, 便于上游判断降级
@app.get("/health", tags=["系统"], summary="健康检查")
async def health():
    # 返回服务状态与关键配置
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "service": "backend-rag",                     # 服务名
            "enabled": rag_enabled(),                     # RAG 是否可用
            "collection": settings.MILVUS_COLLECTION,     # 当前集合
            "embed_model": settings.AI_EMBED_MODEL,       # 向量模型
            "embed_dim": settings.AI_EMBED_DIM,           # 向量维度
        },
    }


# 注册业务路由
app.include_router(index.router)     # 索引写入(upsert/删除/全量重建)
app.include_router(retrieve.router)  # 检索(问答检索/画像召回)
