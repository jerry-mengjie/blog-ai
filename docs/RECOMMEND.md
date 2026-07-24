# 博客文章推荐系统文档（LangChain + LangGraph 多节点）

> 本文档由 AI 生成，覆盖架构设计、召回策略、模块拆分、接口说明与性能优化要点。

---

## 1. 技术选型

| 组件 | 选型 | 作用 |
| --- | --- | --- |
| 编排框架 | LangGraph `StateGraph`（经典 TypedDict 状态 + 条件路由） | 多节点推荐流程编排，一次编译进程内复用 |
| 向量库 | Milvus 2.6（HNSW + COSINE + 标量倒排索引） | 文章分块向量存储与画像向量召回 |
| 向量来源 | 复用 AI 问答的文章分块向量（LangChain `OpenAIEmbeddings` 写入） | 推荐不额外调用 embedding API，零新增成本 |
| 行为数据 | MySQL `tb_user_browse`（次数/时长）+ `tb_favorite`（收藏） | 用户偏好权重计算 |
| 兴趣标签 | MySQL `tb_user_tag`（复用全局标签词典，管理端可维护） | 冷启动用户的标签召回 |

---

## 2. 推荐图结构（LangGraph 多节点）

```
                        ┌─(有阅读/收藏历史)→ profile_recall ─┐
START → load_behavior ──┤                                    ├─(数量足)→ assemble → END
                        └─(无历史)────────→ tag_recall ──────┴─(不足)→ fallback_recall → assemble
```

| 节点 | 职责 |
| --- | --- |
| `load_behavior` | 读取最近 20 条浏览行为 + 全部收藏，计算各文章偏好权重 |
| `profile_recall` | 行为文章向量**加权平均**生成用户画像向量，Milvus 向量召回 |
| `tag_recall` | 无阅读历史时跳过画像，按用户兴趣标签从 MySQL 召回（兴趣内按热度排序） |
| `fallback_recall` | 召回数量不足时，依次补充 **最新 / 热门 / 收藏最多** 的已发布文章 |
| `assemble` | 有序去重截断，一次 `IN` 查询装配文章卡片并附带策略标记 |

两处条件路由（经典 `add_conditional_edges`）：

1. `load_behavior` 之后：有行为 → 画像召回；无行为（含匿名） → 标签召回。
2. 两条召回路径之后：候选数 ≥ 目标数 → 直接装配；不足 → 兜底补齐。

### 2.1 偏好权重公式

对每篇有行为的文章：

```
weight = log1p(浏览次数) + log1p(停留时长分钟) + (收藏 ? 2.0 : 0)
```

- `log1p` 压缩长尾，防止单篇高频行为垄断画像；
- 收藏是显式强偏好，给固定加成；只收藏未浏览的文章也计入画像；
- 画像向量 = Σ(文章均值向量 × weight) / Σweight。

### 2.2 三条召回路径的降级关系

| 场景 | 路径 |
| --- | --- |
| 登录 + 有浏览/收藏历史 + 向量库可用 | 画像向量召回（strategy=`profile`） |
| 登录 + 无历史 + 已绑定兴趣标签 | 标签召回（strategy=`tag`） |
| 匿名 / 无标签 / AI 未启用 / 召回不足 | 兜底：最新 → 热门 → 收藏最多（strategy=`fallback`） |

已读与已收藏的文章在所有路径中都会被排除，不重复推荐。

---

## 3. 后端模块拆分

| 文件 | 职责 |
| --- | --- |
| `app/ai/recommend.py` | LangGraph 图定义：状态、5 个节点、2 处条件路由、编译单例与 `recommend_articles` 入口 |
| `app/ai/vector_store.py` | 新增 `fetch_article_mean_vectors`（分块向量按文章聚合均值）与 `search_article_ids_by_vector`（按向量召回 + 文章级聚合取最高分） |
| `app/api/rec.py` | `GET /api/rec/articles` 薄路由，登录个性化、匿名兜底 |
| `app/api/deps.py` | 新增 `get_current_user_optional` 可选登录依赖（匿名不抛 401） |
| `app/schemas/rec.py` | 推荐卡片与列表响应模型 |
| `sql/migrate_rec.sql` | 存量库增量索引（新库 `init.sql` 已含） |

---

## 4. 接口说明

### GET `/api/rec/articles?size=6`

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

行为数据的采集接口复用既有浏览模块：`POST /api/browse/report`（次数 + 停留时长，见 [USER_BROWSE.md](USER_BROWSE.md)）；兴趣标签由管理端维护：`PUT /api/admin/user/{id}/tags`（见 [USER_ADMIN.md](USER_ADMIN.md)）。

---

## 5. 前端集成（移动端）

- `src/api/index.js`：新增 `recApi.articles`。
- `src/views/index.vue`：分类 Tabs 最左侧新增「为你推荐」Tab（在「全部」左边，Vant `van-tabs` 经典方案）；选中后展示推荐文章卡片列表（带「猜你喜欢 / 兴趣推荐 / 热门精选」策略角标），支持下拉刷新；「全部」与分类 Tab 仍为热门横滑 + 分页列表。推荐加载失败静默降级为空态，不影响其他 Tab。
- 行为采集复用既有能力：文章详情页停留时长上报（登录用户）。

---

## 6. 性能优化要点

**MySQL**

- 行为查询命中 `idx_user_last(user_id, last_browse_time)`，只取最近 20 条与权重计算所需列；
- 标签召回 `tag_id IN` 命中 `idx_tag`，`GROUP BY` 对多标签命中同文章去重；
- 兜底「最新」「热门」分别命中新增复合索引 `idx_status_create(status, create_time)`、`idx_status_view(status, view_count)`，避免 `filesort`；
- 收藏最多聚合走 `tb_favorite.idx_article` 覆盖扫描；
- 卡片装配一次 `IN` 批量查询，全程不取 `content` 大字段；
- 节点内短会话用完即还连接池，不跨节点持有连接。

**Milvus**

- 画像向量取数与召回的标量过滤（`article_id in / not in`）均命中 INVERTED 倒排索引，排除已读在引擎侧完成；
- 分块级检索 TopK 取目标文章数 4 倍缓冲（封顶 256），`ef=128` 保证召回率，文章级聚合取每篇最高分；
- 复用 AI 问答的向量集合与连接单例，推荐链路不调用 embedding API。

**LangGraph**

- 图结构固定，`compile()` 模块级单例，请求间只执行节点函数；
- 节点全异步，数据库与 Milvus IO 不阻塞事件循环。

---

## 7. 降级与容错

| 异常场景 | 行为 |
| --- | --- |
| AI 未启用（无 `AI_API_KEY`） | 画像节点直接返回空候选 → 标签/兜底接管 |
| 行为文章未被向量索引 | 画像构建失败 → 兜底接管 |
| 用户未绑定兴趣标签 | 标签节点返回空候选 → 兜底接管 |
| 库中文章不足 | 按实际数量返回，不报错 |
| 前端推荐请求失败 | 「为你推荐」Tab 展示空态，其余 Tab 正常 |
