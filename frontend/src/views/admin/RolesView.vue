<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { api } from '@/api/client'
import { auth } from '@/api/auth'

interface Role { id: number; code: string; name: string; is_builtin?: boolean; tenant_id?: number }
const roles = ref<Role[]>([])
const loading = ref(false)
const err = ref('')
const toast = (m: string) => (window as any).toast?.(m)

const canWrite = computed(() => auth.can('/admin/roles POST'))

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

// —— 角色新增/编辑/删除 ——
const drawer = reactive({ open: false, editing: false })
const form = reactive({ id: 0, code: '', name: '' })
const saving = ref(false)
function openCreate() {
  Object.assign(form, { id: 0, code: '', name: '' })
  drawer.editing = false
  drawer.open = true
}
function openEdit(r: Role) {
  Object.assign(form, { id: r.id, code: r.code, name: r.name })
  drawer.editing = true
  drawer.open = true
}
async function save() {
  saving.value = true
  err.value = ''
  try {
    await api.post<Role>('/admin/roles', { code: form.code.trim(), name: form.name.trim() })
    toast('角色已创建（API 授权需在 Casbin 策略中配置）')
    drawer.open = false
    await reload()
  } catch (e: any) {
    err.value = e?.message || '保存失败'
  } finally {
    saving.value = false
  }
}
async function rename(r: Role) {
  const name = prompt('修改角色名称（编码不可改）：', r.name)
  if (!name || name.trim() === r.name) return
  try {
    await api.put(`/admin/roles/${r.id}`, { name: name.trim() })
    toast('角色名称已更新')
    await reload()
  } catch (e: any) {
    err.value = e?.message || '更新失败'
  }
}
async function remove(r: Role) {
  if (r.is_builtin) { toast('内置角色不可删除'); return }
  if (!confirm(`确认删除角色「${r.name}（${r.code}）」？已绑定用户时将被拒绝。`)) return
  try {
    await api.del(`/admin/roles/${r.id}`)
    toast('角色已删除')
    await reload()
  } catch (e: any) {
    err.value = e?.message || '删除失败'
  }
}
onMounted(reload)
</script>

<template>
  <div class="card" style="padding:18px">
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
      <h3 style="margin:0">角色与权限</h3>
      <button class="btn sm seal" v-if="canWrite" @click="openCreate">＋ 新增角色</button>
    </div>
    <div v-if="err" style="color:#c0392b;margin:8px 0">{{ err }}</div>
    <p style="opacity:.7;font-size:13px">
      角色目录由管理员维护（新增/改名/删除：内置角色不可删、已绑定用户需先解绑）；页面可见性为静态配置（镜像路由 <code>meta.roles</code>，粒度①）；「我的能力」为后端 <code>/auth/me</code> 依 Casbin 策略派生的按钮/操作级集合（粒度②）。<b>提示</b>：新增角色的 API 授权需在 Casbin 策略（policy.csv）中配置后方可实际访问接口。
    </p>

    <h4>角色目录（{{ roles.length }}）</h4>
    <table class="tbl" style="border-collapse:collapse;width:100%;margin-bottom:18px">
      <thead><tr style="text-align:left"><th>code</th><th>名称</th><th>内置</th><th v-if="canWrite">操作</th></tr></thead>
      <tbody>
        <tr v-for="r in roles" :key="r.id">
          <td class="mono">{{ r.code }}</td><td>{{ r.name }}</td>
          <td>{{ r.is_builtin ? '是' : '否' }}</td>
          <td v-if="canWrite" style="white-space:nowrap">
            <button class="btn sm mini" @click="rename(r)">改名</button>
            <button class="btn sm mini" v-if="!r.is_builtin" @click="remove(r)">删除</button>
          </td>
        </tr>
        <tr v-if="!roles.length"><td colspan="4" style="opacity:.6">{{ loading?'加载中…':'无' }}</td></tr>
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

    <!-- 新增角色抽屉 -->
    <div v-if="drawer.open" style="position:fixed;inset:0;background:rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;z-index:60">
      <div style="background:#fff;width:min(440px,92vw);max-height:88vh;overflow:auto;padding:20px;border-radius:10px">
        <h3 style="margin-top:0">新增角色</h3>
        <div class="fld"><label>角色编码 *（如 R-LAB，租户内唯一，创建后不可改）</label><input v-model="form.code" placeholder="R-XXX" /></div>
        <div class="fld"><label>角色名称 *</label><input v-model="form.name" placeholder="如：实验室主任" /></div>
        <p style="font-size:12px;color:var(--ink-mute)">创建后需在 Casbin 策略（policy.csv）中为该编码配置 API 授权，并可在「用户管理」中为用户授予此角色。</p>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
          <button class="btn" @click="drawer.open=false">取消</button>
          <button class="btn seal" :disabled="saving || !form.code.trim() || !form.name.trim()" @click="save">{{ saving?'保存中…':'保存' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mono { font-family: var(--mono, monospace); font-size: 12px; }
.tbl .btn.sm.mini { padding: 2px 8px; font-size: 11px; border-radius: 3px; }
.tbl .btn.sm.mini + .btn.sm.mini { margin-left: 4px; }
.fld { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; }
.fld label { font-size: 12px; color: var(--ink-mute); }
.fld input { border: 1px solid var(--line-hard); border-radius: 4px; padding: 7px 10px; font: inherit; font-size: 13px; }
</style>
