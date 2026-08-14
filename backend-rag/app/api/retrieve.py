"""检索路由: 问答检索 / 画像召回 (2 个接口)。

调用方均为 backend-agent:
- /rag/retrieve: 问答图的检索节点, 取回与问题相关的文章分块
- /rag/similar : 推荐图的画像召回节点, 取回与用户偏好相似的文章
"""

# 导入路由与依赖工具
from fastapi import APIRouter, Depends

# 导入统一响应
from app.core.response import Result, ok
# 导入服务间令牌与可用性校验
from app.api.deps import require_rag_enabled, verify_internal_token
# 导入画像召回能力
from app.rag.profile import recall_similar_articles
# 导入检索能力
from app.rag.retriever import retrieve as retrieve_chunks
# 导入请求/响应模型
from app.schemas.rag import RetrieveOut, RetrieveReq, SimilarOut, SimilarReq

# 创建检索路由, 前缀 /rag, 全局挂服务间令牌与可用性校验
router = APIRouter(
    prefix="/rag",
    tags=["检索"],
    dependencies=[Depends(verify_internal_token), Depends(require_rag_enabled)],
)


# 1. 问答检索: 按范围过滤 + 向量近邻, 返回相关分块
@router.post("/retrieve", response_model=Result, summary="检索相关文章分块")
async def retrieve(body: RetrieveReq):
    # 执行检索(内部带 Redis 结果缓存)
    chunks = await retrieve_chunks(
        query=body.query,
        article_id=body.article_id,
        category_id=body.category_id,
        top_k=body.top_k,
        min_score=body.min_score,
    )
    # 包装统一响应
    return ok(RetrieveOut(chunks=chunks))


# 2. 画像召回: 行为文章加权合成画像向量后召回相似文章
@router.post("/similar", response_model=Result, summary="按用户画像召回相似文章")
async def similar(body: SimilarReq):
    # 执行召回(行为为空时内部直接返回空列表)
    items = await recall_similar_articles(
        behaviors=[b.model_dump() for b in body.behaviors],
        exclude_ids=body.exclude_ids,
        limit=body.limit,
    )
    # 包装统一响应
    return ok(SimilarOut(items=items))
