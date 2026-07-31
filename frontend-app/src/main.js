// 应用入口: 创建 Vue 实例并挂载路由、状态管理与样式
import { createApp } from 'vue'
// 引入 Pinia 状态管理
import { createPinia } from 'pinia'
// 引入根组件
import App from './App.vue'
// 引入路由实例
import router from './router'
// 将真实 router 注入 api 层代理, 供 401 跳转使用
import { setRouter } from './api/navigate'
// 引入 Vant 全局样式(组件本身按需自动导入)
import 'vant/lib/index.css'
// 引入自定义全局样式
import './style.css'

// 注入 router, 使 api 拦截器可调用 router.push
setRouter(router)

// 创建应用实例
const app = createApp(App)
// 注册 Pinia
app.use(createPinia())
// 注册路由
app.use(router)
// 挂载到页面
app.mount('#app')
