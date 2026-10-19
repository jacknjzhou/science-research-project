<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { auth } from '@/api/auth'

const vrouter = useRouter()

interface Role { id: number; code: string; name: string; is_builtin?: boolean; tenant_id?: number }
const roles = ref<Role[]>([])
const loading = ref(false)
const err = ref('')
const toast = (m: string) => (window as any).toast?.(m)

const canWrite = computed(() => auth.can('/admin/roles POST'))
const canWriteMatrix = computed(() => auth.can('/admin/page-grants PUT'))

// 矩阵页面清单：router.options.routes 过滤 public（自动同步新路由，zh 取 meta.zh）
const pages = computed(() =>
  vrouter.options.routes
    .filter((r) => r.name && !r.meta?.public)
    .map((r) => ({ name: r.name as string, zh: (r.meta?.zh as string) || (r.name as string) })),
)
// '*' 伪角色列 = 所有已登录（原 meta.roles 空/缺省语义）
const STAR = '*'

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

// —— 页面可见性矩阵（PRD 2.9 在线配置；真源 sys_page_grant）——
const matrix = ref<Record<string, Set<string>>>({})
const matrixLoading = ref(false)
const matrixSaving = ref(false)

async function reloadMatrix() {
  matrixLoading.value = true
  try {
    const d = await api.get<{ grants: Array<{ page_name: string; role_code: string }> }>('/page-grants')
    const m: Record<string, Set<string>> = {}
    for (const g of d?.grants ?? []) (m[g.page_name] ??= new Set()).add(g.role_code)
    matrix.value = m
  } catch (e: any) {
    err.value = e?.message || '矩阵加载失败'
  } finally {
    matrixLoading.value = false
  }
}

function isChecked(page: string, role: string): boolean {
  if (role === 'R-ADMIN') return true // 超管恒可见（前端硬编码兜底，防自锁）
  return !!matrix.value[page]?.has(role)
}
function toggle(page: string, role: string): void {
  if (role === 'R-ADMIN') return
  const set = (matrix.value[page] ??= new Set())
  if (set.has(role)) set.delete(role)
  else set.add(role)
  matrix.value = { ...matrix.value } // 触发响应式
}
async function saveMatrix() {
  matrixSaving.value = true
  err.value = ''
  try {
    const grants: Array<{ page_name: string; role_code: string }> = []
    for (const [page, set] of Object.entries(matrix.value)) {
      for (const role of set) grants.push({ page_name: page, role_code: role })
    }
    const d = await api.put<{ grants: Array<{ page_name: string; role_code: string }> }>('/admin/page-grants', { grants })
    auth.applyGrants(d?.grants ?? grants) // 本地矩阵即时生效（本会话菜单/守卫立即反映）
    toast('可见性矩阵已保存；其他在线会话重新登录后生效')
  } catch (e: any) {
    err.value = e?.message || '保存失败'
  } finally {
    matrixSaving.value = false
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
    toast('角色已创建；可在下方「接口权限」面板为其勾选授权')
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
    await reloadMatrix()
  } catch (e: any) {
    err.value = e?.message || '删除失败'
  }
}
// —— 接口权限管理（Django 风格：权限目录 sys_permission + 角色-权限指派 sys_role_permission）——
interface Perm { id: number; code: string; name: string; obj: string; act: string; domain: string; roles: string[] }
const perm = reactive({
  open: false, role: 'R-MANAGER', domain: '', q: '',
  items: [] as Perm[], domains: [] as string[], total: 0, page: 1, size: 50,
  loading: false, saving: false,
})
const permAssigned = ref<Set<string>>(new Set())   // 加载时该角色持有的权限码
const permDirty = ref<Set<string>>(new Set())      // 本地勾选状态
const canWritePerms = computed(() => auth.can('/admin/roles PUT') || auth.can('/api/v1/* PUT'))
const permRole = computed(() => roles.value.find((r) => r.code === perm.role))

async function loadPerms() {
  perm.loading = true
  err.value = ''
  try {
    const qs = new URLSearchParams({
      role_code: perm.role, page: String(perm.page), size: String(perm.size),
    })
    if (perm.domain) qs.set('domain', perm.domain)
    if (perm.q.trim()) qs.set('q', perm.q.trim())
    const d = await api.get<{ total: number; domains: string[]; items: Perm[] }>(
      `/admin/permissions?${qs.toString()}`)
    perm.items = d?.items ?? []
    perm.domains = d?.domains ?? []
    perm.total = d?.total ?? 0
    permAssigned.value = new Set(perm.items.filter((x) => x.roles.includes(perm.role)).map((x) => x.code))
    permDirty.value = new Set(permAssigned.value)
  } catch (e: any) {
    err.value = e?.message || '权限加载失败'
  } finally {
    perm.loading = false
  }
}

function permChecked(code: string): boolean {
  if (perm.role === 'R-ADMIN') return true // 超管通配（后端铁律兜底，防自锁）
  return permDirty.value.has(code)
}
function permToggle(code: string) {
  if (perm.role === 'R-ADMIN') return
  const s = new Set(permDirty.value)
  if (s.has(code)) s.delete(code)
  else s.add(code)
  permDirty.value = s
}
const permDiff = computed(() => {
  const grants: string[] = []
  const revokes: string[] = []
  for (const c of permDirty.value) if (!permAssigned.value.has(c)) grants.push(c)
  for (const c of permAssigned.value) if (!permDirty.value.has(c)) revokes.push(c)
  return { grants, revokes }
})
async function savePerms() {
  const { grants, revokes } = permDiff.value
  if (!grants.length && !revokes.length) { toast('无变更'); return }
  perm.saving = true
  err.value = ''
  try {
    await api.put(`/admin/roles/${perm.role}/permissions`, { grants, revokes })
    toast(`已保存：授权 ${grants.length} 项、回收 ${revokes.length} 项（即时生效；其他在线会话下次请求起生效）`)
    await loadPerms()
  } catch (e: any) {
    err.value = e?.message || '保存失败'
  } finally {
    perm.saving = false
  }
}

onMounted(() => { reload(); reloadMatrix(); loadPerms() })
</script>

<template>
  <div class="card" style="padding:18px">
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
      <h3 style="margin:0">角色与权限</h3>
      <button class="btn sm seal" v-if="canWrite" @click="openCreate">＋ 新增角色</button>
    </div>
    <div v-if="err" style="color:#c0392b;margin:8px 0">{{ err }}</div>
    <p style="opacity:.7;font-size:13px">
      角色目录由管理员维护（新增/改名/删除：内置角色不可删、已绑定用户需先解绑）；页面可见性矩阵为<b>在线配置</b>（真源 <code>sys_page_grant</code>，PRD 2.9，勾选后保存即时生效）；接口权限为<b>在线配置</b>（真源 <code>sys_permission</code> × <code>sys_role_permission</code>，casbin 从 DB 热加载，授权/回收即时生效）；「我的能力」为后端 <code>/auth/me</code> 依策略派生的按钮/操作级集合（粒度②）。新增角色后可在「接口权限」面板直接勾选授权。
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

    <h4 style="display:flex;align-items:center;gap:10px">
      页面可见性矩阵
      <span v-if="canWriteMatrix" style="display:flex;gap:8px;align-items:center;font-weight:400">
        <button class="btn sm" @click="reloadMatrix" :disabled="matrixLoading">{{ matrixLoading ? '加载中…' : '刷新' }}</button>
        <button class="btn sm seal" @click="saveMatrix" :disabled="matrixSaving || matrixLoading">{{ matrixSaving ? '保存中…' : '保存矩阵' }}</button>
      </span>
    </h4>
    <div style="overflow:auto">
      <table class="tbl" style="border-collapse:collapse;font-size:13px">
        <thead>
          <tr>
            <th style="text-align:left">页面 \ 角色</th>
            <th style="text-align:center" title="所有已登录角色可见">已登录*</th>
            <th v-for="r in roles" :key="r.code" style="text-align:center" :title="r.name">{{ r.code.replace('R-','') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in pages" :key="p.name">
            <td style="white-space:nowrap">{{ p.zh }} <span class="mono" style="opacity:.5">{{ p.name }}</span></td>
            <td style="text-align:center">
              <input type="checkbox" :checked="isChecked(p.name, STAR)" :disabled="!canWriteMatrix" @change="toggle(p.name, STAR)" />
            </td>
            <td v-for="r in roles" :key="r.code" style="text-align:center">
              <input v-if="r.code !== 'R-ADMIN'" type="checkbox"
                     :checked="isChecked(p.name, r.code)" :disabled="!canWriteMatrix"
                     @change="toggle(p.name, r.code)" />
              <span v-else title="超管恒可见（防自锁，不入库）">✓</span>
            </td>
          </tr>
          <tr v-if="!pages.length"><td :colspan="roles.length + 2" style="opacity:.6">{{ matrixLoading ? '加载中…' : '无' }}</td></tr>
        </tbody>
      </table>
    </div>
    <p style="opacity:.6;font-size:12px;margin-top:6px">
      白名单制：未勾选 = 不可见；「已登录*」列 = 所有已登录角色可见（含自定义角色）。R-ADMIN 恒可见由前端兜底，不可编辑。保存为全量替换；本会话立即生效，其他在线会话重新登录后生效。
    </p>

    <h4 style="display:flex;align-items:center;gap:10px;margin-top:18px">
      接口权限（角色 × 操作授权）
      <span style="display:flex;gap:8px;align-items:center;font-weight:400">
        <select v-model="perm.role" @change="perm.page = 1; loadPerms()" class="btn sm">
          <option v-for="r in roles" :key="r.code" :value="r.code">{{ r.code }}（{{ r.name }}）</option>
        </select>
        <select v-model="perm.domain" @change="perm.page = 1; loadPerms()" class="btn sm">
          <option value="">全部业务域</option>
          <option v-for="dm in perm.domains" :key="dm" :value="dm">{{ dm }}</option>
        </select>
        <input v-model="perm.q" placeholder="搜索权限码/路径" style="border:1px solid var(--line-hard);border-radius:4px;padding:4px 8px;font-size:12px;width:160px"
               @keydown.enter="perm.page = 1; loadPerms()" />
        <button class="btn sm" @click="perm.page = 1; loadPerms()" :disabled="perm.loading">查询</button>
        <button class="btn sm seal" v-if="canWritePerms" @click="savePerms"
                :disabled="perm.saving || perm.role === 'R-ADMIN' || (!permDiff.grants.length && !permDiff.revokes.length)">
          {{ perm.saving ? '保存中…' : `保存授权（+${permDiff.grants.length}/-${permDiff.revokes.length}）` }}
        </button>
      </span>
    </h4>
    <div style="overflow:auto;max-height:420px;border:1px solid var(--line, #e5e5e5);border-radius:6px">
      <table class="tbl" style="border-collapse:collapse;font-size:12px;width:100%">
        <thead>
          <tr style="text-align:left">
            <th style="width:36px"></th><th>权限码</th><th>方法</th><th>路径模板</th><th>持有人数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="x in perm.items" :key="x.code">
            <td style="text-align:center">
              <input v-if="perm.role !== 'R-ADMIN'" type="checkbox" :checked="permChecked(x.code)"
                     :disabled="!canWritePerms || perm.saving" @change="permToggle(x.code)" />
              <span v-else title="R-ADMIN 通配 /api/v1/*，不可修改">✓</span>
            </td>
            <td class="mono">{{ x.code }}</td>
            <td><span style="background:#eef;border-radius:3px;padding:1px 5px;font-size:11px">{{ x.act }}</span></td>
            <td class="mono" style="opacity:.75">{{ x.obj }}</td>
            <td style="text-align:center" :title="x.roles.join(', ')">{{ x.roles.length }}</td>
          </tr>
          <tr v-if="!perm.items.length"><td colspan="5" style="opacity:.6;padding:8px">{{ perm.loading ? '加载中…' : '无匹配权限' }}</td></tr>
        </tbody>
      </table>
    </div>
    <div style="display:flex;gap:8px;align-items:center;margin-top:6px;font-size:12px;opacity:.75">
      <span>共 {{ perm.total }} 项</span>
      <button class="btn sm mini" :disabled="perm.page <= 1 || perm.loading" @click="perm.page--; loadPerms()">上一页</button>
      <span>{{ perm.page }} / {{ Math.max(1, Math.ceil(perm.total / perm.size)) }}</span>
      <button class="btn sm mini" :disabled="perm.page >= Math.ceil(perm.total / perm.size) || perm.loading" @click="perm.page++; loadPerms()">下一页</button>
      <span style="margin-left:auto">授权/回收即时热生效（casbin enforcer 重载）；「已登录*」菜单可见性请用上方页面矩阵。</span>
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
        <p style="font-size:12px;color:var(--ink-mute)">创建后可在下方「接口权限」面板为该角色勾选 API 授权（即时生效），并可在「用户管理」中为用户授予此角色。</p>
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
