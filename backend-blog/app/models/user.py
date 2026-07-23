"""用户 ORM 模型, 对应数据表 tb_user。"""

# 导入日期时间类型
from datetime import datetime

# 导入字段类型、复合索引与列定义
from sqlalchemy import BigInteger, DateTime, Index, SmallInteger, String, func
# 导入 2.0 风格的映射工具
from sqlalchemy.orm import Mapped, mapped_column

# 导入声明基类
from app.core.database import Base


# 用户模型类
class User(Base):
    # 绑定数据库表名
    __tablename__ = "tb_user"
    # 复合索引: 管理端列表常用「状态过滤 + 创建时间倒序」, 命中索引避免 filesort
    __table_args__ = (
        Index("idx_status_create", "status", "create_time"),
    )

    # 主键 ID, 自增
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 用户名, 唯一, 建索引
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    # 密码哈希
    password: Mapped[str] = mapped_column(String(100))
    # 昵称
    nickname: Mapped[str] = mapped_column(String(50), default="")
    # 头像 URL
    avatar: Mapped[str] = mapped_column(String(255), default="")
    # 邮箱
    email: Mapped[str] = mapped_column(String(100), default="")
    # 创建时间, 由数据库默认填充当前时间
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # 状态: 1 正常 0 禁用
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
    # 是否管理员: 1 是 0 否
    is_admin: Mapped[int] = mapped_column(SmallInteger, default=0)
