"""标签与文章标签关联 ORM 模型, 对应 tb_tag 与 tb_article_tag。"""

# 导入字段类型
from sqlalchemy import BigInteger, String, UniqueConstraint
# 导入映射工具
from sqlalchemy.orm import Mapped, mapped_column

# 导入声明基类
from app.core.database import Base


# 标签模型类
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
