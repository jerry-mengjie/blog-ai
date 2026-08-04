# 置顶文章多级缓存文档

> 本文档由 AI 生成。覆盖 `GET /api/article/top` 的 L1/L2 缓存、Redis/MySQL/Milvus 性能要点与失效策略。

---

## 1. 功能概览

首页「置顶」Tab 请求：

```http
GET /api/article/top
```

返回已发布且 `is_top=1` 的文章，按 `create_time` 倒序，固定最多 **10** 条。读多写少、结果集极小，适合经典**多级缓存**：

| 层级 | 介质 | 作用 |
| --- | --- | --- |
| L1 | 进程内内存 + TTL | 同进程零网络 |
| L2 | Redis `SET … EX ttl` | 多 Worker 共享 |
| 回源 | MySQL 投影查询 | 命中 `idx_status_top_time` |

与 `/api/article/list` 第 1 页共用同一套 `MultiLevelCache` 实现与 TTL 配置，仅 key 前缀不同。

---

## 2. 技术选型（各框架经典方案）

| 环节 | 方案 | 说明 |
| --- | --- | --- |
| Web | FastAPI 薄路由 + `services.article` | 路由只做依赖注入与信封 |
| L1/L2 | `MultiLevelCache`（dict TTL + `redis.asyncio`） | 与列表缓存同一门面；单飞防击穿 |
| Key | `article:top:v1:limit10` | 条数写入 key，改 LIMIT 自然隔离 |
| 失效 | 写后 `invalidate_article_caches()` | 同时清 list + top 前缀 |
| MySQL | 列投影 + `idx_status_top_time(status, is_top, create_time)` | `WHERE status=1 AND is_top=1 ORDER BY create_time DESC LIMIT 10` |
| Milvus | 与列表解耦；写路径仍异步索引 | 启动 `load_collection` + HNSW/INVERTED |

---

## 3. 架构与数据流

```
GET /api/article/top
        │
        ▼
  services.article.list_top_articles
        │
        ├─ L1 命中 ──────────────────────────────▶ 返回 [ArticleListItem]
        │
        ├─ L2 Redis GET 命中 ─▶ 回填 L1 ──────────▶ 返回列表
        │
        └─ 单飞锁 → MySQL(投影 + LIMIT 10)
                    │
                    ├─ SET Redis EX ttl
                    ├─ 写 L1
                    └─ 返回列表

POST/PUT/DELETE 文章成功提交后
        │
        └─ invalidate_article_caches
              ├─ SCAN article:list:v1:* → UNLINK + 清 L1
              └─ SCAN article:top:v1:*  → UNLINK + 清 L1
```

---

## 4. 模块位置

| 路径 | 职责 |
| --- | --- |
| `app/core/cache.py` | 通用 L1+L2（复用） |
| `app/core/redis.py` | Redis 连接池（复用） |
| `app/services/article.py` | `query_top_articles` / `list_top_articles` / 失效 |
| `app/api/article.py` | `GET /top` 委托；写接口调 `invalidate_article_caches` |

---

## 5. Redis Key 与配置

```
article:top:v1:limit10
```

TTL / L1 容量复用列表配置（`.env`）：

```env
ARTICLE_LIST_CACHE_TTL=60
ARTICLE_LIST_L1_MAXSIZE=256
```

`REDIS_HOST` 为空时仅 L1，行为与列表一致。

---

## 6. MySQL 性能

```sql
SELECT id, title, cover, summary, category_id, view_count, is_top, create_time
FROM tb_article
WHERE status = 1 AND is_top = 1
ORDER BY create_time DESC
LIMIT 10;
```

- **不选** `content`
- 复合索引 `idx_status_top_time(status, is_top, create_time)`：过滤 + 排序一体，免 filesort
- 结果最多 10 行，网络与序列化成本极低

---

## 7. 一致性说明

| 事件 | 策略 |
| --- | --- |
| 发文 / 编辑（含改 `is_top`/`status`）/ 删除 | `invalidate_article_caches()` 立即失效 top + list |
| 详情 PV | 不主动失效；依赖 TTL，列表/置顶浏览量可短时陈旧 |
| 多 Worker | L2 为共享真相；失效清本机 L1 + 远程 key |

---

## 8. 前端约定

`frontend-app` 首页「置顶」Tab 调用 `articleApi.top()`，无分页；切换 Tab / 下拉刷新会再次请求，此时应命中 L1 或 L2。

---

## 9. 自测清单

1. 连续两次 `GET /api/article/top`：第二次应更快。
2. Redis 中可见 `article:top:v1:limit10`。
3. 将某文设为置顶或取消置顶后，接口立即反映。
4. 停 Redis：接口仍可用（L1 或直查）。

相关文档：[文章列表多级缓存](./ARTICLE_LIST_CACHE.md)
