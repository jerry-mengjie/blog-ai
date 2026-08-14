"""文章问答图: LangGraph StateGraph + 条件路由 + LCEL 生成节点。

图结构:
                        ┌─(检索为空且可放宽)→ widen_retrieve ─┐
START → retrieve ───────┤                                     ├→ generate → END
                        └─(检索有结果)────────────────────────┘

节点职责:
1. retrieve      : 按请求范围(本文 / 本系列)调 backend-rag 检索相关分块
2. widen_retrieve: 本文范围内检索不到时自动放宽到同系列再试一次(自纠正检索)
3. generate      : LCEL 链(提示词模板 | 对话模型 | 输出解析)流式生成回答

为什么用图而不是一条 LCEL 链:
「检索不到就放宽范围重试」是一个带条件分支的决策, 用图表达比在链里塞 if 更清晰,
后续要加「改写问题重检索」「回答质量自评」等节点也只是加节点与边, 不动既有代码。

流式输出:
generate 节点内部用 `chain.astream()` 消费模型输出, LangGraph 的 `messages`
流模式会把这些 token 透传给调用方(见 api/chat.py), 因此 SSE 首字延迟等于模型首字延迟。

降级策略:
backend-rag 不可用时检索节点返回空片段而不是抛错, 模型会据实回答「文章中没有提到」,
问答入口不至于整体不可用。
"""

# 导入日志
import logging
# 导入类型注解工具(LangGraph 经典 TypedDict 状态)
from typing import TypedDict

# 导入 LangChain 输出解析器(把模型消息流转为纯文本流)
from langchain_core.output_parsers import StrOutputParser
# 导入可运行链类型注解
from langchain_core.runnables import Runnable
# 导入 LangGraph 状态图与起止节点常量
from langgraph.graph import END, START, StateGraph

# 导入 backend-rag 客户端
from app.clients import rag as rag_client
# 导入服务调用异常
from app.clients.http import ServiceError
# 导入对话模型
from app.llm.models import get_chat_model
# 导入提示词
from app.llm.prompts import EMPTY_CONTEXT, build_qa_prompt

# 模块日志器
logger = logging.getLogger(__name__)

# 检索范围: 仅当前文章
SCOPE_ARTICLE = "article"
# 检索范围: 当前系列(同分类)
SCOPE_SERIES = "series"


# 图状态: 节点间通过该字典传递数据
class QAState(TypedDict, total=False):
    # 读者的问题
    question: str
    # 当前文章 ID
    article_id: int
    # 当前文章所属分类 ID(0 表示无分类)
    category_id: int
    # 当前文章标题(写进提示词让模型知道阅读场景)
    article_title: str
    # 请求的检索范围: article / series
    scope: str
    # 检索命中的分块列表
    chunks: list[dict]
    # 是否已放宽过检索范围(避免重复放宽)
    widened: bool
    # 最终回答文本
    answer: str


# 模块级 LCEL 链单例(无状态, 可跨请求复用)
_chain: Runnable | None = None


# 获取全局唯一的问答链: 提示词模板 | 对话模型 | 字符串解析器
def _get_chain() -> Runnable:
    # 声明使用模块级变量
    global _chain
    # 首次调用时组装链
    if _chain is None:
        # LCEL 管道组合: 模板渲染 → 模型生成 → 文本解析
        _chain = build_qa_prompt() | get_chat_model() | StrOutputParser()
    # 返回单例
    return _chain


# 内部工具: 调检索服务, 服务不可用时降级为空片段
async def _safe_retrieve(**kwargs) -> list[dict]:
    # 检索失败不应让整个问答不可用
    try:
        # 调 backend-rag
        return await rag_client.retrieve(**kwargs)
    except ServiceError:
        # 记录后按「无可用资料」处理
        logger.warning("检索服务不可用, 本次问答无参考片段", exc_info=True)
        # 空片段
        return []


# 节点 1: 按请求范围检索相关分块
async def _retrieve(state: QAState) -> dict:
    # series 范围且文章有分类: 检索同分类(系列)下所有文章
    if state.get("scope") == SCOPE_SERIES and state.get("category_id"):
        # 按分类过滤检索
        chunks = await _safe_retrieve(
            query=state["question"], category_id=state["category_id"]
        )
    else:
        # 默认范围: 仅检索当前文章
        chunks = await _safe_retrieve(
            query=state["question"], article_id=state["article_id"]
        )
    # 写回图状态
    return {"chunks": chunks}


# 条件路由: 本文范围内没检索到内容且文章有分类时, 放宽到同系列再试一次
def _route_after_retrieve(state: QAState) -> str:
    # 已有命中直接生成
    if state.get("chunks"):
        # 进入生成
        return "generate"
    # 已放宽过则不再重试, 避免来回打转
    if state.get("widened"):
        # 进入生成(模型会明确告知文章中没有提到)
        return "generate"
    # 无分类时放宽也是同样的空结果, 直接生成
    if not state.get("category_id"):
        # 进入生成
        return "generate"
    # 满足放宽条件
    return "widen_retrieve"


# 节点 2: 放宽检索范围到同系列, 给读者一次「相关文章里有没有」的机会
async def _widen_retrieve(state: QAState) -> dict:
    # 按分类过滤重新检索
    chunks = await _safe_retrieve(
        query=state["question"], category_id=state["category_id"]
    )
    # 标记已放宽, 防止再次进入本节点
    return {"chunks": chunks, "widened": True}


# 内部工具: 将检索到的分块拼装为提示词中的上下文文本
def _build_context(chunks: list[dict]) -> str:
    # 无命中时返回明确标记, 让模型知道无可用资料
    if not chunks:
        # 空上下文占位
        return EMPTY_CONTEXT
    # 按 "来源文章 + 原文顺序" 排序, 保持上下文连贯
    ordered = sorted(chunks, key=lambda c: (c["article_id"], c["chunk_index"]))
    # 每个片段标注来源标题, 便于模型引用
    return "\n\n".join(
        f"【片段 {i + 1} · 来自《{c['title']}》】\n{c['text']}"
        for i, c in enumerate(ordered)
    )


# 节点 3: 流式生成回答
async def _generate(state: QAState) -> dict:
    # 收集完整回答(节点返回值需要是最终状态)
    parts: list[str] = []
    # 流式执行链: token 通过 LangGraph messages 流模式透传给调用方
    async for token in _get_chain().astream(
        {
            "title": state.get("article_title") or "",          # 当前文章标题
            "context": _build_context(state.get("chunks") or []),  # 检索上下文
            "question": state["question"],                      # 读者问题
        }
    ):
        # 累积非空片段
        if token:
            # 记录以便写回状态
            parts.append(token)
    # 写回完整回答
    return {"answer": "".join(parts)}


# 构建并编译问答图(进程内仅执行一次)
def _build_graph():
    # 以 QAState 为状态创建图
    graph = StateGraph(QAState)
    # 注册三个节点
    graph.add_node("retrieve", _retrieve)
    graph.add_node("widen_retrieve", _widen_retrieve)
    graph.add_node("generate", _generate)
    # 入口: 先检索
    graph.add_edge(START, "retrieve")
    # 条件路由: 检索为空且可放宽时先扩大范围
    graph.add_conditional_edges(
        "retrieve", _route_after_retrieve, ["widen_retrieve", "generate"]
    )
    # 放宽检索后进入生成
    graph.add_edge("widen_retrieve", "generate")
    # 生成后结束
    graph.add_edge("generate", END)
    # 编译为可执行图
    return graph.compile()


# 模块级编译单例: 图结构固定, 请求间复用
graph = _build_graph()


# 从命中分块中提取去重后的来源文章列表(供前端展示引用)
def extract_sources(chunks: list[dict]) -> list[dict]:
    # 以 (id, title) 去重后按文章 ID 排序
    unique = sorted({(c["article_id"], c["title"]) for c in chunks})
    # 转为字典列表
    return [{"article_id": aid, "title": title} for aid, title in unique]
