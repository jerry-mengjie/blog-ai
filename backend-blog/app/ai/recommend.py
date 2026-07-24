"""博客文章推荐系统: LangGraph 多节点编排(经典 StateGraph + 条件路由方案)。

图结构:
                        ┌─(有阅读/收藏历史)→ profile_recall ─┐
START → load_behavior ──┤                                    ├─(数量足)→ assemble → END
                        └─(无历史)────────→ tag_recall ──────┴─(不足)→ fallback_recall → assemble

节点职责:
1. load_behavior   : 读取行为数据(浏览次数/停留时长/收藏), 计算各文章偏好权重
2. profile_recall  : 行为文章向量加权平均 → 用户画像向量 → Milvus 向量召回
3. tag_recall      : 无历史用户跳过画像, 按用户兴趣标签从 MySQL 召回
4. fallback_recall : 召回不足时兜底, 依次补充 最新 / 热门 / 收藏最多 文章
5. assemble        : 去重截断, 一次 IN 查询装配文章卡片

性能优化要点:
1. MySQL: 行为查询命中 idx_user_last 只取最近 N 条; 标签召回走 idx_tag;
   兜底命中 idx_status_create / idx_status_view; 卡片一次 IN 批量装配, 全程不取正文大字段
2. Milvus: 画像向量取数与召回均走 article_id 倒排索引; 分块级检索后文章级聚合取最高分
3. 图编译单例: StateGraph 进程内只 compile 一次, 每次请求仅执行节点函数
"""

# 导入对数函数用于行为权重压缩
import math
# 导入类型注解工具(LangGraph 经典 TypedDict 状态)
from typing import TypedDict

# 导入 numpy 做画像向量加权平均
import numpy as np
# 导入 LangGraph 状态图与起止节点常量
from langgraph.graph import END, START, StateGraph
# 导入查询与聚合构造器
from sqlalchemy import func, select

# 导入 AI 开关判断(未配置 API Key 时画像召回自动降级)
from app.ai.llm import ai_enabled
# 导入向量库的文章向量聚合与按向量召回能力
from app.ai.vector_store import fetch_article_mean_vectors, search_article_ids_by_vector
# 导入会话工厂(节点内自管理短会话, 用完即还连接池)
from app.core.database import AsyncSessionLocal
# 导入相关 ORM 模型
from app.models.article import Article
from app.models.browse import UserBrowse
from app.models.favorite import Favorite
from app.models.tag import ArticleTag, UserTag

# 画像最多采用最近 N 条浏览行为(控制 Milvus 取数规模)
_BEHAVIOR_LIMIT = 20
# 收藏行为的固定加权(强偏好信号)
_FAVORITE_WEIGHT = 2.0
# 召回候选相对目标数量的缓冲倍数(去重截断后仍有富余)
_RECALL_BUFFER = 2


# 图状态: 节点间通过该字典传递数据(LangGraph 经典 TypedDict 方案)
class RecState(TypedDict, total=False):
    # 当前用户 ID(匿名为 None)
    user_id: int | None
    # 期望返回的文章数量
    size: int
    # 需要排除的文章 ID(已读/已收藏不再推荐)
    exclude_ids: list[int]
    # 行为偏好列表: [{"article_id": int, "weight": float}]
    behaviors: list[dict]
    # 召回候选列表: [{"article_id": int, "score": float, "strategy": str}]
    candidates: list[dict]
    # 最终装配的文章卡片列表
    articles: list[dict]


# 节点 1: 加载用户行为, 整合 浏览次数 / 停留时长 / 收藏 计算偏好权重
async def _load_behavior(state: RecState) -> dict:
    # 匿名用户无行为, 直接置空(后续路由到标签召回, 再兜底)
    if state.get("user_id") is None:
        # 返回空行为与空排除集
        return {"behaviors": [], "exclude_ids": []}
    # 打开短会话查询行为数据
    async with AsyncSessionLocal() as db:
        # 最近 N 条浏览: 命中 idx_user_last(user_id + last_browse_time), 只取权重计算所需列
        rows = (
            await db.execute(
                select(UserBrowse.article_id, UserBrowse.view_count, UserBrowse.total_duration)
                .where(UserBrowse.user_id == state["user_id"])
                .order_by(UserBrowse.last_browse_time.desc())
                .limit(_BEHAVIOR_LIMIT)
            )
        ).all()
        # 该用户全部收藏文章 ID: 命中 user_id 索引
        fav_ids = set(
            (
                await db.execute(
                    select(Favorite.article_id).where(Favorite.user_id == state["user_id"])
                )
            ).scalars().all()
        )
    # 组装偏好权重: log1p 压缩长尾, 防止单篇高频行为垄断画像
    behaviors: list[dict] = []
    # 遍历浏览行为
    for article_id, view_count, total_duration in rows:
        # 权重 = 次数项 + 时长项(分钟) + 收藏加成
        weight = (
            math.log1p(view_count)                                  # 阅读次数: 对数压缩
            + math.log1p(total_duration / 60)                       # 停留时长: 按分钟对数压缩
            + (_FAVORITE_WEIGHT if article_id in fav_ids else 0.0)  # 收藏: 固定强信号加成
        )
        # 追加该文章的偏好记录
        behaviors.append({"article_id": article_id, "weight": weight})
    # 收藏但未出现在最近浏览中的文章, 以收藏权重补入画像
    browsed = {b["article_id"] for b in behaviors}
    # 遍历收藏集合
    for article_id in fav_ids - browsed:
        # 仅收藏信号的偏好记录
        behaviors.append({"article_id": article_id, "weight": _FAVORITE_WEIGHT})
    # 已读与已收藏文章均不再推荐
    exclude_ids = sorted(browsed | fav_ids)
    # 写回图状态
    return {"behaviors": behaviors, "exclude_ids": exclude_ids}


# 条件路由 1: 有行为走画像召回, 无阅读历史跳过画像直接标签召回
def _route_by_history(state: RecState) -> str:
    # 行为非空即认为有历史
    return "profile_recall" if state["behaviors"] else "tag_recall"


# 节点 2: 画像向量召回 —— 行为文章向量加权平均生成偏好向量, 再向量检索
async def _profile_recall(state: RecState) -> dict:
    # AI 未启用(缺 API Key)时向量不可用, 交给兜底
    if not ai_enabled():
        # 空候选触发兜底路由
        return {"candidates": []}
    # 按权重倒序取头部行为文章, 控制 Milvus 取数规模
    top = sorted(state["behaviors"], key=lambda b: b["weight"], reverse=True)[:_BEHAVIOR_LIMIT]
    # 批量取这些文章的均值向量(一次 query, article_id 走倒排索引)
    vectors = await fetch_article_mean_vectors([b["article_id"] for b in top])
    # 行为文章都未被索引(如刚清空向量库)时无法构建画像
    if not vectors:
        # 空候选触发兜底路由
        return {"candidates": []}
    # 取出有向量的行为及其权重
    pairs = [(vectors[b["article_id"]], b["weight"]) for b in top if b["article_id"] in vectors]
    # 权重矩阵化: 向量堆叠为矩阵, 权重为列向量
    matrix = np.asarray([v for v, _ in pairs], dtype=np.float32)
    # 权重数组
    weights = np.asarray([w for _, w in pairs], dtype=np.float32)
    # 加权平均得到用户偏好向量(画像向量)
    profile = (matrix * weights[:, None]).sum(axis=0) / max(float(weights.sum()), 1e-6)
    # 用画像向量召回相似文章, 引擎侧排除已读/已收藏
    hits = await search_article_ids_by_vector(
        vector=profile.tolist(),                       # 画像向量
        exclude_ids=state["exclude_ids"],              # 排除集(not in 走倒排索引)
        limit=state["size"] * _RECALL_BUFFER,          # 带缓冲的召回数量
    )
    # 标注召回策略后写入候选
    return {
        "candidates": [
            {"article_id": h["article_id"], "score": h["score"], "strategy": "profile"}
            for h in hits
        ]
    }


# 节点 3: 标签召回 —— 无阅读历史用户按兴趣标签从 MySQL 召回
async def _tag_recall(state: RecState) -> dict:
    # 匿名用户无标签, 直接空候选走兜底
    if state.get("user_id") is None:
        # 空候选触发兜底路由
        return {"candidates": []}
    # 打开短会话执行标签召回
    async with AsyncSessionLocal() as db:
        # 用户兴趣标签 ID 集合: 命中 user_id 索引
        tag_ids = (
            await db.execute(select(UserTag.tag_id).where(UserTag.user_id == state["user_id"]))
        ).scalars().all()
        # 未绑定兴趣标签则空候选走兜底
        if not tag_ids:
            # 返回空候选
            return {"candidates": []}
        # 兴趣标签命中的已发布文章, 按热度倒序: tag_id IN 走 idx_tag, 只取 ID 与热度
        stmt = (
            select(Article.id, Article.view_count)
            .join(ArticleTag, ArticleTag.article_id == Article.id)
            .where(
                ArticleTag.tag_id.in_(tag_ids),                    # 兴趣标签过滤
                Article.status == 1,                               # 仅已发布
                Article.id.notin_(state["exclude_ids"] or [0]),    # 排除已读/已收藏
            )
            .group_by(Article.id, Article.view_count)              # 多标签命中同文章去重
            .order_by(Article.view_count.desc())                   # 兴趣内按热度排序
            .limit(state["size"] * _RECALL_BUFFER)                 # 带缓冲的召回数量
        )
        # 执行查询
        rows = (await db.execute(stmt)).all()
    # 标注召回策略后写入候选(得分记热度值便于观察)
    return {
        "candidates": [
            {"article_id": aid, "score": float(vc), "strategy": "tag"}
            for aid, vc in rows
        ]
    }


# 条件路由 2: 召回数量足够直接装配, 不足触发兜底
def _route_after_recall(state: RecState) -> str:
    # 候选数达到目标数量即视为足够
    return "assemble" if len(state["candidates"]) >= state["size"] else "fallback_recall"


# 节点 4: 兜底召回 —— 依次补充 最新 / 热门 / 收藏最多 的已发布文章
async def _fallback_recall(state: RecState) -> dict:
    # 计算缺口数量
    need = state["size"] - len(state["candidates"])
    # 排除集 = 已读/已收藏 + 已召回候选(避免兜底重复)
    excluded = set(state["exclude_ids"]) | {c["article_id"] for c in state["candidates"]}
    # 打开短会话执行三路兜底查询
    async with AsyncSessionLocal() as db:
        # 兜底查询公共条件: 已发布 + 不在排除集
        common = [Article.status == 1, Article.id.notin_(list(excluded) or [0])]
        # 兜底 1 最新: 命中 idx_status_create(status + create_time)
        latest = (
            await db.execute(
                select(Article.id).where(*common).order_by(Article.create_time.desc()).limit(need)
            )
        ).scalars().all()
        # 兜底 2 热门: 命中 idx_status_view(status + view_count)
        hottest = (
            await db.execute(
                select(Article.id).where(*common).order_by(Article.view_count.desc()).limit(need)
            )
        ).scalars().all()
        # 兜底 3 收藏最多: 收藏表按文章聚合计数(idx_article 覆盖扫描), 联表过滤已发布
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
    # 复制现有候选, 兜底结果追加其后
    candidates = list(state["candidates"])
    # 按 最新 → 热门 → 收藏最多 的优先级依次补位
    for article_id in [*latest, *hottest, *most_faved]:
        # 缺口补满即停止
        if len(candidates) >= state["size"]:
            # 结束补位
            break
        # 三路之间去重
        if article_id in excluded:
            # 跳过重复
            continue
        # 记入排除集防止后续路重复
        excluded.add(article_id)
        # 追加兜底候选(得分置 0, 策略标 fallback)
        candidates.append({"article_id": article_id, "score": 0.0, "strategy": "fallback"})
    # 写回补齐后的候选
    return {"candidates": candidates}


# 节点 5: 装配 —— 去重截断后一次 IN 查询取卡片字段, 按候选顺序输出
async def _assemble(state: RecState) -> dict:
    # 有序去重并截断到目标数量
    ordered: list[dict] = []
    # 已收录的文章 ID
    seen: set[int] = set()
    # 遍历候选(profile/tag 在前, fallback 在后)
    for cand in state["candidates"]:
        # 跳过重复文章
        if cand["article_id"] in seen:
            # 去重
            continue
        # 标记已收录
        seen.add(cand["article_id"])
        # 收录该候选
        ordered.append(cand)
        # 收满即止
        if len(ordered) >= state["size"]:
            # 结束收录
            break
    # 无任何候选(如库中无文章)直接返回空
    if not ordered:
        # 空结果
        return {"articles": []}
    # 一次 IN 查询装配卡片: 只取展示列, 不取 content 大字段
    async with AsyncSessionLocal() as db:
        # 执行批量查询
        rows = (
            await db.execute(
                select(
                    Article.id, Article.title, Article.cover,
                    Article.summary, Article.view_count,
                ).where(Article.id.in_(list(seen)), Article.status == 1)
            )
        ).all()
    # 建立 ID → 行 的映射便于保序
    row_map = {row.id: row for row in rows}
    # 按候选顺序输出卡片, 并附带召回策略标记
    articles = [
        {
            "id": row.id,                          # 文章 ID
            "title": row.title,                    # 标题
            "cover": row.cover,                    # 封面
            "summary": row.summary,                # 摘要
            "view_count": row.view_count,          # 浏览量
            "strategy": cand["strategy"],          # 召回策略(profile/tag/fallback)
        }
        for cand in ordered
        if (row := row_map.get(cand["article_id"])) is not None
    ]
    # 写回最终结果
    return {"articles": articles}


# 构建并编译推荐图(进程内仅执行一次)
def _build_graph():
    # 以 RecState 为状态创建图
    graph = StateGraph(RecState)
    # 注册五个业务节点
    graph.add_node("load_behavior", _load_behavior)
    graph.add_node("profile_recall", _profile_recall)
    graph.add_node("tag_recall", _tag_recall)
    graph.add_node("fallback_recall", _fallback_recall)
    graph.add_node("assemble", _assemble)
    # 入口: 先加载行为
    graph.add_edge(START, "load_behavior")
    # 条件路由: 有历史走画像, 无历史走标签
    graph.add_conditional_edges("load_behavior", _route_by_history, ["profile_recall", "tag_recall"])
    # 条件路由: 两条召回路径后判断数量是否充足
    graph.add_conditional_edges("profile_recall", _route_after_recall, ["assemble", "fallback_recall"])
    graph.add_conditional_edges("tag_recall", _route_after_recall, ["assemble", "fallback_recall"])
    # 兜底后进入装配
    graph.add_edge("fallback_recall", "assemble")
    # 装配后结束
    graph.add_edge("assemble", END)
    # 编译为可执行图
    return graph.compile()


# 模块级编译单例: 图结构固定, 请求间复用
_graph = _build_graph()


# 对外入口: 执行推荐图并返回文章卡片列表
async def recommend_articles(user_id: int | None, size: int) -> list[dict]:
    # 以初始状态调用图, LangGraph 按边路由依次执行节点
    result = await _graph.ainvoke({"user_id": user_id, "size": size})
    # 返回装配好的卡片列表
    return result["articles"]
