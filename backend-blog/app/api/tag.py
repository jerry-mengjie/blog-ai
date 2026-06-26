"""标签模块路由: 全部标签/新增标签 (2 个接口)。"""

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
# 导入管理员权限依赖
from app.api.deps import require_admin
# 导入标签模型
from app.models.tag import Tag
# 导入标签 schema
from app.schemas.common import TagCreateReq, TagOut

# 创建标签路由, 前缀 /api/tag
router = APIRouter(prefix="/api/tag", tags=["标签模块"])


# 1. 全部标签(公开接口)
@router.get("/list", response_model=Result, summary="全部标签")
async def list_tags(db: AsyncSession = Depends(get_db)):
    # 查询所有标签, 按 ID 升序
    result = await db.execute(select(Tag).order_by(Tag.id.asc()))
    # 取出所有标签
    rows = result.scalars().all()
    # 映射为响应
    return ok([TagOut.model_validate(r) for r in rows])


# 2. 新增标签(仅管理员)
@router.post("/add", response_model=Result, summary="新增标签")
async def add_tag(
    body: TagCreateReq,
    _: object = Depends(require_admin),  # 校验管理员权限
    db: AsyncSession = Depends(get_db),
):
    # 校验标签名是否已存在
    exists = await db.execute(select(Tag.id).where(Tag.name == body.name))
    # 重复则报错
    if exists.scalar_one_or_none():
        # 标签已存在
        raise HTTPException(status_code=400, detail="标签已存在")
    # 构造标签对象
    tag = Tag(name=body.name)
    # 加入会话
    db.add(tag)
    # 提交事务
    await db.commit()
    # 刷新获取 ID
    await db.refresh(tag)
    # 返回新标签
    return ok(TagOut.model_validate(tag))
