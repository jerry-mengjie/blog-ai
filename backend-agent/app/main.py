"""backend-agent 应用入口: AI 编排微服务(FastAPI + LangGraph + LangChain)。

职责边界:
- 只做「编排 + 生成」: 问答图、推荐图、提示词、大模型调用
- 业务数据向 backend-blog 取, 向量检索向 backend-rag 取, 自己不持有任何数据库
- 用户身份由本地 JWT 验签得到, 与 backend-blog 共享同一个 SECRET_KEY

对外暴露的路径与拆分前保持一致(/api/ai/*, /api/rec/*), 前端无需改动业务代码。
"""

# 导入异步上下文管理器工具
from contextlib import asynccontextmanager

# 导入 FastAPI 核心类与异常
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# 导入下游客户端统一关闭
from app.clients.http import close_all_clients
# 导入全局配置
from app.core.config import settings
# 导入日志初始化
from app.core.logging import setup_logging
# 导入 Redis 预热与关闭
from app.core.redis import close_redis, get_redis, redis_enabled
# 导入 AI 开关
from app.llm.models import ai_enabled
# 导入业务路由
from app.api import chat, recommend


# 应用生命周期: 启动时预热连接, 关闭时释放全部连接池
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 最早初始化日志
    setup_logging()
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
                # 启动期 Redis 不可用时静默, 推荐退化为 L1, 限流退化为单机
                pass
    # yield 之前为启动逻辑, 之后为关闭逻辑
    yield
    # 关闭阶段: 释放下游服务 HTTP 连接池
    await close_all_clients()
    # 关闭阶段: 释放 Redis 连接池
    await close_redis()


# 创建 FastAPI 应用实例
app = FastAPI(
    title="AI 编排服务",                                        # 文档标题
    description="FastAPI + LangGraph + LangChain 问答与推荐编排",  # 文档描述
    version="1.0.0",                                           # 版本号
    lifespan=lifespan,                                         # 绑定生命周期
)

# 注册 CORS 中间件: 前端可直连本服务(生产环境一般由网关统一转发)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,  # 允许的来源列表
    allow_credentials=True,                    # 允许携带凭证
    allow_methods=["*"],                       # 允许所有方法
    allow_headers=["*"],                       # 允许所有请求头
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


# 健康检查接口: 暴露 AI 开关与下游地址, 便于部署探活与排查
@app.get("/health", tags=["系统"], summary="健康检查")
async def health():
    # 返回服务状态与关键配置
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "service": "backend-agent",             # 服务名
            "enabled": ai_enabled(),                # AI 是否可用
            "chat_model": settings.AI_CHAT_MODEL,    # 对话模型
            "blog": settings.BLOG_BASE_URL,          # 业务服务地址
            "rag": settings.RAG_BASE_URL,            # 检索服务地址
        },
    }


# 注册业务路由
app.include_router(chat.router)                # AI 问答(config / ask / reindex)
app.include_router(recommend.router)           # 推荐文章
app.include_router(recommend.internal_router)  # 内部: 失效推荐缓存
