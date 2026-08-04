"""文章 ORM 模型, 对应数据表 tb_article。"""

# 导入日期时间类型
from datetime import datetime

# 导入字段类型与索引工具
from sqlalchemy import BigInteger, DateTime, Index, Integer, SmallInteger, String, Text, func
# 导入映射工具
from sqlalchemy.orm import Mapped, mapped_column

# 导入声明基类
from app.core.database import Base


# 文章模型类
class Article(Base):
    # 绑定表名
    __tablename__ = "tb_article"
    # 复合索引(列表 / 推荐兜底查询用)
    __table_args__ = (
        # 全部分类列表: status + 置顶优先 + 时间倒序, 免 filesort
        Index("idx_status_top_time", "status", "is_top", "create_time"),
        # 按分类列表: status + category + 置顶 + 时间, 覆盖 /list?category_id=
        Index("idx_status_cat_top_time", "status", "category_id", "is_top", "create_time"),
        # 兜底"最新": 状态过滤 + 时间倒序免 filesort
        Index("idx_status_create", "status", "create_time"),
        # 兜底"热门": 状态过滤 + 浏览量倒序免 filesort
        Index("idx_status_view", "status", "view_count"),
    )

    # 主键 ID
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 作者用户 ID, 建索引
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # 标题
    title: Mapped[str] = mapped_column(String(200))
    # 封面图 URL
    cover: Mapped[str] = mapped_column(String(255), default="")
    # 正文(大字段), 列表查询时不应加载以提升性能
    content: Mapped[str] = mapped_column(Text, default="")
    # 摘要
    summary: Mapped[str] = mapped_column(String(500), default="")
    # 分类 ID, 建索引
    category_id: Mapped[int] = mapped_column(BigInteger, default=0, index=True)
    # 浏览量
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    # 是否置顶: 1 是 0 否
    is_top: Mapped[int] = mapped_column(SmallInteger, default=0)
    # 创建时间
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # 更新时间, 行更新时自动刷新
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    # 状态: 1 已发布 0 草稿/下架
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
