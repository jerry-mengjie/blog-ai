"""backend-agent 客户端: 文章变更后通知失效推荐缓存。

推荐结果缓存在 backend-agent 里(它才是推荐的产出方), 但「什么时候该失效」
只有本服务知道 —— 文章的增删改都可能让推荐结果里出现已删除或已下架的文章。
因此由本服务在写路径末尾发一条通知; 推荐缓存本身是短 TTL(默认 30s),
通知失败也只是多陈旧几十秒, 所以这里同样只记日志不抛错。
"""

# 导入日志
import logging

# 导入全局配置
from app.core.config import settings
# 导入客户端工厂
from app.clients.base import get_client

# 模块日志器
logger = logging.getLogger(__name__)


# 内部工具: 获取 backend-agent 客户端
def _agent():
    # 复用单例
    return get_client("backend-agent", settings.AGENT_BASE_URL)


# 是否启用编排服务通知
def agent_enabled() -> bool:
    # 地址非空即启用
    return bool(settings.AGENT_BASE_URL and settings.AGENT_BASE_URL.strip())


# 后台任务: 通知 backend-agent 失效推荐缓存
async def invalidate_recommend_cache() -> None:
    # 未启用则跳过
    if not agent_enabled():
        # 静默返回
        return
    # 通知失败仅告警, 由推荐缓存的短 TTL 兜底
    try:
        # 调用内部失效接口
        resp = await _agent().post("/internal/rec/invalidate")
        # 非 2xx 记录状态码
        resp.raise_for_status()
    except Exception:
        # 记录异常但不抛出
        logger.warning("通知失效推荐缓存失败, 将由 TTL 自然过期", exc_info=True)
