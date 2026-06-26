"""分类 ORM 模型, 对应数据表 tb_category。"""

# 导入日期时间类型
from datetime import datetime

# 导入字段类型
from sqlalchemy import BigInteger, DateTime, Integer, String, func
# 导入映射工具
from sqlalchemy.orm import Mapped, mapped_column

# 导入声明基类
from app.core.database import Base


# 分类模型类
class Category(Base):
    # 绑定表名
    __tablename__ = "tb_category"

    # 主键 ID
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 分类名称, 唯一
    name: Mapped[str] = mapped_column(String(50), unique=True)
    # 排序值, 越小越靠前
    sort: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # 创建时间
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
