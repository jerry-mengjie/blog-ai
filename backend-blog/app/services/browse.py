"""用户文章浏览领域服务: 上报累计 / 我的足迹 / 管理端分页。

性能要点:
1. 上报用 INSERT ... ON DUPLICATE KEY UPDATE 单语句原子累计, 避免先查后改竞态
2. 列表只选必要列, JOIN 文章标题等展示字段, 不拉正文
3. 我的足迹命中 idx_user_last; 管理端按 article 反查命中 idx_article
"""

# 导入文本 SQL 与查询/聚合工具
from sqlalchemy import func, or_, select, text
# 导入异步会话类型
from sqlalchemy.ext.asyncio import AsyncSession

# 导入文章与用户模型(联表展示)
from app.models.article import Article
from app.models.browse import UserBrowse
from app.models.user import User
# 导入响应 schema
from app.schemas.browse import BrowseItemOut

# 单次上报时长上限(秒), 防止异常/刷量把总时长撑爆
_MAX_DURATION = 7200


# 校验文章是否存在且已发布, 返回是否有效
async def article_exists(db: AsyncSession, article_id: int) -> bool:
    # 只查主键, 轻量存在性判断
    result = await db.execute(
        select(Article.id).where(Article.id == article_id, Article.status == 1)
    )
    # 有行则存在
    return result.scalar_one_or_none() is not None


# 上报一次浏览: 次数 +1, 累加时长, 刷新最好浏览时间
async def report_browse(
    db: AsyncSession,
    user_id: int,
    article_id: int,
    duration: int,
) -> None:
    # 裁剪时长到合法区间
    seconds = max(0, min(int(duration), _MAX_DURATION))
    # 原子 upsert: 唯一键冲突则累计更新
    await db.execute(
        text(
            """
            INSERT INTO tb_user_browse
              (user_id, article_id, view_count, total_duration,
               best_duration, best_browse_time, last_browse_time)
            VALUES
              (:user_id, :article_id, 1, :duration,
               :duration, IF(:duration > 0, NOW(), NULL), NOW())
            ON DUPLICATE KEY UPDATE
              view_count = view_count + 1,
              total_duration = total_duration + :duration,
              best_browse_time = IF(
                :duration > best_duration, NOW(), best_browse_time
              ),
              best_duration = IF(
                :duration > best_duration, :duration, best_duration
              ),
              last_browse_time = NOW()
            """
        ),
        {"user_id": user_id, "article_id": article_id, "duration": seconds},
    )
    # 提交事务
    await db.commit()


# 将联表行映射为 BrowseItemOut
def _row_to_item(row) -> BrowseItemOut:
    # row 为 mappings() 字典风格
    return BrowseItemOut(
        id=row["id"],
        user_id=row["user_id"],
        article_id=row["article_id"],
        title=row.get("title") or "",
        cover=row.get("cover") or "",
        summary=row.get("summary") or "",
        view_count=row["view_count"],
        total_duration=row["total_duration"],
        best_duration=row["best_duration"],
        best_browse_time=row["best_browse_time"],
        last_browse_time=row["last_browse_time"],
        username=row.get("username") or "",
        nickname=row.get("nickname") or "",
    )


# 当前用户足迹列表(分页, 按最近浏览倒序)
async def list_my_browses(
    db: AsyncSession,
    user_id: int,
    page: int,
    page_size: int,
) -> tuple[list[BrowseItemOut], int]:
    # 计数: 只 count 本用户行
    total = int(
        (
            await db.execute(
                select(func.count(UserBrowse.id)).where(UserBrowse.user_id == user_id)
            )
        ).scalar_one()
    )
    # 列表: JOIN 文章展示字段, 不选 content
    stmt = (
        select(
            UserBrowse.id,
            UserBrowse.user_id,
            UserBrowse.article_id,
            UserBrowse.view_count,
            UserBrowse.total_duration,
            UserBrowse.best_duration,
            UserBrowse.best_browse_time,
            UserBrowse.last_browse_time,
            Article.title,
            Article.cover,
            Article.summary,
        )
        .join(Article, Article.id == UserBrowse.article_id)
        .where(UserBrowse.user_id == user_id)
        .order_by(UserBrowse.last_browse_time.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    # 执行查询
    rows = (await db.execute(stmt)).mappings().all()
    # 映射响应
    return [_row_to_item(r) for r in rows], total


# 管理端浏览统计分页(可按用户/文章过滤)
async def admin_list_browses(
    db: AsyncSession,
    page: int,
    page_size: int,
    user_id: int | None = None,
    article_id: int | None = None,
    keyword: str = "",
) -> tuple[list[BrowseItemOut], int]:
    # 动态过滤条件
    conditions: list = []
    # 按用户过滤
    if user_id is not None:
        # 等值命中 uk / idx 左前缀
        conditions.append(UserBrowse.user_id == user_id)
    # 按文章过滤
    if article_id is not None:
        # 命中 idx_article
        conditions.append(UserBrowse.article_id == article_id)
    # 关键字匹配用户名/昵称/文章标题
    if keyword:
        # LIKE 模式
        like = f"%{keyword}%"
        # 追加 OR 条件
        conditions.append(
            or_(
                User.username.like(like),
                User.nickname.like(like),
                Article.title.like(like),
            )
        )
    # 基查询: 浏览 + 用户 + 文章
    base = (
        select(UserBrowse, User.username, User.nickname, Article.title, Article.cover, Article.summary)
        .join(User, User.id == UserBrowse.user_id)
        .join(Article, Article.id == UserBrowse.article_id)
    )
    # 挂条件
    if conditions:
        # 应用 where
        base = base.where(*conditions)
    # 计数子查询: 对同一过滤 count
    count_stmt = select(func.count()).select_from(base.subquery())
    # 执行计数
    total = int((await db.execute(count_stmt)).scalar_one())
    # 分页列表, 最近浏览倒序
    list_stmt = (
        base.order_by(UserBrowse.last_browse_time.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    # 执行列表
    result = await db.execute(list_stmt)
    # 装配响应
    items: list[BrowseItemOut] = []
    # 逐行拆 ORM + 联表列
    for browse, username, nickname, title, cover, summary in result.all():
        # 追加一条
        items.append(
            BrowseItemOut(
                id=browse.id,
                user_id=browse.user_id,
                article_id=browse.article_id,
                title=title or "",
                cover=cover or "",
                summary=summary or "",
                view_count=browse.view_count,
                total_duration=browse.total_duration,
                best_duration=browse.best_duration,
                best_browse_time=browse.best_browse_time,
                last_browse_time=browse.last_browse_time,
                username=username or "",
                nickname=nickname or "",
            )
        )
    # 返回列表与总数
    return items, total
