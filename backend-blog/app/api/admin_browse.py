"""管理端浏览统计路由: 分页查询用户×文章浏览累计数据。

权限: require_admin。列表逻辑在 services.browse。
"""

# 导入路由与依赖工具
from fastapi import APIRouter, Depends, Query
# 导入异步会话类型
from sqlalchemy.ext.asyncio import AsyncSession

# 导入数据库会话依赖
from app.core.database import get_db
# 导入统一响应
from app.core.response import Result, ok
# 导入管理员权限依赖
from app.api.deps import require_admin
# 导入用户模型
from app.models.user import User
# 导入浏览分页 schema
from app.schemas.browse import BrowsePageOut
# 导入浏览领域服务
from app.services import browse as svc

# 创建管理端浏览路由
router = APIRouter(prefix="/api/admin/browse", tags=["管理端-浏览"])


# 1. 浏览统计分页列表
@router.get("/list", response_model=Result, summary="浏览统计列表")
async def admin_browse_list(
    # 页码
    page: int = Query(1, ge=1, description="页码"),
    # 每页条数上限 100
    page_size: int = Query(10, ge=1, le=100, description="每页条数"),
    # 按用户 ID 过滤
    user_id: int | None = Query(None, ge=1, description="用户ID"),
    # 按文章 ID 过滤
    article_id: int | None = Query(None, ge=1, description="文章ID"),
    # 关键字: 用户名/昵称/文章标题
    keyword: str = Query("", max_length=50, description="用户名/昵称/标题关键字"),
    # 校验管理员
    _: User = Depends(require_admin),
    # 注入会话
    db: AsyncSession = Depends(get_db),
):
    # 调用服务层分页查询
    items, total = await svc.admin_list_browses(
        db,
        page=page,
        page_size=page_size,
        user_id=user_id,
        article_id=article_id,
        keyword=keyword.strip(),
    )
    # 包装分页结构返回
    return ok(BrowsePageOut(total=total, list=items))
