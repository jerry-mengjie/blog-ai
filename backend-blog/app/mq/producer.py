"""RocketMQ 生产者单例: 浏览上报 / 文章 PV 异步投递。

经典方案: rocketmq-python-client Producer + Topic/Tag 二级分类。
同步 send 包在 asyncio.to_thread, 不阻塞 FastAPI 事件循环。
"""

# 导入异步工具(to_thread 卸载阻塞 send)
import asyncio
# 导入日志
import logging
# 导入线程锁保证 Producer 懒加载线程安全
import threading

# 导入 RocketMQ 5.x 官方 Python 客户端(经典 Producer API)
from rocketmq import ClientConfiguration, Credentials, Message, Producer

# 导入全局配置
from app.core.config import settings
# 导入消息体
from app.mq.messages import ArticlePvMsg, BrowseReportMsg
# 导入 Topic/Tag
from app.mq.topics import TAG_PV, TAG_REPORT, browse_topic

# 模块日志器
logger = logging.getLogger(__name__)

# 进程内 Producer 单例(未启动时为 None)
_producer: Producer | None = None

# 保护 _producer 初始化的互斥锁
_lock = threading.Lock()

# 投递超时秒数: Proxy/Broker 异常时避免拖死 HTTP 请求
_SEND_TIMEOUT_SEC = 3.0


# 是否启用 RocketMQ(未配置 endpoints 则关闭, API 回落同步写库)
def mq_enabled() -> bool:
    # 去掉空白后非空即视为启用
    return bool(settings.ROCKETMQ_ENDPOINTS.strip())


# 懒加载并启动 Producer(双检锁)
def _ensure_producer() -> Producer | None:
    # 声明写全局单例
    global _producer
    # 未启用直接返回
    if not mq_enabled():
        # 调用方据此判断走同步回落
        return None
    # 已有实例则复用
    if _producer is not None:
        # 返回单例
        return _producer
    # 加锁创建
    with _lock:
        # 双检: 其他线程可能已创建
        if _producer is not None:
            # 直接返回
            return _producer
        # 本地无鉴权时使用空凭证
        credentials = Credentials()
        # 指向 Proxy gRPC 地址(如 127.0.0.1:8022)
        config = ClientConfiguration(settings.ROCKETMQ_ENDPOINTS, credentials)
        # 预声明 Topic, 启动时完成路由感知
        producer = Producer(config, (browse_topic(),))
        # 启动底层客户端
        producer.startup()
        # 赋值全局单例
        _producer = producer
        # 记录启动日志
        logger.info(
            "RocketMQ Producer 已启动 endpoints=%s", settings.ROCKETMQ_ENDPOINTS
        )
        # 返回实例
        return _producer


# 应用关闭时释放 Producer
def shutdown_producer() -> None:
    # 声明写全局单例
    global _producer
    # 加锁避免与发送并发
    with _lock:
        # 未启动则无事可做
        if _producer is None:
            # 直接返回
            return
        # 尝试优雅关闭
        try:
            # 关闭客户端连接
            _producer.shutdown()
            # 记录成功
            logger.info("RocketMQ Producer 已关闭")
        except Exception:
            # 关闭失败只记日志, 不阻断进程退出
            logger.exception("RocketMQ Producer 关闭失败")
        finally:
            # 无论成败都清空单例
            _producer = None


# 同步发送一条消息(供 to_thread 调用)
def _send_sync(tag: str, body: bytes, keys: str) -> bool:
    # 确保 Producer 可用
    producer = _ensure_producer()
    # 未启用则视为投递失败, 上层回落
    if producer is None:
        # 返回失败
        return False
    # 构造消息对象
    msg = Message()
    # 设置 Topic
    msg.topic = browse_topic()
    # 设置 Tag 做二级分类
    msg.tag = tag
    # 设置业务键便于排查/排查堆积
    msg.keys = keys
    # 设置二进制正文
    msg.body = body
    # 同步发送并拿到回执
    result = producer.send(msg)
    # 调试级记录回执
    logger.debug("RocketMQ 投递成功 tag=%s keys=%s result=%s", tag, keys, result)
    # 返回成功
    return True


# 带超时的异步投递; 超时/异常返回 False 触发同步回落
async def _publish(tag: str, body: bytes, keys: str, err_msg: str, *err_args) -> bool:
    # 未启用 MQ 直接失败
    if not mq_enabled():
        # 返回失败
        return False
    # 捕获超时与发送异常, 避免打垮请求
    try:
        # 阻塞 send 丢到线程池, 并限制最长等待
        return await asyncio.wait_for(
            asyncio.to_thread(_send_sync, tag, body, keys),
            timeout=_SEND_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        # Proxy/Broker 卡住时记警告并回落
        logger.warning("RocketMQ 投递超时(%.1fs) %s", _SEND_TIMEOUT_SEC, keys)
        # 回落标记
        return False
    except Exception:
        # 记录失败并返回 False 触发回落
        logger.exception(err_msg, *err_args)
        # 回落标记
        return False


# 异步投递浏览上报; 成功 True, 未启用/失败 False(由 API 回落同步写)
async def publish_browse_report(user_id: int, article_id: int, duration: int) -> bool:
    # 构造消息体
    payload = BrowseReportMsg(user_id=user_id, article_id=article_id, duration=duration)
    # 带超时投递
    return await _publish(
        TAG_REPORT,
        payload.to_bytes(),
        f"browse-{user_id}-{article_id}",
        "浏览上报投递失败 user=%s article=%s",
        user_id,
        article_id,
    )


# 异步投递文章 PV; 成功 True, 未启用/失败 False
async def publish_article_pv(article_id: int) -> bool:
    # 构造 PV 消息
    payload = ArticlePvMsg(article_id=article_id)
    # 带超时投递
    return await _publish(
        TAG_PV,
        payload.to_bytes(),
        f"pv-{article_id}",
        "文章 PV 投递失败 article=%s",
        article_id,
    )
