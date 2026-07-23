// RBAC 权限定义: 角色 -> 权限码映射, 路由与菜单据此控制可见性
// 说明: 后端目前以 is_admin 区分超管, 此处在前端建立可扩展的角色权限体系。
// 未来后端返回 role 字段时, 仅需调整 store 中的角色推导逻辑即可。

// 权限码常量(细粒度功能点)
export const PERMISSIONS = {
  // 文章管理
  ARTICLE_VIEW: 'article:view',
  ARTICLE_EDIT: 'article:edit',
  ARTICLE_DELETE: 'article:delete',
  // 分类标签管理
  CATEGORY_VIEW: 'category:view',
  CATEGORY_EDIT: 'category:edit',
  // 用户管理(含兴趣标签)
  USER_VIEW: 'user:view',
  USER_EDIT: 'user:edit'
}

// 角色 -> 权限码列表
export const ROLE_PERMISSIONS = {
  // 超级管理员: 拥有全部权限
  admin: Object.values(PERMISSIONS),
  // 编辑: 仅文章查看与编辑(示例, 体现 RBAC 可扩展性)
  editor: [
    PERMISSIONS.ARTICLE_VIEW,
    PERMISSIONS.ARTICLE_EDIT,
    PERMISSIONS.CATEGORY_VIEW
  ]
}

// 根据角色获取其权限码集合
export function getPermissionsByRole(role) {
  // 返回对应权限, 未知角色返回空数组
  return ROLE_PERMISSIONS[role] || []
}
