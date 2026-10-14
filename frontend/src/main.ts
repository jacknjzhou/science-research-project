import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { auth } from './api/auth'
import { perm } from './directives/perm'
import './styles/prototype.css'
import './styles/app.css'

// 契约 mock：默认开启，拦截 fetch 按 OpenAPI 现场造数。
// 设 VITE_USE_MOCK=false 关闭拦截，改走真实后端（dev 下 /api 透传到 :8787）。
// 用「条件动态 import」而非顶层静态 import：mock 及其 faker/generator/契约 yaml 依赖
// 被 Vite 拆成独立异步分块，生产构建关闭 mock 时该分块根本不会被下载，主包显著瘦身。
auth.init() // 同步恢复令牌 + 注册认证 provider（必须先于挂载 router/app）
async function bootstrap() {
  if (import.meta.env.VITE_USE_MOCK !== 'false') {
    const { installMock } = await import('./api/mock')
    installMock()   // 必须在挂载前安装，确保首屏请求已被拦截
  }
  createApp(App).use(router).directive('perm', perm).mount('#app')
}

bootstrap()
