import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { auth } from '@/api/auth'

// meta.roles：空/缺省 = 所有已登录可见；非空 = 命中任一角色才可达（页面/路由级粒度①）。
// meta.public = 免登录可达（/forbidden 需要在未导航成功时也能渲染）。
declare module 'vue-router' {
  interface RouteMeta {
    zh?: string
    en?: string
    roles?: string[]
    public?: boolean
  }
}

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/dash' },
  { path: '/dash', name: 'dash', meta: { zh: '工作台驾驶舱', en: 'DASHBOARD' }, component: () => import('@/views/DashView.vue') },
  { path: '/bigscreen', name: 'bigscreen', meta: { zh: '经费监督大屏', en: 'SUPERVISION SCREEN', roles: ['R-LEADER', 'R-FINANCE', 'R-AUDITOR', 'R-ADMIN'] }, component: () => import('@/views/BigscreenView.vue') },
  { path: '/guide', name: 'guide', meta: { zh: '申报指南', en: 'GUIDELINES' }, component: () => import('@/views/GuideView.vue') },
  { path: '/editor', name: 'editor', meta: { zh: '申报书撰写', en: 'APPLICATION EDITOR', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] }, component: () => import('@/views/EditorView.vue') },
  { path: '/review', name: 'review', meta: { zh: '评审工作台', en: 'PEER REVIEW', roles: ['R-MANAGER', 'R-EXPERT', 'R-ETHICS', 'R-LEADER', 'R-ADMIN'] }, component: () => import('@/views/ReviewView.vue') },
  { path: '/projects', name: 'projects', meta: { zh: '我的项目', en: 'MY PROJECTS', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] }, component: () => import('@/views/ProjectsView.vue') },
  { path: '/project/:id?', name: 'project', meta: { zh: '项目详情', en: 'PROJECT DETAIL' }, component: () => import('@/views/ProjectView.vue') },
  { path: '/expense', name: 'expense', meta: { zh: '报销填单', en: 'EXPENSE FORM', roles: ['R-STAFF', 'R-MANAGER', 'R-FINANCE'] }, component: () => import('@/views/ExpenseView.vue') },
  { path: '/claim', name: 'claim', meta: { zh: '成果认领', en: 'OUTPUT CLAIM', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] }, component: () => import('@/views/ClaimView.vue') },
  { path: '/transfer', name: 'transfer', meta: { zh: '转化看板', en: 'TECH TRANSFER', roles: ['R-MANAGER', 'R-LEADER', 'R-ADMIN'] }, component: () => import('@/views/TransferView.vue') },
  { path: '/procurement', name: 'procurement', meta: { zh: '采购与合同', en: 'PROCUREMENT & CONTRACT', roles: ['R-MANAGER', 'R-FINANCE', 'R-ADMIN'] }, component: () => import('@/views/ProcurementView.vue') },
  { path: '/asset', name: 'asset', meta: { zh: '资产与耗材台账', en: 'ASSET & CONSUMABLE', roles: ['R-MANAGER', 'R-FINANCE', 'R-ADMIN'] }, component: () => import('@/views/AssetView.vue') },
  { path: '/portrait', name: 'portrait', meta: { zh: 'PI 画像', en: 'RESEARCHER PORTRAIT', roles: ['R-LEADER', 'R-MANAGER', 'R-ADMIN'] }, component: () => import('@/views/PortraitView.vue') },
  { path: '/activity', name: 'activity', meta: { zh: '学术活动', en: 'ACADEMIC ACTIVITIES', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER', 'R-AUDITOR'] }, component: () => import('@/views/ActivityView.vue') },
  // —— 模块 U 管理页（新）——
  { path: '/admin/users', name: 'admin-users', meta: { zh: '用户管理', en: 'USER ADMIN', roles: ['R-ADMIN'] }, component: () => import('@/views/admin/UsersView.vue') },
  { path: '/admin/roles', name: 'admin-roles', meta: { zh: '角色与权限', en: 'ROLES & PERMISSIONS', roles: ['R-ADMIN', 'R-AUDITOR'] }, component: () => import('@/views/admin/RolesView.vue') },
  // —— 越权兜底 ——
  { path: '/forbidden', name: 'forbidden', meta: { zh: '无访问权限', en: 'FORBIDDEN', public: true }, component: () => import('@/views/ForbiddenView.vue') },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// 路由/菜单级守卫（粒度①）：未登录→触发登录浮层(重定向到 /dash?needLogin)；越权→/forbidden。
router.beforeEach(async (to) => {
  if (to.meta.public) return true
  if (!auth.isAuthed) return { path: '/dash', query: { needLogin: '1' } }
  if (!auth.isReady) {
    try {
      await auth.loadMe()
    } catch {
      auth.logout()
      return { path: '/dash', query: { needLogin: '1' } }
    }
  }
  if (to.meta.roles && to.meta.roles.length > 0 && !auth.hasAnyRole(to.meta.roles)) {
    return { path: '/forbidden' }
  }
  return true
})

export default router
