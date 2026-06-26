// 路由配置 + RBAC 全局守卫
import { createRouter, createWebHistory } from 'vue-router'
// 引入权限码
import { PERMISSIONS } from '../rbac/permissions'

// 路由表
const routes = [
  // 登录页(无需鉴权)
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/admin-login.vue'),
    meta: { public: true, title: '登录' }
  },
  // 主框架布局, 内部为需鉴权的业务页
  {
    path: '/',
    component: () => import('../layout/Layout.vue'),
    // 默认重定向到文章管理
    redirect: '/article',
    children: [
      // 文章管理, 需要文章查看权限
      {
        path: 'article',
        name: 'article',
        component: () => import('../views/admin-article.vue'),
        meta: { title: '文章管理', icon: 'Document', permission: PERMISSIONS.ARTICLE_VIEW }
      },
      // 分类标签管理, 需要分类查看权限
      {
        path: 'category-tag',
        name: 'category-tag',
        component: () => import('../views/admin-category-tag.vue'),
        meta: { title: '分类标签', icon: 'CollectionTag', permission: PERMISSIONS.CATEGORY_VIEW }
      }
    ]
  },
  // 兜底: 未匹配跳转首页
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

// 创建路由实例
const router = createRouter({
  // history 模式
  history: createWebHistory(),
  // 路由表
  routes
})

// 全局前置守卫: 实现登录校验与 RBAC 权限控制
router.beforeEach(async (to) => {
  // 延迟引入 store, 避免循环依赖(此时 Pinia 已初始化)
  const { useUserStore } = await import('../store/user')
  // 获取用户 store
  const userStore = useUserStore()
  // 公开页直接放行
  if (to.meta.public) return true
  // 未登录跳转登录页
  if (!userStore.isLogin) return { path: '/login' }
  // 已登录但缺少用户信息(如刷新), 先拉取
  if (!userStore.userInfo) {
    // 捕获异常避免阻塞
    try {
      // 拉取个人信息
      await userStore.fetchInfo()
    } catch (e) {
      // 失败则回登录
      return { path: '/login' }
    }
  }
  // RBAC: 校验当前路由所需权限
  if (to.meta.permission && !userStore.hasPermission(to.meta.permission)) {
    // 无权限则跳回首页(或可改为 403 页)
    return { path: '/' }
  }
  // 通过校验
  return true
})

// 设置标题
router.afterEach((to) => {
  // 更新文档标题
  document.title = to.meta.title ? `${to.meta.title} · 博客后台` : '博客后台'
})

// 导出
export default router
