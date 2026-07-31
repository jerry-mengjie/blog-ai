"""浏览统计 MQ 消息体(JSON 序列化进 Message.body)。"""

# 导入标准库 JSON 编解码
import json
# 导入 dataclass 与字典转换
from dataclasses import asdict, dataclass


# 登录用户浏览上报消息
@dataclass
class BrowseReportMsg:
    # 用户主键
    user_id: int
    # 文章主键
    article_id: int
    # 本次停留秒数
    duration: int

    # 序列化为 UTF-8 字节, 写入 RocketMQ Message.body
    def to_bytes(self) -> bytes:
        # asdict 转普通字典再 dumps
        return json.dumps(asdict(self), ensure_ascii=False).encode("utf-8")

    # 从 Message.body 反序列化
    @classmethod
    def from_bytes(cls, raw: bytes) -> "BrowseReportMsg":
        # 解码 JSON 并构造实例
        data = json.loads(raw.decode("utf-8"))
        # 显式取字段, 避免多余键污染
        return cls(
            user_id=int(data["user_id"]),
            article_id=int(data["article_id"]),
            duration=int(data["duration"]),
        )


# 文章全局浏览量消息
@dataclass
class ArticlePvMsg:
    # 文章主键
    article_id: int

    # 序列化为 UTF-8 字节
    def to_bytes(self) -> bytes:
        # 单字段 JSON
        return json.dumps(asdict(self), ensure_ascii=False).encode("utf-8")

    # 从 Message.body 反序列化
    @classmethod
    def from_bytes(cls, raw: bytes) -> "ArticlePvMsg":
        # 解码 JSON
        data = json.loads(raw.decode("utf-8"))
        # 构造实例
        return cls(article_id=int(data["article_id"]))
