"""推荐路由: 个性化文章推荐(LangGraph 多节点图) + 缓存失效内部接口。

登录用户按 画像向量 → 兴趣标签 → 兜底 的优先级召回;
匿名用户自动落入兜底策略(最新/热门/收藏最多), 接口对所有访客可用。
"""

# 导入路由与查询参数工具
from fastapi import APIRouter, Depends, Query

# 导入依赖
from app.api.deps import current_user_id_optional, verify_internal_token
# 导入统一响应
from app.core.response import Result, ok
# 导入响应模型
from app.schemas.recommend import RecListOut
# 导入推荐缓存服务
from app.services import recommend as recommend_svc

# 创建推荐路由, 前缀 /api/rec
router = APIRouter(prefix="/api/rec", tags=["推荐"])

# 创建内部路由, 供 backend-blog 在文章变更后通知失效缓存
internal_router = APIRouter(
    prefix="/internal/rec",
    tags=["推荐-内部"],
    dependencies=[Depends(verify_internal_token)],
)


# 1. 获取推荐文章列表(登录个性化, 匿名兜底, API 边界层多级缓存)
@router.get("/articles", response_model=Result, summary="推荐文章")
async def rec_articles(
    # 期望数量, 默认 6, 上限 20 防止超大请求
    size: int = Query(6, ge=1, le=20, description="推荐数量"),
    # 可选登录: 有令牌解析用户, 无令牌按匿名处理
    user_id: int | None = Depends(current_user_id_optional),
):
    # 先查 L1/L2; miss 时才执行 LangGraph 推荐图
    articles = await recommend_svc.list_recommended_articles(user_id, size)
    # 包装统一响应
    return ok(RecListOut(list=articles))


# 2. 失效推荐缓存(内部接口): 文章发布/编辑/删除后由 backend-blog 调用
@internal_router.post("/invalidate", response_model=Result, summary="失效推荐缓存")
async def invalidate_cache():
    # 清空 L1 并按前缀删除 L2
    await recommend_svc.invalidate_recommend_cache()
    # 返回成功
    return ok(message="缓存已失效")
