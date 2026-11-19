import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { auth } from '@/api/auth'

// meta.roles：空/缺省 = 所有已登录可见；非空 = 命中任一角色才可达（页面/路由级粒度①）。
// 注意：本表已收敛为 fallback-only 灾备数据（矩阵加载失败时 canSeePage 退回此表）；
// 在线配置的真源是后端 sys_page_grant（PRD 2.9，管理员在「角色与权限」页编辑）。
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
  // —— M1-a A2 借款管理（F-23）：R-STAFF 不可见（仅 manager/finance 发起与审批）——
  { path: '/loan', name: 'loan', meta: { zh: '借款管理', en: 'LOAN', roles: ['R-MANAGER', 'R-FINANCE'] }, component: () => import('@/views/LoanView.vue') },
  { path: '/funding-config', name: 'funding-config', meta: { zh: '经费配置', en: 'FUNDING CONFIG', roles: ['R-MANAGER', 'R-FINANCE'] }, component: () => import('@/views/FundingConfigView.vue') },
  // —— M1-b：成本池核算（A4/F-20）与项目决算（F-17），policy.csv :414-440 → 三角色可见 ——
  { path: '/funding/cost-pool', name: 'funding-cost-pool', meta: { zh: '成本池核算', en: 'COST POOL', roles: ['R-MANAGER', 'R-FINANCE', 'R-LEADER'] }, component: () => import('@/views/FundingCostPoolView.vue') },
  { path: '/funding/settle', name: 'funding-settle', meta: { zh: '项目决算', en: 'SETTLEMENT', roles: ['R-MANAGER', 'R-FINANCE', 'R-LEADER'] }, component: () => import('@/views/FundingSettleView.vue') },
  // —— M1-c：拨款管理（A7/F-11/F-13）与到账认领（A8/F-05/F-06/F-15），policy.csv :443-458 → 三角色可见 ——
  { path: '/funding/disburse', name: 'funding-disburse', meta: { zh: '拨款管理', en: 'DISBURSEMENT', roles: ['R-MANAGER', 'R-FINANCE', 'R-LEADER'] }, component: () => import('@/views/FundingDisburseView.vue') },
  { path: '/funding/income', name: 'funding-income', meta: { zh: '到账认领', en: 'INCOME CLAIM', roles: ['R-MANAGER', 'R-FINANCE', 'R-LEADER'] }, component: () => import('@/views/FundingIncomeView.vue') },
  { path: '/claim', name: 'claim', meta: { zh: '成果认领', en: 'OUTPUT CLAIM', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] }, component: () => import('@/views/ClaimView.vue') },
  { path: '/output', name: 'output', meta: { zh: '成果台账', en: 'OUTPUT LEDGER', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] }, component: () => import('@/views/OutputView.vue') },
  { path: '/transfer', name: 'transfer', meta: { zh: '转化看板', en: 'TECH TRANSFER', roles: ['R-MANAGER', 'R-LEADER', 'R-ADMIN'] }, component: () => import('@/views/TransferView.vue') },
  { path: '/procurement', name: 'procurement', meta: { zh: '采购与合同', en: 'PROCUREMENT & CONTRACT', roles: ['R-MANAGER', 'R-FINANCE', 'R-ADMIN'] }, component: () => import('@/views/ProcurementView.vue') },
  { path: '/asset', name: 'asset', meta: { zh: '资产与耗材台账', en: 'ASSET & CONSUMABLE', roles: ['R-MANAGER', 'R-FINANCE', 'R-ADMIN'] }, component: () => import('@/views/AssetView.vue') },
  { path: '/portrait', name: 'portrait', meta: { zh: 'PI 画像', en: 'RESEARCHER PORTRAIT', roles: ['R-LEADER', 'R-MANAGER', 'R-ADMIN'] }, component: () => import('@/views/PortraitView.vue') },
  { path: '/activity', name: 'activity', meta: { zh: '学术活动', en: 'ACADEMIC ACTIVITIES', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER', 'R-AUDITOR'] }, component: () => import('@/views/ActivityView.vue') },
  { path: '/performance', name: 'performance', meta: { zh: '科研绩效评价', en: 'PERFORMANCE', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER', 'R-FINANCE', 'R-AUDITOR'] }, component: () => import('@/views/PerformanceView.vue') },
  // —— 模块 N 专家与评审（域 N，勿复用 /review 名）——
  { path: '/expert-review', name: 'expert-review', meta: { zh: '专家与评审', en: 'EXPERT REVIEW', roles: ['R-EXPERT', 'R-MANAGER', 'R-LEADER', 'R-AUDITOR'] }, component: () => import('@/views/ExpertReviewView.vue') },
  // —— 模块 O 科研档案管理（域 O）——
  { path: '/archive', name: 'archive', meta: { zh: '科研档案', en: 'ARCHIVE', roles: ['R-ADMIN', 'R-MANAGER', 'R-AUDITOR'] }, component: () => import('@/views/ArchiveView.vue') },
  // —— 模块 U 管理页（新）——
  { path: '/admin/users', name: 'admin-users', meta: { zh: '用户管理', en: 'USER ADMIN', roles: ['R-ADMIN'] }, component: () => import('@/views/admin/UsersView.vue') },
  { path: '/admin/roles', name: 'admin-roles', meta: { zh: '角色与权限', en: 'ROLES & PERMISSIONS', roles: ['R-ADMIN', 'R-AUDITOR'] }, component: () => import('@/views/admin/RolesView.vue') },
  { path: '/admin/dicts', name: 'admin-dicts', meta: { zh: '数据字典', en: 'DICTIONARIES', roles: ['R-ADMIN'] }, component: () => import('@/views/admin/DictsView.vue') },
  // —— M2-a：外部机构注册（公开）/ 机构门户（R-PARTNER）/ 机构审核台（R-MANAGER）——
  { path: '/register', name: 'register', meta: { zh: '外部机构注册', en: 'PARTNER SIGN-UP', public: true }, component: () => import('@/views/RegisterView.vue') },
  { path: '/portal', name: 'portal', meta: { zh: '机构门户', en: 'PARTNER PORTAL', roles: ['R-PARTNER'] }, component: () => import('@/views/PortalView.vue') },
  { path: '/admin/partner-orgs', name: 'admin-partner-orgs', meta: { zh: '机构资质审核', en: 'PARTNER ACCREDITATION', roles: ['R-MANAGER', 'R-ADMIN'] }, component: () => import('@/views/admin/PartnerOrgsView.vue') },
  // —— M2-b：开放课题全流程（门户侧 4 页 + 管理端指南建议审核）——
  { path: '/portal/applications', name: 'portal-applications', meta: { zh: '我的申报', en: 'MY APPLICATIONS', roles: ['R-PARTNER'] }, component: () => import('@/views/portal/ApplicationsView.vue') },
  { path: '/portal/guide-suggest', name: 'portal-guide-suggest', meta: { zh: '指南建议', en: 'GUIDE SUGGESTION', roles: ['R-PARTNER'] }, component: () => import('@/views/portal/GuideSuggestView.vue') },
  { path: '/portal/task-book', name: 'portal-task-book', meta: { zh: '任务书签订', en: 'TASK BOOK', roles: ['R-PARTNER', 'R-MANAGER', 'R-LEADER'] }, component: () => import('@/views/portal/TaskBookView.vue') },
  { path: '/portal/expert-apply', name: 'portal-expert-apply', meta: { zh: '专家申请', en: 'EXPERT APPLY', roles: ['R-PARTNER', 'R-EXPERT', 'R-STAFF'] }, component: () => import('@/views/portal/ExpertApplyView.vue') },
  { path: '/portal/expert', name: 'portal-expert', meta: { zh: '专家门户', en: 'EXPERT PORTAL', roles: ['R-EXPERT'] }, component: () => import('@/views/portal/ExpertPortalView.vue') },
  { path: '/portal/supplier', name: 'portal-supplier', meta: { zh: '供应商门户', en: 'SUPPLIER PORTAL', roles: ['R-PARTNER'] }, component: () => import('@/views/portal/SupplierPortalView.vue') },
  { path: '/portal/project-report', name: 'portal-project-report', meta: { zh: '汇报与验收', en: 'REPORT & ACCEPT', roles: ['R-PARTNER', 'R-STAFF', 'R-MANAGER'] }, component: () => import('@/views/portal/ProjectReportView.vue') },
  { path: '/admin/expert-applications', name: 'admin-expert-applications', meta: { zh: '专家申请审核', en: 'EXPERT REVIEW', roles: ['R-MANAGER', 'R-ADMIN'] }, component: () => import('@/views/admin/ExpertApplicationsView.vue') },
  { path: '/admin/guide-suggestions', name: 'admin-guide-suggestions', meta: { zh: '指南建议审核', en: 'GUIDE SUGGESTION REVIEW', roles: ['R-MANAGER', 'R-ADMIN'] }, component: () => import('@/views/admin/GuideSuggestionsView.vue') },
  // —— 越权兜底 ——
  { path: '/forbidden', name: 'forbidden', meta: { zh: '无访问权限', en: 'FORBIDDEN', public: true }, component: () => import('@/views/ForbiddenView.vue') },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// 路由/菜单级守卫（粒度①）：未登录→触发登录浮层(重定向到 /dash?needLogin)；越权→/forbidden。
// 注意：未登录时目标已经是 /dash?needLogin=1 必须直接放行，否则守卫返回相同重定向
// 会造成 vue-router 无限导航循环（主线程被微任务链占满 → 页面永久空白）。
router.beforeEach(async (to) => {
  if (to.meta.public) return true
  if (!auth.isAuthed) {
    if (to.path === '/dash' && to.query.needLogin === '1') return true
    return { path: '/dash', query: { needLogin: '1' } }
  }
  if (!auth.isReady) {
    try {
      await auth.loadMe()
    } catch {
      auth.logout()
      return { path: '/dash', query: { needLogin: '1' } }
    }
  }
  // 页面可见性统一判定（PRD 2.9）：在线矩阵为唯一权威（可授可收），
  // grants 不可用时 canSeePage 内部退回静态 meta.roles fallback——
  // 不在此处再叠加静态 meta.roles 硬门禁，否则矩阵授予的权限会被旧表拦下，
  // 出现「菜单在（矩阵判定）、点进去 403（静态判定）」的双镜像错位。
  if (!auth.canSeePage(to.name as string, to.meta.roles)) {
    return { path: '/forbidden' }
  }
  return true
})

export default router
