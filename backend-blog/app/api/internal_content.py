"""内部内容接口: 供 backend-agent / backend-rag 读取文章与用户状态 (4 个接口)。

这些接口只在内网暴露, 用共享的服务间令牌鉴权, 不参与用户 JWT 体系。
它们是「MySQL 只属于 backend-blog」这条边界的具体落地: 其他服务想要业务数据,
一律走这里, 不再各自持有 ORM 模型与数据库连接。
"""

# 导入路由与依赖工具
from fastapi import APIRouter, Depends, HTTPException
# 导入查询构造器
from sqlalchemy import select
# 导入异步会话类型
from sqlalchemy.ext.asyncio import AsyncSession

# 导入服务间令牌校验
from app.api.deps import verify_internal_token
# 导入数据库会话依赖
from app.core.database import get_db
# 导入统一响应
from app.core.response import Result, ok
# 导入模型
from app.models.article import Article
from app.models.user import User
# 导入内部契约模型
from app.schemas.internal import (
    ArticleDocumentOut,
    ArticleMetaOut,
    IndexableIdsOut,
    UserStateOut,
)

# 创建内部内容路由, 全局挂服务间令牌校验
router = APIRouter(
    prefix="/internal",
    tags=["内部-内容"],
    dependencies=[Depends(verify_internal_token)],
)


# 1. 文章元信息: backend-agent 问答前校验文章可用性并取标题/分类
@router.get("/article/{article_id}/meta", response_model=Result, summary="文章元信息")
async def article_meta(article_id: int, db: AsyncSession = Depends(get_db)):
    # 只取必要列, 不加载正文大字段
    row = (
        await db.execute(
            select(Article.id, Article.title, Article.category_id, Article.status)
            .where(Article.id == article_id)
        )
    ).mappings().first()
    # 不存在时返回 data=None, 由调用方判空(不用 404 以简化下游处理)
    if not row:
        # 空数据
        return ok(None)
    # 返回元信息
    return ok(
        ArticleMetaOut(
            article_id=row["id"],
            title=row["title"] or "",
            category_id=row["category_id"] or 0,
            status=row["status"] or 0,
        )
    )


# 2. 文章索引文档: backend-rag 全量重建时回源拉取正文
@router.get(
    "/article/{article_id}/document", response_model=Result, summary="文章索引文档"
)
async def article_document(article_id: int, db: AsyncSession = Depends(get_db)):
    # 取索引所需的全部字段(含正文)
    row = (
        await db.execute(
            select(
                Article.id,
                Article.title,
                Article.category_id,
                Article.content,
                Article.status,
            ).where(Article.id == article_id)
        )
    ).mappings().first()
    # 文章不存在时返回 404, 检索服务据此清理残留索引
    if not row:
        # 明确告知不存在
        raise HTTPException(status_code=404, detail="文章不存在")
    # 返回文档
    return ok(
        ArticleDocumentOut(
            article_id=row["id"],
            title=row["title"] or "",
            category_id=row["category_id"] or 0,
            content=row["content"] or "",
            status=row["status"] or 0,
        )
    )


# 3. 可索引文章 ID: 全量重建的遍历清单
@router.get("/article/indexable-ids", response_model=Result, summary="可索引文章 ID")
async def indexable_ids(db: AsyncSession = Depends(get_db)):
    # 仅已发布文章; 只取主键, 命中 idx_status_create 左前缀
    ids = (
        await db.execute(select(Article.id).where(Article.status == 1))
    ).scalars().all()
    # 返回 ID 列表
    return ok(IndexableIdsOut(ids=[int(i) for i in ids]))


# 4. 用户账号状态: backend-agent 执行管理操作前核对实时权限
@router.get("/user/{user_id}", response_model=Result, summary="用户账号状态")
async def user_state(user_id: int, db: AsyncSession = Depends(get_db)):
    # 只取鉴权所需列
    row = (
        await db.execute(
            select(User.id, User.is_admin, User.status).where(User.id == user_id)
        )
    ).mappings().first()
    # 不存在时返回 data=None
    if not row:
        # 空数据
        return ok(None)
    # 返回状态
    return ok(
        UserStateOut(
            user_id=row["id"],
            is_admin=row["is_admin"] or 0,
            status=row["status"] or 0,
        )
    )
