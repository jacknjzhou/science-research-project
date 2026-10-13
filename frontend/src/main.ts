import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './styles/prototype.css'
import './styles/app.css'
import { installMock } from './api/mock'

// 契约 mock：dev 拦截 fetch，按 OpenAPI 现场造数（接真后端时注释掉此行）
installMock()

createApp(App).use(router).mount('#app')
