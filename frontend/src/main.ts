import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './styles/prototype.css'
import './styles/app.css'
import { installMock } from './api/mock'

// 契约 mock：默认开启，拦截 fetch 按 OpenAPI 现场造数。
// 设 VITE_USE_MOCK=false 关闭拦截，改走真实后端（dev 下 /api 透传到 :8787）。
if (import.meta.env.VITE_USE_MOCK !== 'false') {
  installMock()
}

createApp(App).use(router).mount('#app')
