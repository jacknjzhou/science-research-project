<script setup lang="ts">
import { reactive, ref, computed, onMounted } from 'vue'
import { api, list, ApiError } from '@/api/client'
import { auth } from '@/api/auth'

interface User {
  id: number
  username: string
  real_name: string
  email?: string | null
  phone?: string | null
  staff_no?: string | null
  employment_status?: string
  security_level?: string
  status?: 'ACTIVE' | 'LOCKED' | 'DISABLED'
  tenant_id?: number
  legal_entity_id?: number | null
  roles: string[]
  created_at?: string
  updated_at?: string
}
interface Role {
  id: number
  code: string
  name: string
  is_builtin?: boolean
  tenant_id?: number
}

// —— 列表状态 ——
const rows = ref<User[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const keyword = ref('')
const loading = ref(false)
const err = ref('')

const ROLE_OPTIONS = [
  'R-STAFF', 'R-MANAGER', 'R-LEADER', 'R-FINANCE',
  'R-AUDITOR', 'R-EXPERT', 'R-ETHICS', 'R-ADMIN',
]
const rolesCatalog = ref<Role[]>([])

const canCreate = computed(() => auth.can('/admin/users POST'))
const canWrite = computed(() => auth.can('/admin/users PUT') || auth.can('/admin/users DELETE'))

async function reload() {
  loading.value = true
  err.value = ''
  try {
    const params: Record<string, any> = { page: page.value, size: size.value }
    if (keyword.value.trim()) params.q = keyword.value.trim()
    const r = await list<User>('/admin/users', params)
    rows.value = r.rows
    total.value = r.total
  } catch (e: any) {
    err.value = (e as ApiError)?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadRoles() {
  try {
    const d = await api.get<{ list: Role[] }>('/admin/roles')
    rolesCatalog.value = d?.list ?? []
  } catch {
    rolesCatalog.value = []
  }
}

function goPage(p: number) {
  const max = Math.max(1, Math.ceil(total.value / size.value))
  page.value = Math.min(Math.max(1, p), max)
  reload()
}

// —— 抽屉表单 ——
const drawer = reactive({ open: false, mode: 'create' as 'create' | 'edit' })
const form = reactive({
  id: 0,
  username: '',
  real_name: '',
  password: '',
  email: '',
  phone: '',
  staff_no: '',
  security_level: 'INTERNAL',
  employment_status: 'ONBOARD',
  status: 'ACTIVE' as 'ACTIVE' | 'LOCKED' | 'DISABLED',
  roles: [] as string[],
})

function openCreate() {
  drawer.mode = 'create'
  Object.assign(form, {
    id: 0, username: '', real_name: '', password: '', email: '', phone: '', staff_no: '',
    security_level: 'INTERNAL', employment_status: 'ONBOARD', status: 'ACTIVE', roles: [],
  })
  drawer.open = true
}

function openEdit(u: User) {
  drawer.mode = 'edit'
  Object.assign(form, {
    id: u.id, username: u.username, real_name: u.real_name,
    password: '', email: u.email ?? '', phone: u.phone ?? '', staff_no: u.staff_no ?? '',
    security_level: u.security_level ?? 'INTERNAL',
    employment_status: u.employment_status ?? 'ONBOARD',
    status: (u.status as any) ?? 'ACTIVE',
    roles: [...(u.roles ?? [])],
  })
  drawer.open = true
}

const saving = ref(false)
async function save() {
  saving.value = true
  err.value = ''
  try {
    if (drawer.mode === 'create') {
      const created = await api.post<User>('/admin/users', {
        username: form.username, real_name: form.real_name, password: form.password,
        email: form.email || undefined, phone: form.phone || undefined, staff_no: form.staff_no || undefined,
        security_level: form.security_level, employment_status: form.employment_status,
        roles: form.roles,
      })
      // 角色已在 create 内绑定（后端 CreateUser 处理 roles[]）
      ;(window as any).toast?.('已创建用户 ' + created.username)
    } else {
      const body: Record<string, any> = {
        real_name: form.real_name, email: form.email || null, phone: form.phone || null,
        security_level: form.security_level, status: form.status,
      }
      if (form.password) body.password = form.password // 给出即重设
      await api.put<User>(`/admin/users/${form.id}`, body)
      await syncRoles(form.id, form.roles)
      ;(window as any).toast?.('已更新用户')
    }
    drawer.open = false
    await reload()
  } catch (e: any) {
    err.value = (e as ApiError)?.message || '保存失败'
  } finally {
    saving.value = false
  }
}

// 编辑：目标角色集 vs 现有 → 差异调用 assign/revoke
async function syncRoles(userId: number, target: string[]) {
  const cur = rows.value.find((r) => r.id === userId)?.roles ?? []
  const add = target.filter((r) => !cur.includes(r))
  const del = cur.filter((r) => !target.includes(r))
  for (const code of add) {
    const role = rolesCatalog.value.find((x) => x.code === code)
    if (!role) continue
    await api.post(`/admin/users/${userId}/roles`, { role_id: role.id })
  }
  for (const code of del) {
    const role = rolesCatalog.value.find((x) => x.code === code)
    if (!role) continue
    await api.del(`/admin/users/${userId}/roles/${role.id}`)
  }
}

async function disable(u: User) {
  if (!confirm(`确认停用「${u.real_name || u.username}」？`)) return
  try {
    await api.put(`/admin/users/${u.id}`, { status: 'DISABLED' })
    ;(window as any).toast?.('已停用')
    await reload()
  } catch (e: any) {
    err.value = (e as ApiError)?.message || '操作失败'
  }
}

onMounted(async () => {
  await loadRoles()
  await reload()
})
</script>

<template>
  <div class="card" style="padding:18px">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
      <h3 style="margin:0">用户管理</h3>
      <input v-model="keyword" placeholder="按用户名/姓名检索" @keyup.enter="page=1;reload()"
             style="flex:1;max-width:280px" />
      <button class="btn" @click="reload">刷新</button>
      <button class="btn seal" v-if="canCreate" @click="openCreate">＋ 新建用户</button>
    </div>
    <div v-if="err" style="color:#c0392b;margin-bottom:8px">{{ err }}</div>

    <table class="tbl" width="100%" style="border-collapse:collapse">
      <thead>
        <tr style="text-align:left">
          <th>账号</th><th>姓名</th><th>状态</th><th>密级</th><th>角色</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="u in rows" :key="u.id" :style="{opacity: u.status==='DISABLED'?.45:1}">
          <td>{{ u.username }}</td>
          <td>{{ u.real_name }}</td>
          <td>{{ u.status }}</td>
          <td>{{ u.security_level }}</td>
          <td>{{ (u.roles||[]).join(' · ') }}</td>
          <td>
            <button class="btn sm" v-if="canWrite" @click="openEdit(u)">编辑</button>
            <button class="btn sm" v-perm="'/admin/users PUT'"
                    v-if="u.status!=='DISABLED'" @click="disable(u)">停用</button>
          </td>
        </tr>
        <tr v-if="!rows.length"><td colspan="6" style="opacity:.6;padding:16px">{{ loading?'加载中…':'暂无数据' }}</td></tr>
      </tbody>
    </table>

    <div style="display:flex;gap:8px;align-items:center;margin-top:12px">
      <button class="btn sm" :disabled="page<=1" @click="goPage(page-1)">上一页</button>
      <span>第 {{ page }} 页 / 共 {{ Math.max(1,Math.ceil(total/size)) }} 页（{{ total }} 条）</span>
      <button class="btn sm" :disabled="page>=Math.ceil(total/size)" @click="goPage(page+1)">下一页</button>
    </div>

    <!-- 抽屉 -->
    <div v-if="drawer.open" class="drawer-mask" style="position:fixed;inset:0;background:rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;z-index:60">
      <div class="drawer" style="background:#fff;width:min(520px,92vw);max-height:88vh;overflow:auto;padding:20px;border-radius:10px">
        <h3 style="margin-top:0">{{ drawer.mode==='create'?'新建用户':'编辑用户' }}</h3>
        <div class="fld"><label>账号</label><input v-model="form.username" :disabled="drawer.mode==='edit'" /></div>
        <div class="fld"><label>姓名</label><input v-model="form.real_name" /></div>
        <div class="fld"><label>{{ drawer.mode==='create'?'初始密码':'重置密码(留空不改)' }}</label>
          <input v-model="form.password" type="password" :required="drawer.mode==='create'" /></div>
        <div class="fld"><label>邮箱</label><input v-model="form.email" /></div>
        <div class="fld"><label>手机</label><input v-model="form.phone" /></div>
        <div class="fld"><label>密级</label>
          <select v-model="form.security_level">
            <option value="PUBLIC">PUBLIC</option><option value="INTERNAL">INTERNAL</option>
            <option value="SECRET">SECRET</option><option value="TOP_SECRET">TOP_SECRET</option>
          </select></div>
        <div class="fld" v-if="drawer.mode==='edit'"><label>状态</label>
          <select v-model="form.status">
            <option value="ACTIVE">ACTIVE</option><option value="LOCKED">LOCKED</option><option value="DISABLED">DISABLED</option>
          </select></div>
        <div class="fld"><label>角色</label>
          <div style="display:flex;flex-wrap:wrap;gap:6px">
            <label v-for="r in ROLE_OPTIONS" :key="r" style="display:flex;align-items:center;gap:4px">
              <input type="checkbox" :value="r" v-model="form.roles" />{{ r }}
            </label>
          </div>
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
          <button class="btn" @click="drawer.open=false">取消</button>
          <button class="btn seal" :disabled="saving" @click="save">{{ saving?'保存中…':'保存' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
