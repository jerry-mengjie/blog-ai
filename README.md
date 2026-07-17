# AI 博客系统 (blog_ai)

一个前后端分离的全栈博客系统，包含**后端 API**、**移动端**与**管理后台**三个独立工程。

> 本文档由 AI 生成，覆盖架构设计、目录结构、启动步骤、数据库设计、接口清单与性能优化要点。

---

## 1. 技术栈

| 模块 | 目录 | 技术选型 | 说明 |
| --- | --- | --- | --- |
| 后端 | `backend-blog` | FastAPI + SQLAlchemy 2.0(async) + aiomysql + MySQL 9.7 + JWT | uv 管理依赖，异步高性能 |
| AI 问答 | `backend-blog/app/ai` | Milvus 2.6 + OpenAI 兼容 API(百炼) + RAG + SSE | 文章底部智能问答，详见 [docs/AI.md](docs/AI.md) |
| 移动端 | `frontend-app` | Vue3 + Vite + Vant 4 + Pinia + Vue Router + Axios | 面向 C 端用户 |
| 管理后台 | `frontend-admin` | Vue3 + Vite + Element Plus + Pinia + Vue Router + Axios | 含 RBAC 权限控制 |

---

## 2. 系统架构

```
                ┌─────────────────┐        ┌──────────────────┐
  移动端用户 ──▶ │ frontend-app    │        │ frontend-admin   │ ◀── 管理员
                │ (Vue3 + Vant)   │        │ (Vue3 + Element) │
                └────────┬────────┘        └────────┬─────────┘
                         │  HTTP / JSON (RESTful)    │
                         └────────────┬─────────────┘
                                      ▼
                          ┌────────────────────────┐
                          │     backend-blog       │
                          │  FastAPI (async)       │
                          │  JWT 鉴权 + RBAC       │
                          │  RAG 问答 (SSE 流式)    │
                          └─────┬─────────┬────────┘
              SQLAlchemy(async) │         │ 向量检索(gRPC) / LLM(OpenAI 兼容)
                                ▼         ▼
                  ┌──────────────────┐  ┌──────────────────────┐
                  │ MySQL 9.7        │  │ Milvus 向量库         │
                  │ 「blog_ai」       │  │ 文章分块向量 + 过滤索引 │
                  │ 7 张表 + 索引优化 │  └──────────────────────┘
                  └──────────────────┘
```

---

## 3. 快速开始

### 3.1 数据库

```bash
# 登录 MySQL (用户名 root, 密码 qwqwqw78)
mysql -uroot -pqwqwqw78 < backend-blog/sql/init.sql
```

> 库名为 `blog_ai`（含连字符，SQL 中已用反引号处理）。默认创建管理员 `admin / admin123`。
> 后端启动时也会通过 SQLAlchemy 自动建表（`create_all`），但**推荐用上面的 SQL 脚本**以获得完整索引与种子数据。

### 3.2 Milvus 向量库（AI 问答功能需要）

使用官方 Docker Compose standalone 编排（仓库已保留一份 `deploy/milvus/docker-compose.yml`）：

```bash
wget https://gitee.com/milvus-io/milvus/raw/v2.6.4/deployments/docker/standalone/docker-compose.yml -O docker-compose.yml
docker compose up -d
```

> AI 问答还需在 `backend-blog/.env` 中填入 `AI_API_KEY`（阿里云百炼）。留空则 AI 功能自动关闭，其余功能不受影响。存量文章需管理员调用 `POST /api/ai/reindex` 建一次索引。详见 [docs/AI.md](docs/AI.md)。

### 3.3 后端 backend-blog

```bash
cd backend-blog
uv sync                 # 创建虚拟环境并安装依赖
uv run uvicorn app.main:app --reload --port 8000
```

启动后访问交互式文档：<http://127.0.0.1:8000/docs>

### 3.4 移动端 frontend-app

```bash
cd frontend-app
npm install
npm run dev             # 默认 http://localhost:5173
```

### 3.5 管理后台 frontend-admin

```bash
cd frontend-admin
npm install
npm run dev             # 默认 http://localhost:5174
```

> 两个前端均通过 Vite 代理把 `/api` 转发到后端 `127.0.0.1:8000`，无需额外配置跨域；后端 `.env` 的 `CORS_ORIGINS` 也已放行 5173/5174。

---

## 4. 数据库设计（7 张表）

命名规范：表名 `tb_` 前缀。详见 [`backend-blog/sql/init.sql`](backend-blog/sql/init.sql)。

| 表名 | 说明 | 关键索引 |
| --- | --- | --- |
| `tb_user` | 用户表 | 唯一索引 `username`，普通索引 `email` |
| `tb_article` | 文章表 | 复合索引 `(status, is_top, create_time)`、`user_id`、`category_id`、标题前缀索引 |
| `tb_category` | 分类表 | 唯一 `name`、索引 `sort` |
| `tb_tag` | 标签表 | 唯一 `name` |
| `tb_article_tag` | 文章标签中间表 | 唯一 `(article_id, tag_id)`、索引 `tag_id` |
| `tb_comment` | 评论表 | 复合索引 `(article_id, create_time)`、索引 `user_id` |
| `tb_favorite` | 收藏表 | 唯一 `(user_id, article_id)`、索引 `article_id` |

---

## 5. 接口清单（6 模块 / 24 个）

| 模块 | 方法 | 路径 | 说明 | 鉴权 |
| --- | --- | --- | --- | --- |
| 用户 | POST | `/api/user/register` | 注册 | 否 |
| 用户 | POST | `/api/user/login` | 登录 | 否 |
| 用户 | GET | `/api/user/info` | 个人信息 | 是 |
| 用户 | PUT | `/api/user/info` | 修改资料 | 是 |
| 用户 | POST | `/api/user/logout` | 退出登录 | 是 |
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
| AI | GET | `/api/ai/config` | AI 开关 + 预设问题 | 否 |
| AI | POST | `/api/ai/ask` | 文章问答(SSE 流式) | 否(限流) |
| AI | POST | `/api/ai/reindex` | 全量重建向量索引 | 管理员 |

统一响应格式：

```json
{ "code": 0, "message": "success", "data": {} }
```

`code = 0` 为成功；非 0（通常等于 HTTP 状态码）为业务/系统错误。

---

## 6. 前端页面

### 移动端（5 页）
- `index.vue` 首页：文章聚合 + 分类导航 + 热门推荐 + 上拉加载/下拉刷新
- `article-detail.vue` 文章详情：正文 + AI 问答（`components/ai-ask.vue`）+ 评论区 + 收藏
- `search.vue` 搜索页
- `personal.vue` 个人中心：登录/注册 + 资料修改 + 我的收藏
- `about.vue` 关于本站

### 管理后台（3 页）
- `admin-login.vue` 登录（仅管理员可进入）
- `admin-article.vue` 文章管理（增 / 改 / 删 / 搜索 / 分页）
- `admin-category-tag.vue` 分类标签管理

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
- 浏览量自增使用对象级原子更新。

**后端层**
- 全异步（FastAPI + async SQLAlchemy + aiomysql），高并发吞吐。
- 连接池：`pool_size=20 / max_overflow=10 / pool_pre_ping / pool_recycle=28000`，与 MySQL 9.7 `wait_timeout` 对齐。
- JWT 无状态鉴权，水平扩展友好。

**前端层**
- 路由懒加载（代码分割），首屏更快。
- 组件**按需自动导入**（Vant / Element Plus），减小打包体积。
- 移动端首页 `keep-alive` 缓存 + 分页加载。

**AI / 向量层**（详见 [docs/AI.md](docs/AI.md)）
- Milvus 全异步客户端(gRPC) + HNSW 调优 + 标量倒排索引过滤 + range search 引擎侧过滤低分结果。
- 向量索引通过 `BackgroundTasks` 响应后异步同步，发文接口零阻塞。
- 问答接口只查必要列不加载正文大字段；单 IP 滑动窗口限流防刷。

---

## 9. 目录结构

```
blog_ai/
├── README.md                 # 本文档
├── docs/AI.md                # AI 问答功能文档(RAG 架构/接口/性能优化)
├── deploy/milvus/            # Milvus standalone 官方 Docker Compose 编排
├── backend-blog/             # 后端
│   ├── pyproject.toml        # uv 依赖
│   ├── .env                  # 环境配置(DB/JWT/CORS/AI/Milvus)
│   ├── sql/init.sql          # 建表 + 索引 + 种子数据
│   └── app/
│       ├── main.py           # 应用入口(路由/中间件/异常)
│       ├── core/             # 配置/数据库/安全/统一响应
│       ├── models/           # SQLAlchemy 模型
│       ├── schemas/          # Pydantic 模型
│       ├── api/              # 路由 + 依赖(鉴权/RBAC)
│       └── ai/               # RAG: LLM 客户端/分块/向量库/索引同步/检索问答
├── frontend-app/             # 移动端 (Vue3 + Vant)
│   └── src/{api,components,store,router,views}
└── frontend-admin/           # 管理后台 (Vue3 + Element Plus)
    └── src/{api,store,router,rbac,layout,views}
```
