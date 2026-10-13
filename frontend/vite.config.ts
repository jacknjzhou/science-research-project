import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// Node 16 兼容：Vite 4.x
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5178,
    host: '127.0.0.1',
    proxy: {
      // 前端关掉 mock（VITE_USE_MOCK=false）时，/api 透传到契约驱动后端
      '/api': { target: 'http://127.0.0.1:8787', changeOrigin: true },
    },
  },
  build: {
    target: 'es2018',
    outDir: 'dist',
  },
})
