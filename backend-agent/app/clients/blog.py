"""backend-blog 内部接口客户端: 本服务获取业务数据的唯一入口。

设计原则: MySQL 只属于 backend-blog。本服务需要的用户行为、兴趣标签、
文章卡片等一律通过内部接口取, 不直连数据库, 也不复制一份 ORM 模型。
"""

# 导入服务客户端基类
from app.clients.http import ServiceClient
# 导入全局配置
from app.core.config import settings

# backend-blog 客户端单例
_client = ServiceClient("backend-blog", settings.BLOG_BASE_URL)


# 取文章元信息(标题/分类/状态), 问答前用于校验文章可用性
async def get_article_meta(article_id: int) -> dict | None:
    # 调用内部接口
    data = await _client.get(f"/internal/article/{article_id}/meta")
    # 不存在时接口返回 data=None
    return data or None


# 取用户账号状态(是否管理员/是否可用), 管理操作前二次校验
async def get_user_state(user_id: int) -> dict | None:
    # 调用内部接口
    data = await _client.get(f"/internal/user/{user_id}")
    # 不存在时接口返回 data=None
    return data or None


# 取用户行为原始数据: 最近浏览记录 + 收藏文章 ID
async def get_user_behavior(user_id: int, limit: int) -> dict:
    # 调用内部接口, 行为条数上限由本服务决定
    data = await _client.get(
        f"/internal/rec/behavior/{user_id}", params={"limit": limit}
    )
    # 保证结构完整, 避免上层反复判空
    return {
        "browses": (data or {}).get("browses") or [],
        "favorite_ids": (data or {}).get("favorite_ids") or [],
    }


# 兴趣标签召回: 按用户绑定的标签取已发布文章(SQL 联表在 blog 侧完成)
async def recall_by_tags(user_id: int, exclude_ids: list[int], limit: int) -> list[dict]:
    # 调用内部接口
    data = await _client.post(
        "/internal/rec/recall/tags",
        json={"user_id": user_id, "exclude_ids": exclude_ids, "limit": limit},
    )
    # 返回候选列表
    return (data or {}).get("items") or []


# 兜底召回: 最新 / 热门 / 收藏最多, 由 blog 侧按优先级合并去重
async def recall_fallback(exclude_ids: list[int], limit: int) -> list[dict]:
    # 调用内部接口
    data = await _client.post(
        "/internal/rec/recall/fallback",
        json={"exclude_ids": exclude_ids, "limit": limit},
    )
    # 返回候选列表
    return (data or {}).get("items") or []


# 批量取文章卡片字段(一次 IN 查询, 不含正文大字段)
async def get_article_cards(article_ids: list[int]) -> list[dict]:
    # 空入参直接返回, 省一次网络往返
    if not article_ids:
        # 无卡片
        return []
    # 调用内部接口
    data = await _client.post(
        "/internal/rec/cards", json={"article_ids": article_ids}
    )
    # 返回卡片列表
    return (data or {}).get("items") or []
