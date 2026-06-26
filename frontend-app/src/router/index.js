// 路由配置: 使用 history 模式与懒加载提升首屏性能
import { createRouter, createWebHistory } from 'vue-router'

// 路由表定义, 页面组件均懒加载(代码分割)
const routes = [
  // 首页
  { path: '/', name: 'index', component: () => import('../views/index.vue'), meta: { title: '首页' } },
  // 文章详情, 通过 :id 传参
  { path: '/article/:id', name: 'article-detail', component: () => import('../views/article-detail.vue'), meta: { title: '文章详情' } },
  // 搜索页
  { path: '/search', name: 'search', component: () => import('../views/search.vue'), meta: { title: '搜索' } },
  // 个人中心
  { path: '/personal', name: 'personal', component: () => import('../views/personal.vue'), meta: { title: '我的' } },
  // 关于本站
  { path: '/about', name: 'about', component: () => import('../views/about.vue'), meta: { title: '关于' } }
]

// 创建路由实例
const router = createRouter({
  // 使用 HTML5 history 模式
  history: createWebHistory(),
  // 注入路由表
  routes
})

// 全局后置钩子: 根据路由元信息设置页面标题
router.afterEach((to) => {
  // 设置文档标题
  document.title = to.meta.title ? `${to.meta.title} · AI博客` : 'AI博客'
})

// 导出路由
export default router
