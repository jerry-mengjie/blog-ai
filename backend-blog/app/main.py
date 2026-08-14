"""FastAPI 应用入口: 注册中间件、异常处理与全部路由。

本服务在微服务拆分后专注业务(用户/文章/评论/收藏/浏览统计), 对外仍是前端的
主入口; AI 问答与推荐分别由 backend-agent、backend-rag 承担, 本服务只做两件事:
1. 写路径上把文章变更推送给 backend-rag 并通知 backend-agent 失效推荐缓存
2. 通过 /internal/* 向两个服务提供 MySQL 侧的取数能力
"""

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
# 导入 Redis 客户端预热与关闭
from app.core.redis import close_redis, get_redis, redis_enabled
# 确保所有模型被导入以注册到 Base.metadata
from app import models  # noqa: F401
# 导入各业务路由
from app.api import (
    admin_browse,
    admin_user,
    article,
    browse,
    category,
    comment,
    favorite,
    internal_content,
    internal_rec,
    tag,
    user,
)
# 导入下游服务客户端连接池释放
from app.clients.base import close_clients
# 导入 RocketMQ Producer 关闭(进程退出时释放)
from app.mq.producer import shutdown_producer


# 应用生命周期: 启动时可选自动建表, 关闭时释放引擎连接池
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动阶段: 自动创建尚不存在的表(生产环境建议改用迁移工具)
    async with engine.begin() as conn:
        # 依据模型元数据建表
        await conn.run_sync(Base.metadata.create_all)
    # 启用 Redis 时预热连接池(PING 失败不阻断启动, 列表退化为 L1/直查)
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
                # 启动期 Redis 不可用时静默, 读路径会 miss 回源
                pass
    # yield 之前为启动逻辑, 之后为关闭逻辑
    yield
    # 关闭阶段: 释放 RocketMQ Producer(未启用时为空操作)
    shutdown_producer()
    # 关闭阶段: 释放下游服务 HTTP 连接池
    await close_clients()
    # 关闭阶段: 释放 Redis 连接池
    await close_redis()
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
app.include_router(admin_user.router) # 管理端-用户(含兴趣标签)
app.include_router(article.router)    # 文章模块
app.include_router(category.router)   # 分类模块
app.include_router(tag.router)        # 标签模块
app.include_router(comment.router)    # 评论模块
app.include_router(favorite.router)   # 收藏模块
app.include_router(browse.router)     # 浏览足迹(用户×文章累计)
app.include_router(admin_browse.router)  # 管理端-浏览统计
app.include_router(internal_content.router)  # 内部-内容(供 agent/rag 取数)
app.include_router(internal_rec.router)      # 内部-推荐取数(供 agent 推荐图)
