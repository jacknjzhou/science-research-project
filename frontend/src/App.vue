<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()

const showLogin = ref(!new URLSearchParams(location.search).has('autologin'))

interface NavItem { v: string; ic: string; label: string; badge?: number }
interface NavGroup { t: string; items: NavItem[] }

const groups: NavGroup[] = [
  { t: '总 览', items: [
    { v: 'dash', ic: '◈', label: '工作台驾驶舱' },
    { v: 'bigscreen', ic: '▣', label: '经费监督大屏' },
  ]},
  { t: '项目管理', items: [
    { v: 'guide', ic: '◉', label: '申报指南', badge: 6 },
    { v: 'editor', ic: '✎', label: '申报书撰写' },
    { v: 'review', ic: '☰', label: '评审工作台', badge: 3 },
    { v: 'projects', ic: '▦', label: '我的项目' },
    { v: 'project', ic: '◫', label: '项目详情' },
  ]},
  { t: '经费 · 成果', items: [
    { v: 'expense', ic: '¥', label: '报销填单' },
    { v: 'claim', ic: '✧', label: '成果认领', badge: 12 },
    { v: 'transfer', ic: '⇄', label: '转化看板' },
  ]},
  { t: '资 产 · 采 购', items: [
    { v: 'procurement', ic: '⧉', label: '采购与合同', badge: 5 },
    { v: 'asset', ic: '▤', label: '资产与耗材台账' },
  ]},
  { t: '人 员', items: [
    { v: 'portrait', ic: '◍', label: 'PI 画像' },
  ]},
]

const crumbZh = computed(() => (route.meta.zh as string) || '工作台驾驶舱')
const crumbEn = computed(() => (route.meta.en as string) || 'DASHBOARD')

function go(v: string) {
  router.push({ name: v })
}

function enter() {
  showLogin.value = false
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
      <span class="login-close" @click="enter">✕</span>
      <h2>科研管理系统</h2>
      <div class="sub">ResearchOS · Scientific Research Management · V9</div>
      <div class="fld"><label>统一身份账号 / ORCID</label><input placeholder="请输入工号或 ORCID" /></div>
      <div class="fld"><label>密码 / 动态码</label><input type="password" placeholder="••••••••" /></div>
      <button class="btn seal login-btn" @click="enter(); toast('登录成功 · 欢迎回来，周研究员')">登 录</button>
      <div class="login-foot">支持 <b>信创环境</b> · 等保三级 · <span style="color:var(--ai)">AI 助手已就绪</span></div>
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
        <div class="nav-group" v-for="g in groups" :key="g.t">
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
        <div class="role-chip" @click="toast('切换角色（演示）：科研人员 → 管理员 → 领导')">
          <div class="av">周</div>
          <div class="nm"><b>周明远</b><span>研究员 / PI</span></div>
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
