"""推荐模块路由: 个性化文章推荐(LangGraph 多节点图)。

登录用户按 画像向量 → 兴趣标签 → 兜底 的优先级召回;
匿名用户自动落入兜底策略(最新/热门/收藏最多), 接口对所有访客可用。
"""

# 导入路由与查询参数工具
from fastapi import APIRouter, Depends, Query

# 导入 LangGraph 推荐图入口
from app.ai.recommend import recommend_articles
# 导入可选登录依赖(匿名不报错)
from app.api.deps import get_current_user_optional
# 导入统一响应
from app.core.response import Result, ok
# 导入用户模型(类型注解)
from app.models.user import User
# 导入推荐 schema
from app.schemas.rec import RecListOut

# 创建推荐路由, 前缀 /api/rec
router = APIRouter(prefix="/api/rec", tags=["推荐模块"])


# 1. 获取推荐文章列表(登录个性化, 匿名兜底)
@router.get("/articles", response_model=Result, summary="推荐文章")
async def rec_articles(
    # 期望数量, 默认 6, 上限 20 防止超大请求
    size: int = Query(6, ge=1, le=20, description="推荐数量"),
    # 可选登录: 有令牌解析用户, 无令牌按匿名处理
    current: User | None = Depends(get_current_user_optional),
):
    # 执行推荐图(内部自管数据库会话与 Milvus 检索)
    articles = await recommend_articles(current.id if current else None, size)
    # 包装统一响应
    return ok(RecListOut(list=articles))
