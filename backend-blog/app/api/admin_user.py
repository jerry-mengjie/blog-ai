"""管理端用户路由: 分页列表 / 详情 / 资料更新 / 兴趣标签管理。

权限: 全部接口依赖 require_admin。
业务逻辑下沉至 services.user_admin, 本文件保持薄路由。
"""

# 导入路由与依赖工具
from fastapi import APIRouter, Depends, HTTPException, Query
# 导入查询构造器
from sqlalchemy import select
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
# 导入管理端 schema
from app.schemas.user import (
    AdminSetUserTagsReq,
    AdminUpdateUserReq,
    AdminUserPageOut,
)
# 导入用户管理领域服务
from app.services import user_admin as svc

# 创建管理端用户路由, 前缀 /api/admin/user
router = APIRouter(prefix="/api/admin/user", tags=["管理端-用户"])


# 1. 用户分页列表
@router.get("/list", response_model=Result, summary="用户分页列表")
async def admin_list_users(
    # 页码, 从 1 起
    page: int = Query(1, ge=1, description="页码"),
    # 每页条数, 上限 100 防止大页拖垮
    page_size: int = Query(10, ge=1, le=100, description="每页条数"),
    # 用户名/昵称关键字
    keyword: str = Query("", max_length=50, description="用户名/昵称关键字"),
    # 状态过滤, 不传则不过滤
    status: int | None = Query(None, ge=0, le=1, description="状态过滤: 1正常 0禁用"),
    # 校验管理员
    _: User = Depends(require_admin),
    # 注入会话
    db: AsyncSession = Depends(get_db),
):
    # 调用服务层分页查询
    items, total = await svc.list_users(
        db, page=page, page_size=page_size, keyword=keyword.strip(), status=status
    )
    # 包装分页结构返回
    return ok(AdminUserPageOut(total=total, list=items))


# 2. 用户详情
@router.get("/detail/{user_id}", response_model=Result, summary="用户详情")
async def admin_user_detail(
    # 路径参数: 用户 ID
    user_id: int,
    # 校验管理员
    _: User = Depends(require_admin),
    # 注入会话
    db: AsyncSession = Depends(get_db),
):
    # 查询详情
    data = await svc.get_user_detail(db, user_id)
    # 不存在返回 404
    if not data:
        # 用户不存在
        raise HTTPException(status_code=404, detail="用户不存在")
    # 返回详情
    return ok(data)


# 3. 更新用户资料(昵称/邮箱/头像/状态/管理员标识)
@router.put("/{user_id}", response_model=Result, summary="更新用户资料")
async def admin_update_user(
    # 路径参数: 目标用户 ID
    user_id: int,
    # 请求体
    body: AdminUpdateUserReq,
    # 当前管理员(用于自保护校验)
    current: User = Depends(require_admin),
    # 注入会话
    db: AsyncSession = Depends(get_db),
):
    # 按主键加载目标用户
    result = await db.execute(select(User).where(User.id == user_id))
    # 取出用户
    user = result.scalar_one_or_none()
    # 不存在返回 404
    if not user:
        # 用户不存在
        raise HTTPException(status_code=404, detail="用户不存在")
    # 禁止禁用当前登录账号, 防止把自己锁死
    if body.status is not None and body.status == 0 and user.id == current.id:
        # 自禁用拦截
        raise HTTPException(status_code=400, detail="不能禁用当前登录账号")
    # 禁止取消自己的管理员权限
    if body.is_admin is not None and body.is_admin == 0 and user.id == current.id:
        # 自降权拦截
        raise HTTPException(status_code=400, detail="不能取消自己的管理员权限")
    # 按需更新昵称
    if body.nickname is not None:
        # 写入昵称
        user.nickname = body.nickname
    # 按需更新邮箱
    if body.email is not None:
        # 写入邮箱
        user.email = body.email
    # 按需更新头像
    if body.avatar is not None:
        # 写入头像
        user.avatar = body.avatar
    # 按需更新状态
    if body.status is not None:
        # 写入状态
        user.status = body.status
    # 按需更新管理员标识
    if body.is_admin is not None:
        # 写入管理员标识
        user.is_admin = body.is_admin
    # 提交事务
    await db.commit()
    # 刷新 ORM 状态
    await db.refresh(user)
    # 返回最新详情(含兴趣标签)
    data = await svc.get_user_detail(db, user_id)
    # 包装响应
    return ok(data)


# 4. 设置用户兴趣标签(全量替换, 标签来自文章标签词典)
@router.put("/{user_id}/tags", response_model=Result, summary="设置用户兴趣标签")
async def admin_set_user_tags(
    # 路径参数: 用户 ID
    user_id: int,
    # 请求体: 标签 ID 列表
    body: AdminSetUserTagsReq,
    # 校验管理员
    _: User = Depends(require_admin),
    # 注入会话
    db: AsyncSession = Depends(get_db),
):
    # 先确认用户存在(只查 id, 轻量)
    exists = await db.execute(select(User.id).where(User.id == user_id))
    # 不存在返回 404
    if exists.scalar_one_or_none() is None:
        # 用户不存在
        raise HTTPException(status_code=404, detail="用户不存在")
    # 尝试全量替换标签
    try:
        # 调用服务层替换
        tags = await svc.replace_user_tags(db, user_id, body.tag_ids)
    except ValueError as e:
        # 标签 ID 非法转为 400
        raise HTTPException(status_code=400, detail=str(e)) from e
    # 拉取完整详情返回(与更新资料接口响应形状一致)
    data = await svc.get_user_detail(db, user_id)
    # 若详情异常(理论上不应), 至少返回刚写入的标签
    if data is None:
        # 兜底仅返回标签
        return ok({"interest_tags": tags})
    # 正常返回详情
    return ok(data)
