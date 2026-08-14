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
  // 构建配置
  build: {
    // Rollup 打包选项
    rollupOptions: {
      // 产物输出规则
      output: {
        // 第三方依赖固定分包: 路由懒加载的 hash 只写进入口包, 业务页面 chunk 不再因其他页面改动而失效
        manualChunks(id) {
          // router 代理被入口与 api 层共用, 若并入入口包会让 api chunk 引用入口 hash, 故单独成包
          if (id.replace(/\\/g, '/').includes('/src/api/navigate.js')) return 'app-hooks'
          // 仅处理依赖包, 业务代码交由 Rollup 按路由自动分割
          if (!id.includes('node_modules')) return
          // Vant 组件库体积较大, 单独成包
          if (id.includes('/vant/')) return 'vendor-vant'
          // Vue 全家桶(vue/vue-router/pinia)合并为一包, 避免互相引用产生额外级联
          if (/\/(@vue|vue|vue-router|pinia)\//.test(id)) return 'vendor-vue'
          // 其余依赖统一归入 vendor
          return 'vendor'
        },
        // 入口文件命名
        entryFileNames: 'assets/js/[name]-[hash].js',
        // 分包文件命名
        chunkFileNames: 'assets/js/[name]-[hash].js',
        // 静态资源按扩展名分目录
        assetFileNames: 'assets/[ext]/[name]-[hash].[ext]'
      }
    }
  },
  // 开发服务器配置
  server: {
    // 移动端开发端口(与后端 CORS 白名单一致)
    port: 5173,
    // 接口代理: 按路径前缀分发到对应微服务, 前端仍统一请求同源 /api
    // 注意顺序: Vite 按声明顺序匹配, 更具体的前缀必须写在 '/api' 之前
    proxy: {
      // AI 问答(SSE 流式) → backend-agent
      '/api/ai': {
        // Agent 服务地址
        target: 'http://127.0.0.1:8001',
        // 修改请求头中的 origin
        changeOrigin: true
      },
      // 个性化推荐 → backend-agent
      '/api/rec': {
        // Agent 服务地址
        target: 'http://127.0.0.1:8001',
        // 修改请求头中的 origin
        changeOrigin: true
      },
      // 其余业务接口 → backend-blog
      '/api': {
        // 业务服务地址
        target: 'http://127.0.0.1:8000',
        // 修改请求头中的 origin
        changeOrigin: true
      }
    }
  }
})
