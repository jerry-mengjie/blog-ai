"""AI 问答路由: 配置查询 / 文章问答(SSE 流式) / 全量重建索引 (3 个接口)。

接口路径与拆分前完全一致(/api/ai/*), 前端代码无需任何改动, 只是由网关或
Vite 代理把 /api/ai 指向本服务。

SSE 事件序列: sources → delta(多条) → done, 出错时下发 error。
"""

# 导入 json 用于序列化 SSE 数据帧
import json
# 导入日志
import logging

# 导入路由与依赖工具
from fastapi import APIRouter, Depends, HTTPException, Request

# 导入 SSE 流式响应
from fastapi.responses import StreamingResponse

# 导入依赖
from app.api.deps import require_admin, require_ai_enabled
# 导入下游客户端
from app.clients import blog as blog_client
from app.clients import rag as rag_client
# 导入服务调用异常
from app.clients.http import ServiceError
# 导入限流
from app.core.ratelimit import allow_ask
# 导入统一响应
from app.core.response import Result, ok
# 导入问答图
from app.graphs import qa
# 导入 AI 开关
from app.llm.models import ai_enabled
# 导入预设问题
from app.llm.prompts import PRESET_QUESTIONS
# 导入请求/响应模型
from app.schemas.chat import AiConfigOut, AskReq, ReindexOut

# 模块日志器
logger = logging.getLogger(__name__)

# 创建 AI 路由, 前缀 /api/ai
router = APIRouter(prefix="/api/ai", tags=["AI 问答"])


# 内部工具: 将事件与数据序列化为一条 SSE 消息
def _sse(event: str, data: dict) -> str:
    # 按 SSE 协议拼装 "event + data + 空行"
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# 1. AI 问答配置: 前端据此渲染入口与预设问题
@router.get("/config", response_model=Result, summary="AI 问答配置")
async def ai_config():
    # 返回开关状态与预设问题列表
    return ok(AiConfigOut(enabled=ai_enabled(), preset_questions=PRESET_QUESTIONS))


# 2. 文章问答(SSE 流式): 执行问答图并把检索来源与生成 token 逐帧推送
@router.post(
    "/ask",
    summary="文章 AI 问答(SSE 流式)",
    dependencies=[Depends(require_ai_enabled)],
)
async def ask(body: AskReq, request: Request):
    # 单 IP 限流, 防止刷接口消耗 token
    if not await allow_ask(request.client.host if request.client else "unknown"):
        # 超限返回 429
        raise HTTPException(status_code=429, detail="提问太频繁, 请稍后再试")
    # 取文章元信息(标题/分类/状态), 由 backend-blog 提供
    try:
        # 调内部接口
        meta = await blog_client.get_article_meta(body.article_id)
    except ServiceError as exc:
        # 业务服务不可达
        raise HTTPException(status_code=503, detail="业务服务不可用") from exc
    # 文章不存在或未发布则报错
    if not meta or int(meta.get("status") or 0) != 1:
        # 文章不存在
        raise HTTPException(status_code=404, detail="文章不存在")

    # 图的初始状态
    init_state = {
        "question": body.question,                              # 读者问题
        "article_id": int(meta["article_id"]),                  # 文章 ID
        "category_id": int(meta.get("category_id") or 0),       # 分类 ID
        "article_title": meta.get("title") or "",               # 文章标题
        "scope": body.scope,                                    # 检索范围
    }

    # SSE 事件生成器: sources -> 多个 delta -> done
    async def event_stream():
        # 检索到的来源(可能被 widen 节点覆盖为放宽后的结果)
        sources: list[dict] = []
        # 是否已下发 sources 事件
        sources_sent = False
        # 异常兜底: 流式过程中出错以 error 事件告知前端
        try:
            # 同时订阅两种流:
            # - updates : 节点返回值, 用于拿到检索到的片段
            # - messages: 节点内部大模型的流式 token
            async for mode, payload in qa.graph.astream(
                init_state, stream_mode=["updates", "messages"]
            ):
                # 节点状态更新
                if mode == "updates":
                    # payload 形如 {节点名: 状态增量}
                    for delta in payload.values():
                        # 检索节点会写入 chunks; 放宽检索时以后一次为准
                        if isinstance(delta, dict) and "chunks" in delta:
                            # 提取去重后的来源文章
                            sources = qa.extract_sources(delta["chunks"] or [])
                    # 状态更新本身不下发给前端
                    continue
                # 大模型 token: 首个 token 之前先把来源发出去, 保证前端渲染顺序
                if not sources_sent:
                    # 下发来源事件
                    yield _sse("sources", {"sources": sources})
                    # 标记已下发
                    sources_sent = True
                # payload 形如 (消息块, 元数据)
                chunk = payload[0]
                # 取出文本内容(纯文本模型下 content 为 str)
                text = getattr(chunk, "content", "")
                # 仅下发非空文本
                if isinstance(text, str) and text:
                    # 每段增量作为一条 delta 事件
                    yield _sse("delta", {"text": text})
            # 模型一个 token 都没产出时, 也要把来源补发出去
            if not sources_sent:
                # 下发来源事件
                yield _sse("sources", {"sources": sources})
            # 下发结束事件
            yield _sse("done", {})
        except Exception:
            # 记录完整堆栈便于排查
            logger.exception("问答流式生成失败")
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


# 3. 全量重建向量索引(管理员): 转发给 backend-rag 执行
@router.post("/reindex", response_model=Result, summary="全量重建向量索引")
async def reindex(_: int = Depends(require_admin)):
    # 转发到检索服务(耗时较长, 客户端已配置独立超时)
    try:
        # 调用重建接口
        data = await rag_client.reindex()
    except ServiceError as exc:
        # 检索服务不可用
        raise HTTPException(status_code=503, detail="检索服务不可用") from exc
    # 返回重建统计
    return ok(ReindexOut(**data), message="重建完成")
