"""文章推荐图: LangGraph 多节点编排(经典 StateGraph + 条件路由方案)。

图结构:
                        ┌─(有阅读/收藏历史)→ profile_recall ─┐
START → load_behavior ──┤                                    ├─(数量足)→ assemble → END
                        └─(无历史)────────→ tag_recall ──────┴─(不足)→ fallback_recall → assemble

节点职责:
1. load_behavior   : 向 backend-blog 取行为原始数据, 在本服务计算各文章偏好权重
2. profile_recall  : 把「文章 + 权重」交给 backend-rag 做画像向量召回
3. tag_recall      : 无历史用户改走兴趣标签召回(SQL 联表在 backend-blog 侧完成)
4. fallback_recall : 召回不足时兜底, 由 backend-blog 合并 最新 / 热门 / 收藏最多
5. assemble        : 去重截断后一次批量取卡片字段, 按候选顺序输出

服务边界:
- 推荐「算法」属于本服务: 权重公式、召回优先级、去重截断策略都在这里
- 推荐「数据」属于下游: MySQL 查询在 backend-blog, 向量计算在 backend-rag
这样换算法只改本文件, 换存储只改下游, 两边互不影响。

性能优化要点:
1. 每个节点只发一次网络请求, 图的深度就是最坏情况下的串行 RTT 数(最多 4 次)
2. 装配阶段一次批量取卡片, 避免逐篇查询导致的 N+1
3. 整图结果在 API 边界层做 L1/L2 缓存(见 services/recommend.py), 命中时零下游调用
4. 图编译单例: StateGraph 进程内只 compile 一次, 每次请求仅执行节点函数
"""

# 导入对数函数用于行为权重压缩
import math
# 导入日志
import logging
# 导入类型注解工具
from typing import TypedDict

# 导入 LangGraph 状态图与起止节点常量
from langgraph.graph import END, START, StateGraph

# 导入下游客户端
from app.clients import blog as blog_client
from app.clients import rag as rag_client
# 导入服务调用异常
from app.clients.http import ServiceError
# 导入全局配置
from app.core.config import settings

# 模块日志器
logger = logging.getLogger(__name__)


# 图状态: 节点间通过该字典传递数据
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
    # 下游不可用时降级为「无行为」, 推荐仍能出兜底结果
    try:
        # 取行为原始数据: 最近 N 条浏览 + 全部收藏
        raw = await blog_client.get_user_behavior(
            state["user_id"], settings.REC_BEHAVIOR_LIMIT
        )
    except ServiceError:
        # 记录后降级
        logger.warning("加载用户行为失败, 本次推荐降级为兜底策略", exc_info=True)
        # 空行为
        return {"behaviors": [], "exclude_ids": []}
    # 收藏文章 ID 集合(强偏好信号)
    fav_ids = {int(i) for i in raw["favorite_ids"]}
    # 组装偏好权重: log1p 压缩长尾, 防止单篇高频行为垄断画像
    behaviors: list[dict] = []
    # 遍历浏览行为
    for row in raw["browses"]:
        # 取出文章 ID
        article_id = int(row["article_id"])
        # 权重 = 次数项 + 时长项(分钟) + 收藏加成
        weight = (
            math.log1p(float(row.get("view_count") or 0))              # 阅读次数: 对数压缩
            + math.log1p(float(row.get("total_duration") or 0) / 60)   # 停留时长: 按分钟对数压缩
            + (settings.REC_FAVORITE_WEIGHT if article_id in fav_ids else 0.0)  # 收藏: 固定强信号
        )
        # 追加该文章的偏好记录
        behaviors.append({"article_id": article_id, "weight": weight})
    # 已出现在浏览行为中的文章
    browsed = {b["article_id"] for b in behaviors}
    # 收藏但未出现在最近浏览中的文章, 以收藏权重补入画像
    for article_id in fav_ids - browsed:
        # 仅收藏信号的偏好记录
        behaviors.append(
            {"article_id": article_id, "weight": settings.REC_FAVORITE_WEIGHT}
        )
    # 已读与已收藏文章均不再推荐
    exclude_ids = sorted(browsed | fav_ids)
    # 写回图状态
    return {"behaviors": behaviors, "exclude_ids": exclude_ids}


# 条件路由 1: 有行为走画像召回, 无阅读历史跳过画像直接标签召回
def _route_by_history(state: RecState) -> str:
    # 行为非空即认为有历史
    return "profile_recall" if state.get("behaviors") else "tag_recall"


# 节点 2: 画像向量召回 —— 行为文章加权合成偏好向量后做向量近邻检索
async def _profile_recall(state: RecState) -> dict:
    # 向量服务不可用时返回空候选, 交给兜底
    try:
        # 按权重倒序取头部行为文章, 控制画像取数规模
        top = sorted(
            state["behaviors"], key=lambda b: b["weight"], reverse=True
        )[: settings.REC_BEHAVIOR_LIMIT]
        # 交给 backend-rag 完成 画像向量合成 + 近邻召回 + 文章级聚合
        hits = await rag_client.recall_similar(
            behaviors=top,                                          # 行为与权重
            exclude_ids=state.get("exclude_ids") or [],             # 排除已读/已收藏
            limit=state["size"] * settings.REC_RECALL_BUFFER,       # 带缓冲的召回数量
        )
    except ServiceError:
        # 记录后降级
        logger.warning("画像召回失败, 转入兜底策略", exc_info=True)
        # 空候选触发兜底路由
        return {"candidates": []}
    # 标注召回策略后写入候选
    return {
        "candidates": [
            {"article_id": h["article_id"], "score": h.get("score") or 0.0, "strategy": "profile"}
            for h in hits
        ]
    }


# 节点 3: 标签召回 —— 无阅读历史用户按兴趣标签召回
async def _tag_recall(state: RecState) -> dict:
    # 匿名用户无标签, 直接空候选走兜底
    if state.get("user_id") is None:
        # 空候选触发兜底路由
        return {"candidates": []}
    # 下游不可用时返回空候选
    try:
        # 兴趣标签命中的已发布文章(SQL 联表与排序在 blog 侧完成)
        items = await blog_client.recall_by_tags(
            user_id=state["user_id"],
            exclude_ids=state.get("exclude_ids") or [],
            limit=state["size"] * settings.REC_RECALL_BUFFER,
        )
    except ServiceError:
        # 记录后降级
        logger.warning("标签召回失败, 转入兜底策略", exc_info=True)
        # 空候选
        return {"candidates": []}
    # 标注召回策略后写入候选(得分记热度值便于观察)
    return {
        "candidates": [
            {"article_id": i["article_id"], "score": float(i.get("score") or 0.0), "strategy": "tag"}
            for i in items
        ]
    }


# 条件路由 2: 召回数量足够直接装配, 不足触发兜底
def _route_after_recall(state: RecState) -> str:
    # 候选数达到目标数量即视为足够
    return "assemble" if len(state.get("candidates") or []) >= state["size"] else "fallback_recall"


# 节点 4: 兜底召回 —— 由 backend-blog 按 最新 / 热门 / 收藏最多 补齐缺口
async def _fallback_recall(state: RecState) -> dict:
    # 现有候选
    candidates = list(state.get("candidates") or [])
    # 计算缺口数量
    need = state["size"] - len(candidates)
    # 已补满则无需兜底
    if need <= 0:
        # 原样返回
        return {"candidates": candidates}
    # 排除集 = 已读/已收藏 + 已召回候选(避免兜底重复)
    excluded = set(state.get("exclude_ids") or []) | {c["article_id"] for c in candidates}
    # 下游不可用时返回现有候选
    try:
        # 取兜底文章 ID(blog 侧已按优先级合并去重)
        items = await blog_client.recall_fallback(
            exclude_ids=sorted(excluded), limit=need
        )
    except ServiceError:
        # 记录后返回现有候选
        logger.warning("兜底召回失败, 返回已有候选", exc_info=True)
        # 原样返回
        return {"candidates": candidates}
    # 依次补位
    for item in items:
        # 缺口补满即停止
        if len(candidates) >= state["size"]:
            # 结束补位
            break
        # 取出文章 ID
        article_id = int(item["article_id"])
        # 与已有候选去重
        if article_id in excluded:
            # 跳过重复
            continue
        # 记入排除集
        excluded.add(article_id)
        # 追加兜底候选(得分置 0, 策略标 fallback)
        candidates.append({"article_id": article_id, "score": 0.0, "strategy": "fallback"})
    # 写回补齐后的候选
    return {"candidates": candidates}


# 节点 5: 装配 —— 去重截断后一次批量取卡片字段, 按候选顺序输出
async def _assemble(state: RecState) -> dict:
    # 有序去重并截断到目标数量
    ordered: list[dict] = []
    # 已收录的文章 ID
    seen: set[int] = set()
    # 遍历候选(profile/tag 在前, fallback 在后)
    for cand in state.get("candidates") or []:
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
    # 下游不可用时返回空结果, 由前端展示空态
    try:
        # 一次批量取卡片字段(不含正文大字段)
        cards = await blog_client.get_article_cards(sorted(seen))
    except ServiceError:
        # 记录后返回空
        logger.warning("装配推荐卡片失败", exc_info=True)
        # 空结果
        return {"articles": []}
    # 建立 ID → 卡片 的映射便于保序
    card_map = {int(c["id"]): c for c in cards}
    # 按候选顺序输出卡片, 并附带召回策略标记
    articles = [
        {
            "id": card["id"],                          # 文章 ID
            "title": card.get("title") or "",          # 标题
            "cover": card.get("cover") or "",          # 封面
            "summary": card.get("summary") or "",      # 摘要
            "view_count": card.get("view_count") or 0,  # 浏览量
            "strategy": cand["strategy"],              # 召回策略(profile/tag/fallback)
        }
        for cand in ordered
        if (card := card_map.get(cand["article_id"])) is not None
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
    graph.add_conditional_edges(
        "load_behavior", _route_by_history, ["profile_recall", "tag_recall"]
    )
    # 条件路由: 两条召回路径后判断数量是否充足
    graph.add_conditional_edges(
        "profile_recall", _route_after_recall, ["assemble", "fallback_recall"]
    )
    graph.add_conditional_edges(
        "tag_recall", _route_after_recall, ["assemble", "fallback_recall"]
    )
    # 兜底后进入装配
    graph.add_edge("fallback_recall", "assemble")
    # 装配后结束
    graph.add_edge("assemble", END)
    # 编译为可执行图
    return graph.compile()


# 模块级编译单例: 图结构固定, 请求间复用
graph = _build_graph()


# 对外入口: 执行推荐图并返回文章卡片列表
async def recommend_articles(user_id: int | None, size: int) -> list[dict]:
    # 以初始状态调用图, LangGraph 按边路由依次执行节点
    result = await graph.ainvoke({"user_id": user_id, "size": size})
    # 返回装配好的卡片列表
    return result.get("articles") or []
