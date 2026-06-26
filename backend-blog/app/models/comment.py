"""评论 ORM 模型, 对应数据表 tb_comment。"""

# 导入日期时间类型
from datetime import datetime

# 导入字段类型
from sqlalchemy import BigInteger, DateTime, SmallInteger, String, func
# 导入映射工具
from sqlalchemy.orm import Mapped, mapped_column

# 导入声明基类
from app.core.database import Base


# 评论模型类
class Comment(Base):
    # 绑定表名
    __tablename__ = "tb_comment"

    # 主键 ID
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 所属文章 ID, 建索引
    article_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # 评论用户 ID, 建索引
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # 父评论 ID, 0 表示顶级评论
    parent_id: Mapped[int] = mapped_column(BigInteger, default=0)
    # 评论内容
    content: Mapped[str] = mapped_column(String(1000))
    # 创建时间
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # 状态: 1 正常 0 删除/屏蔽
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
