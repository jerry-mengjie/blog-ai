# AI 博客系统 (blog_ai)

一个前后端分离的全栈博客系统：**三个后端微服务** + **移动端** + **管理后台**，共 5 个独立工程。

> 本文档由 AI 生成，覆盖架构设计、目录结构、启动步骤、数据库设计、接口清单与性能优化要点。
> 微服务拆分依据、服务边界与内部接口契约详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 1. 技术栈

| 模块 | 目录 | 端口 | 技术选型 | 说明 |
| --- | --- | --- | --- | --- |
| 业务服务 | `backend-blog` | 8000 | FastAPI 经典分层 + SQLAlchemy 2.0(async) + aiomysql + MySQL 9.7 + JWT | 用户/文章/评论/收藏/浏览统计；MySQL 的唯一持有者 |
| 编排服务 | `backend-agent` | 8001 | FastAPI + **LangGraph** + **LangChain**(LCEL) + SSE | AI 问答图与推荐图，详见 [docs/AI.md](docs/AI.md)、[docs/RECOMMEND.md](docs/RECOMMEND.md) |
| 检索服务 | `backend-rag` | 8002 | FastAPI + **LlamaIndex** + Milvus 2.6 | 分块/向量化/索引/向量检索/画像召回；Milvus 的唯一持有者 |
| 缓存 | Redis 7 | 6379 | 三服务共用实例（列表缓存 / 推荐缓存 + 限流 / 检索缓存） | L1 内存 + L2 Redis 多级缓存 |
| 消息队列 | `deploy/rocketmq` | 8022 | Apache RocketMQ 5.x（NameServer + Broker + Proxy + Dashboard） | 浏览上报 / 文章 PV 解耦，详见 [docs/USER_BROWSE.md](docs/USER_BROWSE.md) |
| 向量库 | `deploy/milvus` | 19530 | Milvus 2.6 standalone（etcd + MinIO + Milvus） | HNSW + 标量倒排索引 |
| 移动端 | `frontend-app` | 5173 | Vue3 + Vite + Vant 4 + Pinia + Vue Router + Axios | 面向 C 端用户 |
| 管理后台 | `frontend-admin` | 5174 | Vue3 + Vite + Element Plus + Pinia + Vue Router + Axios | 含 RBAC 权限控制 |

用户管理与兴趣标签见 [docs/USER_ADMIN.md](docs/USER_ADMIN.md)。

---

## 2. 系统架构

```
                ┌─────────────────┐        ┌──────────────────┐
  移动端用户 ──▶ │ frontend-app    │        │ frontend-admin   │ ◀── 管理员
                │ (Vue3 + Vant)   │        │ (Vue3 + Element) │
                └────────┬────────┘        └────────┬─────────┘
                         │  /api/ai/*, /api/rec/* → 8001
                         │  其余 /api/*           → 8000     (Vite 代理 / 网关按前缀分发)
              ┌──────────┴───────────────┬──────────────────────┐
              ▼                          ▼                      │
  ┌────────────────────────┐  ┌──────────────────────────┐       │
  │     backend-blog       │  │      backend-agent       │       │
  │  FastAPI 经典分层      │  │  LangGraph 问答/推荐图   │       │
  │  JWT 签发 + RBAC       │  │  LangChain LCEL + SSE    │       │
  │  RocketMQ Producer     │  │  Redis 推荐缓存 + 限流   │       │
  └──┬────────┬────────┬───┘  └────┬──────────────┬──────┘       │
     │        │        │ ▲         │              │        /api/ai/reindex
     │        │        │ └── /internal/*(取业务数据)         (管理员)
     │        │        │  索引推送   │  /rag/retrieve         │
     │        │        └────────┬───┴─ /rag/similar ─────────┤
     │        │                 ▼                            │
     │        │      ┌──────────────────────────┐            │
     │        │      │       backend-rag        │◀───────────┘
     │        │      │  LlamaIndex 索引 + 检索  │
     │        │      └────────────┬─────────────┘
     ▼        ▼                   ▼
┌────────┐ ┌──────────────┐ ┌──────────┐   ┌──────────────────────┐
│ MySQL  │ │ RocketMQ 5.x │ │ Milvus   │   │ Redis(三服务共用)    │
│blog_ai │ │ Proxy:8022   │ │ 2.6      │   │ 多级缓存 L2 + 限流   │
└────────┘ └──────────────┘ └──────────┘   └──────────────────────┘
```

三条硬边界：**MySQL 只属于 `backend-blog`**，**Milvus 只属于 `backend-rag`**，跨服务一律走 HTTP 内部接口（共享令牌 `X-Internal-Token`）。任一 AI 服务不可用时业务功能不受影响，降级矩阵见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#6-降级矩阵)。

---

## 3. 快速开始

### 3.1 数据库

```bash
# 登录 MySQL (用户名 root, 密码 qwqwqw78)
mysql -uroot -pqwqwqw78 < backend-blog/sql/init.sql
```

> 库名为 `blog_ai`（含连字符，SQL 中已用反引号处理）。默认创建管理员 `admin / admin123`。
> 后端启动时也会通过 SQLAlchemy 自动建表（`create_all`），但**推荐用上面的 SQL 脚本**以获得完整索引与种子数据。

### 3.2 Milvus 向量库 + Redis（AI 问答 / 推荐需要）

Milvus 使用官方 Docker Compose standalone 编排（仓库已保留一份 `deploy/milvus/docker-compose.yml`）：

```bash
cd deploy/milvus && docker compose up -d          # gRPC 19530, 健康检查 9091

docker run -d -p 6379:6379 redis:latest --requirepass 123456   # 三服务共用
```

> AI 问答需在 `backend-agent/.env`（对话模型）与 `backend-rag/.env`（向量模型）中填入 `AI_API_KEY`（阿里云百炼）。留空则 AI 功能自动关闭，其余功能不受影响。存量文章需管理员调用 `POST /api/ai/reindex` 建一次索引。详见 [docs/AI.md](docs/AI.md)。
>
> Redis 未启动时缓存与限流全部 fail-open，功能正常，仅性能下降。

### 3.3 RocketMQ（浏览统计异步写，推荐启用）

Python 官方客户端走 **Proxy gRPC（宿主机 8022）**，不是 NameServer 9876。仓库已提供含 Proxy + Dashboard 的编排：

```bash
cd deploy/rocketmq
docker compose up -d
# 管理后台: http://127.0.0.1:8020
```

手动 `docker run` 时需 NameServer + Broker（`autoCreateTopicEnable=true`）+ Proxy。详情与回落策略见 [docs/USER_BROWSE.md](docs/USER_BROWSE.md)。

在 `backend-blog/.env` 配置：

```bash
ROCKETMQ_ENDPOINTS=127.0.0.1:8022
ROCKETMQ_TOPIC_BROWSE=blog_browse
ROCKETMQ_GROUP_BROWSE=blog_browse_consumer
```

留空 `ROCKETMQ_ENDPOINTS` 则关闭 MQ，接口同步写库（无 Worker 也能跑通）。

### 3.4 三个后端服务

按 blog → rag → agent 的顺序启动（另两个服务都要回调 blog 取数）：

```bash
# 业务服务 8000
cd backend-blog && uv sync && uv run uvicorn app.main:app --reload --port 8000
# 另开终端启动浏览统计 Worker（启用 MQ 时需要）
cd backend-blog && uv run python -m app.mq.worker

# 检索服务 8002（启动时自动确保 Milvus 集合与索引就绪）
cd backend-rag && uv sync && uv run uvicorn app.main:app --reload --port 8002

# 编排服务 8001
cd backend-agent && uv sync && uv run uvicorn app.main:app --reload --port 8001
```

交互式文档：<http://127.0.0.1:8000/docs>、<http://127.0.0.1:8001/docs>、<http://127.0.0.1:8002/docs>

三份 `.env` 中 `INTERNAL_TOKEN` 必须完全一致；`backend-agent` 的 `SECRET_KEY` / `ALGORITHM` 必须与 `backend-blog` 一致，否则无法识别登录用户（推荐会全部走匿名兜底）。

### 3.5 移动端 frontend-app

```bash
cd frontend-app
npm install
npm run dev             # 默认 http://localhost:5173
```

### 3.6 管理后台 frontend-admin

```bash
cd frontend-admin
npm install
npm run dev             # 默认 http://localhost:5174
```

> 两个前端均通过 Vite 代理转发接口，无需配置跨域：`/api/ai`、`/api/rec` → `127.0.0.1:8001`（backend-agent），其余 `/api` → `127.0.0.1:8000`（backend-blog）。更具体的前缀必须写在 `/api` 之前，Vite 按声明顺序匹配。`backend-blog` 与 `backend-agent` 的 `CORS_ORIGINS` 均已放行 5173/5174。

---

## 4. 数据库设计（9 张表）

命名规范：表名 `tb_` 前缀。详见 [`backend-blog/sql/init.sql`](backend-blog/sql/init.sql)。

| 表名 | 说明 | 关键索引 |
| --- | --- | --- |
| `tb_user` | 用户表 | 唯一索引 `username`，普通索引 `email`，复合索引 `(status, create_time)` |
| `tb_article` | 文章表 | 复合索引 `(status, is_top, create_time)`、`(status, create_time)`、`(status, view_count)`、`user_id`、`category_id`、标题前缀索引 |
| `tb_category` | 分类表 | 唯一 `name`、索引 `sort` |
| `tb_tag` | 标签表 | 唯一 `name` |
| `tb_article_tag` | 文章标签中间表 | 唯一 `(article_id, tag_id)`、索引 `tag_id` |
| `tb_user_tag` | 用户兴趣标签中间表（复用 `tb_tag`） | 唯一 `(user_id, tag_id)`、索引 `tag_id` |
| `tb_user_browse` | 用户文章浏览统计（累计） | 唯一 `(user_id, article_id)`、`(user_id, last_browse_time)`、`article_id` |
| `tb_comment` | 评论表 | 复合索引 `(article_id, create_time)`、索引 `user_id` |
| `tb_favorite` | 收藏表 | 唯一 `(user_id, article_id)`、索引 `article_id` |

> 兴趣标签：[docs/USER_ADMIN.md](docs/USER_ADMIN.md)；浏览统计：[docs/USER_BROWSE.md](docs/USER_BROWSE.md)。增量迁移见 `sql/migrate_*.sql`。

---

## 5. 接口清单

| 模块 | 方法 | 路径 | 说明 | 鉴权 |
| --- | --- | --- | --- | --- |
| 用户 | POST | `/api/user/register` | 注册 | 否 |
| 用户 | POST | `/api/user/login` | 登录 | 否 |
| 用户 | GET | `/api/user/info` | 个人信息 | 是 |
| 用户 | PUT | `/api/user/info` | 修改资料 | 是 |
| 用户 | POST | `/api/user/logout` | 退出登录 | 是 |
| 管理端用户 | GET | `/api/admin/user/list` | 用户分页列表 | 管理员 |
| 管理端用户 | GET | `/api/admin/user/detail/{id}` | 用户详情(含兴趣标签) | 管理员 |
| 管理端用户 | PUT | `/api/admin/user/{id}` | 更新资料/状态/管理员 | 管理员 |
| 管理端用户 | PUT | `/api/admin/user/{id}/tags` | 全量设置兴趣标签 | 管理员 |
| 文章 | GET | `/api/article/list` | 分页列表 | 否 |
| 文章 | GET | `/api/article/detail/{id}` | 详情 | 否 |
| 文章 | POST | `/api/article/add` | 发布 | 是 |
| 文章 | PUT | `/api/article/update/{id}` | 编辑 | 是(作者/管理员) |
| 文章 | DELETE | `/api/article/del/{id}` | 删除 | 是(作者/管理员) |
| 文章 | GET | `/api/article/top` | 置顶列表 | 否 |
| 文章 | GET | `/api/article/search` | 搜索 | 否 |
| 分类 | GET | `/api/category/list` | 全部分类 | 否 |
| 分类 | POST | `/api/category/add` | 新增分类 | 管理员 |
| 标签 | GET | `/api/tag/list` | 全部标签 | 否 |
| 标签 | POST | `/api/tag/add` | 新增标签 | 管理员 |
| 评论 | GET | `/api/comment/list/{articleId}` | 评论列表 | 否 |
| 评论 | POST | `/api/comment/add` | 发表评论 | 是 |
| 评论 | DELETE | `/api/comment/del/{id}` | 删除评论 | 是(本人/管理员) |
| 收藏 | POST | `/api/favorite/add` | 收藏/取消收藏 | 是 |
| 收藏 | GET | `/api/favorite/list` | 我的收藏 | 是 |
| 浏览 | POST | `/api/browse/report` | 上报浏览(次数/时长) | 是 |
| 浏览 | GET | `/api/browse/list` | 我的足迹 | 是 |
| 管理端浏览 | GET | `/api/admin/browse/list` | 浏览统计列表 | 管理员 |

以上均由 `backend-blog`(8000) 提供。下列接口由 `backend-agent`(8001) 提供，路径与拆分前一致，前端零改动：

| 模块 | 方法 | 路径 | 说明 | 鉴权 |
| --- | --- | --- | --- | --- |
| AI | GET | `/api/ai/config` | AI 开关 + 预设问题 | 否 |
| AI | POST | `/api/ai/ask` | 文章问答(SSE 流式，LangGraph 问答图) | 否(限流) |
| AI | POST | `/api/ai/reindex` | 全量重建向量索引(转发 backend-rag) | 管理员 |
| 推荐 | GET | `/api/rec/articles` | 个性化文章推荐(LangGraph 推荐图) | 可选(匿名兜底) |

服务间还有 13 个内部接口（`backend-blog` 的 `/internal/*` 8 个、`backend-rag` 的 `/rag/*` 5 个），用共享令牌 `X-Internal-Token` 鉴权，不对浏览器暴露，契约见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#4-内部接口契约)。

统一响应格式（三个服务与内部接口一致）：

```json
{ "code": 0, "message": "success", "data": {} }
```

`code = 0` 为成功；非 0（通常等于 HTTP 状态码）为业务/系统错误。

---

## 6. 前端页面

### 移动端（5 页）
- `index.vue` 首页：分类 Tabs（为你推荐 | 置顶 | 全部 | 分类）+ 上拉加载/下拉刷新
- `article-detail.vue` 文章详情：正文 + AI 问答（`components/ai-ask.vue`）+ 评论区 + 收藏 + 登录用户停留上报
- `search.vue` 搜索页
- `personal.vue` 个人中心：登录/注册 + 资料修改 + 我的足迹 + 我的收藏
- `about.vue` 关于本站

### 管理后台（5 页）
- `admin-login.vue` 登录（仅管理员可进入）
- `admin-article.vue` 文章管理（增 / 改 / 删 / 搜索 / 分页）
- `admin-category-tag.vue` 分类标签管理
- `admin-user.vue` 用户管理（资料 / 状态 / 兴趣标签）
- `admin-browse.vue` 浏览统计（次数 / 时长 / 最好浏览时间）

---

## 7. RBAC 权限控制（管理后台）

- **角色推导**：后端 `is_admin=1` 映射为 `admin` 角色，否则 `editor`（可扩展为后端直接返回 `role`）。
- **权限定义**：`frontend-admin/src/rbac/permissions.js` 中以「角色 → 权限码」声明。
- **路由级控制**：路由 `meta.permission` + 全局守卫 `router.beforeEach` 校验。
- **菜单级控制**：`Layout.vue` 依据权限动态渲染侧边菜单。
- **按钮级控制**：页面内 `v-if="userStore.hasPermission(code)"` 控制新增/编辑/删除按钮。

---

## 8. 性能优化要点

**数据库层**
- 列表/搜索查询**只选必要列**，不加载 `content` 大字段。
- 文章列表命中复合索引 `(status, is_top, create_time)`，避免 `filesort`。
- 收藏、文章标签使用唯一索引防重并加速「是否存在」判断。
- 浏览量自增使用 SQL `view_count = view_count + 1`（非 ORM 读改写），并发不丢更新。
- 用户浏览用 `INSERT ... ON DUPLICATE KEY UPDATE` 单语句原子累计。

**后端层**
- 全异步（FastAPI + async SQLAlchemy + aiomysql），高并发吞吐。
- 连接池：`pool_size=20 / max_overflow=10 / pool_pre_ping / pool_recycle=28000`，与 MySQL 9.7 `wait_timeout` 对齐。
- JWT 无状态鉴权，水平扩展友好；`backend-agent` 用相同密钥本地验签，不为每个请求回调 blog。
- 浏览上报 / 文章 PV 经 RocketMQ 异步落库（Producer + SimpleConsumer），投递失败同步回落。
- 服务间调用统一走进程级 `httpx.AsyncClient`（keep-alive + 连接池上限），`lifespan` 关闭时显式释放；索引推送与缓存失效通知都在 `BackgroundTasks` 里，写接口耗时与下游无关。

**Redis 多级缓存**（三服务）
- blog：文章列表 / 置顶 L1 内存 + L2 Redis；agent：推荐结果 L1 + L2（匿名共享 key、登录分 key、TTL 30s）；rag：检索结果 Redis 单层（问题长尾，L1 不划算）。
- L2 TTL 附加 0~20% 随机抖动防雪崩；同 key 单飞锁防击穿，锁表引用计数归零即回收。
- 前缀失效用 `SCAN` + 批量 `UNLINK`；限流用 `INCR` + `EXPIRE NX` pipeline 合并为一个 RTT。
- Redis 异常一律 fail-open 回源，只记告警。

**前端层**
- 路由懒加载（代码分割），首屏更快。
- 组件**按需自动导入**（Vant / Element Plus），减小打包体积。
- 移动端首页 `keep-alive` 缓存 + 分页加载。

**AI / 向量层**（详见 [docs/AI.md](docs/AI.md)）
- LlamaIndex / LangChain 全链路原生异步 + 模型/存储/链/图模块级单例复用。
- Milvus：标量字段独立成列 + INVERTED 倒排索引 + HNSW 调优 + `radius` 引擎侧过滤低分块。
- `output_fields` 白名单排除 `_node_content`（正文 JSON 副本），检索回传量约减半；`consistency_level=Bounded` 换取高吞吐。
- 确定性节点 ID + `upsert_mode`，重复索引天然幂等；检索结果 Redis 缓存省下向量化与检索开销。
- SSE 首字延迟等于模型首字延迟（LangGraph `messages` 流模式透传 token）；单 IP Redis 固定窗口限流防刷。

**推荐层**（详见 [docs/RECOMMEND.md](docs/RECOMMEND.md)）
- LangGraph 图编译单例，节点全异步；每节点一次网络请求，最坏 4 次串行 RTT。
- 画像复用问答的分块向量，零新增 embedding 成本；每篇只取开头 3 块作代表向量。
- 行为/标签/兜底查询分别命中 `idx_user_last`、`idx_tag`、`(status, create_time)`/`(status, view_count)` 索引；卡片一次 `IN` 装配。
- Milvus 排除已读用 `not in` 走倒排索引，引擎侧完成过滤；分块检索后文章级聚合取最高分。
- 缓存命中时整张图与全部下游调用一起跳过。

---

## 9. 目录结构

```
blog_ai/
├── README.md                 # 本文档
├── docs/ARCHITECTURE.md      # 微服务架构文档(拆分依据/服务边界/内部接口契约/降级矩阵)
├── docs/AI.md                # AI 问答功能文档(问答图 + LlamaIndex 检索/接口/性能优化)
├── docs/RECOMMEND.md         # 文章推荐系统文档(LangGraph 多节点/召回策略/多级缓存)
├── docs/USER_ADMIN.md        # 管理端用户管理与兴趣标签文档
├── docs/USER_BROWSE.md       # 用户文章浏览统计文档(含 RocketMQ 异步链路)
├── deploy/milvus/            # Milvus standalone 官方 Docker Compose 编排
├── deploy/rocketmq/          # RocketMQ NameServer + Broker + Proxy + Dashboard 编排
├── backend-blog/             # 业务服务 8000 (FastAPI 经典分层)
│   ├── .env                  # DB / JWT / CORS / Redis / RocketMQ / 下游服务地址
│   ├── sql/init.sql          # 建表 + 索引 + 种子数据
│   └── app/
│       ├── main.py           # 应用入口(路由/中间件/异常/生命周期)
│       ├── core/             # 配置/数据库/安全/多级缓存/Redis/统一响应
│       ├── models/           # SQLAlchemy 模型(9 张表)
│       ├── schemas/          # Pydantic 模型(含 internal.py 内部契约)
│       ├── api/              # 业务路由 + internal_content / internal_rec 内部路由
│       ├── services/         # 领域服务(文章缓存/浏览/召回取数 recall.py)
│       ├── clients/          # 下游客户端(rag 索引推送 / agent 缓存失效)
│       └── mq/               # RocketMQ: Producer / Worker / 消息体
├── backend-agent/            # 编排服务 8001 (FastAPI + LangGraph + LangChain)
│   ├── .env                  # 对话模型 / JWT / 下游地址 / Redis / 推荐参数
│   └── app/
│       ├── main.py           # 应用入口
│       ├── core/             # 配置/日志/安全/Redis/多级缓存/限流
│       ├── llm/              # ChatOpenAI 单例 + 提示词
│       ├── graphs/           # LangGraph: qa.py 问答图 / recommend.py 推荐图
│       ├── services/         # 推荐缓存门面
│       ├── clients/          # blog / rag 内部接口客户端
│       ├── schemas/          # 请求响应模型
│       └── api/              # /api/ai/* 与 /api/rec/* 路由
├── backend-rag/              # 检索服务 8002 (FastAPI + LlamaIndex)
│   ├── .env                  # 向量模型 / Milvus / 分块检索参数 / Redis
│   └── app/
│       ├── main.py           # 应用入口(启动期确保集合与索引就绪)
│       ├── core/             # 配置/日志/Redis/检索缓存/统一响应
│       ├── rag/              # models 全局组件 / vector_store / ingest / retriever / profile
│       ├── clients/          # blog 内部接口客户端(全量重建回源)
│       ├── schemas/          # 请求响应模型
│       └── api/              # /rag/* 索引与检索路由
├── frontend-app/             # 移动端 (Vue3 + Vant)
│   └── src/{api,components,store,router,views}
└── frontend-admin/           # 管理后台 (Vue3 + Element Plus)
    └── src/{api,store,router,rbac,layout,views}
```
