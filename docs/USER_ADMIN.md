# 管理端用户管理文档（兴趣标签）

> 本文档由 AI 生成。覆盖功能说明、数据模型、接口、前后端拆分与 MySQL 性能优化。

---

## 1. 功能概览

管理后台新增 **用户管理** 模块：

- **用户列表**：分页、用户名/昵称关键字、按状态筛选。
- **资料维护**：昵称、邮箱、头像、启用/禁用、是否管理员。
- **兴趣标签**：为每个用户绑定感兴趣的标签；**标签词典与文章标签共用** `tb_tag`，不另建一套标签名。

安全约束（后端强制）：

- 全部接口需管理员（`require_admin`）。
- 不能禁用当前登录账号。
- 不能取消自己的管理员权限。

---

## 2. 数据模型

### 表关系

```
tb_user ──┐
          ├── tb_user_tag ──▶ tb_tag ◀── tb_article_tag ── tb_article
```

`tb_tag` 为全局词典；文章侧与用户兴趣侧只存关联，避免两套标签名不一致。

### `tb_user_tag`

| 字段 | 说明 |
| --- | --- |
| `user_id` + `tag_id` | 联合唯一 `uk_user_tag`，防重复绑定 |
| `idx_tag(tag_id)` | 按标签反查用户 |
| `create_time` | 绑定时间 |

### 索引

| 索引 | 表 | 用途 |
| --- | --- | --- |
| `idx_status_create(status, create_time)` | `tb_user` | 管理端「状态过滤 + 时间倒序」列表 |
| `uk_user_tag(user_id, tag_id)` | `tb_user_tag` | 防重 + 按用户查标签 |
| `idx_tag(tag_id)` | `tb_user_tag` | 按标签反查 |

已有库执行：`backend-blog/sql/migrate_user_tag.sql`  
全新初始化：`backend-blog/sql/init.sql`（已包含上表与索引）。

应用启动时 `create_all` 也会创建尚不存在的表；**复合索引**建议用迁移 SQL 显式加到已有库。

---

## 3. 后端模块拆分

| 路径 | 职责 |
| --- | --- |
| `app/models/tag.py` → `UserTag` | 用户兴趣标签 ORM |
| `app/models/user.py` | `idx_status_create` |
| `app/schemas/user.py` | `AdminUserOut` / `AdminUpdateUserReq` / `AdminSetUserTagsReq` 等 |
| `app/services/user_admin.py` | 列表、详情、标签校验与全量替换（领域逻辑） |
| `app/api/admin_user.py` | 薄路由：鉴权 + 入参转发 + HTTP 错误码 |

设计原则：路由不做复杂 SQL；服务层负责批量装配与替换，避免 N+1。

### 性能要点

1. **永不在列表/详情响应中带 `password`**（显式字段组装 `AdminUserOut`）。
2. **兴趣标签一次 `IN` + JOIN 批量加载**（`map_user_tags`），禁止按用户循环查库。
3. **列表 count 与 list 分查**：`count(id)` + 分页 `ORDER BY create_time DESC`；状态过滤走 `idx_status_create`。
4. **标签全量替换**：`DELETE WHERE user_id=?` 后批量 `INSERT`，一次事务提交。
5. **分页 `page_size` 上限 100**，防止超大页拖垮。
6. **存在性校验只 `SELECT id`**，不拖全行。

---

## 4. 接口

前缀：`/api/admin/user`，鉴权：Bearer + 管理员。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/list` | 分页列表；Query：`page`、`page_size`、`keyword`、`status` |
| GET | `/detail/{user_id}` | 详情（含 `interest_tags`） |
| PUT | `/{user_id}` | 更新资料；可选字段：`nickname`/`email`/`avatar`/`status`/`is_admin` |
| PUT | `/{user_id}/tags` | 全量设置兴趣标签；Body：`{ "tag_ids": [1,2] }` |

统一响应：`{ code, message, data }`。

### 列表 `data` 形状

```json
{
  "total": 100,
  "list": [
    {
      "id": 1,
      "username": "alice",
      "nickname": "Alice",
      "avatar": "",
      "email": "a@b.c",
      "status": 1,
      "is_admin": 0,
      "create_time": "2026-07-23T10:00:00",
      "interest_tags": [{ "id": 1, "name": "Python" }]
    }
  ]
}
```

---

## 5. 前端（`frontend-admin`）

| 路径 | 说明 |
| --- | --- |
| `src/views/admin-user.vue` | 列表 + 编辑资料 + 兴趣标签多选弹窗 |
| `src/api/index.js` → `adminUserApi` | 封装四个管理端接口 |
| `src/rbac/permissions.js` | `USER_VIEW` / `USER_EDIT`（仅 `admin` 角色） |
| `src/router/index.js` | 路由 `/user`，菜单「用户管理」 |

兴趣标签下拉数据来自已有 `tagApi.list()`（与「分类标签」页同一词典）。新标签仍在「分类标签」页新增。

---

## 6. 本地验证建议

1. 执行 `migrate_user_tag.sql`（或依赖启动 `create_all` 建表后手动加索引）。
2. 管理端登录 → 侧栏「用户管理」。
3. 搜索/按状态筛选列表。
4. 编辑用户状态、管理员标识（勿对当前账号禁用/自降权）。
5. 为用户设置兴趣标签，刷新后列表展示标签名。
6. 在「分类标签」新增标签后，兴趣标签下拉应出现新项。

---

## 7. 文件清单

```
backend-blog/
  app/models/user.py              # + idx_status_create
  app/models/tag.py               # + UserTag
  app/models/__init__.py          # export UserTag
  app/schemas/user.py             # Admin* schemas
  app/services/__init__.py        # 服务包
  app/services/user_admin.py      # 领域服务
  app/api/admin_user.py           # 管理端路由
  app/main.py                     # include_router
  sql/init.sql                    # tb_user_tag + 索引
  sql/migrate_user_tag.sql        # 已有库增量
frontend-admin/
  src/views/admin-user.vue
  src/api/index.js
  src/rbac/permissions.js
  src/router/index.js
docs/USER_ADMIN.md                # 本文档
```
