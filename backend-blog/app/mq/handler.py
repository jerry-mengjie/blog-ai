"""浏览统计消息处理器: 消费侧调用领域服务落库。

与 indexer 相同模式: 自建 AsyncSessionLocal, 失败抛出让 Worker 不 ack 以便重试。
"""

# 导入日志
import logging

# 导入独立会话工厂(Worker 不走 FastAPI 依赖注入)
from app.core.database import AsyncSessionLocal
# 导入消息体
from app.mq.messages import ArticlePvMsg, BrowseReportMsg
# 导入 Tag 常量
from app.mq.topics import TAG_PV, TAG_REPORT
# 导入浏览领域服务
from app.services import browse as browse_svc

# 模块日志器
logger = logging.getLogger(__name__)


# 按 Tag 分发并落库; 未知 Tag 仅告警
async def handle_browse_message(tag: str, body: bytes) -> None:
    # 登录用户浏览上报
    if tag == TAG_REPORT:
        # 反序列化消息
        msg = BrowseReportMsg.from_bytes(body)
        # 独立会话写入 MySQL
        async with AsyncSessionLocal() as db:
            # 原子 upsert 累计
            await browse_svc.report_browse(db, msg.user_id, msg.article_id, msg.duration)
        # 记录消费成功
        logger.info(
            "消费浏览上报 user=%s article=%s duration=%s",
            msg.user_id,
            msg.article_id,
            msg.duration,
        )
        # 处理完成
        return
    # 文章全局 PV
    if tag == TAG_PV:
        # 反序列化
        msg = ArticlePvMsg.from_bytes(body)
        # 独立会话原子 +1
        async with AsyncSessionLocal() as db:
            # SQL 层 view_count = view_count + 1, 避免并发丢更新
            await browse_svc.incr_article_view(db, msg.article_id)
        # 记录成功
        logger.info("消费文章 PV article=%s", msg.article_id)
        # 处理完成
        return
    # 未知 Tag 不抛错(避免毒消息无限重试), 仅告警
    logger.warning("忽略未知浏览消息 tag=%s", tag)
