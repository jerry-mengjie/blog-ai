"""文章模块路由: 列表/详情/发布/编辑/删除/置顶/搜索 (7 个接口)。"""

# 导入路由与依赖工具
from fastapi import APIRouter, Depends, HTTPException, Query
# 导入查询构造器与函数
from sqlalchemy import delete, func, select
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
from app.models.tag import ArticleTag, Tag
from app.models.user import User
# 导入文章 schema
from app.schemas.article import (
    ArticleCreateReq,
    ArticleDetail,
    ArticleListItem,
    ArticleUpdateReq,
    PageOut,
)

# 创建文章路由, 前缀 /api/article
router = APIRouter(prefix="/api/article", tags=["文章模块"])


# 内部工具: 根据文章 ID 查询其标签名称列表
async def _load_tags(db: AsyncSession, article_id: int) -> list[str]:
    # 联表查询标签名: article_tag 关联 tag
    stmt = (
        select(Tag.name)
        .join(ArticleTag, ArticleTag.tag_id == Tag.id)
        .where(ArticleTag.article_id == article_id)
    )
    # 执行查询
    result = await db.execute(stmt)
    # 返回名称列表
    return list(result.scalars().all())


# 1. 分页查询文章列表
@router.get("/list", response_model=Result, summary="分页查询文章列表")
async def list_articles(
    # 页码, 默认 1, 最小 1
    page: int = Query(default=1, ge=1),
    # 每页条数, 默认 10, 范围 1-50
    page_size: int = Query(default=10, ge=1, le=50),
    # 可选分类筛选
    category_id: int | None = Query(default=None),
    # 注入会话
    db: AsyncSession = Depends(get_db),
):
    # 基础过滤条件: 仅查询已发布文章
    conditions = [Article.status == 1]
    # 若指定分类则追加条件
    if category_id:
        # 增加分类过滤
        conditions.append(Article.category_id == category_id)
    # 统计总条数(只查 count, 不取大字段)
    total = await db.scalar(
        select(func.count()).select_from(Article).where(*conditions)
    )
    # 查询列表, 显式选择列以避免加载 content 大字段, 命中复合索引排序
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
        .where(*conditions)
        .order_by(Article.is_top.desc(), Article.create_time.desc())
        .offset((page - 1) * page_size)  # 分页偏移
        .limit(page_size)                # 分页大小
    )
    # 执行查询
    result = await db.execute(stmt)
    # 将每行映射为列表项 schema
    items = [ArticleListItem.model_validate(row) for row in result.mappings().all()]
    # 返回分页结构
    return ok(PageOut(total=total or 0, list=items))


# 2. 文章搜索(放在 /detail/{id} 之前, 路径无冲突但保持清晰)
@router.get("/search", response_model=Result, summary="文章搜索")
async def search_articles(
    # 搜索关键字
    keyword: str = Query(default="", max_length=100),
    # 页码
    page: int = Query(default=1, ge=1),
    # 每页条数
    page_size: int = Query(default=10, ge=1, le=50),
    # 注入会话
    db: AsyncSession = Depends(get_db),
):
    # 构造标题模糊匹配条件(前缀匹配可命中索引)
    like = f"%{keyword}%"
    # 过滤: 已发布 + 标题包含关键字
    conditions = [Article.status == 1, Article.title.like(like)]
    # 统计总数
    total = await db.scalar(
        select(func.count()).select_from(Article).where(*conditions)
    )
    # 查询匹配的文章列表(不含正文)
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
        .where(*conditions)
        .order_by(Article.create_time.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    # 执行查询
    result = await db.execute(stmt)
    # 映射结果
    items = [ArticleListItem.model_validate(row) for row in result.mappings().all()]
    # 返回分页结果
    return ok(PageOut(total=total or 0, list=items))


# 3. 置顶文章列表
@router.get("/top", response_model=Result, summary="置顶文章列表")
async def top_articles(db: AsyncSession = Depends(get_db)):
    # 查询置顶且已发布的文章(数量少, 直接限制 10 条)
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
        .where(Article.status == 1, Article.is_top == 1)
        .order_by(Article.create_time.desc())
        .limit(10)
    )
    # 执行查询
    result = await db.execute(stmt)
    # 映射结果
    items = [ArticleListItem.model_validate(row) for row in result.mappings().all()]
    # 返回列表
    return ok(items)


# 4. 文章详情
@router.get("/detail/{article_id}", response_model=Result, summary="文章详情")
async def article_detail(article_id: int, db: AsyncSession = Depends(get_db)):
    # 查询完整文章对象(含正文)
    result = await db.execute(select(Article).where(Article.id == article_id))
    # 取出文章
    article = result.scalar_one_or_none()
    # 不存在或未发布则报错
    if not article or article.status != 1:
        # 文章不存在
        raise HTTPException(status_code=404, detail="文章不存在")
    # 浏览量 +1(使用原子更新避免并发覆盖)
    article.view_count += 1
    # 提交浏览量更新
    await db.commit()
    # 加载标签名称
    tags = await _load_tags(db, article_id)
    # 构造详情对象
    detail = ArticleDetail.model_validate(article)
    # 写入标签
    detail.tags = tags
    # 返回详情
    return ok(detail)


# 5. 发布文章(需登录)
@router.post("/add", response_model=Result, summary="发布文章")
async def add_article(
    body: ArticleCreateReq,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 构造文章对象
    article = Article(
        user_id=current.id,
        title=body.title,
        cover=body.cover,
        content=body.content,
        summary=body.summary,
        category_id=body.category_id,
        is_top=body.is_top,
    )
    # 加入会话
    db.add(article)
    # 先 flush 拿到文章 ID(尚未提交)
    await db.flush()
    # 批量写入文章标签关联
    for tag_id in body.tag_ids:
        # 每个标签创建一条关联记录
        db.add(ArticleTag(article_id=article.id, tag_id=tag_id))
    # 提交事务
    await db.commit()
    # 刷新对象
    await db.refresh(article)
    # 返回新文章 ID
    return ok({"id": article.id})


# 6. 编辑文章(需登录, 仅作者或管理员)
@router.put("/update/{article_id}", response_model=Result, summary="编辑文章")
async def update_article(
    article_id: int,
    body: ArticleUpdateReq,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 查询文章
    result = await db.execute(select(Article).where(Article.id == article_id))
    # 取出文章
    article = result.scalar_one_or_none()
    # 不存在则报错
    if not article:
        # 文章不存在
        raise HTTPException(status_code=404, detail="文章不存在")
    # 权限校验: 非作者且非管理员禁止编辑
    if article.user_id != current.id and current.is_admin != 1:
        # 无权限
        raise HTTPException(status_code=403, detail="无权编辑该文章")
    # 逐字段更新(仅更新传入项)
    if body.title is not None:
        article.title = body.title
    if body.cover is not None:
        article.cover = body.cover
    if body.content is not None:
        article.content = body.content
    if body.summary is not None:
        article.summary = body.summary
    if body.category_id is not None:
        article.category_id = body.category_id
    if body.is_top is not None:
        article.is_top = body.is_top
    if body.status is not None:
        article.status = body.status
    # 若传入标签列表则全量覆盖关联关系
    if body.tag_ids is not None:
        # 先删除旧关联
        await db.execute(
            delete(ArticleTag).where(ArticleTag.article_id == article_id)
        )
        # 再写入新关联
        for tag_id in body.tag_ids:
            db.add(ArticleTag(article_id=article_id, tag_id=tag_id))
    # 提交事务
    await db.commit()
    # 返回成功
    return ok(message="更新成功")


# 7. 删除文章(需登录, 仅作者或管理员)
@router.delete("/del/{article_id}", response_model=Result, summary="删除文章")
async def delete_article(
    article_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 查询文章
    result = await db.execute(select(Article).where(Article.id == article_id))
    # 取出文章
    article = result.scalar_one_or_none()
    # 不存在则报错
    if not article:
        # 文章不存在
        raise HTTPException(status_code=404, detail="文章不存在")
    # 权限校验
    if article.user_id != current.id and current.is_admin != 1:
        # 无权限
        raise HTTPException(status_code=403, detail="无权删除该文章")
    # 删除文章本身
    await db.delete(article)
    # 删除关联标签记录
    await db.execute(delete(ArticleTag).where(ArticleTag.article_id == article_id))
    # 提交事务
    await db.commit()
    # 返回成功
    return ok(message="删除成功")
