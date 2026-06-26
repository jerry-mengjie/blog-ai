// Vite 配置文件: 配置 Vue 插件、Vant 组件按需自动导入与开发代理
import { defineConfig } from 'vite'
// 引入 Vue 单文件组件插件
import vue from '@vitejs/plugin-vue'
// 引入组件自动按需导入插件
import Components from 'unplugin-vue-components/vite'
// 引入 Vant 组件解析器, 实现按需引入以减小打包体积
import { VantResolver } from 'unplugin-vue-components/resolvers'

// 导出配置
export default defineConfig({
  // 注册插件
  plugins: [
    // 启用 Vue 支持
    vue(),
    // 按需自动导入 Vant 组件(无需手动 import)
    Components({ resolvers: [VantResolver()] })
  ],
  // 开发服务器配置
  server: {
    // 移动端开发端口(与后端 CORS 白名单一致)
    port: 5173,
    // 配置接口代理, 将 /api 转发到后端, 规避跨域
    proxy: {
      '/api': {
        // 后端地址
        target: 'http://127.0.0.1:8000',
        // 修改请求头中的 origin
        changeOrigin: true
      }
    }
  }
})
