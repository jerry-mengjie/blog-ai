"""浏览模块路由: 上报停留时长 / 我的足迹列表。

登录用户打开文章后由前端计时上报; 未登录不记入本表(全局浏览量仍走文章详情)。
上报优先投递 RocketMQ, 失败/未启用时回落同步写库, 保证接口不因 MQ 不可用而丢数。
业务逻辑在 services.browse, 本文件保持薄路由。
"""

# 导入路由与依赖工具
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
# 导入异步会话类型
from sqlalchemy.ext.asyncio import AsyncSession

# 导入数据库会话依赖与后台任务用会话工厂
from app.core.database import AsyncSessionLocal, get_db
# 导入统一响应
from app.core.response import Result, ok
# 导入当前用户依赖
from app.api.deps import get_current_user
# 导入用户模型(类型注解)
from app.models.user import User
# 导入 RocketMQ 生产者
from app.mq.producer import publish_browse_report
# 导入浏览 schema
from app.schemas.browse import BrowsePageOut, BrowseReportReq
# 导入浏览领域服务
from app.services import browse as svc

# 创建浏览路由, 前缀 /api/browse
router = APIRouter(prefix="/api/browse", tags=["浏览模块"])


# 响应返回后记录浏览: 优先 MQ, 失败则同步落库(自建会话)
async def _record_browse_report(user_id: int, article_id: int, duration: int) -> None:
    # 优先异步投递
    sent = await publish_browse_report(user_id, article_id, duration)
    # 已进队列则由 Worker 落库
    if sent:
        # 无需同步写
        return
    # MQ 未启用/超时/失败: 独立会话原子累计, 保证不丢
    async with AsyncSessionLocal() as db:
        # 原子 upsert
        await svc.report_browse(db, user_id, article_id, duration)


# 1. 上报一次浏览会话(次数 +1, 累加时长, 刷新最好浏览时间)
@router.post("/report", response_model=Result, summary="上报浏览")
async def report_browse(
    # 请求体: 文章 ID + 本次停留秒数
    body: BrowseReportReq,
    # 响应后后台投递/落库
    background: BackgroundTasks,
    # 必须登录
    current: User = Depends(get_current_user),
    # 注入会话
    db: AsyncSession = Depends(get_db),
):
    # 校验文章存在且已发布(轻量主键查询, 避免无效消息进 MQ)
    if not await svc.article_exists(db, body.article_id):
        # 文章不可用
        raise HTTPException(status_code=404, detail="文章不存在")
    # 校验通过后立即返回; 投递放到后台, 避免 MQ 卡住拖死上报接口
    background.add_task(
        _record_browse_report, current.id, body.article_id, body.duration
    )
    # async=true 表示已交后台异步处理(MQ 或同步回落)
    return ok({"reported": True, "async": True})


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
