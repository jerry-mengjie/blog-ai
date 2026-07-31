"""浏览统计 RocketMQ Worker 入口。

经典方案: SimpleConsumer 长轮询 receive → 业务处理 → ack。
启动: uv run python -m app.mq.worker
"""

# 导入异步事件循环
import asyncio
# 导入日志
import logging
# 导入信号处理(优雅退出)
import signal
# 导入 sleep 做 receive 异常退避
import time

# 导入 RocketMQ 5.x 官方消费者 API
from rocketmq import ClientConfiguration, Credentials, FilterExpression, SimpleConsumer

# 导入全局配置
from app.core.config import settings
# 导入消息处理
from app.mq.handler import handle_browse_message
# 导入 Topic/消费组
from app.mq.topics import browse_group, browse_topic

# 配置根日志格式, 便于 docker/本地直接看输出
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Worker 专用日志器
logger = logging.getLogger("app.mq.worker")

# 主循环开关, 收到停止信号后置 False
_running = True


# SIGINT/SIGTERM 回调: 标记退出, 不在回调里做重活
def _stop(*_args) -> None:
    # 修改全局开关
    global _running
    # 置为停止
    _running = False
    # 提示即将退出
    logger.info("收到停止信号, 准备退出 Worker")


# Worker 主流程(阻塞运行直到停止)
def main() -> None:
    # 未配置 endpoints 则直接失败, 避免空转
    if not settings.ROCKETMQ_ENDPOINTS.strip():
        # 抛出明确错误
        raise SystemExit("请先在 .env 配置 ROCKETMQ_ENDPOINTS(例如 127.0.0.1:8022)")
    # 注册 Ctrl+C
    signal.signal(signal.SIGINT, _stop)
    # 注册 kill/docker stop
    signal.signal(signal.SIGTERM, _stop)
    # 本地无鉴权空凭证
    credentials = Credentials()
    # Proxy gRPC 地址
    config = ClientConfiguration(settings.ROCKETMQ_ENDPOINTS, credentials)
    # 订阅 Topic, FilterExpression() 默认匹配全部 Tag
    subscriptions = {browse_topic(): FilterExpression()}
    # 创建 SimpleConsumer(经典推/拉混合长轮询模型)
    consumer = SimpleConsumer(config, browse_group(), subscriptions)
    # 启动消费者
    consumer.startup()
    # 启动成功日志
    logger.info(
        "浏览统计 Worker 已启动 endpoints=%s topic=%s group=%s",
        settings.ROCKETMQ_ENDPOINTS,
        browse_topic(),
        browse_group(),
    )
    # 为异步 handler 准备独立事件循环(RocketMQ 客户端本身是同步 API)
    loop = asyncio.new_event_loop()
    # 设为当前线程默认循环
    asyncio.set_event_loop(loop)
    # 主消费循环
    try:
        # 直到收到停止信号
        while _running:
            # 拉取一批消息(同步阻塞, 最长约 await_duration)
            try:
                # max_message_num=16 批量; invisible_duration=30s 处理窗口
                messages = consumer.receive(16, 30)
            except Exception as exc:
                # 空拉取/网络抖动常见, 警告后短睡再试
                logger.warning("receive 异常: %s", exc)
                # 退避 1 秒避免狂打日志
                time.sleep(1)
                # 继续下一轮
                continue
            # 无消息则继续轮询
            if not messages:
                # 下一轮
                continue
            # 逐条处理
            for msg in messages:
                # 取出 Tag(可能为 None)
                tag = msg.tag or ""
                # 取出正文并统一为 bytes
                body = msg.body
                # 兼容 str/bytearray
                if isinstance(body, str):
                    # 转 bytes
                    body = body.encode("utf-8")
                elif isinstance(body, bytearray):
                    # 转不可变 bytes
                    body = bytes(body)
                # 业务处理; 失败不 ack, 等待可见性超时重投
                try:
                    # 在事件循环中跑异步 handler
                    loop.run_until_complete(handle_browse_message(tag, body))
                    # 成功则 ack, 消息出队
                    consumer.ack(msg)
                except Exception:
                    # 记录失败, 故意不 ack
                    logger.exception(
                        "处理浏览消息失败 message_id=%s",
                        getattr(msg, "message_id", None),
                    )
    finally:
        # 关闭事件循环
        loop.close()
        # 关闭消费者
        try:
            # shutdown 释放连接
            consumer.shutdown()
        except Exception:
            # 关闭失败仅记日志
            logger.exception("Consumer 关闭失败")
        # 退出日志
        logger.info("浏览统计 Worker 已退出")


# 允许 python -m app.mq.worker 启动
if __name__ == "__main__":
    # 进入主流程
    main()
