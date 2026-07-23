"""用户文章浏览统计 ORM 模型, 对应数据表 tb_user_browse。

一行记录「某用户对某文章」的累计浏览: 总次数、总时长、最好(最长)一次的时间。
"""

# 导入日期时间类型
from datetime import datetime

# 导入字段类型、唯一约束与索引
from sqlalchemy import BigInteger, DateTime, Index, Integer, UniqueConstraint, func
# 导入映射工具
from sqlalchemy.orm import Mapped, mapped_column

# 导入声明基类
from app.core.database import Base


# 用户-文章浏览统计模型(一对多累计, 非流水日志)
class UserBrowse(Base):
    # 绑定表名
    __tablename__ = "tb_user_browse"
    # 唯一约束 + 列表/反查索引
    __table_args__ = (
        # 同一用户同一文章仅一行, 支撑 upsert 累计
        UniqueConstraint("user_id", "article_id", name="uk_user_browse"),
        # 我的足迹: 按用户过滤 + 最近浏览倒序
        Index("idx_user_last", "user_id", "last_browse_time"),
        # 按文章反查读者/统计
        Index("idx_article", "article_id"),
    )

    # 主键 ID
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 用户 ID
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 文章 ID
    article_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 浏览总次数
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    # 总时长(秒)
    total_duration: Mapped[int] = mapped_column(Integer, default=0)
    # 单次最长浏览时长(秒), 用于判定「最好」那次
    best_duration: Mapped[int] = mapped_column(Integer, default=0)
    # 最好浏览时间: 单次时长创纪录时的时间点
    best_browse_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 最近浏览时间(列表排序用)
    last_browse_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    # 首次记录时间
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
