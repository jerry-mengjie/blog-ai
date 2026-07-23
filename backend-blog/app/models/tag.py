"""标签 / 文章标签 / 用户兴趣标签 ORM 模型。

对应表: tb_tag、tb_article_tag、tb_user_tag。
兴趣标签复用全局标签词典, 避免维护两套标签名。
"""

# 导入日期时间类型
from datetime import datetime

# 导入字段类型与唯一约束
from sqlalchemy import BigInteger, DateTime, String, UniqueConstraint, func
# 导入映射工具
from sqlalchemy.orm import Mapped, mapped_column

# 导入声明基类
from app.core.database import Base


# 标签模型类(全局词典, 文章标签与用户兴趣标签共用)
class Tag(Base):
    # 绑定表名
    __tablename__ = "tb_tag"

    # 主键 ID
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 标签名称, 唯一
    name: Mapped[str] = mapped_column(String(50), unique=True)


# 文章-标签 关联模型(多对多中间表)
class ArticleTag(Base):
    # 绑定表名
    __tablename__ = "tb_article_tag"
    # 联合唯一约束, 防止同一文章重复绑定同一标签
    __table_args__ = (
        UniqueConstraint("article_id", "tag_id", name="uk_article_tag"),
    )

    # 主键 ID
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 文章 ID, 建索引
    article_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # 标签 ID, 建索引
    tag_id: Mapped[int] = mapped_column(BigInteger, index=True)


# 用户-兴趣标签 关联模型(复用 tb_tag, 不另建标签名)
class UserTag(Base):
    # 绑定表名
    __tablename__ = "tb_user_tag"
    # 联合唯一约束, 防止同一用户重复绑定同一标签
    __table_args__ = (
        UniqueConstraint("user_id", "tag_id", name="uk_user_tag"),
    )

    # 主键 ID
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 用户 ID, 建索引(按用户查兴趣标签)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # 标签 ID, 建索引(按标签反查用户)
    tag_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # 绑定时间, 由数据库默认填充
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
