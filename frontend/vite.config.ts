import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // 开发代理到 Java 平台（backend），traceId 由前端生成并透传
      '/api': { target: 'http://localhost:8090', changeOrigin: true },
    },
  },
})
