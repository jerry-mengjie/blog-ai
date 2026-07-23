# 用户文章浏览统计文档

> 本文档由 AI 生成。覆盖功能说明、数据模型、上报链路、接口与 MySQL 性能优化。

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

- **全局文章浏览量**仍由 `GET /api/article/detail` 对 `tb_article.view_count` +1（含匿名）。
- **本表仅登录用户**：详情页计时，离开/切后台后上报。
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

## 3. 模块拆分

| 路径 | 职责 |
| --- | --- |
| `app/models/browse.py` | `UserBrowse` ORM |
| `app/schemas/browse.py` | 上报/列表 schema |
| `app/services/browse.py` | upsert 累计、我的足迹、管理端列表 |
| `app/api/browse.py` | C 端：上报 + 我的足迹 |
| `app/api/admin_browse.py` | 管理端分页查询 |

路由只做鉴权与转发；累计逻辑集中在服务层。

### 性能要点

1. **单语句原子 upsert**（`INSERT ... ON DUPLICATE KEY UPDATE`），避免「先 SELECT 再 UPDATE」竞态与双 round-trip。
2. **单次 `duration` 上限 7200 秒**，防止异常/刷量撑爆总时长。
3. **列表 JOIN 只选标题/封面/摘要**，不拉 `content`。
4. **足迹命中 `idx_user_last`**；按文章过滤命中 `idx_article`。
5. **分页 `page_size` 封顶**（C 端 50 / 管理端 100）。

### 最好浏览时间更新逻辑

当本次 `duration > best_duration`（旧值）时：

- `best_duration = duration`
- `best_browse_time = NOW()`

否则只累加次数与总时长，并刷新 `last_browse_time`。

---

## 4. 接口

### C 端（需登录）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/browse/report` | Body：`{ article_id, duration }` |
| GET | `/api/browse/list` | 我的足迹；Query：`page`、`page_size` |

### 管理端（需管理员）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/admin/browse/list` | Query：`page`、`page_size`、`user_id`、`article_id`、`keyword` |

统一响应：`{ code, message, data }`。

---

## 5. 前端

### 移动端 `frontend-app`

| 路径 | 行为 |
| --- | --- |
| `article-detail.vue` | 登录用户可见时段计时；`visibilitychange` 暂停；离开页静默上报 |
| `personal.vue` | 「我的足迹」列表 |
| `api/index.js` → `browseApi` | `report`（`silent: true`）、`list` |
| `api/request.js` | 支持 `silent`，离开页不上报失败 Toast/跳转 |

### 管理端 `frontend-admin`

| 路径 | 说明 |
| --- | --- |
| `admin-browse.vue` | 浏览统计表 |
| `rbac/permissions.js` | `BROWSE_VIEW` |
| `router/index.js` | `/browse` 菜单「浏览统计」 |

---

## 6. 本地验证建议

1. 执行 `migrate_user_browse.sql`（或依赖启动 `create_all`）。
2. 移动端登录 → 打开文章停留数十秒 → 返回。
3. 「我的」页应出现足迹（次数、总时长）。
4. 管理端「浏览统计」可见对应用户×文章行，`最好浏览时间` 在更长单次后更新。

---

## 7. 文件清单

```
backend-blog/
  app/models/browse.py
  app/schemas/browse.py
  app/services/browse.py
  app/api/browse.py
  app/api/admin_browse.py
  app/main.py
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
