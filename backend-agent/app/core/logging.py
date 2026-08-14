"""日志初始化: 统一格式, 便于多服务日志聚合时按服务名检索。"""

# 导入标准日志库
import logging

# 导入全局配置
from app.core.config import settings

# 日志格式: 时间 + 级别 + 服务名 + 模块 + 消息
_FORMAT = "%(asctime)s %(levelname)s [agent] %(name)s: %(message)s"


# 配置根日志器, 在应用启动最早期调用一次
def setup_logging() -> None:
    # basicConfig 幂等: 已有 handler 时不会重复添加
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format=_FORMAT,
    )
    # httpx 会把每次服务间调用打成 INFO, 噪音过大统一降级
    for noisy in ("httpx", "httpcore", "openai"):
        # 逐个提升阈值
        logging.getLogger(noisy).setLevel(logging.WARNING)
