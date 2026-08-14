# 博客文章推荐系统文档（backend-agent LangGraph 多节点）

> 本文档由 AI 生成。覆盖技术选型、图结构、服务边界、L1/L2 多级缓存、接口说明、性能优化与降级策略。
> 服务边界与内部接口契约见 [ARCHITECTURE.md](ARCHITECTURE.md)。

---

## 1. 技术选型

| 组件 | 选型 | 所在服务 | 作用 |
| --- | --- | --- | --- |
| 编排框架 | LangGraph `StateGraph`（TypedDict 状态 + 条件路由） | agent | 多路召回流程编排，一次编译进程内复用 |
| 接口缓存 | `MultiLevelCache`（L1 内存 + L2 Redis） | agent | 命中时整张图与全部下游调用一起跳过 |
| 画像召回 | LlamaIndex + Milvus（HNSW + COSINE + 倒排索引） | rag | 偏好向量合成与向量近邻召回 |
| 向量来源 | 复用 AI 问答的文章分块向量 | rag | 推荐不额外调用 embedding API，零新增成本 |
| 行为数据 | MySQL `tb_user_browse`（次数/时长）+ `tb_favorite`（收藏） | blog | 偏好权重计算的原始数据 |
| 兴趣标签 | MySQL `tb_user_tag`（复用全局标签词典，管理端维护） | blog | 冷启动用户的标签召回 |

**职责划分**：推荐「算法」在 agent（权重公式、召回优先级、去重截断），推荐「数据」在下游（SQL 在 blog，向量计算在 rag）。换算法只改 `app/graphs/recommend.py`，换存储只改下游。

---

## 2. 推荐图结构（LangGraph 多节点）

```
                        ┌─(有阅读/收藏历史)→ profile_recall ─┐
START → load_behavior ──┤                                    ├─(数量足)→ assemble → END
                        └─(无历史)────────→ tag_recall ──────┴─(不足)→ fallback_recall → assemble
```

| 节点 | 职责 | 下游调用 |
| --- | --- | --- |
| `load_behavior` | 取最近 20 条浏览 + 全部收藏，计算各文章偏好权重、汇总排除集 | `GET /internal/rec/behavior/{user_id}` |
| `profile_recall` | 把「文章 + 权重」交给检索服务合成画像向量并做近邻召回 | `POST /rag/similar` |
| `tag_recall` | 无阅读历史时按兴趣标签召回（联表与热度排序在 blog 侧） | `POST /internal/rec/recall/tags` |
| `fallback_recall` | 召回不足时补齐 **最新 / 热门 / 收藏最多** | `POST /internal/rec/recall/fallback` |
| `assemble` | 有序去重截断，一次批量取卡片字段并附策略标记 | `POST /internal/rec/cards` |

两处条件路由（经典 `add_conditional_edges`）：

1. `load_behavior` 之后：有行为 → 画像召回；无行为（含匿名） → 标签召回。
2. 两条召回路径之后：候选数 ≥ 目标数 → 直接装配；不足 → 兜底补齐。

图的深度决定最坏情况下的串行 RTT 数：**每个节点只发一次网络请求，最多 4 次**。

### 2.1 偏好权重公式（agent 侧计算）

对每篇有行为的文章：

```
weight = log1p(浏览次数) + log1p(停留时长分钟) + (收藏 ? 2.0 : 0)
```

- `log1p` 压缩长尾，防止单篇高频行为垄断画像；
- 收藏是显式强偏好，给固定加成；只收藏未浏览的文章也计入画像；
- 画像向量 = Σ(文章代表向量 × weight) / Σweight（在 rag 侧用 float32 矩阵一次算完）；
- 文章代表向量 = 该文章开头 3 个分块向量的均值（只取头部，回传量压到千分之一级别）。

### 2.2 三条召回路径的降级关系

| 场景 | 路径 |
| --- | --- |
| 登录 + 有浏览/收藏历史 + 检索服务可用 | 画像向量召回（strategy=`profile`） |
| 登录 + 无历史 + 已绑定兴趣标签 | 标签召回（strategy=`tag`） |
| 匿名 / 无标签 / AI 未启用 / 召回不足 | 兜底：最新 → 热门 → 收藏最多（strategy=`fallback`） |

已读与已收藏的文章在所有路径中都会被排除，不重复推荐。

---

## 3. 模块拆分

### backend-agent

| 文件 | 职责 |
| --- | --- |
| `app/graphs/recommend.py` | 图定义：`RecState`、5 个节点、2 处条件路由、编译单例、`recommend_articles` 入口 |
| `app/services/recommend.py` | 推荐缓存门面：匿名/登录分 key、L1/L2 读写、前缀失效 |
| `app/core/cache.py` | 多级缓存实现：TTL 抖动、单飞锁（引用计数回收）、`SCAN + UNLINK` 前缀失效 |
| `app/api/recommend.py` | `GET /api/rec/articles` 薄路由 + `POST /internal/rec/invalidate` 失效接口 |
| `app/api/deps.py` | `current_user_id_optional` 可选登录依赖（匿名不抛 401） |
| `app/schemas/recommend.py` | 推荐卡片与列表响应模型 |

### backend-blog

| 文件 | 职责 |
| --- | --- |
| `app/services/recall.py` | 召回取数 SQL：行为、标签召回、兜底召回、卡片批量装配（**只取数不含策略**） |
| `app/api/internal_rec.py` | 4 个内部接口，供推荐图调用 |
| `app/clients/agent.py` | 文章增删改后通知 agent 失效推荐缓存（`BackgroundTasks`，失败仅记日志） |

### backend-rag

| 文件 | 职责 |
| --- | --- |
| `app/rag/profile.py` | 代表向量取数、加权画像向量合成、近邻召回 + 文章级聚合取最高分 |
| `app/api/retrieve.py` | `POST /rag/similar` 路由 |

---

## 4. 接口说明

### GET `/api/rec/articles?size=6`（backend-agent，8001）

- 鉴权：可选。带有效 JWT 走个性化，匿名自动兜底。
- 参数：`size` 期望数量（默认 6，上限 20）。
- 响应：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "list": [
      {
        "id": 8,
        "title": "LangGraph经典例子",
        "cover": "https://...",
        "summary": "...",
        "view_count": 39,
        "strategy": "profile"
      }
    ]
  }
}
```

`strategy` 取值：`profile`（画像向量）/ `tag`（兴趣标签）/ `fallback`（兜底），前端映射为「猜你喜欢 / 兴趣推荐 / 热门精选」角标。

行为数据的采集接口仍在 blog：`POST /api/browse/report`（次数 + 停留时长，见 [USER_BROWSE.md](USER_BROWSE.md)）；兴趣标签由管理端维护：`PUT /api/admin/user/{id}/tags`（见 [USER_ADMIN.md](USER_ADMIN.md)）。

### POST `/internal/rec/invalidate`（backend-agent，需 `X-Internal-Token`）

由 `backend-blog` 在文章增删改后调用。**为什么由 blog 反向通知 agent**：推荐结果缓存在 agent（它是产出方），但「什么时候该失效」只有 blog 知道（文章的增删改都可能让推荐里出现已删除或已下架的文章）。通知走 `BackgroundTasks`，失败只是多陈旧几十秒（TTL 30s 自然收敛），不影响文章接口。

### 4.1 多级缓存 Key

- 匿名：`rec:articles:v1:anon:size:{size}`
- 登录：`rec:articles:v1:user:{user_id}:size:{size}`

命中链路：

```text
L1 内存 → L2 Redis → LangGraph 推荐图 → (blog 内部接口 / rag 画像召回)
```

设计要点：

- 匿名推荐本质是共享热点，聚合为单 key，命中率最高；
- 登录推荐受浏览/收藏/标签影响更频繁，按 `user_id` 分 key 并使用短 TTL（30s）；
- 文章增删改统一清空推荐缓存前缀，避免返回已删除、已下架或内容已变更的文章；
- 缓存在 API 边界层，命中时**跳过整张图**，也就跳过了对 blog 与 rag 的全部网络调用。

---

## 5. 前端集成（移动端）

- `src/api/index.js`：`recApi.articles` 请求路径不变（`/api/rec/articles`），由 Vite 代理指向 8001。
- `src/views/index.vue`：分类 Tabs 最左侧「为你推荐」Tab（Vant `van-tabs` 经典方案），展示带策略角标的推荐卡片，支持下拉刷新；加载失败静默降级为空态，不影响其他 Tab。
- 行为采集复用既有能力：文章详情页停留时长上报（登录用户）。

---

## 6. 性能优化要点

**MySQL（blog 侧）**

- 行为查询命中 `idx_user_last(user_id, last_browse_time)`，只取最近 20 条与权重计算所需列；
- 标签召回 `tag_id IN` 命中 `idx_tag`，`GROUP BY` 对多标签命中同文章去重；
- 兜底「最新」「热门」分别命中 `idx_status_create(status, create_time)`、`idx_status_view(status, view_count)`，避免 `filesort`；
- 收藏最多聚合走 `tb_favorite.idx_article`；
- 卡片装配一次 `IN` 批量查询，全程不取 `content` 大字段；
- 每个内部接口一个短会话，用完即还连接池。

**Redis / 多级缓存（agent 侧）**

- API 边界层优先命中 `MultiLevelCache`，命中时零下游调用；
- L1 进程内字典 + TTL，命中零网络；L2 `redis.asyncio` + 连接池 + `SET EX`，跨副本共享；
- L2 TTL 附加 0~20% 随机抖动防雪崩；
- 同 key 单飞锁防击穿，锁表用引用计数在归零时回收（用户维度 key 不会让锁表无限增长）；
- 前缀失效用 `SCAN` + 批量 `UNLINK`，不阻塞 Redis；
- Redis 异常一律 fail-open 回源，只记告警。

**Milvus（rag 侧）**

- 画像取数与召回的标量过滤（`article_id in / not in`、`chunk_index <`）均命中 INVERTED 倒排索引，排除已读在引擎侧完成；
- 每篇行为文章只取开头 3 个分块作代表向量，`limit` 精确等于「文章数 × 3」；
- 分块级检索 TopK 取目标篇数 4 倍缓冲（封顶 256），`ef` 不低于候选数保证召回率，文章级聚合取每篇最高分；
- 复用问答的向量集合与连接单例，推荐链路**不调用 embedding API**。

**LangGraph / 服务间调用**

- 图结构固定，`compile()` 模块级单例，请求间只执行节点函数；
- 每节点一次网络请求，最坏 4 次串行 RTT；
- 服务间统一进程级 `httpx.AsyncClient`（keep-alive + 连接池），关闭时显式释放；
- 节点全异步，IO 不阻塞事件循环。

---

## 7. 降级与容错

| 异常场景 | 行为 |
| --- | --- |
| 未配置 `AI_API_KEY` / rag 不可达 | 画像节点返回空候选 → 标签/兜底接管 |
| 行为文章未被向量索引 | 画像构建失败 → 兜底接管 |
| 用户未绑定兴趣标签 | 标签节点返回空候选 → 兜底接管 |
| blog 内部接口不可达 | 行为/标签/兜底节点逐一降级，装配失败则返回空列表 |
| Redis 不可达 | 缓存 fail-open，每次请求执行整张图 |
| 库中文章不足 | 按实际数量返回，不报错 |
| 前端推荐请求失败 | 「为你推荐」Tab 展示空态，其余 Tab 正常 |

## 8. 一致性与失效策略

| 事件 | 策略 |
| --- | --- |
| 文章新增 / 编辑 / 删除 | blog 调 agent 的 `/internal/rec/invalidate` 清空推荐缓存前缀 |
| 浏览 / 收藏 / 用户兴趣标签变化 | 不主动删 key，依赖短 TTL（30s）自然收敛 |
| 失效通知失败 | 仅记日志，退化为 TTL 收敛 |
| 匿名高并发 | 匿名共享 key + 单飞锁 |
| 多副本 | L1 进程隔离；Redis 为共享真相 |
