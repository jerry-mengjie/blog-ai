"""数据库连接与会话管理: 基于 SQLAlchemy 2.0 异步引擎 + 连接池。"""

# 导入异步类型注解工具
from typing import AsyncGenerator

# 导入 SQLAlchemy 异步引擎与会话相关组件
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
# 导入 ORM 声明基类
from sqlalchemy.orm import DeclarativeBase

# 导入全局配置
from app.core.config import settings


# 创建异步数据库引擎, 配置连接池以优化高并发性能
engine = create_async_engine(
    settings.DATABASE_URL,        # 数据库连接 URL
    echo=False,                   # 生产环境关闭 SQL 日志, 避免 I/O 开销
    pool_size=20,                 # 连接池常驻连接数
    max_overflow=10,              # 允许临时溢出的额外连接数
    pool_recycle=3600,            # 连接回收时间(秒), 防止 MySQL 8 小时断连
    pool_pre_ping=True,           # 取连接前 ping 一次, 自动剔除失效连接
)

# 创建异步会话工厂, expire_on_commit=False 避免提交后访问对象触发额外查询
AsyncSessionLocal = async_sessionmaker(
    bind=engine,                  # 绑定上面创建的引擎
    class_=AsyncSession,          # 使用异步会话类
    expire_on_commit=False,       # 提交后不过期对象, 便于序列化返回
    autoflush=False,              # 关闭自动 flush, 由业务显式控制, 提升可预测性
)


# 所有 ORM 模型的声明基类
class Base(DeclarativeBase):
    # 继承 DeclarativeBase 即可, 无需额外属性
    pass


# FastAPI 依赖: 为每个请求提供独立的数据库会话, 请求结束自动关闭
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    # 使用 async with 确保会话最终被正确关闭
    async with AsyncSessionLocal() as session:
        # 将会话交给路由处理函数使用
        yield session
