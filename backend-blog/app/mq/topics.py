"""浏览统计 Topic / Tag / 消费组常量(与 .env 默认值对齐)。"""

# 导入全局配置
from app.core.config import settings


# 浏览统计 Topic 名称(Producer/Consumer 共用)
def browse_topic() -> str:
    # 从配置读取, 便于环境差异化
    return settings.ROCKETMQ_TOPIC_BROWSE


# 浏览统计消费组名称(Worker 订阅用)
def browse_group() -> str:
    # 从配置读取消费组
    return settings.ROCKETMQ_GROUP_BROWSE


# Tag: 登录用户上报停留时长
TAG_REPORT = "report"

# Tag: 文章全局 PV +1
TAG_PV = "pv"
