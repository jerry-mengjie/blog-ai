"""FastAPI 应用入口: 注册中间件、异常处理与全部路由。"""

# 导入异步上下文管理器工具
from contextlib import asynccontextmanager

# 导入 FastAPI 核心类与异常
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# 导入全局配置
from app.core.config import settings
# 导入数据库引擎与基类(用于可选自动建表)
from app.core.database import Base, engine
# 确保所有模型被导入以注册到 Base.metadata
from app import models  # noqa: F401
# 导入各业务路由
from app.api import ai, article, category, comment, favorite, tag, user
# 导入 AI 开关判断
from app.ai.llm import ai_enabled
# 导入 Milvus 集合初始化与连接释放
from app.ai.vector_store import close_vector_store, ensure_collection


# 应用生命周期: 启动时可选自动建表, 关闭时释放引擎连接池
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动阶段: 自动创建尚不存在的表(生产环境建议改用迁移工具)
    async with engine.begin() as conn:
        # 依据模型元数据建表
        await conn.run_sync(Base.metadata.create_all)
    # 启用 AI 时初始化 Milvus 集合(HNSW 向量索引 + 标量倒排索引)
    if ai_enabled():
        # 幂等操作, 已存在且维度一致时直接复用
        await ensure_collection()
    # yield 之前为启动逻辑, 之后为关闭逻辑
    yield
    # 关闭阶段: 释放 Milvus 客户端连接
    await close_vector_store()
    # 关闭阶段: 释放数据库连接池
    await engine.dispose()


# 创建 FastAPI 应用实例
app = FastAPI(
    title="博客系统 API",          # 文档标题
    description="FastAPI + MySQL 9.7 博客后端", # 文档描述
    version="1.0.0",               # 版本号
    lifespan=lifespan,             # 绑定生命周期
)

# 注册 CORS 中间件, 允许前端跨域访问
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
    # 返回 422 与首条错误信息
    return JSONResponse(
        status_code=422,
        content={"code": 422, "message": "参数校验失败", "data": exc.errors()},
    )


# 健康检查接口, 便于部署探活
@app.get("/health", tags=["系统"], summary="健康检查")
async def health():
    # 返回服务正常标识
    return {"code": 0, "message": "ok", "data": "healthy"}


# 注册全部业务路由
app.include_router(user.router)       # 用户模块
app.include_router(article.router)    # 文章模块
app.include_router(category.router)   # 分类模块
app.include_router(tag.router)        # 标签模块
app.include_router(comment.router)    # 评论模块
app.include_router(favorite.router)   # 收藏模块
app.include_router(ai.router)         # AI 问答模块(RAG)
