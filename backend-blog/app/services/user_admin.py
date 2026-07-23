"""用户管理领域服务: 列表/详情/资料更新/兴趣标签绑定。

路由层只做鉴权与入参转发, 复杂查询与批量装配放在此处, 保持代码简洁。
性能要点:
1. 列表只选必要列, 永不 SELECT password
2. 兴趣标签一次 IN 批量加载, 避免 N+1
3. 列表过滤命中 idx_status_create 复合索引
"""

# 导入删除、聚合、或条件与查询构造器
from sqlalchemy import delete, func, or_, select
# 导入异步会话类型
from sqlalchemy.ext.asyncio import AsyncSession
# 导入列延迟加载工具(列表不取 password)
from sqlalchemy.orm import load_only

# 导入用户模型
from app.models.user import User
# 导入标签与用户兴趣标签模型
from app.models.tag import Tag, UserTag
# 导入管理端响应 schema
from app.schemas.user import AdminUserOut, TagBrief

# 管理端用户列表/详情需要的列(显式排除 password)
_USER_COLS = (
    User.id,
    User.username,
    User.nickname,
    User.avatar,
    User.email,
    User.status,
    User.is_admin,
    User.create_time,
)


# 批量装配用户兴趣标签: 一次 JOIN + IN, 返回 {user_id: [TagBrief, ...]}
async def map_user_tags(
    db: AsyncSession,
    user_ids: list[int],
) -> dict[int, list[TagBrief]]:
    # 空列表直接返回, 避免无效 SQL
    if not user_ids:
        # 无用户则映射为空
        return {}
    # 初始化每个用户的空标签列表, 保证调用方 get 时必有 key
    mapping: dict[int, list[TagBrief]] = {uid: [] for uid in user_ids}
    # 一次查出所有用户的标签(只取 id/name, 不拖无关列)
    result = await db.execute(
        select(UserTag.user_id, Tag.id, Tag.name)
        .join(Tag, Tag.id == UserTag.tag_id)
        .where(UserTag.user_id.in_(user_ids))
        .order_by(Tag.id.asc())
    )
    # 遍历结果行, 按 user_id 分桶
    for user_id, tag_id, name in result.all():
        # 追加到对应用户的标签列表
        mapping[user_id].append(TagBrief(id=tag_id, name=name))
    # 返回完整映射
    return mapping


# 将 ORM 用户与标签列表组装为管理端响应(显式字段, 永不带 password)
def to_admin_user_out(user: User, tags: list[TagBrief]) -> AdminUserOut:
    # 构造响应对象
    return AdminUserOut(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        avatar=user.avatar,
        email=user.email,
        status=user.status,
        is_admin=user.is_admin,
        create_time=user.create_time,
        interest_tags=tags,
    )


# 分页查询用户列表, 支持关键字与状态过滤
async def list_users(
    db: AsyncSession,
    page: int,
    page_size: int,
    keyword: str = "",
    status: int | None = None,
) -> tuple[list[AdminUserOut], int]:
    # 动态 WHERE 条件列表
    conditions: list = []
    # 关键字非空时按用户名/昵称模糊匹配(OR)
    if keyword:
        # 构造 LIKE 模式
        like = f"%{keyword}%"
        # 追加 OR 条件
        conditions.append(or_(User.username.like(like), User.nickname.like(like)))
    # 状态过滤(命中 idx_status_create 左前缀)
    if status is not None:
        # 追加状态等值条件
        conditions.append(User.status == status)
    # 计数语句: 只 count(id), 不加载行
    count_stmt = select(func.count(User.id))
    # 有条件则挂上 where
    if conditions:
        # 应用过滤
        count_stmt = count_stmt.where(*conditions)
    # 执行计数
    total = int((await db.execute(count_stmt)).scalar_one())
    # 列表语句: 只加载必要列 + 按创建时间倒序分页
    list_stmt = (
        select(User)
        .options(load_only(*_USER_COLS))
        .order_by(User.create_time.desc())
    )
    # 有条件则挂上 where
    if conditions:
        # 应用过滤
        list_stmt = list_stmt.where(*conditions)
    # 分页偏移与限制
    list_stmt = list_stmt.offset((page - 1) * page_size).limit(page_size)
    # 执行列表查询
    rows = (await db.execute(list_stmt)).scalars().all()
    # 批量加载本页用户的兴趣标签(避免 N+1)
    tag_map = await map_user_tags(db, [u.id for u in rows])
    # 装配响应列表
    items = [to_admin_user_out(u, tag_map.get(u.id, [])) for u in rows]
    # 返回 (列表, 总数)
    return items, total


# 查询单个用户详情(含兴趣标签), 不存在返回 None
async def get_user_detail(db: AsyncSession, user_id: int) -> AdminUserOut | None:
    # 按主键查用户(不加载 password)
    result = await db.execute(
        select(User).options(load_only(*_USER_COLS)).where(User.id == user_id)
    )
    # 取出用户或 None
    user = result.scalar_one_or_none()
    # 不存在则直接返回
    if not user:
        # 调用方据此返回 404
        return None
    # 批量加载该用户标签(复用同一工具函数)
    tag_map = await map_user_tags(db, [user.id])
    # 组装并返回
    return to_admin_user_out(user, tag_map.get(user.id, []))


# 校验标签 ID: 去重后核对 tb_tag 是否全部存在, 返回 (有效ID列表, 缺失ID列表)
async def validate_tag_ids(
    db: AsyncSession,
    tag_ids: list[int],
) -> tuple[list[int], list[int]]:
    # 保序去重, 避免重复插入
    unique_ids = list(dict.fromkeys(tag_ids))
    # 空列表无需查库
    if not unique_ids:
        # 无标签即全部有效
        return [], []
    # 一次查出存在的标签 ID
    result = await db.execute(select(Tag.id).where(Tag.id.in_(unique_ids)))
    # 转为集合便于差集
    found = set(result.scalars().all())
    # 计算缺失 ID
    missing = [tid for tid in unique_ids if tid not in found]
    # 返回有效与缺失
    return unique_ids, missing


# 全量替换用户兴趣标签: 先删后插, 保证与请求一致
async def replace_user_tags(
    db: AsyncSession,
    user_id: int,
    tag_ids: list[int],
) -> list[TagBrief]:
    # 校验标签是否存在
    valid_ids, missing = await validate_tag_ids(db, tag_ids)
    # 有缺失则抛错, 由路由转为 400
    if missing:
        # 拼出缺失 ID 便于前端提示
        raise ValueError(f"标签不存在: {missing}")
    # 删除该用户全部旧绑定(单条 DELETE, 命中 user_id 索引)
    await db.execute(delete(UserTag).where(UserTag.user_id == user_id))
    # 逐个插入新绑定
    for tid in valid_ids:
        # 构造关联行
        db.add(UserTag(user_id=user_id, tag_id=tid))
    # 提交事务
    await db.commit()
    # 重新加载并返回最新标签列表
    tag_map = await map_user_tags(db, [user_id])
    # 取出该用户标签
    return tag_map.get(user_id, [])
