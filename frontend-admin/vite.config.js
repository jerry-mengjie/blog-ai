// Vite 配置: Vue 插件 + Element Plus 按需自动导入 + 开发代理
import { defineConfig } from 'vite'
// Vue 单文件组件插件
import vue from '@vitejs/plugin-vue'
// API 自动导入插件(如 ElMessage 等)
import AutoImport from 'unplugin-auto-import/vite'
// 组件自动导入插件
import Components from 'unplugin-vue-components/vite'
// Element Plus 解析器
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

// 导出配置
export default defineConfig({
  // 插件列表
  plugins: [
    // 启用 Vue
    vue(),
    // 自动导入 Element Plus 相关 API
    AutoImport({ resolvers: [ElementPlusResolver()] }),
    // 自动按需导入 Element Plus 组件
    Components({ resolvers: [ElementPlusResolver()] })
  ],
  // 开发服务器
  server: {
    // 管理后台端口(与后端 CORS 白名单一致)
    port: 5174,
    // 接口代理: 按路径前缀分发到对应微服务
    // 注意顺序: Vite 按声明顺序匹配, 更具体的前缀必须写在 '/api' 之前
    proxy: {
      // AI 相关(如全量重建索引) → backend-agent
      '/api/ai': {
        // Agent 服务地址
        target: 'http://127.0.0.1:8001',
        // 修改 origin
        changeOrigin: true
      },
      // 其余管理端接口 → backend-blog
      '/api': {
        // 业务服务地址
        target: 'http://127.0.0.1:8000',
        // 修改 origin
        changeOrigin: true
      }
    }
  }
})
