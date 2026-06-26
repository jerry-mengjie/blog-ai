// 应用入口: 创建实例, 挂载路由/状态/Element Plus 图标
import { createApp } from 'vue'
// Pinia 状态管理
import { createPinia } from 'pinia'
// 根组件
import App from './App.vue'
// 路由
import router from './router'
// Element Plus 暗黑/基础样式
import 'element-plus/dist/index.css'
// 全部图标(便于直接使用)
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
// 自定义全局样式
import './style.css'

// 创建应用
const app = createApp(App)
// 全局注册所有 Element Plus 图标组件
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  // 以图标名注册
  app.component(key, component)
}
// 注册 Pinia
app.use(createPinia())
// 注册路由
app.use(router)
// 挂载
app.mount('#app')
