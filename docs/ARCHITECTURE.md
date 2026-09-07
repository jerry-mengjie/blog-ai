# 微服务架构文档（backend-blog / backend-agent / backend-rag）

> 本文档由 AI 生成。覆盖服务拆分依据、职责边界、调用关系、内部接口契约、启动顺序、降级矩阵与性能优化要点。

---

## 1. 为什么拆成三个服务

拆分前所有能力都在 `backend-blog` 一个进程里：业务 CRUD、LangChain RAG、LangGraph 推荐共享同一份依赖与同一个事件循环。问题很具体：

1. **依赖耦合**：一次 `langchain` 升级会牵动整个博客后端，业务接口跟着一起回归测试。
2. **伸缩比例不同**：文章列表是高 QPS 短请求，AI 问答是低 QPS 长连接（SSE 一路占着 worker），两者放一起没法分别扩容。
3. **故障域重叠**：Milvus 抖动、大模型超时不应该影响登录和发文。
4. **框架取向冲突**：编排（LangGraph）与检索（LlamaIndex）各自都有一套「最经典写法」，混在一个包里必然互相妥协。

拆分后每个服务只用一套框架的经典方案，各自独立部署与伸缩。

| 服务 | 端口 | 框架 | 职责 | 直连的存储 |
| --- | --- | --- | --- | --- |
| `backend-blog` | 8000 | FastAPI + SQLAlchemy 2.0(async) | 业务：用户 / 文章 / 分类 / 标签 / 评论 / 收藏 / 浏览统计 | MySQL、Redis、RocketMQ |
| `backend-agent` | 8001 | FastAPI + LangGraph + LangChain | AI 编排：问答图（RAG + 自纠正检索）、推荐图（多路召回） | Redis（缓存 + 限流） |
| `backend-rag` | 8002 | FastAPI + LlamaIndex | 检索：分块、向量化、索引、向量检索、画像召回 | Milvus、Redis（检索缓存） |

**存储归属是硬边界**：MySQL 只属于 `backend-blog`，Milvus 只属于 `backend-rag`。任何服务都不持有别人的表模型或连接串。

---

## 2. 调用关系

```
                     ┌──────────────────┐        ┌──────────────────┐
        移动端用户 ──▶│  frontend-app    │        │ frontend-admin   │◀── 管理员
                     │  (Vue3 + Vant)   │        │ (Vue3 + Element) │
                     └────────┬─────────┘        └────────┬─────────┘
                              │  /api/ai/*, /api/rec/*  →  8001        (Vite 代理 / 网关按前缀分发)
                              │  其余 /api/*            →  8000
                ┌─────────────┴───────────────┬───────────────────────┐
                ▼                             ▼                       │
   ┌────────────────────────┐    ┌──────────────────────────┐         │
   │     backend-blog       │    │      backend-agent       │         │
   │  FastAPI 经典分层      │    │  LangGraph 问答图/推荐图 │         │
   │  JWT 签发 + RBAC       │    │  LangChain LCEL + SSE    │         │
   │  RocketMQ Producer     │    │  Redis 推荐缓存 + 限流   │         │
   └──┬──────┬──────┬───────┘    └──────┬────────────┬──────┘         │
      │      │      │  ▲                │            │                │
      │      │      │  └── /internal/*(取业务数据)───┘            /api/ai/reindex
      │      │      │                                │            (管理员)
      │      │      │  索引推送 /rag/documents        │ /rag/retrieve, /rag/similar
      │      │      └──────────────┬─────────────────┘                │
      │      │                     ▼                                  │
      │      │        ┌──────────────────────────┐                     │
      │      │        │       backend-rag        │◀────────────────────┘
      │      │        │  LlamaIndex 分块/索引     │
      │      │        │  向量检索 + 画像召回      │
      │      │        └────────────┬─────────────┘
      ▼      ▼                     ▼
 ┌────────┐ ┌──────────────┐ ┌──────────┐
 │ MySQL  │ │ RocketMQ 5.x │ │ Milvus   │
 │blog_ai │ │ Proxy:8022   │ │ 2.6      │
 └────────┘ └──────────────┘ └──────────┘
            ┌──────────────────────────┐
            │  Redis(三服务共用实例)   │  blog: 列表缓存 / agent: 推荐缓存+限流 / rag: 检索缓存
            └──────────────────────────┘
```

调用方向一共只有四条，都很短：

| 方向 | 触发时机 | 是否阻塞用户请求 |
| --- | --- | --- |
| blog → rag `POST /rag/documents`、`DELETE /rag/documents/{id}` | 文章发布 / 编辑 / 删除后 | 否（`BackgroundTasks`，响应已返回） |
| blog → agent `POST /internal/rec/invalidate` | 文章发布 / 编辑 / 删除后 | 否（同上） |
| agent → blog `GET/POST /internal/*` | 问答与推荐执行期间 | 是（图节点内串行 RTT） |
| agent → rag `POST /rag/retrieve`、`/rag/similar`、`/rag/reindex` | 问答与推荐执行期间 | 是 |
| rag → blog `GET /internal/article/*` | 仅全量重建索引 | 是（低频管理操作） |

**为什么写路径是 blog 主动推送，而不是 rag 轮询数据库**：推送让 `backend-rag` 彻底不需要 MySQL 连接，索引与数据库解耦；代价是需要一次 HTTP 调用，放在 `BackgroundTasks` 里对接口耗时零影响，失败只丢一次索引更新，可由管理员的全量重建兜底。

---

## 3. 鉴权与信任模型

| 通道 | 机制 | 说明 |
| --- | --- | --- |
| 前端 → 任意服务 | JWT `Authorization: Bearer` | `backend-blog` 签发；`backend-agent` 用**相同的 `SECRET_KEY` 本地验签**，不为每个请求回调 blog |
| 服务 → 服务 | 共享令牌 `X-Internal-Token` | 保护全部 `/internal/*` 与 `backend-rag` 的接口；三个服务的 `INTERNAL_TOKEN` 必须一致，留空表示不校验（仅本地开发） |

管理员操作（如全量重建索引）在 `backend-agent` 里做两步校验：先本地验签拿到 `user_id`，再调 `GET /internal/user/{id}` 核对**实时**的 `is_admin` 与 `status`。这样既避免每个普通请求都多一次 RTT，又不会让一个已被降权的旧 token 继续执行管理操作。

---

## 4. 内部接口契约

全部内部接口沿用统一信封 `{code, message, data}`，`code=0` 为成功。

### 4.1 `backend-blog` 提供（`/internal/*`，需 `X-Internal-Token`）

| 方法 | 路径 | 用途 | 调用方 |
| --- | --- | --- | --- |
| GET | `/internal/article/{id}/meta` | 文章标题 / 分类 / 状态（不含正文） | agent（问答前校验） |
| GET | `/internal/article/{id}/document` | 索引用文档（含正文），文章不存在返回 404 | rag（全量重建） |
| GET | `/internal/article/indexable-ids` | 全部已发布文章 ID | rag（全量重建） |
| GET | `/internal/user/{id}` | `is_admin` / `status` | agent（管理操作二次校验） |
| GET | `/internal/rec/behavior/{user_id}?limit=` | 最近浏览（次数/时长）+ 全部收藏 ID | agent（推荐图 `load_behavior`） |
| POST | `/internal/rec/recall/tags` | 兴趣标签召回（含热度排序、`GROUP BY` 去重） | agent（推荐图 `tag_recall`） |
| POST | `/internal/rec/recall/fallback` | 兜底召回（最新 / 热门 / 收藏最多，已合并去重） | agent（推荐图 `fallback_recall`） |
| POST | `/internal/rec/cards` | 批量取卡片字段（一次 `IN` 查询） | agent（推荐图 `assemble`） |

SQL 全部收敛在 `app/services/recall.py`：**只取数，不含推荐策略**。权重公式、召回优先级、去重截断都在 agent 侧，因此换算法不用改 SQL，改表结构不用改算法。

### 4.2 `backend-rag` 提供（需 `X-Internal-Token`）

| 方法 | 路径 | 用途 | 调用方 |
| --- | --- | --- | --- |
| POST | `/rag/documents` | 单篇文章 upsert 索引（幂等） | blog（写路径推送） |
| DELETE | `/rag/documents/{id}` | 删除单篇文章的全部分块 | blog（删除 / 下架） |
| POST | `/rag/reindex` | 全量重建（回源 blog 拉正文，受并发上限约束） | agent（管理员转发） |
| POST | `/rag/retrieve` | 向量检索分块（按 `article_id` / `category_id` 限定范围） | agent（问答图） |
| POST | `/rag/similar` | 画像召回（入参「文章+权重」，出参「文章+得分」） | agent（推荐图） |

### 4.3 `backend-agent` 提供

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| GET | `/api/ai/config` | AI 开关 + 预设问题 | 否 |
| POST | `/api/ai/ask` | 文章问答（SSE 流式） | 否（单 IP 限流） |
| POST | `/api/ai/reindex` | 转发全量重建 | 管理员 |
| GET | `/api/rec/articles` | 个性化推荐 | 可选（匿名兜底） |
| POST | `/internal/rec/invalidate` | 失效推荐缓存 | `X-Internal-Token` |

前端路径与拆分前**完全一致**，业务代码零改动，只需把 `/api/ai`、`/api/rec` 指向 8001。

---

## 5. 启动顺序与本地开发

```bash
# 0) 基础设施
docker compose -f deploy/milvus/docker-compose.yml up -d      # Milvus 19530
docker compose -f deploy/rocketmq/docker-compose.yml up -d    # RocketMQ Proxy 8022
docker run -d --name redis -p 6379:6379 -v redis_data:/data redis:8-alpine redis-server --requirepass qwqwqw78  # Redis 6379

# 1) 业务服务(其余两个服务都要回调它取数)
cd backend-blog && uv sync && uv run uvicorn app.main:app --reload --port 8000

# 2) 检索服务(启动时确保 Milvus 集合与索引就绪)
cd backend-rag && uv sync && uv run uvicorn app.main:app --reload --port 8002

# 3) 编排服务
cd backend-agent && uv sync && uv run uvicorn app.main:app --reload --port 8001

# 4) 前端
cd frontend-app && npm run dev     # 5173
cd frontend-admin && npm run dev   # 5174
```

启动顺序不是强约束（服务间调用失败都有降级），但按 blog → rag → agent 的顺序启动可以避免启动日志里出现无意义的连接告警。

三份 `.env` 中必须保持一致的配置：

| 配置 | 出现在 | 不一致的后果 |
| --- | --- | --- |
| `INTERNAL_TOKEN` | 三个服务 | 内部接口 401，问答与推荐降级为兜底 |
| `SECRET_KEY` / `ALGORITHM` | blog、agent | agent 无法识别登录用户，推荐全部走匿名兜底 |
| `AI_EMBED_MODEL` / `AI_EMBED_DIM` | rag（唯一持有方） | 改动后需重新执行一次全量重建 |

---

## 6. 降级矩阵

每一次跨服务调用都有明确的降级行为，任一服务挂掉都不会让整站不可用。

| 故障 | 表现 | 受影响范围 |
| --- | --- | --- |
| `backend-rag` 不可达 | 问答检索返回空片段，模型据实回答「文章中没有提到」；推荐画像召回失败转标签/兜底 | 仅 AI 质量下降 |
| `backend-agent` 不可达 | 前端问答区与「为你推荐」Tab 空态；文章缓存失效通知失败，靠 30s TTL 收敛 | 业务功能不受影响 |
| `backend-blog` 不可达 | 问答返回 503（无法校验文章），推荐返回空列表 | AI 功能不可用 |
| Milvus 不可达 | rag 接口 5xx，等价于「rag 不可达」 | 同上 |
| Redis 不可达 | 缓存与限流全部 fail-open：直接回源，限流退化为进程内窗口 | 仅性能下降 |
| 未配置 `AI_API_KEY` | agent `/config` 返回 `enabled=false`（前端隐藏入口）；rag 接口返回 503 | AI 功能整体关闭 |
| 索引推送失败 | 仅记日志，文章事务已提交；可由管理员全量重建补齐 | 新文章暂时问答不到 |

---

## 7. 性能优化要点（按存储归类）

### MySQL（backend-blog）

- 连接池 `pool_size=20 / max_overflow=10 / pool_pre_ping / pool_recycle=28000`，与 `wait_timeout=28800` 对齐。
- 列表、搜索、召回、卡片装配**只 SELECT 必要列**，永不加载 `content` 大字段。
- 行为查询命中 `idx_user_last(user_id, last_browse_time)`；标签召回 `tag_id IN` 命中 `idx_tag`；兜底命中 `idx_status_create` / `idx_status_view`，避免 `filesort`。
- 卡片装配一次 `IN` 批量查询，避免 N+1；浏览量自增用 `view_count = view_count + 1` 单语句。
- 内部接口全部是「主键或索引 + 列投影」的短查询，跨服务调用的开销集中在网络而不是数据库。

### Redis（三服务）

- blog：文章列表 / 置顶 L1 内存 + L2 Redis 多级缓存。
- agent：推荐结果 L1 + L2（匿名共享 key、登录按 `user_id` 分 key、短 TTL 30s）；提问限流用 Redis 固定窗口，`INCR` + `EXPIRE NX` 用 pipeline 合并为一个 RTT。
- rag：检索结果 Redis 单层缓存（问题长尾，L1 命中率低，不值得占进程内存），命中即省下一次向量化 HTTP 与一次 Milvus 检索；索引写入后整批失效，不会引用已删除内容。
- 通用做法：TTL 附加 0~20% 随机抖动防雪崩；同 key 单飞锁防击穿，锁表引用计数归零即回收；Redis 异常一律 fail-open 回源。

### Milvus（backend-rag）

- 标量字段提升为真实列（`article_id` / `category_id` / `title` / `chunk_index`），并对参与过滤的三列建 **INVERTED** 倒排索引。
- HNSW `M=16 / efConstruction=128`，检索 `ef=64` 可配；`radius` 把相似度下限下推到引擎侧，低分块不回传。
- `output_fields` 白名单排除 LlamaIndex 的 `_node_content`（正文 JSON 副本），检索回传量约减半。
- `consistency_level=Bounded`：检索不等同步点，换取显著更高吞吐，代价是新文章秒级可见延迟。
- `upsert_mode=True` + 确定性节点 ID（`article:{id}:chunk:{i}` 的 UUID5），重复索引天然幂等。
- 画像召回只取每篇文章开头 3 个分块作代表向量，把回传的向量数据量压到千分之一级别。

### 应用层

- LangGraph 图 `compile()` 模块级单例；LCEL 链、`ChatOpenAI`、LlamaIndex `Settings`、Milvus 存储、`httpx.AsyncClient` 全部单例，复用连接池。
- 服务间调用统一走进程级 `AsyncClient`（keep-alive + 连接池上限），关闭时在 `lifespan` 里显式 `aclose()`。
- SSE 首字延迟等于模型首字延迟：LangGraph `messages` 流模式透传 token，不等整段生成完成。
- 通知类调用（索引推送、缓存失效）全部在 `BackgroundTasks` 中执行，写接口耗时与下游无关。
