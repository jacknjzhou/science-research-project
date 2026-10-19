<script setup lang="ts">
import { ref, computed, reactive, watch, onBeforeUnmount } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { auth } from '@/api/auth'
import { api, list } from '@/api/client'

const router = useRouter()
const route = useRoute()

// —— 通知中心（NF）铃铛：unread-count 30s 轮询 + 收件箱面板（T20：待办/消息/预警三 tab）——
interface Notification { id: number; typ: string; title: string; content: string | null; biz_ref: string | null; read: boolean; created_at: string }
const unread = ref(0)
const notifOpen = ref(false)
const notifList = ref<Notification[]>([])
const notifLoading = ref(false)
const notifTab = ref<'todo' | 'msg' | 'warn'>('todo')
const taskSummary = ref<{ todo: number; message: number; warning: number }>({ todo: 0, message: 0, warning: 0 })
const taskList = ref<Array<{ kind: string; id: number; title: string; content?: string | null; amount?: string; code?: string | null; created_at?: string }>>([])
let pollTimer: number | undefined

async function loadUnread() {
  if (!auth.isAuthed) return
  try {
    const d = await api.get<{ unread: number }>('/notifications/unread-count')
    unread.value = d?.unread ?? 0
  } catch { /* 静默：铃铛轮询失败不打扰 */ }
}
async function loadSummary() {
  try {
    const d = await api.get<{ todo: number; message: number; warning: number }>('/tasks/summary')
    if (d) taskSummary.value = d
  } catch { /* ignore */ }
}
async function loadTab() {
  notifLoading.value = true
  try {
    if (notifTab.value === 'todo') {
      const d = await api.get<{ list: typeof taskList.value }>('/tasks', { size: 20 })
      taskList.value = d?.list ?? []
    } else if (notifTab.value === 'msg') {
      const d = await api.get<{ list: Notification[] }>('/messages', { page: 1, size: 10 })
      notifList.value = d?.list ?? []
    } else {
      const d = await api.get<{ list: Notification[] }>('/notifications', { page: 1, size: 10, typ: 'WARNING' })
      notifList.value = d?.list ?? []
    }
  } catch { taskList.value = []; notifList.value = [] } finally { notifLoading.value = false }
}
async function openNotif() {
  notifOpen.value = !notifOpen.value
  if (!notifOpen.value || !auth.isAuthed) return
  loadSummary()
  loadTab()
}
function switchTab(t: 'todo' | 'msg' | 'warn') {
  notifTab.value = t
  loadTab()
}
async function markRead(n: Notification) {
  if (n.read) return
  try {
    await api.post(`/notifications/${n.id}/read`)
    n.read = true
    unread.value = Math.max(0, unread.value - 1)
  } catch { /* ignore */ }
}
async function markAllRead() {
  try {
    await api.post('/notifications/read-all')
    notifList.value.forEach((n) => (n.read = true))
    unread.value = 0
  } catch { /* ignore */ }
}
const TYP_META: Record<string, { ic: string; cls: string }> = {
  TODO: { ic: '◉', cls: 'warn' }, MESSAGE: { ic: '✉', cls: 'info' },
  WARNING: { ic: '⚠', cls: 'bad' }, ANNOUNCE: { ic: '📢', cls: 'ok' },
}
watch(() => auth.isAuthed, (on) => {
  window.clearInterval(pollTimer)
  if (on) {
    loadUnread()
    pollTimer = window.setInterval(loadUnread, 30_000)
    loadBadges(true)
  } else {
    unread.value = 0
    notifOpen.value = false
  }
}, { immediate: true })
onBeforeUnmount(() => window.clearInterval(pollTimer))

// —— 侧边栏徽标（动态：与各页面真实数量一致；失败/无权限静默不显示）——
// guide=可申报指南数 / review=待我评分任务数 / claim=待认领成果数 / procurement=进行中采购申请数
const navBadge = reactive<Record<string, number | undefined>>({})
let badgeFetchedAt = 0
async function loadBadges(force = false) {
  const keys = ['guide', 'review', 'claim', 'procurement']
  if (!auth.isAuthed) {
    keys.forEach((k) => (navBadge[k] = undefined))
    return
  }
  const now = Date.now()
  if (!force && now - badgeFetchedAt < 30_000) return  // 节流：30s 内复用
  badgeFetchedAt = now
  const one = async (path: string, params: Record<string, any>): Promise<number | undefined> => {
    try {
      const d = await list<{ total: number }>(path, { page: 1, size: 1, ...params })
      return d.total ?? 0
    } catch { return undefined }  // 403/失败 → 不显示徽标
  }
  const [guide, review, claim, reqs] = await Promise.all([
    one('/apply/guidelines', { status: 'PUBLISHED' }),
    one('/apply/review/mytasks', { status: 'SCORING' }),
    one('/output/pending-claim', { min_confidence: 0 }),
    list<{ status: string }>('/procurement/requisitions', { page: 1, size: 200 })
      .then((d) => d.rows).catch(() => undefined),  // 后端不支持 status 过滤 → 拉全量本地计
  ])
  navBadge.guide = guide
  navBadge.review = review
  navBadge.claim = claim
  // 进行中 = 待审/方式已定/评标中（草稿、已下单、已取消不计）
  navBadge.procurement = reqs
    ? reqs.filter((r) => ['SUBMITTED', 'WAY_DECIDED', 'BIDDING'].includes(r.status)).length
    : undefined
}

// 登录浮层：未登录即显示；带 needLogin 查询(守卫回跳)时也强制显示。
const showLogin = computed(() => !auth.isAuthed || route.query.needLogin === '1')

// 登录表单（真实提交；reactive 使 v-model 生效）
const loginForm = reactive({ username: '', password: '' })
const logging = ref(false)
const loginErr = ref('')
async function submitLogin() {
  logging.value = true
  loginErr.value = ''
  try {
    await auth.login(loginForm.username.trim(), loginForm.password)
    // 清掉 needLogin，避免守卫再次拦截回跳
    await router.replace({ name: 'dash' })
    toast('登录成功 · 欢迎回来，' + (auth.user?.real_name || auth.user?.username || ''))
  } catch (e: any) {
    loginErr.value = e?.message || '账号或密码错误'
  } finally {
    logging.value = false
  }
}

function doLogout() {
  auth.logout()
  router.replace({ path: '/dash', query: { needLogin: '1' } })
  toast('已退出登录')
}

interface NavItem { v: string; ic: string; label: string; roles?: string[] }
interface NavGroup { t: string; items: NavItem[] }

// 菜单 groups 的 roles 已收敛为 fallback-only 数据源（在线矩阵真源 sys_page_grant，PRD 2.9）。

const groups: NavGroup[] = [
  { t: '总 览', items: [
    { v: 'dash', ic: '◈', label: '工作台驾驶舱' },
    { v: 'bigscreen', ic: '▣', label: '经费监督大屏', roles: ['R-LEADER', 'R-FINANCE', 'R-AUDITOR', 'R-ADMIN'] },
  ]},
  { t: '项目管理', items: [
    { v: 'guide', ic: '◉', label: '申报指南' },
    { v: 'editor', ic: '✎', label: '申报书撰写', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] },
    { v: 'review', ic: '☰', label: '评审工作台', roles: ['R-MANAGER', 'R-EXPERT', 'R-ETHICS', 'R-LEADER', 'R-ADMIN'] },
    { v: 'projects', ic: '▦', label: '我的项目', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] },
    { v: 'project', ic: '◫', label: '项目详情' },
  ]},
  { t: '经费 · 成果', items: [
    { v: 'expense', ic: '¥', label: '报销填单', roles: ['R-STAFF', 'R-MANAGER', 'R-FINANCE'] },
    { v: 'funding-config', ic: '⚗', label: '经费配置', roles: ['R-MANAGER', 'R-FINANCE'] },
    { v: 'claim', ic: '✧', label: '成果认领', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] },
    { v: 'output', ic: '▧', label: '成果台账', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] },
    { v: 'transfer', ic: '⇄', label: '转化看板', roles: ['R-MANAGER', 'R-LEADER', 'R-ADMIN'] },
  ]},
  { t: '资 产 · 采 购', items: [
    { v: 'procurement', ic: '⧉', label: '采购与合同', roles: ['R-MANAGER', 'R-FINANCE', 'R-ADMIN'] },
    { v: 'asset', ic: '▤', label: '资产与耗材台账', roles: ['R-MANAGER', 'R-FINANCE', 'R-ADMIN'] },
  ]},
  { t: '学 术 活 动', items: [
    { v: 'activity', ic: '✪', label: '学术活动管理', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER', 'R-AUDITOR'] },
    { v: 'performance', ic: '★', label: '科研绩效评价', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER', 'R-FINANCE', 'R-AUDITOR'] },
    { v: 'expert-review', ic: '✦', label: '专家与评审', roles: ['R-EXPERT', 'R-MANAGER', 'R-LEADER', 'R-AUDITOR'] },
    { v: 'archive', ic: '⌘', label: '科研档案', roles: ['R-ADMIN', 'R-MANAGER', 'R-AUDITOR'] },
  ]},
  { t: '人 员', items: [
    { v: 'portrait', ic: '◍', label: 'PI 画像', roles: ['R-LEADER', 'R-MANAGER', 'R-ADMIN'] },
  ]},
  { t: '系 统', items: [
    { v: 'admin-users', ic: '⚑', label: '用户管理', roles: ['R-ADMIN'] },
    { v: 'admin-roles', ic: '⚙', label: '角色与权限', roles: ['R-ADMIN', 'R-AUDITOR'] },
    { v: 'admin-dicts', ic: '☰', label: '数据字典', roles: ['R-ADMIN'] },
  ]},
]

// 菜单可见性（粒度①）：统一走 canSeePage（在线矩阵优先 / grants 不可用退回静态 roles）；整组皆不可见则隐组。
const visibleGroups = computed(() =>
  groups
    .map((g) => ({ ...g, items: g.items.filter((it) => auth.canSeePage(it.v, it.roles)) }))
    .filter((g) => g.items.length > 0),
)

const userName = computed(() => auth.user?.real_name || auth.user?.username || '未登录')
const userSub = computed(() =>
  auth.roles.length ? auth.roles.map(roleLabel).join(' / ') : '访客',
)
const userAvatar = computed(() => (userName.value[0] || '访'))

const ROLE_LABEL: Record<string, string> = {
  'R-STAFF': '研究员', 'R-MANAGER': '主管', 'R-LEADER': '领导',
  'R-FINANCE': '财务', 'R-AUDITOR': '审计', 'R-EXPERT': '评审专家',
  'R-ETHICS': '伦理委员', 'R-ADMIN': '系统管理员',
}
function roleLabel(r: string): string {
  return ROLE_LABEL[r] || r
}

const crumbZh = computed(() => (route.meta.zh as string) || '工作台驾驶舱')
const crumbEn = computed(() => (route.meta.en as string) || 'DASHBOARD')

function go(v: string) {
  router.push({ name: v })
}

// 供子组件调用的全局 toast（简易实现）
const toastMsg = ref('')
let toastTimer: number | undefined
function toast(m: string) {
  toastMsg.value = m
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => (toastMsg.value = ''), 2600)
}
;(window as any).toast = toast

// 路由切换后静默刷新徽标（30s 节流内建在 loadBadges）
watch(() => route.path, () => { if (auth.isAuthed) loadBadges() })
</script>

<template>
  <!-- 登录浮层 -->
  <div class="login-wrap" :class="{ on: showLogin }" id="loginScreen">
    <div class="login-paper">
      <h2>科研管理系统</h2>
      <div class="sub">ResearchOS · Scientific Research Management · V9</div>
      <div class="fld"><label>账号</label><input v-model="loginForm.username" placeholder="请输入登录账号" @keyup.enter="submitLogin" /></div>
      <div class="fld"><label>密码</label><input type="password" v-model="loginForm.password" placeholder="••••••••" @keyup.enter="submitLogin" /></div>
      <div v-if="loginErr" style="color:#c0392b;font-size:13px;margin:-4px 0 8px">{{ loginErr }}</div>
      <button class="btn seal login-btn" :disabled="logging" @click="submitLogin">{{ logging ? '登录中…' : '登 录' }}</button>
      <div class="login-foot">演示账号 <b>admin/Admin@123456</b> · <b>staff/Staff@123456</b> · <b>finance/Finance@123456</b></div>
    </div>
  </div>

  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="zh">科研管理</div>
        <div class="en">ResearchOS</div>
        <span class="ver">CONTRACT-DRIVEN v0.1</span>
      </div>
      <nav class="nav">
        <div class="nav-group" v-for="g in visibleGroups" :key="g.t">
          <div class="t">{{ g.t }}</div>
          <div
            class="nav-item"
            :class="{ active: route.name === item.v }"
            v-for="item in g.items"
            :key="item.v"
            @click="go(item.v)"
          >
            <span class="ic">{{ item.ic }}</span>{{ item.label }}
            <span class="bdg" v-if="navBadge[item.v]">{{ navBadge[item.v] }}</span>
          </div>
        </div>
      </nav>
      <div class="side-foot">启元研究院 · 租户演示 · 契约 mock</div>
    </aside>

    <div class="main">
      <div class="topbar">
        <div class="crumb">
          <span>{{ crumbZh }}</span><small>{{ crumbEn }}</small>
        </div>
        <div class="top-search">
          <span>⌕</span>
          <input placeholder="问点什么… 例如「去年到账经费最高的三个 PI」" />
          <span class="ai-tag">AI 直达</span>
        </div>
        <div class="bell-wrap" style="position:relative">
          <span class="bell" @click="openNotif" title="通知中心">🔔<i v-if="unread > 0" style="position:absolute;top:-4px;right:-6px;background:var(--seal,#c0392b);color:#fff;font-style:normal;font-size:10px;min-width:16px;height:16px;line-height:16px;border-radius:8px;text-align:center;padding:0 3px">{{ unread > 99 ? '99+' : unread }}</i></span>
          <div v-if="notifOpen" style="position:absolute;right:0;top:40px;width:360px;background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 12px 32px rgba(0,0,0,.14);z-index:60;overflow:hidden">
            <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 14px;border-bottom:1px solid var(--line)">
              <b style="font-size:13px">通知中心 <span style="color:var(--seal)">{{ unread }}</span> 条未读</b>
              <span v-if="notifTab !== 'todo'" style="font-size:12px;color:var(--ai);cursor:pointer" @click="markAllRead">全部已读</span>
            </div>
            <div style="display:flex;border-bottom:1px solid var(--line)">
              <div v-for="t in [['todo','待办',taskSummary.todo],['msg','消息',taskSummary.message],['warn','预警',taskSummary.warning]] as any"
                   :key="t[0]" @click="switchTab(t[0])"
                   style="flex:1;text-align:center;padding:8px 0;font-size:12.5px;cursor:pointer;border-bottom:2px solid transparent"
                   :style="{ fontWeight: notifTab === t[0] ? 700 : 400, color: notifTab === t[0] ? 'var(--ink)' : 'var(--ink-mute)', borderBottomColor: notifTab === t[0] ? 'var(--seal,#c0392b)' : 'transparent' }">
                {{ t[1] }}<span v-if="t[2] > 0" style="color:var(--seal,#c0392b)"> ({{ t[2] }})</span>
              </div>
            </div>
            <div style="max-height:320px;overflow:auto">
              <div v-if="notifLoading" style="padding:18px;text-align:center;font-size:12px;color:var(--ink-mute)">加载中…</div>
              <!-- 待办 tab：聚合（通知待办 + 我名下 PENDING 审批单） -->
              <template v-else-if="notifTab === 'todo'">
                <div v-if="!taskList.length" style="padding:18px;text-align:center;font-size:12px;color:var(--ink-mute)">暂无待办</div>
                <div v-for="(t, i) in taskList" :key="'t' + t.kind + t.id + i"
                     style="padding:10px 14px;border-bottom:1px solid var(--line);display:flex;gap:8px;align-items:flex-start">
                  <span class="tag" :class="t.kind === 'APPROVAL' ? 'warn' : 'info'" style="flex-shrink:0;font-size:10px">{{ t.kind === 'APPROVAL' ? '✓ 待审' : '◉ 通知' }}</span>
                  <div style="flex:1;min-width:0">
                    <div style="font-size:12.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ t.title }}</div>
                    <div v-if="t.content" style="font-size:11px;color:var(--ink-mute);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ t.content }}</div>
                    <div v-if="t.amount" style="font-size:11px;color:var(--ink);margin-top:2px">金额 ¥{{ t.amount }}<span v-if="t.code" style="color:var(--ink-mute)"> · {{ t.code }}</span></div>
                  </div>
                </div>
              </template>
              <!-- 消息/预警 tab：通知收件箱 -->
              <template v-else>
                <div v-if="!notifList.length" style="padding:18px;text-align:center;font-size:12px;color:var(--ink-mute)">暂无内容</div>
                <div v-for="n in notifList" :key="n.id" @click="markRead(n)"
                     style="padding:10px 14px;border-bottom:1px solid var(--line);cursor:pointer;display:flex;gap:8px;align-items:flex-start"
                     :style="{ background: n.read ? 'transparent' : 'rgba(192,57,43,.04)' }">
                  <span class="tag" :class="TYP_META[n.typ]?.cls || 'info'" style="flex-shrink:0;font-size:10px">{{ TYP_META[n.typ]?.ic || '•' }} {{ n.typ }}</span>
                  <div style="flex:1;min-width:0">
                    <div style="font-size:12.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" :style="{ color: n.read ? 'var(--ink-mute)' : 'var(--ink)' }">{{ n.title }}</div>
                    <div v-if="n.content" style="font-size:11px;color:var(--ink-mute);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ n.content }}</div>
                    <div style="font-size:10px;color:var(--ink-mute);margin-top:2px">{{ (n.created_at || '').replace('T', ' ').slice(0, 16) }}</div>
                  </div>
                  <span v-if="!n.read" style="width:7px;height:7px;border-radius:50%;background:var(--seal,#c0392b);flex-shrink:0;margin-top:5px"></span>
                </div>
              </template>
            </div>
          </div>
        </div>
        <div class="role-chip" @click="doLogout" title="点击退出登录">
          <div class="av">{{ userAvatar }}</div>
          <div class="nm"><b>{{ userName }}</b><span>{{ userSub }}</span></div>
        </div>
      </div>

      <div class="content">
        <router-view v-slot="{ Component }">
          <component :is="Component" />
        </router-view>
      </div>
    </div>
  </div>

  <div id="toast" :class="{ on: !!toastMsg }">{{ toastMsg }}</div>
</template>
