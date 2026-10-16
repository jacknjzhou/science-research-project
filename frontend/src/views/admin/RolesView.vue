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
    await reloadMatrix()
  } catch (e: any) {
    err.value = e?.message || '删除失败'
  }
}
onMounted(() => { reload(); reloadMatrix() })
</script>

<template>
  <div class="card" style="padding:18px">
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
      <h3 style="margin:0">角色与权限</h3>
      <button class="btn sm seal" v-if="canWrite" @click="openCreate">＋ 新增角色</button>
    </div>
    <div v-if="err" style="color:#c0392b;margin:8px 0">{{ err }}</div>
    <p style="opacity:.7;font-size:13px">
      角色目录由管理员维护（新增/改名/删除：内置角色不可删、已绑定用户需先解绑）；页面可见性矩阵为<b>在线配置</b>（真源 <code>sys_page_grant</code>，PRD 2.9，勾选后保存即时生效）；「我的能力」为后端 <code>/auth/me</code> 依 Casbin 策略派生的按钮/操作级集合（粒度②）。<b>提示</b>：新增角色的 API 授权需在 Casbin 策略（policy.csv）中配置后方可实际访问接口。
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
