import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'

// 13 屏：与 prototype 侧栏一一对应。meta.zh/en 驱动面包屑。
const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/dash' },
  { path: '/dash', name: 'dash', meta: { zh: '工作台驾驶舱', en: 'DASHBOARD' }, component: () => import('@/views/DashView.vue') },
  { path: '/bigscreen', name: 'bigscreen', meta: { zh: '经费监督大屏', en: 'SUPERVISION SCREEN' }, component: () => import('@/views/BigscreenView.vue') },
  { path: '/guide', name: 'guide', meta: { zh: '申报指南', en: 'GUIDELINES' }, component: () => import('@/views/GuideView.vue') },
  { path: '/editor', name: 'editor', meta: { zh: '申报书撰写', en: 'APPLICATION EDITOR' }, component: () => import('@/views/EditorView.vue') },
  { path: '/review', name: 'review', meta: { zh: '评审工作台', en: 'PEER REVIEW' }, component: () => import('@/views/ReviewView.vue') },
  { path: '/projects', name: 'projects', meta: { zh: '我的项目', en: 'MY PROJECTS' }, component: () => import('@/views/ProjectsView.vue') },
  { path: '/project/:id?', name: 'project', meta: { zh: '项目详情', en: 'PROJECT DETAIL' }, component: () => import('@/views/ProjectView.vue') },
  { path: '/expense', name: 'expense', meta: { zh: '报销填单', en: 'EXPENSE FORM' }, component: () => import('@/views/ExpenseView.vue') },
  { path: '/claim', name: 'claim', meta: { zh: '成果认领', en: 'OUTPUT CLAIM' }, component: () => import('@/views/ClaimView.vue') },
  { path: '/transfer', name: 'transfer', meta: { zh: '转化看板', en: 'TECH TRANSFER' }, component: () => import('@/views/TransferView.vue') },
  { path: '/procurement', name: 'procurement', meta: { zh: '采购与合同', en: 'PROCUREMENT & CONTRACT' }, component: () => import('@/views/ProcurementView.vue') },
  { path: '/asset', name: 'asset', meta: { zh: '资产与耗材台账', en: 'ASSET & CONSUMABLE' }, component: () => import('@/views/AssetView.vue') },
  { path: '/portrait', name: 'portrait', meta: { zh: 'PI 画像', en: 'RESEARCHER PORTRAIT' }, component: () => import('@/views/PortraitView.vue') },
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
})
