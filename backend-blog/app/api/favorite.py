"""收藏模块路由: 收藏/取消收藏(切换)、我的收藏列表 (2 个接口)。"""

# 导入路由与依赖工具
from fastapi import APIRouter, Depends
# 导入查询构造器
from sqlalchemy import delete, select
# 导入异步会话类型
from sqlalchemy.ext.asyncio import AsyncSession

# 导入数据库会话依赖
from app.core.database import get_db
# 导入统一响应
from app.core.response import Result, ok
# 导入当前用户依赖
from app.api.deps import get_current_user
# 导入模型
from app.models.article import Article
from app.models.favorite import Favorite
from app.models.user import User
# 导入文章列表项 schema 与收藏请求 schema
from app.schemas.article import ArticleListItem
from app.schemas.common import FavoriteReq

# 创建收藏路由, 前缀 /api/favorite
router = APIRouter(prefix="/api/favorite", tags=["收藏模块"])


# 1. 收藏 / 取消收藏(切换语义: 已收藏则取消, 未收藏则新增)
@router.post("/add", response_model=Result, summary="收藏/取消收藏")
async def toggle_favorite(
    body: FavoriteReq,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 查询是否已收藏(命中唯一索引)
    result = await db.execute(
        select(Favorite).where(
            Favorite.user_id == current.id,
            Favorite.article_id == body.article_id,
        )
    )
    # 取出已有收藏记录
    fav = result.scalar_one_or_none()
    # 已收藏则执行取消
    if fav:
        # 删除收藏记录
        await db.delete(fav)
        # 提交事务
        await db.commit()
        # 返回已取消状态
        return ok({"favorited": False}, message="已取消收藏")
    # 未收藏则新增
    db.add(Favorite(user_id=current.id, article_id=body.article_id))
    # 提交事务
    await db.commit()
    # 返回已收藏状态
    return ok({"favorited": True}, message="收藏成功")


# 2. 我的收藏列表(联表查询文章信息, 不含正文)
@router.get("/list", response_model=Result, summary="我的收藏列表")
async def my_favorites(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 联表查询: 收藏 + 文章, 按收藏时间倒序
    stmt = (
        select(
            Article.id,
            Article.title,
            Article.cover,
            Article.summary,
            Article.category_id,
            Article.view_count,
            Article.is_top,
            Article.create_time,
        )
        .join(Favorite, Favorite.article_id == Article.id)
        .where(Favorite.user_id == current.id, Article.status == 1)
        .order_by(Favorite.create_time.desc())
    )
    # 执行查询
    result = await db.execute(stmt)
    # 映射结果
    items = [ArticleListItem.model_validate(row) for row in result.mappings().all()]
    # 返回收藏列表
    return ok(items)
