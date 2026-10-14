<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api } from '@/api/client'
import { auth } from '@/api/auth'

interface Role { id: number; code: string; name: string; is_builtin?: boolean; tenant_id?: number }
const roles = ref<Role[]>([])
const loading = ref(false)
const err = ref('')

// 角色 → 可见页面（镜像 router meta.roles；粒度①的只读呈现，非后端 caps）
const PAGES: Array<{ name: string; zh: string; roles: string[] }> = [
  { name: 'dash', zh: '工作台', roles: [] },
  { name: 'bigscreen', zh: '监督大屏', roles: ['R-LEADER', 'R-FINANCE', 'R-AUDITOR', 'R-ADMIN'] },
  { name: 'editor', zh: '申报撰写', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] },
  { name: 'review', zh: '评审工作台', roles: ['R-MANAGER', 'R-EXPERT', 'R-ETHICS', 'R-LEADER', 'R-ADMIN'] },
  { name: 'expense', zh: '报销填单', roles: ['R-STAFF', 'R-MANAGER', 'R-FINANCE'] },
  { name: 'claim', zh: '成果认领', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] },
  { name: 'procurement', zh: '采购合同', roles: ['R-MANAGER', 'R-FINANCE', 'R-ADMIN'] },
  { name: 'asset', zh: '资产台账', roles: ['R-MANAGER', 'R-FINANCE', 'R-ADMIN'] },
  { name: 'portrait', zh: 'PI 画像', roles: ['R-LEADER', 'R-MANAGER', 'R-ADMIN'] },
  { name: 'admin-users', zh: '用户管理', roles: ['R-ADMIN'] },
  { name: 'admin-roles', zh: '角色权限', roles: ['R-ADMIN', 'R-AUDITOR'] },
]

function canSeePage(role: string, p: { roles: string[] }): boolean {
  if (p.roles.length === 0) return true // 所有已登录可见
  if (p.roles.includes(role)) return true
  if (role === 'R-ADMIN') return true // 超管兜底（与后端 /api/v1/* 对齐）
  return false
}

// 当前登录用户自身能力（粒度②），来自 /auth/me
const myCaps = computed(() => auth.caps)
const isAdmin = computed(() => auth.roles.includes('R-ADMIN'))

async function reload() {
  loading.value = true
  err.value = ''
  try {
    const d = await api.get<{ list: Role[] }>('/admin/roles')
    roles.value = d?.list ?? []
  } catch (e: any) {
    err.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(reload)
</script>

<template>
  <div class="card" style="padding:18px">
    <h3 style="margin-top:0">角色与权限</h3>
    <div v-if="err" style="color:#c0392b">{{ err }}</div>
    <p style="opacity:.7;font-size:13px">
      页面可见性为静态配置（镜像路由 <code>meta.roles</code>，粒度①）；「我的能力」为后端 <code>/auth/me</code> 依 Casbin 策略派生的按钮/操作级集合（粒度②）。本轮角色↔权限不入库、不可在线编辑（P-U1-dyn）。
    </p>

    <h4>角色目录（{{ roles.length }}）</h4>
    <table class="tbl" style="border-collapse:collapse;width:100%;margin-bottom:18px">
      <thead><tr style="text-align:left"><th>code</th><th>名称</th><th>内置</th></tr></thead>
      <tbody>
        <tr v-for="r in roles" :key="r.id">
          <td>{{ r.code }}</td><td>{{ r.name }}</td>
          <td>{{ r.is_builtin ? '是' : '否' }}</td>
        </tr>
        <tr v-if="!roles.length"><td colspan="3" style="opacity:.6">{{ loading?'加载中…':'无' }}</td></tr>
      </tbody>
    </table>

    <h4>页面可见性矩阵</h4>
    <div style="overflow:auto">
      <table class="tbl" style="border-collapse:collapse;font-size:13px">
        <thead>
          <tr>
            <th>页面 \ 角色</th>
            <th v-for="r in roles" :key="r.code" style="text-align:center">{{ r.code.replace('R-','') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in PAGES" :key="p.name">
            <td>{{ p.zh }}</td>
            <td v-for="r in roles" :key="r.code" style="text-align:center">
              {{ canSeePage(r.code, p) ? '✓' : '·' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <h4 style="margin-top:18px">我的能力（当前登录 · {{ auth.roles.join('/') || '无' }}）</h4>
    <div v-if="isAdmin" style="opacity:.7;font-size:12px;margin-bottom:6px">R-ADMIN 拥有 <code>/api/v1/*</code> 通配能力，列表为策略原文截取。</div>
    <div style="display:flex;flex-wrap:wrap;gap:6px">
      <span v-for="c in myCaps" :key="c"
            style="background:#eef;border-radius:4px;padding:2px 6px;font-size:12px">{{ c }}</span>
      <span v-if="!myCaps.length" style="opacity:.6">（无 / 尚未加载）</span>
    </div>
  </div>
</template>
