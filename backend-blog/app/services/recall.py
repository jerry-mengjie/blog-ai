"""召回数据服务: 为 backend-agent 的推荐图提供 MySQL 侧的取数能力。

职责划分很明确 —— 这里只负责「按条件把文章 ID 捞出来」, 不含任何推荐策略:
权重公式、召回优先级、去重截断都在 backend-agent 的推荐图里。这样换推荐算法
不用改 SQL, 改表结构不用改算法。

MySQL 性能要点:
1. 行为查询命中 idx_user_last(user_id + last_browse_time), 只取权重计算所需列
2. 标签召回 tag_id IN 走 tb_article_tag 的 idx_tag, 再按热度排序
3. 兜底命中 idx_status_create / idx_status_view; 收藏聚合走 tb_favorite 的 idx_article
4. 全程只 SELECT 必要列, 永不加载 content 大字段
5. 卡片装配一次 IN 批量查询, 避免逐篇查询的 N+1
"""

# 导入聚合与查询构造器
from sqlalchemy import func, select
# 导入异步会话
from sqlalchemy.ext.asyncio import AsyncSession

# 导入相关 ORM 模型
from app.models.article import Article
from app.models.browse import UserBrowse
from app.models.favorite import Favorite
from app.models.tag import ArticleTag, UserTag


# 取用户行为原始数据: 最近 N 条浏览记录 + 全部收藏文章 ID
async def load_user_behavior(
    db: AsyncSession,
    user_id: int,
    limit: int,
) -> dict:
    # 最近 N 条浏览: 命中 idx_user_last, 只取权重计算所需列
    rows = (
        await db.execute(
            select(
                UserBrowse.article_id,
                UserBrowse.view_count,
                UserBrowse.total_duration,
            )
            .where(UserBrowse.user_id == user_id)
            .order_by(UserBrowse.last_browse_time.desc())
            .limit(max(1, int(limit)))
        )
    ).all()
    # 该用户全部收藏文章 ID: 命中 user_id 唯一索引前缀
    fav_ids = (
        await db.execute(
            select(Favorite.article_id).where(Favorite.user_id == user_id)
        )
    ).scalars().all()
    # 组装为 JSON 友好结构
    return {
        "browses": [
            {
                "article_id": article_id,          # 文章 ID
                "view_count": view_count or 0,     # 阅读次数
                "total_duration": total_duration or 0,  # 累计停留秒数
            }
            for article_id, view_count, total_duration in rows
        ],
        "favorite_ids": [int(i) for i in fav_ids],
    }


# 兴趣标签召回: 按用户绑定的标签取已发布文章, 按热度倒序
async def recall_by_tags(
    db: AsyncSession,
    user_id: int,
    exclude_ids: list[int],
    limit: int,
) -> list[dict]:
    # 用户兴趣标签 ID 集合: 命中 user_id 索引
    tag_ids = (
        await db.execute(select(UserTag.tag_id).where(UserTag.user_id == user_id))
    ).scalars().all()
    # 未绑定兴趣标签则无候选
    if not tag_ids:
        # 空列表
        return []
    # 兴趣标签命中的已发布文章: tag_id IN 走 idx_tag, 只取 ID 与热度
    rows = (
        await db.execute(
            select(Article.id, Article.view_count)
            .join(ArticleTag, ArticleTag.article_id == Article.id)
            .where(
                ArticleTag.tag_id.in_(tag_ids),               # 兴趣标签过滤
                Article.status == 1,                          # 仅已发布
                Article.id.notin_(exclude_ids or [0]),        # 排除已读/已收藏
            )
            .group_by(Article.id, Article.view_count)         # 多标签命中同文章去重
            .order_by(Article.view_count.desc())              # 兴趣内按热度排序
            .limit(max(1, int(limit)))
        )
    ).all()
    # 得分记热度值, 便于上层观察召回来源
    return [{"article_id": aid, "score": float(vc or 0)} for aid, vc in rows]


# 兜底召回: 依次补充 最新 / 热门 / 收藏最多 的已发布文章, 三路合并去重
async def recall_fallback(
    db: AsyncSession,
    exclude_ids: list[int],
    limit: int,
) -> list[dict]:
    # 规范化缺口数量
    need = max(1, int(limit))
    # 公共条件: 已发布 + 不在排除集
    common = [Article.status == 1, Article.id.notin_(exclude_ids or [0])]
    # 兜底 1 最新: 命中 idx_status_create(status + create_time)
    latest = (
        await db.execute(
            select(Article.id).where(*common)
            .order_by(Article.create_time.desc()).limit(need)
        )
    ).scalars().all()
    # 兜底 2 热门: 命中 idx_status_view(status + view_count)
    hottest = (
        await db.execute(
            select(Article.id).where(*common)
            .order_by(Article.view_count.desc()).limit(need)
        )
    ).scalars().all()
    # 兜底 3 收藏最多: 收藏表按文章聚合计数, 联表过滤已发布
    most_faved = (
        await db.execute(
            select(Favorite.article_id)
            .join(Article, Article.id == Favorite.article_id)
            .where(*common)
            .group_by(Favorite.article_id)
            .order_by(func.count(Favorite.id).desc())
            .limit(need)
        )
    ).scalars().all()
    # 按 最新 → 热门 → 收藏最多 的优先级合并去重
    merged: list[dict] = []
    # 已收录的文章 ID
    seen: set[int] = set()
    # 依次补位
    for article_id in [*latest, *hottest, *most_faved]:
        # 补满即停止
        if len(merged) >= need:
            # 结束
            break
        # 三路之间去重
        if article_id in seen:
            # 跳过重复
            continue
        # 标记已收录
        seen.add(article_id)
        # 追加候选
        merged.append({"article_id": int(article_id)})
    # 返回合并结果
    return merged


# 批量取文章卡片字段(一次 IN 查询, 不含正文大字段)
async def load_article_cards(
    db: AsyncSession,
    article_ids: list[int],
) -> list[dict]:
    # 空入参直接返回, 避免拼出无意义的 IN ()
    if not article_ids:
        # 无卡片
        return []
    # 显式列投影 + 主键 IN + 仅已发布
    rows = (
        await db.execute(
            select(
                Article.id,           # 文章 ID
                Article.title,        # 标题
                Article.cover,        # 封面
                Article.summary,      # 摘要
                Article.view_count,   # 浏览量
            ).where(Article.id.in_(article_ids), Article.status == 1)
        )
    ).mappings().all()
    # 转为普通字典列表(保序由调用方按候选顺序处理)
    return [dict(row) for row in rows]
