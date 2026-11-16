<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { api, list } from '@/api/client'
import { auth } from '@/api/auth'
import { toNum } from '@/utils/money'

// —— 经费配置（F 域 T15 科目树 + F-02/03/04 预算编制/提交/批复；plan 2026-10-16-funding-config）——
// 写权限口径（policy.csv）：科目/预算写仅 R-MANAGER（R-ADMIN 通配）；R-FINANCE 只读可见。
interface Subject {
  id: number; code: string | null; name: string
  parent_id: number | null; level: number
  category: 'DIRECT' | 'INDIRECT' | 'PERFORMANCE'
  is_leaf: boolean; ratio_limit: string | null; sort_no: number
}
interface Budget {
  id: number; code: string | null; project_id: number; legal_entity_id: number
  mode: string; total_approved: string; total_adjusted: string
  version: number; status: string
}
interface BudgetLine {
  id: number; budget_id: number; subject_id: number
  amount_planned: string; amount_used: string; remaining: string
}
interface MyProject { id: number; name?: string; code?: string; title?: string; [k: string]: unknown }

const toast = (m: string) => (window as any).toast?.(m)
const num = (v?: string | number | null) => toNum(v)
const money = (v?: string | number | null) => num(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const loading = ref(true)
const err = ref('')
const canWriteSubjects = computed(() => auth.can('/subjects POST'))
const canWriteBudgets = computed(() => auth.can('/budgets POST'))

// —— 差旅费用标准（M1-a A3 / F-24）：契约 TravelStandard camelCase、Money string（design/03 :3013）——
// 唯一性：同 (tenant, staffCategory, cityTier) 仅一条 ACTIVE（违者 40901）；报销超标仅告警 travelOverLimit（warn-only）
interface TravelStandard {
  id: number; name: string; staffCategory: string; cityTier: string
  accommodationCap: string; mealsCap: string; transportCap: string
  effectiveFrom: string; effectiveTo: string | null
  status: 'ACTIVE' | 'DISABLED'; remark: string | null
}
const tab = ref<'base' | 'travel'>('base')
const canWriteTravel = computed(() => auth.can('/travel-standards POST'))
const canDeleteTravel = computed(() => auth.can('/travel-standards DELETE'))
const travel = ref<TravelStandard[]>([])
const travelLoading = ref(false)
const TS_STATUS_ZH: Record<string, string> = { ACTIVE: '生效中', DISABLED: '已停用' }
const tsCls = (s: string) => (s === 'ACTIVE' ? 'ok' : 'muted')
const capTotal = (t: TravelStandard) => num(t.accommodationCap) + num(t.mealsCap) + num(t.transportCap)
const STAFF_CAT_OPTS = ['普通员工', '中层管理人员'] // 与 seed_demo 词表对齐，仅作输入建议
const CITY_TIER_OPTS = ['一类城市', '二类城市']

async function reloadTravel() {
  travelLoading.value = true
  try {
    const d = await list<TravelStandard>('/travel-standards', { size: 50 }).catch(() => ({ rows: [] as TravelStandard[], total: 0 }))
    travel.value = d.rows ?? []
  } finally {
    travelLoading.value = false
  }
}

// 差旅标准抽屉（新增/编辑；PUT 全量字段，POST 返回 200 envelope ok）
const tDrawer = reactive({ open: false, editing: false, saving: false })
const tForm = reactive({ id: 0, name: '', staffCategory: '', cityTier: '', accommodationCap: '', mealsCap: '', transportCap: '', effectiveFrom: '', effectiveTo: '', remark: '' })
function openTravelCreate() {
  Object.assign(tForm, {
    id: 0, name: '', staffCategory: STAFF_CAT_OPTS[0], cityTier: CITY_TIER_OPTS[0],
    accommodationCap: '', mealsCap: '', transportCap: '',
    effectiveFrom: new Date().toISOString().slice(0, 10), effectiveTo: '', remark: '',
  })
  tDrawer.editing = false
  tDrawer.open = true
}
function openTravelEdit(t: TravelStandard) {
  Object.assign(tForm, {
    id: t.id, name: t.name, staffCategory: t.staffCategory, cityTier: t.cityTier,
    accommodationCap: t.accommodationCap, mealsCap: t.mealsCap, transportCap: t.transportCap,
    effectiveFrom: t.effectiveFrom, effectiveTo: t.effectiveTo ?? '', remark: t.remark ?? '',
  })
  tDrawer.editing = true
  tDrawer.open = true
}
async function saveTravel() {
  if (tDrawer.saving) return
  if (!tForm.name.trim()) { toast('请填写标准名称'); return }
  if (!tForm.staffCategory.trim() || !tForm.cityTier.trim()) { toast('请填写员工类别与城市类别'); return }
  const caps = [tForm.accommodationCap, tForm.mealsCap, tForm.transportCap].map((v) => num(v))
  if (caps.some((c) => !(c > 0))) { toast('住宿 / 伙食 / 交通三项上限均须 > 0'); return }
  if (!tForm.effectiveFrom) { toast('请选择生效起始日'); return }
  tDrawer.saving = true
  err.value = ''
  try {
    const body: Record<string, unknown> = {
      name: tForm.name.trim(),
      staffCategory: tForm.staffCategory.trim(),
      cityTier: tForm.cityTier.trim(),
      accommodationCap: caps[0].toFixed(2),
      mealsCap: caps[1].toFixed(2),
      transportCap: caps[2].toFixed(2),
      effectiveFrom: tForm.effectiveFrom,
      effectiveTo: tForm.effectiveTo || null, // 空=长期有效
      status: 'ACTIVE',
    }
    if (tForm.remark.trim()) body.remark = tForm.remark.trim()
    if (tDrawer.editing) {
      await api.put(`/travel-standards/${tForm.id}`, body)
      toast('差旅标准已更新')
    } else {
      await api.post('/travel-standards', body)
      toast('差旅标准已创建（生效中）；同类别组合重复将被 40901 拒绝')
    }
    tDrawer.open = false
    await reloadTravel()
  } catch (e: any) {
    err.value = e?.message || '保存失败'
  } finally {
    tDrawer.saving = false
  }
}
async function removeTravel(t: TravelStandard) {
  if (!confirm(`删除差旅标准「${t.name}」（${t.staffCategory} × ${t.cityTier}）？`)) return
  try {
    await api.del(`/travel-standards/${t.id}`)
    toast('差旅标准已删除')
    await reloadTravel()
  } catch (e: any) {
    err.value = e?.message || '删除失败'
  }
}

// —— 科目树（GET /subjects 扁平 + 客户端组树，mapper 输出干净字段）——
const subjects = ref<Subject[]>([])
interface TreeNode extends Subject { kids: TreeNode[] }
const tree = computed<TreeNode[]>(() => {
  const byId = new Map<number, TreeNode>()
  for (const s of subjects.value) byId.set(s.id, { ...s, kids: [] })
  const roots: TreeNode[] = []
  for (const n of byId.values()) {
    if (n.parent_id && byId.has(n.parent_id)) byId.get(n.parent_id)!.kids.push(n)
    else roots.push(n)
  }
  const sortRec = (arr: TreeNode[]) => {
    arr.sort((a, b) => a.sort_no - b.sort_no || a.id - b.id)
    arr.forEach((n) => sortRec(n.kids))
  }
  sortRec(roots)
  return roots
})
const CAT_ZH: Record<string, string> = { DIRECT: '直接', INDIRECT: '间接', PERFORMANCE: '绩效' }
const leafSubjects = computed(() => subjects.value.filter((s) => s.is_leaf))

// 科目抽屉（新增/编辑；新增可带 parent）
const sDrawer = reactive({ open: false, editing: false })
const sForm = reactive({ id: 0, parent_id: null as number | null, code: '', name: '', category: 'DIRECT' as Subject['category'], is_leaf: true, ratio_limit: '', sort_no: 0 })
const sSaving = ref(false)
function parentName(pid: number | null) {
  if (!pid) return '（根级）'
  return subjects.value.find((s) => s.id === pid)?.name || ('#' + pid)
}
function openSubjectCreate(parent: TreeNode | null) {
  Object.assign(sForm, { id: 0, parent_id: parent?.id ?? null, code: '', name: '', category: parent?.category ?? 'DIRECT', is_leaf: true, ratio_limit: '', sort_no: 0 })
  sDrawer.editing = false
  sDrawer.open = true
}
function openSubjectEdit(n: TreeNode) {
  Object.assign(sForm, { id: n.id, parent_id: n.parent_id, code: n.code ?? '', name: n.name, category: n.category, is_leaf: n.is_leaf, ratio_limit: n.ratio_limit ?? '', sort_no: n.sort_no })
  sDrawer.editing = true
  sDrawer.open = true
}
async function saveSubject() {
  sSaving.value = true
  err.value = ''
  try {
    if (sDrawer.editing) {
      // 后端 PUT 仅支持 name/ratio_limit/sort_no/remark 局部更新
      await api.put(`/subjects/${sForm.id}`, {
        name: sForm.name.trim(),
        ratio_limit: sForm.ratio_limit || null,
        sort_no: sForm.sort_no,
      })
      toast('科目已更新')
    } else {
      const body: Record<string, unknown> = {
        name: sForm.name.trim(),
        category: sForm.category,
        is_leaf: sForm.is_leaf,
        sort_no: sForm.sort_no,
      }
      if (sForm.parent_id) body.parent_id = sForm.parent_id
      if (sForm.code.trim()) body.code = sForm.code.trim()
      if (sForm.ratio_limit) body.ratio_limit = sForm.ratio_limit
      await api.post('/subjects', body)
      toast('科目已创建')
    }
    sDrawer.open = false
    await reloadSubjects()
  } catch (e: any) {
    err.value = e?.message || '保存失败'
  } finally {
    sSaving.value = false
  }
}
async function removeSubject(n: TreeNode) {
  if (!confirm(`确认删除科目「${n.name}」？存在下级科目或已被预算引用时将被拒绝。`)) return
  try {
    await api.del(`/subjects/${n.id}`)
    toast('科目已删除')
    await reloadSubjects()
  } catch (e: any) {
    // 40901 有子级 / 40902 被预算引用——后端守卫文案直接透出
    err.value = e?.message || '删除失败'
  }
}

// —— 预算（列表/水位/新建/提交/批复）——
const budgets = ref<Budget[]>([])
const statusFilter = ref('')
const budLoading = ref(false)
const BUD_STATUS_ZH: Record<string, string> = {
  DRAFT: '草稿', SUBMITTED: '待批复', UNDER_REVIEW: '审批中', APPROVED: '已批复',
  EXECUTING: '执行中', ADJUSTING: '调整中', RE_APPROVED: '重新批复', CLOSED: '已关闭',
}
const statusCls = (s: string) =>
  s === 'EXECUTING' || s === 'APPROVED' || s === 'RE_APPROVED' ? 'ok' : s === 'DRAFT' ? 'warn' : s === 'SUBMITTED' || s === 'UNDER_REVIEW' ? 'info' : 'muted'

const myProjects = ref<MyProject[]>([])
const mode = ref<'预算制' | '包干制'>('预算制')

// 水位抽屉
const wDrawer = reactive({ open: false, budget: null as Budget | null })
const water = ref<BudgetLine[]>([])
const wLoading = ref(false)
function subjectName(sid: number) {
  return subjects.value.find((s) => s.id === sid)?.name || ('科目 #' + sid)
}
function waterPct(l: BudgetLine) {
  const planned = num(l.amount_planned)
  return planned ? Math.min(100, Math.round((num(l.amount_used) / planned) * 100)) : 0
}
async function openWater(b: Budget) {
  wDrawer.budget = b
  wDrawer.open = true
  wLoading.value = true
  try {
    const w = await api.get<{ list: BudgetLine[] }>(`/budgets/${b.id}/lines`).catch(() => null)
    water.value = w?.list ?? []
  } finally {
    wLoading.value = false
  }
}

// 新建预算抽屉
const bDrawer = reactive({ open: false })
const bForm = reactive({ project_id: null as number | null, legal_entity_id: 1 })
interface BLine { subject_id: number | null; amount: number }
const bLines = ref<BLine[]>([{ subject_id: null, amount: 0 }])
const bSaving = ref(false)
const bTotal = computed(() => bLines.value.reduce((a, l) => a + (Number(l.amount) || 0), 0))
function openBudgetCreate() {
  bLines.value = [{ subject_id: null, amount: 0 }]
  bDrawer.open = true
}
function addBLine() { bLines.value.push({ subject_id: null, amount: 0 }) }
function removeBLine(i: number) { bLines.value = bLines.value.filter((_, idx) => idx !== i) }
async function saveBudget() {
  if (!bForm.project_id) { toast('请选择项目'); return }
  const lines = bLines.value.filter((l) => l.subject_id && Number(l.amount) > 0)
  if (!lines.length) { toast('请至少填写一行有效明细（科目 + 金额 > 0）'); return }
  bSaving.value = true
  err.value = ''
  try {
    await api.post('/budgets', {
      project_id: bForm.project_id,
      legal_entity_id: bForm.legal_entity_id,
      mode: mode.value,
      lines: lines.map((l) => ({ subject_id: l.subject_id, amount: String(l.amount) })),
    })
    toast('预算已创建（草稿），可提交批复')
    bDrawer.open = false
    await reloadBudgets()
  } catch (e: any) {
    err.value = e?.message || '创建失败'
  } finally {
    bSaving.value = false
  }
}
async function submitBudget(b: Budget) {
  if (!confirm(`提交预算「${b.code || '#' + b.id}」进入批复流程？`)) return
  try {
    await api.post(`/budgets/${b.id}/submit`, {})
    toast('预算已提交')
    await reloadBudgets()
  } catch (e: any) {
    err.value = e?.message || '提交失败'
  }
}
async function approveBudget(b: Budget) {
  if (!confirm(`批复通过预算「${b.code || '#' + b.id}」（¥${money(b.total_approved)}）？`)) return
  try {
    await api.post(`/budgets/${b.id}/approve`, {})
    toast('预算已批复')
    await reloadBudgets()
  } catch (e: any) {
    err.value = e?.message || '批复失败'
  }
}

async function reloadSubjects() {
  const s = await api.get<{ list: Subject[] }>('/subjects').catch(() => null)
  subjects.value = s?.list ?? []
}
async function reloadBudgets() {
  budLoading.value = true
  try {
    const params: Record<string, unknown> = { size: 50 }
    if (statusFilter.value) params.status = statusFilter.value
    const d = await list<Budget>('/budgets', params).catch(() => ({ rows: [] as Budget[], total: 0 }))
    budgets.value = d.rows ?? []
  } finally {
    budLoading.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    await Promise.all([
      reloadSubjects(),
      reloadBudgets(),
      reloadTravel(),
      list<MyProject>('/project/mine', { size: 50 }).catch(() => ({ rows: [] as MyProject[], total: 0 })).then((d) => { myProjects.value = d.rows ?? [] }),
    ])
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="card" style="padding:18px">
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
      <h3 style="margin:0">经费配置</h3>
      <span class="tag muted">支出科目树 · 预算编制与批复</span>
    </div>
    <div v-if="err" style="color:#c0392b;margin:8px 0">{{ err }}</div>
    <p style="opacity:.7;font-size:13px">
      报销填单页「预算（执行中）」「支出科目」两个下拉的数据真源：科目为 <code>f_subject</code> 树形字典（末级科目方可挂预算行），预算为 <code>f_budget + f_budget_line</code>。写操作限管理/主管（Casbin 粒度②），财务为只读视图。
    </p>

    <!-- tab 导航：科目与预算 / 差旅标准（M1-a A3，无新路由） -->
    <div style="display:flex;gap:4px;margin:10px 0 14px;border-bottom:2px solid var(--line-hard)">
      <button class="tabbtn" :class="{ on: tab === 'base' }" @click="tab = 'base'">科目与预算</button>
      <button class="tabbtn" :class="{ on: tab === 'travel' }" @click="tab = 'travel'">差旅标准（{{ travel.length }}）</button>
    </div>

    <div v-show="tab === 'base'">
    <!-- ===== 节一：支出科目树 ===== -->
    <h4 style="display:flex;align-items:center;gap:10px">
      支出科目（{{ subjects.length }}）
      <button v-if="canWriteSubjects" class="btn sm seal" @click="openSubjectCreate(null)">＋ 新增根级科目</button>
    </h4>
    <div style="overflow:auto;min-width:0">
      <table class="tbl" style="border-collapse:collapse;font-size:13px;table-layout:fixed;width:100%">
        <thead>
          <tr style="text-align:left">
            <th style="width:44%">科目（树形）</th>
            <th style="width:10%">类目</th>
            <th style="width:10%">末级</th>
            <th style="width:14%">比例上限</th>
            <th style="width:22%" v-if="canWriteSubjects">操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="root in tree" :key="root.id">
            <tr v-for="(n, i) in (function flat(t: TreeNode): TreeNode[] { const out: TreeNode[] = []; const walk = (x: TreeNode) => { out.push(x); x.kids.forEach(walk) }; walk(t); return out })(root)" :key="n.id">
              <td :style="{ paddingLeft: 10 + n.level * 22 + 'px' }">
                <span v-if="n.level > 1" style="opacity:.4;margin-right:4px">└</span>
                <b>{{ n.name }}</b>
                <span v-if="n.code" class="mono" style="opacity:.5;margin-left:6px">{{ n.code }}</span>
              </td>
              <td><span class="tag" :class="n.category === 'DIRECT' ? 'info' : 'muted'">{{ CAT_ZH[n.category] || n.category }}</span></td>
              <td>{{ n.is_leaf ? '是' : '否' }}</td>
              <td class="mono">{{ n.ratio_limit ? (Number(n.ratio_limit) * 100).toFixed(0) + '%' : '—' }}</td>
              <td v-if="canWriteSubjects" style="white-space:nowrap">
                <button class="btn sm mini" @click="openSubjectCreate(n)">+子级</button>
                <button class="btn sm mini" @click="openSubjectEdit(n)">编辑</button>
                <button class="btn sm mini" @click="removeSubject(n)">删除</button>
              </td>
            </tr>
          </template>
          <tr v-if="!tree.length"><td :colspan="canWriteSubjects ? 5 : 4" style="opacity:.6">{{ loading ? '加载中…' : '无' }}</td></tr>
        </tbody>
      </table>
    </div>

    <!-- ===== 节二：预算列表与编制 ===== -->
    <h4 style="display:flex;align-items:center;gap:10px;margin-top:20px">
      预算（{{ budgets.length }}）
      <select v-model="statusFilter" @change="reloadBudgets" style="font-weight:400">
        <option value="">全部状态</option>
        <option v-for="(zh, s) in BUD_STATUS_ZH" :key="s" :value="s">{{ zh }}</option>
      </select>
      <button v-if="canWriteBudgets" class="btn sm seal" @click="openBudgetCreate">＋ 新建预算</button>
    </h4>
    <div style="overflow:auto;min-width:0">
      <table class="tbl" style="border-collapse:collapse;font-size:13px;table-layout:fixed;width:100%">
        <thead>
          <tr style="text-align:left">
            <th style="width:18%">编号</th>
            <th style="width:12%">项目</th>
            <th style="width:10%">模式</th>
            <th style="width:16%" class="num">批复总额</th>
            <th style="width:12%">状态</th>
            <th style="width:8%">版本</th>
            <th style="width:24%">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="b in budgets" :key="b.id">
            <td class="mono">{{ b.code || '预算 #' + b.id }}</td>
            <td>项目 {{ b.project_id }}</td>
            <td>{{ b.mode }}</td>
            <td class="mono num">¥ {{ money(b.total_approved) }}</td>
            <td><span class="tag" :class="statusCls(b.status)">{{ BUD_STATUS_ZH[b.status] || b.status }}</span></td>
            <td>v{{ b.version }}</td>
            <td style="white-space:nowrap">
              <button class="btn sm mini" @click="openWater(b)">水位</button>
              <template v-if="canWriteBudgets">
                <button v-if="b.status === 'DRAFT'" class="btn sm mini" @click="submitBudget(b)">提交</button>
                <button v-if="b.status === 'SUBMITTED'" class="btn sm mini" @click="approveBudget(b)">批复</button>
              </template>
            </td>
          </tr>
          <tr v-if="!budgets.length"><td colspan="7" style="opacity:.6">{{ budLoading ? '加载中…' : '无' }}</td></tr>
        </tbody>
      </table>
    </div>
    </div><!-- /tab base -->

    <!-- ===== 节三：差旅费用标准（M1-a A3 / F-24） ===== -->
    <div v-show="tab === 'travel'">
      <h4 style="display:flex;align-items:center;gap:10px;margin-top:4px;flex-wrap:wrap">
        差旅费用标准（{{ travel.length }}）
        <span style="font-size:12px;font-weight:400;opacity:.6">同一（员工类别 × 城市类别）仅一条生效标准（40901）；报销超标仅告警不拦截</span>
        <button v-if="canWriteTravel" class="btn sm seal" @click="openTravelCreate">＋ 新建标准</button>
      </h4>
      <div style="overflow:auto;min-width:0">
        <table class="tbl" style="border-collapse:collapse;font-size:13px;table-layout:fixed;width:100%">
          <thead>
            <tr style="text-align:left">
              <th style="width:15%">名称</th>
              <th style="width:11%">员工类别</th>
              <th style="width:11%">城市类别</th>
              <th style="width:11%" class="num">住宿/晚</th>
              <th style="width:11%" class="num">伙食/天</th>
              <th style="width:11%" class="num">交通/天</th>
              <th style="width:11%" class="num">合计上限</th>
              <th style="width:13%">有效期</th>
              <th style="width:7%">状态</th>
              <th v-if="canWriteTravel" style="width:12%">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in travel" :key="t.id">
              <td><b>{{ t.name }}</b><span v-if="t.remark" class="mono" style="opacity:.5;margin-left:6px">{{ t.remark }}</span></td>
              <td>{{ t.staffCategory }}</td>
              <td>{{ t.cityTier }}</td>
              <td class="mono num">¥ {{ money(t.accommodationCap) }}</td>
              <td class="mono num">¥ {{ money(t.mealsCap) }}</td>
              <td class="mono num">¥ {{ money(t.transportCap) }}</td>
              <td class="mono num"><b>¥ {{ money(capTotal(t)) }}</b></td>
              <td class="mono" style="font-size:11px">{{ t.effectiveFrom }} ~ {{ t.effectiveTo || '长期' }}</td>
              <td><span class="tag" :class="tsCls(t.status)">{{ TS_STATUS_ZH[t.status] || t.status }}</span></td>
              <td v-if="canWriteTravel" style="white-space:nowrap">
                <button class="btn sm mini" @click="openTravelEdit(t)">编辑</button>
                <button v-if="canDeleteTravel" class="btn sm mini" @click="removeTravel(t)">删除</button>
              </td>
            </tr>
            <tr v-if="!travel.length"><td :colspan="canWriteTravel ? 10 : 9" style="opacity:.6">{{ travelLoading ? '加载中…' : '无' }}</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 科目新增/编辑抽屉 -->
    <div v-if="sDrawer.open" style="position:fixed;inset:0;background:rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;z-index:60">
      <div style="background:#fff;width:min(460px,92vw);max-height:88vh;overflow:auto;padding:20px;border-radius:10px">
        <h3 style="margin-top:0">{{ sDrawer.editing ? '编辑科目' : '新增科目' }}</h3>
        <p style="font-size:12px;color:var(--ink-mute);margin-top:0">上级：{{ parentName(sForm.parent_id) }}</p>
        <div class="fld"><label>科目名称 *</label><input v-model="sForm.name" placeholder="如：测试化验加工费" /></div>
        <div class="fld" v-if="!sDrawer.editing"><label>编码（可选）</label><input v-model="sForm.code" placeholder="如 SUBJ-TEST" /></div>
        <div class="fld" v-if="!sDrawer.editing">
          <label>类目 *</label>
          <select v-model="sForm.category">
            <option value="DIRECT">直接费用</option>
            <option value="INDIRECT">间接费用</option>
            <option value="PERFORMANCE">绩效</option>
          </select>
        </div>
        <div class="fld" v-if="!sDrawer.editing">
          <label>末级（仅末级科目可挂预算行）</label>
          <select v-model="sForm.is_leaf"><option :value="true">是</option><option :value="false">否（还有下级）</option></select>
        </div>
        <div class="fld"><label>比例上限（0~1 的小数，如 0.30 = 30%；可选）</label><input v-model="sForm.ratio_limit" placeholder="0.30" /></div>
        <div class="fld"><label>排序号</label><input v-model.number="sForm.sort_no" type="number" /></div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
          <button class="btn" @click="sDrawer.open = false">取消</button>
          <button class="btn seal" :disabled="sSaving || !sForm.name.trim()" @click="saveSubject">{{ sSaving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>

    <!-- 预算水位抽屉 -->
    <div v-if="wDrawer.open" style="position:fixed;inset:0;background:rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;z-index:60">
      <div style="background:#fff;width:min(560px,92vw);max-height:88vh;overflow:auto;padding:20px;border-radius:10px">
        <h3 style="margin-top:0">预算水位 · {{ wDrawer.budget?.code || '预算 #' + wDrawer.budget?.id }}</h3>
        <p style="font-size:12px;color:var(--ink-mute);margin-top:0">项目 {{ wDrawer.budget?.project_id }} · {{ wDrawer.budget?.mode }} · 批复 ¥{{ money(wDrawer.budget?.total_approved) }}</p>
        <table class="tbl" style="border-collapse:collapse;font-size:13px;table-layout:fixed;width:100%">
          <thead><tr style="text-align:left"><th style="width:28%">科目</th><th style="width:18%" class="num">预算</th><th style="width:18%" class="num">已用</th><th style="width:18%" class="num">余额</th><th style="width:18%">水位</th></tr></thead>
          <tbody>
            <tr v-for="l in water" :key="l.id">
              <td>{{ subjectName(l.subject_id) }}</td>
              <td class="mono num">{{ money(l.amount_planned) }}</td>
              <td class="mono num">{{ money(l.amount_used) }}</td>
              <td class="mono num">{{ money(l.remaining) }}</td>
              <td>
                <div class="wmeter"><div class="wfill" :style="{ width: waterPct(l) + '%' }"></div></div>
                <span style="font-size:11px;opacity:.6">{{ waterPct(l) }}%</span>
              </td>
            </tr>
            <tr v-if="!water.length"><td colspan="5" style="opacity:.6">{{ wLoading ? '加载中…' : '无明细' }}</td></tr>
          </tbody>
        </table>
        <div style="display:flex;justify-content:flex-end;margin-top:12px"><button class="btn" @click="wDrawer.open = false">关闭</button></div>
      </div>
    </div>

    <!-- 新建预算抽屉 -->
    <div v-if="bDrawer.open" style="position:fixed;inset:0;background:rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;z-index:60">
      <div style="background:#fff;width:min(560px,92vw);max-height:88vh;overflow:auto;padding:20px;border-radius:10px">
        <h3 style="margin-top:0">新建预算（草稿）</h3>
        <div class="fld">
          <label>项目 *</label>
          <select v-model.number="bForm.project_id">
            <option :value="null" disabled>选择项目…</option>
            <option v-for="p in myProjects" :key="p.id" :value="p.id">{{ (p.code ? p.code + ' · ' : '') + (p.name || p.title || '项目 #' + p.id) }}</option>
          </select>
        </div>
        <div class="fld">
          <label>经费管理模式 *</label>
          <select v-model="mode"><option>预算制</option><option>包干制</option></select>
        </div>
        <div class="fld"><label>主责法人 ID（默认 1）</label><input v-model.number="bForm.legal_entity_id" type="number" min="1" /></div>
        <h4 style="margin:12px 0 6px">科目明细（仅末级科目）</h4>
        <div v-for="(l, i) in bLines" :key="i" style="display:flex;gap:8px;margin-bottom:8px;align-items:center">
          <select v-model.number="l.subject_id" style="flex:1.4">
            <option :value="null">选择科目…</option>
            <option v-for="s in leafSubjects" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
          <input v-model.number="l.amount" type="number" min="0" step="0.01" placeholder="金额" style="flex:1" />
          <button class="btn sm mini" v-if="bLines.length > 1" @click="removeBLine(i)">✕</button>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px">
          <button class="btn sm" @click="addBLine">＋ 加一行</button>
          <b class="mono">合计 ¥ {{ money(bTotal) }}</b>
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px">
          <button class="btn" @click="bDrawer.open = false">取消</button>
          <button class="btn seal" :disabled="bSaving" @click="saveBudget">{{ bSaving ? '保存中…' : '创建' }}</button>
        </div>
      </div>
    </div>
    <!-- 差旅标准新增/编辑抽屉（M1-a A3） -->
    <div v-if="tDrawer.open" style="position:fixed;inset:0;background:rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;z-index:60">
      <div style="background:#fff;width:min(540px,92vw);max-height:88vh;overflow:auto;padding:20px;border-radius:10px">
        <h3 style="margin-top:0">{{ tDrawer.editing ? '编辑差旅标准' : '新建差旅标准' }}</h3>
        <div class="fld"><label>标准名称 *</label><input v-model="tForm.name" placeholder="如：普通员工一类城市标准" /></div>
        <div style="display:flex;gap:10px">
          <div class="fld" style="flex:1"><label>员工类别 *</label><input v-model="tForm.staffCategory" list="dl-staff-cat" placeholder="普通员工" /></div>
          <div class="fld" style="flex:1"><label>城市类别 *</label><input v-model="tForm.cityTier" list="dl-city-tier" placeholder="一类城市" /></div>
        </div>
        <datalist id="dl-staff-cat"><option v-for="s in STAFF_CAT_OPTS" :key="s" :value="s" /></datalist>
        <datalist id="dl-city-tier"><option v-for="c in CITY_TIER_OPTS" :key="c" :value="c" /></datalist>
        <div style="display:flex;gap:10px">
          <div class="fld" style="flex:1"><label>住宿上限（元/晚）*</label><input v-model="tForm.accommodationCap" inputmode="decimal" placeholder="450" /></div>
          <div class="fld" style="flex:1"><label>伙食上限（元/天）*</label><input v-model="tForm.mealsCap" inputmode="decimal" placeholder="130" /></div>
          <div class="fld" style="flex:1"><label>交通上限（元/天）*</label><input v-model="tForm.transportCap" inputmode="decimal" placeholder="500" /></div>
        </div>
        <div style="display:flex;gap:10px">
          <div class="fld" style="flex:1"><label>生效起始日 *</label><input v-model="tForm.effectiveFrom" type="date" /></div>
          <div class="fld" style="flex:1"><label>失效日（空 = 长期有效）</label><input v-model="tForm.effectiveTo" type="date" /></div>
        </div>
        <div class="fld"><label>备注（可选）</label><input v-model="tForm.remark" placeholder="依据财字〔2025〕12号" /></div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
          <button class="btn" @click="tDrawer.open = false">取消</button>
          <button class="btn seal" :disabled="tDrawer.saving" @click="saveTravel">{{ tDrawer.saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tabbtn { border: none; background: none; padding: 8px 14px; font: inherit; font-size: 13.5px; cursor: pointer; color: var(--ink-mute, #888); border-bottom: 2px solid transparent; margin-bottom: -2px; }
.tabbtn.on { color: var(--ink, #1c2b4a); font-weight: 700; border-bottom-color: var(--seal, #8b2e2e); }
.mono { font-family: var(--mono, monospace); font-size: 12px; }
.tbl .btn.sm.mini { padding: 2px 8px; font-size: 11px; border-radius: 3px; }
.tbl .btn.sm.mini + .btn.sm.mini { margin-left: 4px; }
.num { text-align: right; }
.fld { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; }
.fld label { font-size: 12px; color: var(--ink-mute); }
.fld input, .fld select { border: 1px solid var(--line-hard); border-radius: 4px; padding: 7px 10px; font: inherit; font-size: 13px; }
.wmeter { height: 6px; background: #eee; border-radius: 3px; overflow: hidden; }
.wfill { height: 100%; background: var(--seal, #8b2e2e); }
.tag { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; }
.tag.ok { background: #e6f4ea; color: #1e7a3c; }
.tag.info { background: #e8f0fe; color: #1a56a0; }
.tag.warn { background: #fdf3e0; color: #9a6b1a; }
.tag.muted { background: #f0f0f0; color: #666; }
</style>
