"""收藏 ORM 模型, 对应数据表 tb_favorite。"""

# 导入日期时间类型
from datetime import datetime

# 导入字段类型
from sqlalchemy import BigInteger, DateTime, UniqueConstraint, func
# 导入映射工具
from sqlalchemy.orm import Mapped, mapped_column

# 导入声明基类
from app.core.database import Base


# 收藏模型类
class Favorite(Base):
    # 绑定表名
    __tablename__ = "tb_favorite"
    # 联合唯一约束, 防止重复收藏
    __table_args__ = (
        UniqueConstraint("user_id", "article_id", name="uk_user_article"),
    )

    # 主键 ID
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 用户 ID, 建索引
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # 文章 ID, 建索引
    article_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # 收藏时间
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
