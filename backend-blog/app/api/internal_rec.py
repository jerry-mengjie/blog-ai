"""内部推荐取数接口: 供 backend-agent 的推荐图使用 (4 个接口)。

只提供「取数」, 不提供「策略」—— 权重公式、召回优先级、去重截断都在
backend-agent 侧。对应的 SQL 全部收敛在 services/recall.py。
"""

# 导入路由与依赖工具
from fastapi import APIRouter, Depends, Query
# 导入异步会话类型
from sqlalchemy.ext.asyncio import AsyncSession

# 导入服务间令牌校验
from app.api.deps import verify_internal_token
# 导入数据库会话依赖
from app.core.database import get_db
# 导入统一响应
from app.core.response import Result, ok
# 导入内部契约模型
from app.schemas.internal import (
    BehaviorOut,
    CardsOut,
    CardsReq,
    FallbackRecallReq,
    RecallOut,
    TagRecallReq,
)
# 导入召回取数服务
from app.services import recall as recall_svc

# 创建内部推荐路由, 全局挂服务间令牌校验
router = APIRouter(
    prefix="/internal/rec",
    tags=["内部-推荐取数"],
    dependencies=[Depends(verify_internal_token)],
)


# 1. 用户行为原始数据: 最近浏览 + 全部收藏
@router.get("/behavior/{user_id}", response_model=Result, summary="用户行为原始数据")
async def user_behavior(
    user_id: int,
    # 取最近多少条浏览记录, 由调用方(推荐图)决定
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    # 查询行为数据
    data = await recall_svc.load_user_behavior(db, user_id, limit)
    # 返回结构化结果
    return ok(BehaviorOut(**data))


# 2. 兴趣标签召回
@router.post("/recall/tags", response_model=Result, summary="兴趣标签召回")
async def recall_tags(body: TagRecallReq, db: AsyncSession = Depends(get_db)):
    # 执行标签召回
    items = await recall_svc.recall_by_tags(
        db, body.user_id, body.exclude_ids, body.limit
    )
    # 返回候选列表
    return ok(RecallOut(items=items))


# 3. 兜底召回(最新 / 热门 / 收藏最多)
@router.post("/recall/fallback", response_model=Result, summary="兜底召回")
async def recall_fallback(
    body: FallbackRecallReq, db: AsyncSession = Depends(get_db)
):
    # 执行兜底召回
    items = await recall_svc.recall_fallback(db, body.exclude_ids, body.limit)
    # 返回候选列表
    return ok(RecallOut(items=items))


# 4. 批量取文章卡片
@router.post("/cards", response_model=Result, summary="批量取文章卡片")
async def article_cards(body: CardsReq, db: AsyncSession = Depends(get_db)):
    # 一次 IN 查询取卡片字段
    items = await recall_svc.load_article_cards(db, body.article_ids)
    # 返回卡片列表
    return ok(CardsOut(items=items))
