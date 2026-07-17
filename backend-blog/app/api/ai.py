"""AI 问答模块路由: 配置查询/文章问答(SSE 流式)/全量重建索引 (3 个接口)。"""

# 导入 json 用于序列化 SSE 数据帧
import json
# 导入 time 用于滑动窗口限流
import time
# 导入 defaultdict 存储各 IP 的请求时间戳
from collections import defaultdict, deque

# 导入路由与依赖工具
from fastapi import APIRouter, Depends, HTTPException, Request
# 导入 SSE 流式响应
from fastapi.responses import StreamingResponse
# 导入查询构造器
from sqlalchemy import select
# 导入异步会话类型
from sqlalchemy.ext.asyncio import AsyncSession

# 导入数据库会话依赖
from app.core.database import get_db
# 导入统一响应
from app.core.response import Result, ok
# 导入全局配置
from app.core.config import settings
# 导入管理员依赖(重建索引为管理操作)
from app.api.deps import require_admin
# 导入文章模型
from app.models.article import Article
# 导入 AI 能力模块
from app.ai.llm import ai_enabled
from app.ai.indexer import reindex_all
from app.ai.rag import PRESET_QUESTIONS, answer_stream, extract_sources, retrieve
# 导入请求 schema
from app.schemas.ai import AskReq

# 创建 AI 路由, 前缀 /api/ai
router = APIRouter(prefix="/api/ai", tags=["AI 问答模块"])

# 内存滑动窗口限流器: IP -> 最近请求时间戳队列(单实例部署的轻量方案)
_rate_buckets: dict[str, deque] = defaultdict(deque)


# 内部工具: 单 IP 每分钟请求数限流, 超限抛 429
def _check_rate_limit(ip: str) -> None:
    # 当前时间戳
    now = time.monotonic()
    # 取出该 IP 的时间戳队列
    bucket = _rate_buckets[ip]
    # 移除 60 秒之前的旧记录(滑动窗口)
    while bucket and now - bucket[0] > 60:
        # 弹出过期时间戳
        bucket.popleft()
    # 窗口内已达上限则拒绝
    if len(bucket) >= settings.AI_RATE_LIMIT:
        # 返回 429 提示稍后再试
        raise HTTPException(status_code=429, detail="提问太频繁, 请稍后再试")
    # 记录本次请求时间
    bucket.append(now)


# 内部工具: 将事件与数据序列化为一条 SSE 消息
def _sse(event: str, data: dict | str) -> str:
    # data 为字典时序列化为 JSON
    payload = json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else data
    # 按 SSE 协议拼装 "event + data + 空行"
    return f"event: {event}\ndata: {payload}\n\n"


# 1. AI 问答配置: 前端据此渲染入口与预设问题
@router.get("/config", response_model=Result, summary="AI 问答配置")
async def ai_config():
    # 返回开关状态与预设问题列表
    return ok({"enabled": ai_enabled(), "preset_questions": PRESET_QUESTIONS})


# 2. 文章问答(SSE 流式): 检索当前文章/系列内容后流式生成回答
@router.post("/ask", summary="文章 AI 问答(SSE 流式)")
async def ask(
    body: AskReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # 未配置 API Key 时功能不可用
    if not ai_enabled():
        # 返回 503 提示未启用
        raise HTTPException(status_code=503, detail="AI 问答功能未启用")
    # 单 IP 限流, 防止刷接口消耗 token
    _check_rate_limit(request.client.host if request.client else "unknown")
    # 查询文章(仅取必要列, 不加载正文大字段)
    result = await db.execute(
        select(Article.id, Article.title, Article.category_id, Article.status)
        .where(Article.id == body.article_id)
    )
    # 取出文章行
    article = result.mappings().first()
    # 不存在或未发布则报错
    if not article or article["status"] != 1:
        # 文章不存在
        raise HTTPException(status_code=404, detail="文章不存在")

    # SSE 事件生成器: sources -> 多个 delta -> done
    async def event_stream():
        # 异常兜底: 流式过程中出错以 error 事件告知前端
        try:
            # 检索阶段: 按范围取回相关分块
            chunks = await retrieve(
                question=body.question,
                article_id=article["id"],
                category_id=article["category_id"],
                scope=body.scope,
            )
            # 先下发来源文章列表, 前端可提前渲染引用
            yield _sse("sources", {"sources": extract_sources(chunks)})
            # 生成阶段: 流式下发回答增量
            async for delta in answer_stream(body.question, article["title"], chunks):
                # 每段增量作为一条 delta 事件
                yield _sse("delta", {"text": delta})
            # 下发结束事件
            yield _sse("done", {})
        except Exception:
            # 出错时下发 error 事件, 前端提示重试
            yield _sse("error", {"message": "回答生成失败, 请稍后重试"})

    # 返回 SSE 流式响应, 关闭代理缓冲保证实时性
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",     # 禁止缓存流式内容
            "X-Accel-Buffering": "no",       # 关闭 Nginx 缓冲, 逐帧推送
        },
    )


# 3. 全量重建向量索引(管理员): 初始化或更换向量模型后手动触发
@router.post("/reindex", response_model=Result, summary="全量重建向量索引")
async def reindex(_: object = Depends(require_admin)):
    # 未配置 API Key 时功能不可用
    if not ai_enabled():
        # 返回 503 提示未启用
        raise HTTPException(status_code=503, detail="AI 问答功能未启用")
    # 同步执行全量重建并返回处理数量(文章多时耗时较长)
    count = await reindex_all()
    # 返回重建的文章数
    return ok({"indexed": count}, message="重建完成")
