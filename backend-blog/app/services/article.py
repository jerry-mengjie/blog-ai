"""文章 Feed 领域服务: MySQL 查询 + 经典 L1/L2 多级缓存。

缓存策略(首页热点):
1. /list 第 1 页: 全部(cat=all) + 各 category_id
2. /top 置顶列表: 固定 TopN(默认 10), 单 key
读: MultiLevelCache L1 内存 → L2 Redis → MySQL 回源
写: 发文/编辑/删除后失效 list + top 前缀, 避免脏读

MySQL 性能:
- 只 SELECT 列表列, 永不加载 content
- /list 排序命中 idx_status_top_time / idx_status_cat_top_time
- /top 条件 status+is_top + create_time 命中 idx_status_top_time
"""

# 导入聚合与查询构造
from sqlalchemy import func, select
# 导入异步会话
from sqlalchemy.ext.asyncio import AsyncSession

# 导入多级缓存
from app.core.cache import MultiLevelCache
# 导入配置(TTL / L1 容量)
from app.core.config import settings
# 导入文章模型
from app.models.article import Article
# 导入响应 schema
from app.schemas.article import ArticleListItem, PageOut

# ---------- 列表缓存 ----------
# 列表缓存 key 前缀(版本号便于结构变更时整批作废)
_LIST_CACHE_PREFIX = "article:list:v1:"
# 仅第 1 页走多级缓存
_CACHE_PAGE = 1
# 进程级列表多级缓存实例
_list_cache = MultiLevelCache(
    ttl_seconds=settings.ARTICLE_LIST_CACHE_TTL,
    l1_maxsize=settings.ARTICLE_LIST_L1_MAXSIZE,
    prefix=_LIST_CACHE_PREFIX,
)

# ---------- 置顶缓存 ----------
# 置顶缓存 key 前缀
_TOP_CACHE_PREFIX = "article:top:v1:"
# 置顶条数上限(与历史接口 LIMIT 10 对齐)
_TOP_LIMIT = 10
# 进程级置顶多级缓存实例(复用同一 TTL/L1 容量配置)
_top_cache = MultiLevelCache(
    ttl_seconds=settings.ARTICLE_LIST_CACHE_TTL,
    l1_maxsize=settings.ARTICLE_LIST_L1_MAXSIZE,
    prefix=_TOP_CACHE_PREFIX,
)


# 归一化分类: None/0 → all, 其余用数字字符串
def _cat_token(category_id: int | None) -> str:
    # 无分类或 0 视为全部分类
    if not category_id:
        # 全部
        return "all"
    # 具体分类 ID
    return str(int(category_id))


# 是否命中「第 1 页缓存」条件
def _should_cache(page: int) -> bool:
    # 仅首页
    return page == _CACHE_PAGE


# 构造列表缓存 key: p1:ps{size}:cat:{all|id}
def _list_cache_key(page_size: int, category_id: int | None) -> str:
    # 分段拼接, 前缀由 MultiLevelCache 统一加
    return _list_cache.make_key(f"p{_CACHE_PAGE}", f"ps{page_size}", f"cat:{_cat_token(category_id)}")


# 构造置顶缓存 key: limit{N}
def _top_cache_key(limit: int) -> str:
    # 条数写入 key, 避免日后改 LIMIT 读到旧数据
    return _top_cache.make_key(f"limit{limit}")


# 从 MySQL 查询一页文章列表(不含缓存)
async def query_article_page(
    db: AsyncSession,
    page: int,
    page_size: int,
    category_id: int | None = None,
) -> PageOut:
    # 基础条件: 仅已发布
    conditions = [Article.status == 1]
    # 指定分类时追加等值过滤(命中 idx_status_cat_top_time 左前缀)
    if category_id:
        # 分类过滤
        conditions.append(Article.category_id == category_id)
    # 统计总数(轻量 count, 不取行数据)
    total = await db.scalar(
        select(func.count()).select_from(Article).where(*conditions)
    )
    # 列表查询: 显式列投影, 避开 content 大字段
    stmt = (
        select(
            Article.id,              # 主键
            Article.title,           # 标题
            Article.cover,           # 封面
            Article.summary,         # 摘要
            Article.category_id,     # 分类
            Article.view_count,      # 浏览量(允许短时缓存陈旧)
            Article.is_top,          # 置顶标记
            Article.create_time,     # 创建时间
        )
        .where(*conditions)                                    # 过滤
        .order_by(Article.is_top.desc(), Article.create_time.desc())  # 置顶优先再按时间
        .offset((page - 1) * page_size)                        # 偏移
        .limit(page_size)                                      # 条数
    )
    # 执行
    result = await db.execute(stmt)
    # 映射为 schema 列表
    items = [ArticleListItem.model_validate(row) for row in result.mappings().all()]
    # 组装分页结构
    return PageOut(total=total or 0, list=items)


# 从 MySQL 查询置顶文章(不含缓存)
async def query_top_articles(
    db: AsyncSession,
    limit: int = _TOP_LIMIT,
) -> list[ArticleListItem]:
    # 显式列投影 + 等值过滤 + 时间倒序 + LIMIT
    stmt = (
        select(
            Article.id,              # 主键
            Article.title,           # 标题
            Article.cover,           # 封面
            Article.summary,         # 摘要
            Article.category_id,     # 分类
            Article.view_count,      # 浏览量
            Article.is_top,          # 置顶标记
            Article.create_time,     # 创建时间
        )
        # status=1 且 is_top=1: 命中 idx_status_top_time 左前缀后按 create_time
        .where(Article.status == 1, Article.is_top == 1)
        # 最新置顶优先
        .order_by(Article.create_time.desc())
        # 固定条数, 结果集极小
        .limit(limit)
    )
    # 执行查询
    result = await db.execute(stmt)
    # 映射为列表项 schema
    return [ArticleListItem.model_validate(row) for row in result.mappings().all()]


# 对外列表入口: 第 1 页走多级缓存, 其余直查 MySQL
async def list_articles(
    db: AsyncSession,
    page: int,
    page_size: int,
    category_id: int | None = None,
) -> PageOut:
    # 非首页不缓存, 直接查库
    if not _should_cache(page):
        # 直连 MySQL
        return await query_article_page(db, page, page_size, category_id)
    # 缓存 key
    key = _list_cache_key(page_size, category_id)

    # 回源闭包: 查库后转为可 JSON 序列化的 dict
    async def _factory() -> dict:
        # 打 MySQL
        page_out = await query_article_page(db, page, page_size, category_id)
        # model_dump 便于 L2 JSON 存储(datetime → ISO)
        return page_out.model_dump(mode="json")

    # L1 → L2 → MySQL
    payload = await _list_cache.get_or_set(key, _factory)
    # 反序列化为 PageOut(兼容 dict 回填)
    return PageOut.model_validate(payload)


# 对外置顶入口: L1 → L2 → MySQL
async def list_top_articles(
    db: AsyncSession,
    limit: int = _TOP_LIMIT,
) -> list[ArticleListItem]:
    # 规范化条数下限, 防止非法 limit
    size = max(1, int(limit))
    # 固定 key(首页置顶 Tab 热点)
    key = _top_cache_key(size)

    # 回源闭包: 查库后序列化为 JSON 友好结构
    async def _factory() -> list[dict]:
        # 打 MySQL
        items = await query_top_articles(db, size)
        # 逐条 dump, 便于 Redis JSON 存储
        return [item.model_dump(mode="json") for item in items]

    # L1 → L2 → MySQL
    payload = await _top_cache.get_or_set(key, _factory)
    # 还原为 schema 列表
    return [ArticleListItem.model_validate(row) for row in payload]


# 失效列表缓存(全部 + 各分类第 1 页)
async def invalidate_article_list_cache() -> None:
    # 清 L1 并 SCAN 删除 L2 前缀下全部 key
    await _list_cache.invalidate_prefix(f"{_LIST_CACHE_PREFIX}*")


# 失效置顶缓存
async def invalidate_article_top_cache() -> None:
    # 清 L1 并 SCAN 删除置顶前缀
    await _top_cache.invalidate_prefix(f"{_TOP_CACHE_PREFIX}*")


# 文章变更后统一失效 Feed 相关缓存(list + top)
async def invalidate_article_caches() -> None:
    # 先失效列表第 1 页
    await invalidate_article_list_cache()
    # 再失效置顶(is_top/status/删除都会影响)
    await invalidate_article_top_cache()
