"""推荐缓存服务: 在 LangGraph 推荐链路外层加经典 L1 + L2 多级缓存。

缓存策略:
1. 匿名请求按 size 聚合为高命中共享 key
2. 登录请求按 user_id + size 分 key, 使用短 TTL 平衡实时性与性能
3. 文章增删改后统一清推荐缓存; 浏览/收藏/标签变更依赖短 TTL 自然收敛

性能要点:
1. 缓存在 API 边界层, 命中时直接跳过 LangGraph / MySQL / Milvus
2. L1 同进程零网络, L2 Redis 跨 Worker 共享
3. 单飞锁防止匿名热点与大用户同时击穿底层推荐链路
"""

# 导入多级缓存门面
from app.core.cache import MultiLevelCache
# 导入全局配置
from app.core.config import settings
# 导入 LangGraph 推荐入口
from app.ai.recommend import recommend_articles

# 推荐缓存 key 前缀(版本号便于结构调整后整批作废)
_REC_CACHE_PREFIX = "rec:articles:v1:"
# 推荐缓存实例(复用通用多级缓存门面)
_rec_cache = MultiLevelCache(
    ttl_seconds=settings.REC_ARTICLE_CACHE_TTL,
    l1_maxsize=settings.REC_ARTICLE_L1_MAXSIZE,
    prefix=_REC_CACHE_PREFIX,
)


# 构造推荐缓存 key: 匿名共享 / 登录按 user_id 隔离
def _rec_cache_key(user_id: int | None, size: int) -> str:
    # 匿名请求共享同一批推荐 key
    scope = "anon" if user_id is None else f"user:{int(user_id)}"
    # size 写入 key, 避免不同数量串值
    return _rec_cache.make_key(scope, f"size:{int(size)}")


# 对外入口: 先查缓存, miss 再执行 LangGraph 推荐链路
async def list_recommended_articles(user_id: int | None, size: int) -> list[dict]:
    # 规范化请求数量, 与路由层上限保持一致
    normalized_size = max(1, int(size))
    # 生成当前请求的缓存 key
    key = _rec_cache_key(user_id, normalized_size)

    # 回源闭包: 真 miss 时才执行 LangGraph + MySQL + Milvus
    async def _factory() -> list[dict]:
        # 执行底层推荐图, 返回已经装配好的卡片列表
        articles = await recommend_articles(user_id, normalized_size)
        # 直接返回 JSON 友好的字典列表
        return articles

    # L1 → L2 → LangGraph 推荐链路
    payload = await _rec_cache.get_or_set(key, _factory)
    # 返回推荐结果
    return payload


# 文章内容变更后失效推荐缓存(匿名 + 所有用户推荐)
async def invalidate_recommend_cache() -> None:
    # 清空 L1 并按前缀批量删除 Redis key
    await _rec_cache.invalidate_prefix(f"{_REC_CACHE_PREFIX}*")
