<script setup lang="ts">
import { ref, computed, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { auth } from '@/api/auth'

const router = useRouter()
const route = useRoute()

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

interface NavItem { v: string; ic: string; label: string; badge?: number; roles?: string[] }
interface NavGroup { t: string; items: NavItem[] }

const groups: NavGroup[] = [
  { t: '总 览', items: [
    { v: 'dash', ic: '◈', label: '工作台驾驶舱' },
    { v: 'bigscreen', ic: '▣', label: '经费监督大屏', roles: ['R-LEADER', 'R-FINANCE', 'R-AUDITOR', 'R-ADMIN'] },
  ]},
  { t: '项目管理', items: [
    { v: 'guide', ic: '◉', label: '申报指南', badge: 6 },
    { v: 'editor', ic: '✎', label: '申报书撰写', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] },
    { v: 'review', ic: '☰', label: '评审工作台', badge: 3, roles: ['R-MANAGER', 'R-EXPERT', 'R-ETHICS', 'R-LEADER', 'R-ADMIN'] },
    { v: 'projects', ic: '▦', label: '我的项目', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] },
    { v: 'project', ic: '◫', label: '项目详情' },
  ]},
  { t: '经费 · 成果', items: [
    { v: 'expense', ic: '¥', label: '报销填单', roles: ['R-STAFF', 'R-MANAGER', 'R-FINANCE'] },
    { v: 'claim', ic: '✧', label: '成果认领', badge: 12, roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] },
    { v: 'transfer', ic: '⇄', label: '转化看板', roles: ['R-MANAGER', 'R-LEADER', 'R-ADMIN'] },
  ]},
  { t: '资 产 · 采 购', items: [
    { v: 'procurement', ic: '⧉', label: '采购与合同', badge: 5, roles: ['R-MANAGER', 'R-FINANCE', 'R-ADMIN'] },
    { v: 'asset', ic: '▤', label: '资产与耗材台账', roles: ['R-MANAGER', 'R-FINANCE', 'R-ADMIN'] },
  ]},
  { t: '人 员', items: [
    { v: 'portrait', ic: '◍', label: 'PI 画像', roles: ['R-LEADER', 'R-MANAGER', 'R-ADMIN'] },
  ]},
  { t: '系 统', items: [
    { v: 'admin-users', ic: '⚑', label: '用户管理', roles: ['R-ADMIN'] },
    { v: 'admin-roles', ic: '⚙', label: '角色与权限', roles: ['R-ADMIN', 'R-AUDITOR'] },
  ]},
]

// 菜单可见性（粒度①）：登录后依 hasAnyRole 过滤，整组皆不可见则隐组。
const visibleGroups = computed(() =>
  groups
    .map((g) => ({ ...g, items: g.items.filter((it) => auth.hasAnyRole(it.roles)) }))
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
            <span class="bdg" v-if="item.badge">{{ item.badge }}</span>
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
        <span class="bell" @click="toast('3 条未读：经费预警 ×1 · 待评审 ×2')">🔔</span>
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
