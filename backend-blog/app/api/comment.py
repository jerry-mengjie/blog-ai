"""评论模块路由: 文章评论列表/发表评论/删除评论 (3 个接口)。"""

# 导入路由与依赖工具
from fastapi import APIRouter, Depends, HTTPException
# 导入查询构造器
from sqlalchemy import select
# 导入异步会话类型
from sqlalchemy.ext.asyncio import AsyncSession

# 导入数据库会话依赖
from app.core.database import get_db
# 导入统一响应
from app.core.response import Result, ok
# 导入当前用户依赖
from app.api.deps import get_current_user
# 导入模型
from app.models.comment import Comment
from app.models.user import User
# 导入评论 schema
from app.schemas.common import CommentCreateReq, CommentOut

# 创建评论路由, 前缀 /api/comment
router = APIRouter(prefix="/api/comment", tags=["评论模块"])


# 1. 文章评论列表(公开, 联表查询用户昵称头像)
@router.get("/list/{article_id}", response_model=Result, summary="文章评论列表")
async def list_comments(article_id: int, db: AsyncSession = Depends(get_db)):
    # 联表查询: 评论 + 用户信息, 仅取正常状态评论, 按时间倒序
    stmt = (
        select(
            Comment.id,
            Comment.article_id,
            Comment.user_id,
            Comment.parent_id,
            Comment.content,
            Comment.create_time,
            User.nickname,
            User.avatar,
        )
        .join(User, User.id == Comment.user_id)
        .where(Comment.article_id == article_id, Comment.status == 1)
        .order_by(Comment.create_time.desc())
    )
    # 执行查询
    result = await db.execute(stmt)
    # 映射为响应对象
    items = [CommentOut.model_validate(row) for row in result.mappings().all()]
    # 返回评论列表
    return ok(items)


# 2. 发表评论(需登录)
@router.post("/add", response_model=Result, summary="发表评论")
async def add_comment(
    body: CommentCreateReq,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 构造评论对象
    comment = Comment(
        article_id=body.article_id,
        user_id=current.id,
        parent_id=body.parent_id,
        content=body.content,
    )
    # 加入会话
    db.add(comment)
    # 提交事务
    await db.commit()
    # 刷新获取 ID
    await db.refresh(comment)
    # 返回新评论 ID
    return ok({"id": comment.id})


# 3. 删除评论(需登录, 仅本人或管理员)
@router.delete("/del/{comment_id}", response_model=Result, summary="删除评论")
async def delete_comment(
    comment_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 查询评论
    result = await db.execute(select(Comment).where(Comment.id == comment_id))
    # 取出评论
    comment = result.scalar_one_or_none()
    # 不存在则报错
    if not comment:
        # 评论不存在
        raise HTTPException(status_code=404, detail="评论不存在")
    # 权限校验: 非本人且非管理员禁止删除
    if comment.user_id != current.id and current.is_admin != 1:
        # 无权限
        raise HTTPException(status_code=403, detail="无权删除该评论")
    # 逻辑删除: 将状态置为 0(保留数据便于审计)
    comment.status = 0
    # 提交事务
    await db.commit()
    # 返回成功
    return ok(message="删除成功")
