"""浏览模块路由: 上报停留时长 / 我的足迹列表。

登录用户打开文章后由前端计时上报; 未登录不记入本表(全局浏览量仍走文章详情)。
业务逻辑在 services.browse, 本文件保持薄路由。
"""

# 导入路由与依赖工具
from fastapi import APIRouter, Depends, HTTPException, Query
# 导入异步会话类型
from sqlalchemy.ext.asyncio import AsyncSession

# 导入数据库会话依赖
from app.core.database import get_db
# 导入统一响应
from app.core.response import Result, ok
# 导入当前用户依赖
from app.api.deps import get_current_user
# 导入用户模型(类型注解)
from app.models.user import User
# 导入浏览 schema
from app.schemas.browse import BrowsePageOut, BrowseReportReq
# 导入浏览领域服务
from app.services import browse as svc

# 创建浏览路由, 前缀 /api/browse
router = APIRouter(prefix="/api/browse", tags=["浏览模块"])


# 1. 上报一次浏览会话(次数 +1, 累加时长, 刷新最好浏览时间)
@router.post("/report", response_model=Result, summary="上报浏览")
async def report_browse(
    # 请求体: 文章 ID + 本次停留秒数
    body: BrowseReportReq,
    # 必须登录
    current: User = Depends(get_current_user),
    # 注入会话
    db: AsyncSession = Depends(get_db),
):
    # 校验文章存在且已发布
    if not await svc.article_exists(db, body.article_id):
        # 文章不可用
        raise HTTPException(status_code=404, detail="文章不存在")
    # 原子累计写入
    await svc.report_browse(db, current.id, body.article_id, body.duration)
    # 返回成功(无额外载荷)
    return ok({"reported": True})


# 2. 我的足迹(分页)
@router.get("/list", response_model=Result, summary="我的足迹")
async def my_browse_list(
    # 页码
    page: int = Query(1, ge=1, description="页码"),
    # 每页条数上限 50
    page_size: int = Query(10, ge=1, le=50, description="每页条数"),
    # 当前用户
    current: User = Depends(get_current_user),
    # 注入会话
    db: AsyncSession = Depends(get_db),
):
    # 查询本用户足迹
    items, total = await svc.list_my_browses(db, current.id, page, page_size)
    # 包装分页结构
    return ok(BrowsePageOut(total=total, list=items))
