# 文章列表多级缓存文档

> 本文档由 AI 生成。覆盖 `/api/article/list` 全分类第 1 页的 L1/L2 缓存、Redis/MySQL/Milvus 性能优化与失效策略。

---

## 1. 功能概览

首页「全部」与各分类 Tab 首次加载都会请求：

```http
GET /api/article/list?page=1&page_size=10&category_id={0|分类ID}
```

该路径是读多写少的热点。本方案对**所有分类的第 1 页**启用经典**多级缓存**：

| 层级 | 介质 | 作用 |
| --- | --- | --- |
| L1 | 进程内内存字典 + TTL | 同进程零网络，微秒级命中 |
| L2 | Redis (`SET key value EX ttl`) | 多 Worker 共享，扛住重启后冷启动 |
| 回源 | MySQL 异步查询 | 仅投影列表列，命中复合索引 |

`page >= 2`、搜索不走该缓存（避免 key 爆炸与低频页无效占用）。置顶列表见 [ARTICLE_TOP_CACHE.md](./ARTICLE_TOP_CACHE.md)，写路径与 list 一并失效。

---

## 2. 技术选型（各框架经典方案）

| 环节 | 方案 | 说明 |
| --- | --- | --- |
| Web | FastAPI 薄路由 + `services.article` | 路由只做参数与信封，领域逻辑下沉 |
| L1 | 进程 dict + `time.monotonic` TTL + `asyncio.Lock` 单飞 | 经典本地缓存；同 key 并发只回源一次，防击穿 |
| L2 | `redis.asyncio` + `ConnectionPool` + `hiredis` | 官方异步客户端；池化连接；hiredis 加速协议解析 |
| 序列化 | JSON（`model_dump(mode="json")`） | datetime → ISO，跨语言可读 |
| 失效 | 写后 `SCAN` + `UNLINK` 前缀删除 | 分类数少，整前缀失效简单正确 |
| MySQL | 显式列投影 + 复合索引 | 不 `SELECT *`；排序走索引免 filesort |
| Milvus | 启动 `load_collection` + HNSW/INVERTED | 检索前保证集合在内存，避免冷加载 |

---

## 3. 架构与数据流

```
GET /api/article/list (page=1)
        │
        ▼
  services.article.list_articles
        │
        ├─ L1 命中 ──────────────────────────────▶ 返回 PageOut
        │
        ├─ L2 Redis GET 命中 ─▶ 回填 L1 ──────────▶ 返回 PageOut
        │
        └─ 单飞锁 → MySQL count + 列表
                    │
                    ├─ SET Redis EX ttl
                    ├─ 写 L1
                    └─ 返回 PageOut

POST/PUT/DELETE 文章成功提交后
        │
        └─ invalidate_article_caches
              ├─ SCAN article:list:v1:* → UNLINK + 清 L1
              └─ SCAN article:top:v1:*  → UNLINK + 清 L1
```

### 缓存 Key

```
article:list:v1:p1:ps{page_size}:cat:{all|category_id}
```

示例：

- 全部 Tab：`article:list:v1:p1:ps10:cat:all`
- 分类 3：`article:list:v1:p1:ps10:cat:3`

---

## 4. 模块拆分

| 路径 | 职责 |
| --- | --- |
| `app/core/config.py` | Redis / TTL / L1 容量配置 |
| `app/core/redis.py` | 连接池单例、`ping`/`close` |
| `app/core/cache.py` | 通用 `MultiLevelCache`（可复用） |
| `app/services/article.py` | 列表查询、缓存读写、失效 |
| `app/api/article.py` | HTTP 入参与写后失效触发 |
| `app/main.py` lifespan | 启动预热 Redis、退出关池 |

---

## 5. Redis 配置

与本地 Docker 一致：

```bash
docker run -d \
  --name redis \
  -p 6379:6379 \
  -v redis_data:/data \
  redis:8-alpine redis-server --requirepass qwqwqw78
```

`.env`：

```env
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=qwqwqw78
REDIS_DB=0
REDIS_MAX_CONNECTIONS=50
REDIS_SOCKET_TIMEOUT=2.0
ARTICLE_LIST_CACHE_TTL=60
ARTICLE_LIST_L1_MAXSIZE=256
```

将 `REDIS_HOST` 留空可关闭 L2，仅保留 L1（本地无 Redis 也能跑）。

---

## 6. MySQL 性能

列表 SQL 特征：

- `WHERE status = 1 [AND category_id = ?]`
- `ORDER BY is_top DESC, create_time DESC`
- `LIMIT page_size OFFSET …`
- **不选** `content`

索引：

| 索引 | 覆盖场景 |
| --- | --- |
| `idx_status_top_time(status, is_top, create_time)` | 全部 Tab |
| `idx_status_cat_top_time(status, category_id, is_top, create_time)` | 分类 Tab |

已有库执行：

```bash
mysql -u root -p blog_ai < backend-blog/sql/migrate_article_list_index.sql
```

全新库见 `backend-blog/sql/init.sql`。

连接池（既有优化保留）：`pool_pre_ping`、`pool_recycle` 对齐 `wait_timeout`、显式 `charset=utf8mb4`。

---

## 7. Milvus 性能（与列表解耦但同属读路径基建）

列表本身不走向量库；发文/编辑/删除仍异步同步 RAG 索引。本次补强：

- 集合已存在且维度正确时，启动期 **显式 `load_collection`**，避免首次检索触发全量加载抖动。
- 仍保持：HNSW（`M=16/efConstruction=128`）、标量 `INVERTED`、`radius` range search、向量存储单例。

---

## 8. 一致性说明

| 事件 | 策略 |
| --- | --- |
| 发文 / 编辑 / 删除 | 提交事务后立即整前缀失效 |
| 详情 PV（`view_count + 1`） | **不**主动失效；依赖 TTL（默认 60s）允许列表浏览量短时陈旧 |
| 多 Worker | L1 进程隔离；L2 Redis 为共享真相；失效会清本机 L1 + 远程 key |

---

## 9. 前端约定

`frontend-app` 首页 Tab 使用 `page_size: 10`，`category_id=0` 表示全部（与后端 `not category_id → all` 一致）。第 1 页请求命中多级缓存；上拉加载 `page>=2` 直查 MySQL。

---

## 10. 自测清单

1. 启动 Redis（密码 `qwqwqw78`）与后端。
2. 连续两次请求同一分类第 1 页：第二次应明显更快（L1/L2）。
3. `redis-cli -a qwqwqw78 KEYS 'article:list:v1:*'` 可见对应 key。
4. 管理端发文/改文/删文后，列表应立即反映（缓存已失效）。
5. 停止 Redis：接口仍可用（L1 或直查），不 500。
