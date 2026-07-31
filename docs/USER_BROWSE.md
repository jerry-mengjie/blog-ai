# 用户文章浏览统计文档

> 本文档由 AI 生成。覆盖功能说明、数据模型、RocketMQ 异步链路、接口与 MySQL/Milvus 性能优化。

---

## 1. 功能概览

记录**登录用户**对每篇文章的累计浏览行为（非流水日志）：

| 指标 | 字段 | 说明 |
| --- | --- | --- |
| 浏览过哪些文章 | `user_id` + `article_id` | 唯一一行 |
| 浏览总次数 | `view_count` | 每次上报 +1 |
| 总时长 | `total_duration` | 累加本次停留秒数 |
| 最好浏览时间 | `best_browse_time` | 单次时长创纪录时的时刻 |
| （辅助）最长单次 | `best_duration` | 判定「最好」用的秒数 |

说明：

- **全局文章浏览量**由 `GET /api/article/detail` 投递 PV 消息（或同步回落）对 `tb_article.view_count` 原子 +1（含匿名）。
- **本表仅登录用户**：详情页计时，离开/切后台后上报。
- **写路径异步**：上报 / PV 优先进 RocketMQ，Worker 落库；读路径仍直连 MySQL。
- 管理后台「浏览统计」可按用户/文章/关键字查询。

---

## 2. 数据模型

### 表 `tb_user_browse`

```
tb_user ──┐
          ├── tb_user_browse ──▶ tb_article
```

| 索引 | 用途 |
| --- | --- |
| `uk_user_browse(user_id, article_id)` | 防重 + `ON DUPLICATE KEY UPDATE` 原子累计 |
| `idx_user_last(user_id, last_browse_time)` | 我的足迹：过滤 + 最近倒序 |
| `idx_article(article_id)` | 按文章反查读者 |

SQL：

- 全新库：`backend-blog/sql/init.sql`
- 已有库：`backend-blog/sql/migrate_user_browse.sql`

---

## 3. RocketMQ 异步解耦

### 为什么异步

详情接口与离开页上报若同步写 MySQL，会拉长请求 RT，并在热点文章上放大 `view_count` / upsert 锁竞争。经典做法：**校验后投递消息立即返回，消费侧独立会话原子写库**。

### 经典方案选型

| 组件 | 选型 | 说明 |
| --- | --- | --- |
| 客户端 | `rocketmq-python-client` | Apache RocketMQ 5.x 官方 Python SDK |
| 生产 | `Producer` + Topic/Tag | Tag=`report` / `pv` 二级分类 |
| 消费 | `SimpleConsumer` 长轮询 | `receive → handle → ack`；失败不 ack 以便重试 |
| 接入点 | Proxy gRPC `127.0.0.1:8022` | **不是** NameServer `9876` |

> 仅启动 NameServer + Broker（Remoting）时，官方 Python 客户端无法直连。本地请用仓库 `deploy/rocketmq/docker-compose.yml`（含 Proxy），或自行加 Proxy 容器。

### 链路

```
详情 GET /api/article/detail/{id}
  ├─ 读文章 + 标签 → 立即返回
  └─ publish_article_pv ──▶ Topic blog_browse Tag=pv
                              └─ Worker → UPDATE view_count = view_count + 1

上报 POST /api/browse/report
  ├─ 校验文章存在 → 立即返回 { reported, async }
  └─ publish_browse_report ──▶ Tag=report
                              └─ Worker → INSERT ... ON DUPLICATE KEY UPDATE
```

### 回落策略

- `.env` 中 `ROCKETMQ_ENDPOINTS` **为空**：关闭 MQ，API 内同步写库（无 Worker 也能跑通）。
- 已配置但投递失败：同请求内同步回落，**保证不丢数**。
- Worker 处理失败：不 `ack`，等可见性超时重投。

### 本地启动

```bash
# 1. RocketMQ (NameServer + Broker + Proxy + Dashboard)
cd deploy/rocketmq && docker compose up -d
# 管理后台: http://127.0.0.1:8020

# 2. .env 启用 Proxy
# ROCKETMQ_ENDPOINTS=127.0.0.1:8022

# 3. API
cd backend-blog && uv sync && uv run uvicorn app.main:app --reload --port 8000

# 4. Worker（另开终端）
cd backend-blog && uv run python -m app.mq.worker
```

等价于手动 `docker run` 时，需额外启动 Proxy，且 Broker 建议 `autoCreateTopicEnable=true`（本地调试必备）。

### 消息体

| Tag | 字段 | 说明 |
| --- | --- | --- |
| `report` | `user_id`, `article_id`, `duration` | 登录用户停留上报 |
| `pv` | `article_id` | 文章全局 PV |

---

## 4. 模块拆分

| 路径 | 职责 |
| --- | --- |
| `app/models/browse.py` | `UserBrowse` ORM |
| `app/schemas/browse.py` | 上报/列表 schema |
| `app/services/browse.py` | upsert 累计、原子 PV、我的足迹、管理端列表 |
| `app/api/browse.py` | C 端：上报(投递/回落) + 我的足迹 |
| `app/api/admin_browse.py` | 管理端分页查询 |
| `app/mq/producer.py` | Producer 单例 + `publish_*` |
| `app/mq/worker.py` | SimpleConsumer 入口 |
| `app/mq/handler.py` | Tag 分发 → 领域服务 |
| `app/mq/messages.py` | JSON 消息体 |
| `app/mq/topics.py` | Topic / Group / Tag |

路由只做鉴权与转发；累计逻辑集中在服务层；MQ 只负责解耦。

### MySQL 性能要点

1. **单语句原子 upsert**（`INSERT ... ON DUPLICATE KEY UPDATE`），避免「先 SELECT 再 UPDATE」竞态与双 round-trip。
2. **PV 用 `UPDATE ... SET view_count = view_count + 1`**，避免 ORM 读改写在并发下丢更新。
3. **单次 `duration` 上限 7200 秒**，防止异常/刷量撑爆总时长。
4. **列表 JOIN 只选标题/封面/摘要**，不拉 `content`。
5. **足迹命中 `idx_user_last`**；按文章过滤命中 `idx_article`；热文兜底命中 `(status, view_count)`。
6. **分页 `page_size` 封顶**（C 端 50 / 管理端 100）。
7. **写进 MQ、读直连**：热点写与列表读隔离，连接池参数与 `wait_timeout` 对齐。

### Milvus 性能要点（与浏览解耦）

浏览统计不写向量库；推荐画像仍读 `tb_user_browse` + Milvus 分块向量。既有优化保持不变：

1. 文章索引走 `BackgroundTasks`，发文接口零阻塞。
2. HNSW + 标量倒排；range search 过滤低分；排除已读用 `not in` 走倒排。
3. 推荐复用问答分块向量，零新增 embedding 成本。

### 最好浏览时间更新逻辑

当本次 `duration > best_duration`（旧值）时：

- `best_duration = duration`
- `best_browse_time = NOW()`

否则只累加次数与总时长，并刷新 `last_browse_time`。

---

## 5. 接口

### C 端（需登录）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/browse/report` | Body：`{ article_id, duration }`；`data.async=true` 表示已进 MQ |
| GET | `/api/browse/list` | 我的足迹；Query：`page`、`page_size` |

### 管理端（需管理员）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/admin/browse/list` | Query：`page`、`page_size`、`user_id`、`article_id`、`keyword` |

统一响应：`{ code, message, data }`。

---

## 6. 前端

### 移动端 `frontend-app`

| 路径 | 行为 |
| --- | --- |
| `article-detail.vue` | 登录用户可见时段计时；`visibilitychange` 暂停；离开页静默上报（后端可异步落库） |
| `personal.vue` | 「我的足迹」列表（略延迟属正常，MQ 消费后可见） |
| `api/index.js` → `browseApi` | `report`（`silent: true`）、`list` |
| `api/request.js` | 支持 `silent`，离开页不上报失败 Toast/跳转 |

### 管理端 `frontend-admin`

| 路径 | 说明 |
| --- | --- |
| `admin-browse.vue` | 浏览统计表 |
| `rbac/permissions.js` | `BROWSE_VIEW` |
| `router/index.js` | `/browse` 菜单「浏览统计」 |

前端契约不变；异步仅发生在后端写路径。

---

## 7. 本地验证建议

1. `docker compose -f deploy/rocketmq/docker-compose.yml up -d`，确认 `8022` 可连；管理后台见 http://127.0.0.1:8020。
2. `.env` 配置 `ROCKETMQ_ENDPOINTS=127.0.0.1:8022`，启动 API + `python -m app.mq.worker`。
3. 打开文章详情：接口应快速返回；Worker 日志出现「消费文章 PV」。
4. 登录后停留数十秒离开：Worker 出现「消费浏览上报」；「我的」页出现足迹。
5. 管理端「浏览统计」可见对应用户×文章行。
6. 停掉 MQ / 清空 `ROCKETMQ_ENDPOINTS`：接口仍可用（同步回落），验证容灾。

---

## 8. 文件清单

```
deploy/rocketmq/docker-compose.yml
backend-blog/
  app/models/browse.py
  app/schemas/browse.py
  app/services/browse.py
  app/api/browse.py
  app/api/admin_browse.py
  app/api/article.py          # 详情 PV 异步
  app/mq/__init__.py
  app/mq/topics.py
  app/mq/messages.py
  app/mq/producer.py
  app/mq/handler.py
  app/mq/worker.py
  app/main.py
  app/core/config.py
  .env
  pyproject.toml
  sql/init.sql
  sql/migrate_user_browse.sql
frontend-app/
  src/views/article-detail.vue
  src/views/personal.vue
  src/api/index.js
  src/api/request.js
frontend-admin/
  src/views/admin-browse.vue
  src/api/index.js
  src/router/index.js
  src/rbac/permissions.js
docs/USER_BROWSE.md
```
