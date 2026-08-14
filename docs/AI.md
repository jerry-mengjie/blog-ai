# AI 问答功能文档（backend-agent 编排 + backend-rag 检索）

> 本文档由 AI 生成。覆盖功能说明、技术选型、图结构、模块拆分、接口、部署与性能优化。
> 服务边界与内部接口契约见 [ARCHITECTURE.md](ARCHITECTURE.md)。

---

## 1. 功能概览

每篇文章底部提供「**关于这篇文章，问 AI**」问答区：

- **预设问题**：这篇文章的核心内容是什么？/ 能举个例子说明吗？/ 有没有更简单的方法？/ 和本系列其他文章有什么区别？
- **自由提问**：读者可输入任意问题，回答**流式**输出（打字机效果）。
- **检索范围**（只检索这两种范围，不做全库检索）：
  - `当前文章`：只检索正在阅读的这篇文章；
  - `当前系列`：检索该文章所属**分类**下的全部文章（本项目以分类作为系列）。
- **自纠正检索**：本文范围内检索不到内容时，自动放宽到同系列再试一次。
- **来源引用**：回答下方展示引用的文章标题，点击可跳转。

## 2. 技术选型（各框架最经典方案）

问答链路横跨两个服务，各自只用一套框架：

| 环节 | 服务 | 方案 | 说明 |
| --- | --- | --- | --- |
| 流程编排 | agent | **LangGraph `StateGraph`**（TypedDict 状态 + 条件路由） | 「检索不到就放宽范围」是带分支的决策，用图表达比在链里塞 `if` 清晰 |
| 生成 | agent | **LangChain LCEL**：`prompt \| ChatOpenAI \| StrOutputParser` | 声明式组合，`astream` 原生流式 |
| 对话模型 | agent | `langchain-openai` 的 **ChatOpenAI**（默认百炼 `qwen-plus`） | OpenAI 兼容协议 |
| 索引/检索 | rag | **LlamaIndex**：`IngestionPipeline` 写入、`VectorStoreIndex.from_vector_store` + `VectorIndexRetriever` 读取 | LlamaIndex 的经典读写两条主路径 |
| 分块 | rag | `SentenceSplitter`（500 字/块，重叠 80 字，中文句读分隔符） | LlamaIndex 默认分块器 |
| 向量化 | rag | `OpenAILikeEmbedding`（默认 `text-embedding-v4`，1024 维，批量 10） | OpenAI 兼容端点 + 自定义模型名 |
| 向量库 | rag | **Milvus 2.6** + `MilvusVectorStore` | HNSW + 标量倒排索引 + range search；集合 DDL 由 pymilvus 启动期精确控制 |
| 推送 | agent | **SSE**（FastAPI `StreamingResponse`） | 单向流式输出的标准方案 |
| 索引同步 | blog | FastAPI `BackgroundTasks` → `POST /rag/documents` | 发文/编辑/删除后异步推送，不阻塞接口 |

## 3. 架构与数据流

```
┌──────────────────────── 写路径(索引) ────────────────────────┐
发布/编辑/删除文章 ──▶ backend-blog: MySQL 落库(事务提交)
                        │ BackgroundTasks(响应已返回)
                        ▼
                     POST /rag/documents  (status != 1 时转为 DELETE)
                        │
                     backend-rag: IngestionPipeline
                        │ SentenceSplitter 分块 → ChunkStamper 打确定性 ID/序号
                        │ → OpenAILikeEmbedding 批量向量化 → upsert
                        ▼
                     Milvus 集合 blog_rag_nodes
                     列: id(主键)/embedding/text/article_id/category_id/title/chunk_index

┌──────────────────────── 读路径(问答) ────────────────────────┐
读者提问 ──▶ backend-agent: POST /api/ai/ask (SSE)
              │ 1. 单 IP 限流(Redis 固定窗口)
              │ 2. GET /internal/article/{id}/meta 校验文章可用性(不取正文)
              ▼
        LangGraph 问答图
              │  START → retrieve ──(空且可放宽)→ widen_retrieve ─┐
              │                   └──(有命中)───────────────────┴→ generate → END
              │      retrieve/widen: POST /rag/retrieve
              │        backend-rag: 问题向量化 → 标量过滤 + HNSW TopK → 阈值过滤
              │      generate: LCEL 链 astream(拼上下文并标注来源)
              ▼
        SSE: sources → delta × N → done
```

## 4. 模块拆分

### backend-agent（编排）

| 文件 | 职责 |
| --- | --- |
| `app/graphs/qa.py` | 问答图：`QAState`、`retrieve` / `widen_retrieve` / `generate` 三节点、条件路由、编译单例、`extract_sources` |
| `app/llm/models.py` | `ChatOpenAI` 单例（流式开启）与 `ai_enabled` 功能开关 |
| `app/llm/prompts.py` | 系统提示词、用户模板、预设问题、空上下文占位、`build_qa_prompt()` |
| `app/api/chat.py` | 3 个路由：`/config`、`/ask`（SSE）、`/reindex`（管理员转发） |
| `app/clients/rag.py` | 调 `backend-rag`：`retrieve` / `recall_similar` / `reindex`（重建单独放宽超时） |
| `app/clients/blog.py` | 调 `backend-blog` 内部接口取文章元信息与用户状态 |
| `app/core/ratelimit.py` | Redis 固定窗口限流，无 Redis 时退化为进程内滑动窗口 |

### backend-rag（检索）

| 文件 | 职责 |
| --- | --- |
| `app/rag/models.py` | LlamaIndex 全局 `Settings`：嵌入模型 + 分块器；显式 `Settings.llm = None`（本服务不生成） |
| `app/rag/vector_store.py` | `MilvusVectorStore` 单例 + pymilvus 启动期 DDL（Schema / HNSW / 标量倒排索引 / 维度校验 / load） |
| `app/rag/ingest.py` | `IngestionPipeline` + `ChunkStamper`（确定性节点 ID 与 `chunk_index`）、单篇 upsert、按 `article_id` 删除 |
| `app/rag/retriever.py` | `VectorStoreIndex.from_vector_store` → `as_retriever().aretrieve()`，标量过滤 + `radius` 下推 + 阈值兜底 + Redis 缓存 |
| `app/api/index.py` | 索引管理路由：`/rag/documents`（POST/DELETE）、`/rag/reindex` |
| `app/api/retrieve.py` | 检索路由：`/rag/retrieve`、`/rag/similar` |
| `app/clients/blog.py` | 全量重建时回源拉取文章 ID 与正文 |

## 5. 接口

### 面向前端（backend-agent，8001）

| 方法 | 路径 | 说明 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/api/ai/config` | AI 是否启用 + 预设问题列表 | 否 |
| POST | `/api/ai/ask` | 文章问答，SSE 流式返回 | 否（单 IP 限流） |
| POST | `/api/ai/reindex` | 全量重建向量索引（转发给 rag） | 管理员 |

`/api/ai/ask` 请求体：

```json
{ "article_id": 1, "question": "能举个例子吗?", "scope": "article" }
```

`scope`：`article`（仅当前文章，默认）或 `series`（当前系列 = 同分类）。

SSE 事件序列（与拆分前完全一致，前端无需改动）：

```
event: sources   data: {"sources":[{"article_id":1,"title":"..."}]}
event: delta     data: {"text":"回答增量"}     ← 多条
event: done      data: {}
event: error     data: {"message":"..."}      ← 仅出错时
```

### 服务间（backend-rag，8002，需 `X-Internal-Token`）

| 方法 | 路径 | 请求要点 | 响应要点 |
| --- | --- | --- | --- |
| POST | `/rag/documents` | `article_id / category_id / title / content` | `article_id / chunks`（写入块数） |
| DELETE | `/rag/documents/{article_id}` | — | `article_id / chunks=0` |
| POST | `/rag/reindex` | — | `articles / chunks / failed[]` |
| POST | `/rag/retrieve` | `query`、`article_id` 或 `category_id`、`top_k`、`min_score` | `chunks[]`（含 `title` / `chunk_index` / `text` / `score`） |
| POST | `/rag/similar` | `behaviors[{article_id, weight}]`、`exclude_ids`、`limit` | `items[{article_id, score}]` |

## 6. 前端（`frontend-app`）

- `src/components/ai-ask.vue`：文章底部问答组件——范围切换、预设问题、对话气泡、打字机光标、来源跳转；后端未启用时整块隐藏。
- `src/api/ai.js`：配置查询走 axios；`askAi` 用 `fetch` + `ReadableStream` 解析 SSE（axios 不支持流式读取），返回中断函数，离开页面自动取消请求。
- `vite.config.js`：`/api/ai` 与 `/api/rec` 代理到 8001，其余 `/api` 到 8000（更具体的前缀必须写在 `/api` 之前）。
- `App.vue`：`router-view` 增加 `:key="route.fullPath"`，保证从来源引用跳转到其他文章详情时组件重新加载。

## 7. 部署与初始化

### 7.1 启动 Milvus（standalone）

```bash
cd deploy/milvus && docker compose up -d
```

- gRPC 端口 `19530`（应用连接）、健康检查端口 `9091`（`curl http://127.0.0.1:9091/healthz`）。
- `backend-rag` 启动时会自动建集合、补建标量倒排索引并 `load`，无需手工 DDL。

### 7.2 配置 `.env`

```bash
# backend-rag/.env  向量模型(唯一持有方)
AI_API_KEY=sk-xxx          # 阿里云百炼控制台获取; 留空则 rag 接口返回 503, 上游自动降级
AI_EMBED_MODEL=text-embedding-v4
AI_EMBED_DIM=1024

# backend-agent/.env  对话模型
AI_API_KEY=sk-xxx          # 留空则 /config 返回 enabled=false, 前端隐藏问答入口
AI_CHAT_MODEL=qwen-plus
```

`INTERNAL_TOKEN` 三服务必须一致，`SECRET_KEY` 需与 `backend-blog` 一致，其余配置均有默认值，见各服务 `.env` 注释。

### 7.3 索引存量文章

新发布/编辑的文章由 `backend-blog` 自动推送索引；**存量文章**需管理员触发一次全量重建：

```bash
curl -X POST http://127.0.0.1:8001/api/ai/reindex -H "Authorization: Bearer <管理员token>"
```

更换向量模型或维度（`AI_EMBED_MODEL` / `AI_EMBED_DIM`）后，重启 `backend-rag` 会自动按新维度重建空集合，同样需执行一次全量重建。

## 8. 性能优化

### Milvus

- **标量字段独立成列**：`article_id` / `category_id` / `title` / `chunk_index` 提升为真实列，过滤表达式才能命中索引（留在动态字段里只能逐行解析 JSON）。
- **INVERTED 倒排索引**：「只看本文」「只看本系列」「排除已读」三类过滤全部走索引。
- **HNSW 调优**：`M=16, efConstruction=128`，检索 `ef=64`，平衡召回率与速度。
- **range search**：`radius` 取相似度下限，低分块在引擎侧就被丢掉，不占网络也不进提示词。
- **`output_fields` 白名单**：排除 LlamaIndex 的 `_node_content`（正文的 JSON 副本），检索回传量约减半。
- **`consistency_level=Bounded`**：检索不等待数据同步点，吞吐远高于 `Strong`，代价是新索引文章秒级可见延迟。
- **幂等 upsert**：节点 ID 由 `article:{id}:chunk:{i}` 生成 UUID5，重复索引即覆盖，无需先查再写。
- **建集合即建索引并 load**：启动期一次性完成，首次检索无冷启动。

### MySQL（backend-blog 侧）

- 问答只取 `id/title/category_id/status` 四列，**不加载 `content`**；只有全量重建才走 `/document` 取正文。
- 全量重建的 ID 清单按 `status=1` 过滤（命中 `idx_status_create` 前缀），且只取 ID 列。
- 索引推送在 `BackgroundTasks` 中执行，不占用请求会话与事务。

### 应用层

- LangGraph 图 `compile()`、LCEL 链、`ChatOpenAI`、LlamaIndex `Settings`、`MilvusVectorStore`、`httpx.AsyncClient` 全部**模块级单例**，复用连接池。
- 全链路原生异步：`astream` / `aretrieve` / `arun`（Ingestion）/ Milvus 异步客户端，不阻塞事件循环。
- **检索结果 Redis 缓存**（默认 300s，不做进程内 L1：问题是长尾分布，L1 命中率低还占内存）：同一问题 + 同一范围命中即省下一次向量化 HTTP 与一次 Milvus 检索；索引写入（含删除、全量重建）后按前缀 `SCAN + UNLINK` 整批失效，避免引用已删除或已改写的内容。
- 向量化批量 10 条（百炼兼容接口上限），全量重建按 `RAG_REINDEX_CONCURRENCY` 并发但不无限放大。
- SSE 首字延迟等于模型首字延迟：LangGraph `messages` 流模式透传 token；`X-Accel-Buffering: no` 关闭代理缓冲。
- 单 IP Redis 固定窗口限流（默认 10 次/分钟），`INCR` + `EXPIRE NX` 用 pipeline 合并为一个 RTT；多副本共享计数。

## 9. 降级与容错

| 场景 | 行为 |
| --- | --- |
| 未配置 agent 的 `AI_API_KEY` | `/config` 返回 `enabled=false`，前端隐藏问答区；`/ask` 返回 503 |
| 未配置 rag 的 `AI_API_KEY` | rag 接口返回 503，问答按「无参考片段」回答 |
| `backend-rag` 不可达 | 检索节点返回空片段（仅记日志），模型据实告知文章未提及 |
| `backend-blog` 不可达 | `/ask` 返回 503（无法校验文章可用性） |
| Milvus 未启动 | 索引推送失败仅记日志，发文/编辑/删除不受影响；检索降级同「rag 不可达」 |
| Redis 未启动 | 检索缓存与限流 fail-open，功能正常仅性能下降 |
| 检索无命中 | 先自动放宽到同系列重试一次；仍无命中则提示词标注「未检索到相关片段」 |
| 生成中途出错 | SSE 下发 `error` 事件，前端提示重试 |
