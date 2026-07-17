# AI 问答功能文档 (RAG)

> 本文档由 AI 生成。覆盖功能说明、架构设计、数据流、配置、接口与性能优化。

---

## 1. 功能概览

每篇文章底部提供「**关于这篇文章，问 AI**」问答区：

- **预设问题**：这篇文章的核心内容是什么？/ 能举个例子说明吗？/ 有没有更简单的方法？/ 和本系列其他文章有什么区别？
- **自由提问**：读者可输入任意问题（如「这一段什么意思？」），回答**流式**输出（打字机效果）。
- **检索范围**（RAG 只检索这两种范围，不做全库检索）：
  - `当前文章`：只检索正在阅读的这篇文章；
  - `当前系列`：检索该文章所属**分类**下的全部文章（本项目以分类作为系列）。
- **来源引用**：回答下方展示引用的文章标题，点击可跳转。

## 2. 技术选型（各框架最经典方案）

| 环节 | 方案 | 说明 |
| --- | --- | --- |
| 向量库 | **Milvus 2.6**（Docker Compose standalone 部署） | HNSW 图索引 + 标量倒排索引过滤 + range search |
| 向量化 | OpenAI 兼容 Embeddings API（默认阿里云百炼 `text-embedding-v4`，1024 维） | 一套 Key 同时覆盖对话与向量 |
| 对话 | OpenAI 兼容 Chat Completions（默认 `qwen-plus`），`stream=True` | 经典流式对话 |
| 推送 | **SSE**（Server-Sent Events） | 单向流式输出的标准方案，FastAPI `StreamingResponse` 原生支持 |
| 分块 | 按段落聚合 + 滑动窗口重叠（500 字/块，重叠 80 字） | 经典递归分块思路的轻量实现 |
| 索引同步 | FastAPI `BackgroundTasks` | 发文/编辑/删除后异步同步，不阻塞接口响应 |

## 3. 架构与数据流

```
                    ┌──────────────── 写路径(索引) ────────────────┐
发布/编辑/删除文章 ──▶ MySQL 落库 ──▶ BackgroundTasks(响应后异步)
                                      │ 分块(chunker) → 向量化(embeddings)
                                      ▼
                                 Milvus 集合 blog_article_chunks
                                 字段: id(主键)/vector/article_id/category_id/title/chunk_index/text

                    ┌──────────────── 读路径(问答) ────────────────┐
读者提问 ──▶ POST /api/ai/ask (SSE)
             │ 1. 限流(单IP每分钟) + 文章校验(只查必要列)
             │ 2. 问题向量化
             │ 3. Milvus 过滤检索: scope=article 按 article_id / scope=series 按 category_id
             │ 4. TopK 片段拼提示词(标注来源标题, 约束"只依据片段回答")
             ▼
        LLM 流式生成 ──▶ SSE: sources → delta × N → done
```

## 4. 后端模块（`backend-blog/app/ai/`）

| 文件 | 职责 |
| --- | --- |
| `llm.py` | OpenAI 兼容客户端单例；`embed_texts` 批量向量化（自动分批）、`chat_stream` 流式对话、`ai_enabled` 功能开关 |
| `chunker.py` | `split_text` 段落聚合 + 重叠滑窗分块 |
| `vector_store.py` | Milvus 异步客户端单例（`AsyncMilvusClient`, gRPC）；集合管理、幂等 upsert（UUID5 确定性主键）、表达式过滤检索、删除 |
| `indexer.py` | 后台任务：单篇重建 / 删除索引 / 全量重建（失败仅记日志，不影响主业务） |
| `rag.py` | `retrieve` 范围检索、`answer_stream` 提示词构建与流式生成、预设问题 |

路由在 `app/api/ai.py`，请求模型在 `app/schemas/ai.py`。

## 5. 接口

| 方法 | 路径 | 说明 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/api/ai/config` | AI 是否启用 + 预设问题列表 | 否 |
| POST | `/api/ai/ask` | 文章问答，SSE 流式返回 | 否（单 IP 限流） |
| POST | `/api/ai/reindex` | 全量重建向量索引 | 管理员 |

### `/api/ai/ask` 请求体

```json
{ "article_id": 1, "question": "能举个例子吗?", "scope": "article" }
```

`scope`：`article`（仅当前文章，默认）或 `series`（当前系列 = 同分类）。

### SSE 事件序列

```
event: sources   data: {"sources":[{"article_id":1,"title":"..."}]}
event: delta     data: {"text":"回答增量"}     ← 多条
event: done      data: {}
event: error     data: {"message":"..."}      ← 仅出错时
```

## 6. 前端（`frontend-app`）

- `src/components/ai-ask.vue`：文章底部问答组件——范围切换、预设问题、对话气泡、打字机光标、来源跳转；后端未启用时整块隐藏。
- `src/api/ai.js`：配置查询走 axios；`askAi` 用 `fetch` + `ReadableStream` 解析 SSE（axios 不支持流式读取），返回中断函数，离开页面自动取消请求。
- `App.vue`：`router-view` 增加 `:key="route.fullPath"`，保证从来源引用跳转到其他文章详情时组件重新加载。

## 7. 部署与初始化

### 7.1 启动 Milvus（standalone）

使用官方 Docker Compose 编排（etcd + MinIO + Milvus 三个容器），仓库中已保留一份 `deploy/milvus/docker-compose.yml`：

```bash
wget https://gitee.com/milvus-io/milvus/raw/v2.6.4/deployments/docker/standalone/docker-compose.yml -O docker-compose.yml
docker compose up -d
```

- gRPC 端口 `19530`（应用连接）、健康检查端口 `9091`（`curl http://127.0.0.1:9091/healthz`）
- 数据默认持久化在 compose 文件所在目录的 `volumes/` 下（可用环境变量 `DOCKER_VOLUME_DIRECTORY` 指定）

### 7.2 配置 `.env`

```bash
AI_API_KEY=sk-xxx        # 阿里云百炼控制台获取; 留空则 AI 功能自动关闭, 其余功能不受影响
```

其余 AI/Milvus 配置均有默认值，见 `backend-blog/.env` 注释。

### 7.3 索引存量文章

新发布/编辑的文章会自动索引；**存量文章**需管理员登录后触发一次全量重建：

```bash
curl -X POST http://127.0.0.1:8000/api/ai/reindex -H "Authorization: Bearer <管理员token>"
```

更换向量模型或维度（`AI_EMBED_MODEL` / `AI_EMBED_DIM`）后，重启后端会自动按新维度重建空集合，同样需执行一次全量重建。

## 8. 性能优化

### Milvus

- **全异步客户端**（`AsyncMilvusClient`，gRPC 19530）：读写不阻塞 FastAPI 事件循环，客户端模块级单例复用通道。
- **HNSW 调优**：`M=16, efConstruction=128`，检索时 `ef=64`，平衡召回率与速度。
- **标量倒排索引（INVERTED）**：`article_id` / `category_id` 建索引，标量过滤走索引而非全表暴力过滤。
- **range search**：`radius=0.3` 让引擎侧直接过滤低相似度结果 + TopK `6`，降低提示词 token 消耗与噪音。
- **幂等 upsert**：UUID5 确定性主键，重复索引即覆盖（Milvus 内部删旧插新），无需先查再写。
- **显式 Schema**：关闭动态字段（`enable_dynamic_field=False`），字段结构固定、存储与检索开销更小。
- **建集合即建索引并加载**：`create_collection` 传入 `index_params` 一步完成建索引 + load，集合常驻内存可查。

### MySQL

- 问答接口只查 `id/title/category_id/status` 四列，**不加载 `content` 大字段**（走主键，回表极小）。
- 索引同步在 `BackgroundTasks` 中使用**独立会话**，不占用请求会话与事务。
- 全量重建按 `status=1` 过滤（命中 `idx_status_top_time` 复合索引前缀），且只取 ID 列表。

### 应用层

- 索引构建/删除全部**响应后异步执行**，发文接口耗时不受 embedding 网络请求影响。
- OpenAI / Milvus 客户端**模块级单例**，复用连接池与 gRPC 通道。
- 单 IP 滑动窗口限流（默认 10 次/分钟），防止刷接口消耗 token。
- embedding 按接口上限（10 条/批）自动分批，全量重建串行执行避免限流。

## 9. 降级与容错

| 场景 | 行为 |
| --- | --- |
| 未配置 `AI_API_KEY` | `/config` 返回 `enabled=false`，前端隐藏问答区；`/ask` 返回 503 |
| Milvus 未启动 | 索引后台任务失败仅记日志，发文/编辑/删除不受影响 |
| 检索无命中 | 提示词标注「未检索到相关片段」，模型明确告知读者文章未提及 |
| 生成中途出错 | SSE 下发 `error` 事件，前端提示重试 |
