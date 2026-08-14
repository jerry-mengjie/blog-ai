"""RAG 服务的请求/响应模型: 即 backend-blog / backend-agent 调用本服务的契约。"""

# 导入 Pydantic 基类与字段
from pydantic import BaseModel, Field


# ---------- 索引写入 ----------
# 待索引的文章文档(由 backend-blog 在发布/编辑后推送)
class ArticleDocumentReq(BaseModel):
    # 文章 ID, 作为向量库中的分区标识
    article_id: int = Field(gt=0)
    # 分类 ID, 支撑「按系列检索」; 无分类传 0
    category_id: int = Field(default=0, ge=0)
    # 文章标题, 参与向量化并用于标注检索来源
    title: str = Field(default="", max_length=1024)
    # 文章正文, 空字符串等价于「清空该文章索引」
    content: str = Field(default="")


# 单篇索引结果
class IndexResultOut(BaseModel):
    # 文章 ID
    article_id: int
    # 实际写入的分块数(0 表示只做了清理)
    chunks: int


# 全量重建结果
class ReindexOut(BaseModel):
    # 处理的文章数
    articles: int
    # 写入的分块总数
    chunks: int
    # 失败的文章 ID(便于人工重试)
    failed: list[int] = []


# ---------- 检索 ----------
# 检索请求
class RetrieveReq(BaseModel):
    # 检索问题, 限长防止超长文本浪费向量化配额
    query: str = Field(min_length=1, max_length=500)
    # 限定文章(article 范围); 为空则不按文章过滤
    article_id: int | None = Field(default=None, ge=0)
    # 限定分类(series 范围); 为空则不按分类过滤
    category_id: int | None = Field(default=None, ge=0)
    # 返回的分块数; 为空取服务默认值
    top_k: int | None = Field(default=None, ge=1, le=50)
    # 相似度下限; 为空取服务默认值
    min_score: float | None = Field(default=None, ge=-1.0, le=1.0)


# 单个命中分块
class ChunkOut(BaseModel):
    # 来源文章 ID
    article_id: int
    # 来源文章标题
    title: str = ""
    # 块序号, 上层按此还原原文顺序
    chunk_index: int = 0
    # 分块原文
    text: str = ""
    # 余弦相似度得分
    score: float = 0.0


# 检索响应
class RetrieveOut(BaseModel):
    # 命中的分块列表(已按相似度倒序)
    chunks: list[ChunkOut]


# ---------- 画像召回 ----------
# 单条用户行为偏好
class BehaviorItem(BaseModel):
    # 行为涉及的文章 ID
    article_id: int = Field(gt=0)
    # 该文章的偏好权重(由 backend-agent 依据浏览/收藏行为计算)
    weight: float = Field(default=1.0, ge=0.0)


# 画像召回请求
class SimilarReq(BaseModel):
    # 用户行为偏好列表, 空列表直接返回空候选
    behaviors: list[BehaviorItem] = []
    # 需要排除的文章 ID(已读/已收藏)
    exclude_ids: list[int] = []
    # 期望召回的文章数
    limit: int = Field(default=12, ge=1, le=100)


# 单条召回候选
class SimilarItemOut(BaseModel):
    # 召回的文章 ID
    article_id: int
    # 与画像向量的相似度
    score: float = 0.0


# 画像召回响应
class SimilarOut(BaseModel):
    # 召回候选列表(已按得分倒序)
    items: list[SimilarItemOut]
