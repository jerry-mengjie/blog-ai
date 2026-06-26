"""分类模块路由: 全部分类/新增分类 (2 个接口)。"""

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
# 导入分类模型
from app.models.category import Category
# 导入分类 schema
from app.schemas.common import CategoryCreateReq, CategoryOut

# 创建分类路由, 前缀 /api/category
router = APIRouter(prefix="/api/category", tags=["分类模块"])


# 1. 全部分类(公开接口, 按 sort 升序)
@router.get("/list", response_model=Result, summary="全部分类")
async def list_categories(db: AsyncSession = Depends(get_db)):
    # 按排序值升序查询所有分类
    result = await db.execute(select(Category).order_by(Category.sort.asc()))
    # 取出所有分类对象
    rows = result.scalars().all()
    # 映射为响应 schema
    return ok([CategoryOut.model_validate(r) for r in rows])


# 2. 新增分类(仅管理员)
@router.post("/add", response_model=Result, summary="新增分类")
async def add_category(
    body: CategoryCreateReq,
    _: object = Depends(require_admin),  # 校验管理员权限
    db: AsyncSession = Depends(get_db),
):
    # 校验分类名是否已存在
    exists = await db.execute(select(Category.id).where(Category.name == body.name))
    # 重复则报错
    if exists.scalar_one_or_none():
        # 分类已存在
        raise HTTPException(status_code=400, detail="分类已存在")
    # 构造分类对象
    category = Category(name=body.name, sort=body.sort)
    # 加入会话
    db.add(category)
    # 提交事务
    await db.commit()
    # 刷新获取 ID
    await db.refresh(category)
    # 返回新分类
    return ok(CategoryOut.model_validate(category))
