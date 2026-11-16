<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { api, list } from '@/api/client'
import { toNum } from '@/utils/money'

// —— 借款管理（M1-a A2 / F-23）：契约 Loan camelCase、Money 字段 string（design/03 :2984）——
// 生命周期：DRAFT→(submit)SUBMITTED→(approve)APPROVED/REJECTED/RETURNED→(pay)PAID→(write-off/refund)CLOSED
interface Loan {
  id: number
  code: string
  status: string
  projectId: number
  budgetLineId: number | null
  applicantUserId: number
  amount: string
  reason: string | null
  writeOffAmount: string
  refundedAmount: string
  remainingForWriteoff: string
  submittedAt: string | null
  frozenAt: string | null
  paidAt: string | null
  createdAt: string
}
interface Budget { id: number; code: string | null; project_id: number; mode: string; status: string }
interface BudgetLine { id: number; budget_id: number; subject_id: number; amount_planned: string; remaining: string }
interface MyProject { id: number; name?: string; code?: string; title?: string; [k: string]: unknown }

const toast = (m: string) => (window as any).toast?.(m)
const num = (v?: string | number | null) => toNum(v)
const money = (v?: string | number | null) => num(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const LOAN_STATUS_META: Record<string, { tag: string; cls: string }> = {
  DRAFT: { tag: '草稿', cls: 'warn' }, SUBMITTED: { tag: '审批中', cls: 'info' },
  APPROVED: { tag: '已批准', cls: 'ok' }, REJECTED: { tag: '已驳回', cls: 'bad' },
  RETURNED: { tag: '已退回', cls: 'warn' }, PAID: { tag: '已放款', cls: 'ok' },
  CLOSED: { tag: '已结清', cls: 'muted' },
}
const stMeta = (s?: string | null) => LOAN_STATUS_META[s || ''] || { tag: s || '—', cls: 'muted' }

const loading = ref(true)
const rows = ref<Loan[]>([])

async function load() {
  loading.value = true
  try {
    const d = await list<Loan>('/loans', { size: 50 }).catch(() => ({ rows: [] as Loan[], total: 0 }))
    rows.value = d.rows ?? []
  } finally {
    loading.value = false
  }
}
onMounted(load)

// —— 新建借款（POST /loans：projectId/budgetLineId/amount/reason；预算行留空=包干制，不冻结预算）——
const projects = ref<MyProject[]>([])
const budgets = ref<Budget[]>([])
const cDrawer = reactive({ open: false, saving: false })
const cForm = reactive({ projectId: null as number | null, budgetLineId: null as number | null, amount: '', reason: '' })
const cLines = ref<BudgetLine[]>([])
const selProject = computed(() => projects.value.find(p => p.id === cForm.projectId))
const projName = (id?: number | null) => {
  const p = projects.value.find(x => x.id === id)
  return p ? (p.name || p.title || p.code || `项目 #${id}`) : `项目 #${id}`
}

async function reloadCtx() {
  const [ps, bs] = await Promise.all([
    list<MyProject>('/project/mine').catch(() => ({ rows: [] as MyProject[], total: 0 })),
    list<Budget>('/budgets', { status: 'EXECUTING', size: 50 }).catch(() => ({ rows: [] as Budget[], total: 0 })),
  ])
  projects.value = (ps.rows ?? []) as MyProject[]
  budgets.value = bs.rows ?? []
}

function openCreate() {
  cForm.projectId = projects.value[0]?.id ?? null
  cForm.budgetLineId = null
  cForm.amount = ''
  cForm.reason = ''
  cDrawer.open = true
  void onProjectChange()
}

async function onProjectChange() {
  cForm.budgetLineId = null
  cLines.value = []
  const pid = cForm.projectId
  if (!pid) return
  const bs = budgets.value.filter(b => b.project_id === pid)
  const all: BudgetLine[] = []
  for (const b of bs) {
    const w = await api.get<{ list: BudgetLine[] }>(`/budgets/${b.id}/lines`).catch(() => null)
    if (w?.list?.length) all.push(...w.list)
  }
  cLines.value = all
}

async function saveLoan() {
  if (cDrawer.saving) return
  if (!cForm.projectId) { toast('请选择借款项目'); return }
  const amt = num(cForm.amount)
  if (!(amt > 0)) { toast('请填写借款金额（须 > 0）'); return }
  cDrawer.saving = true
  try {
    const payload: Record<string, unknown> = {
      projectId: cForm.projectId,
      budgetLineId: cForm.budgetLineId ?? null, // 空=包干制（提交时不冻结预算行）
      amount: amt.toFixed(2),
      reason: cForm.reason.trim(),
    }
    const created = await api.post<Loan>('/loans', payload)
    toast(`借款单已创建（单号 ${created?.code || '#' + created?.id} · 草稿），可在列表中提交审批`)
    cDrawer.open = false
    await load()
  } catch (e: any) {
    toast('创建失败：' + (e?.message || e))
  } finally {
    cDrawer.saving = false
  }
}

// —— 生命周期动作：submit / approve / pay / write-off / refund（均 POST 子路径）——
async function actSubmit(l: Loan) {
  if (!confirm(`提交借款「${l.code}」进入审批？（预算制将冻结预算行余额，余额不足将被 40902 拒绝）`)) return
  try {
    const r = await api.post<Loan>(`/loans/${l.id}/submit`)
    toast(`借款已提交（${stMeta(r?.status).tag}）· 审批链 R-MANAGER→R-FINANCE`)
    await load()
  } catch (e: any) { toast('提交失败：' + (e?.message || e)) }
}
async function actApprove(l: Loan) {
  if (!confirm(`审批通过借款「${l.code}」（¥${money(l.amount)}）？`)) return
  try {
    const r = await api.post<Loan>(`/loans/${l.id}/approve`, { action: 'approve' })
    toast(`审批动作完成（${stMeta(r?.status).tag}）`)
    await load()
  } catch (e: any) { toast('审批失败：' + (e?.message || e)) }
}
async function actPay(l: Loan) {
  if (!confirm(`放款借款「${l.code}」（¥${money(l.amount)}）？冻结额度将结转为实扣。`)) return
  try {
    await api.post<Loan>(`/loans/${l.id}/pay`)
    toast('借款已放款（已放款），可发起冲销 / 退款')
    await load()
  } catch (e: any) { toast('放款失败：' + (e?.message || e)) }
}
async function actWriteOff(l: Loan) {
  const raw = window.prompt(
    `冲销借款「${l.code}」：输入关联的已批复报销单 id\n（须为 APPROVED 且关联本借款；剩余可冲销 ¥${money(l.remainingForWriteoff)}）`,
  )
  if (raw == null) return
  const eid = Number(String(raw).trim())
  if (!Number.isInteger(eid) || eid <= 0) { toast('请输入有效的报销单 id'); return }
  try {
    const r = await api.post<Loan>(`/loans/${l.id}/write-off`, { expenseId: eid })
    toast(`冲销完成（${stMeta(r?.status).tag}）· 剩余可冲销 ¥${money(r?.remainingForWriteoff)}`)
    await load()
  } catch (e: any) { toast('冲销失败：' + (e?.message || e)) }
}
async function actRefund(l: Loan) {
  const raw = window.prompt(`退款借款「${l.code}」：输入本次退款金额（≤ 剩余可冲销 ¥${money(l.remainingForWriteoff)}）`, l.remainingForWriteoff)
  if (raw == null) return
  const amt = num(raw)
  if (!(amt > 0)) { toast('请输入有效的退款金额'); return }
  try {
    const r = await api.post<Loan>(`/loans/${l.id}/refund`, { amount: amt.toFixed(2) })
    toast(`退款成功 · 剩余可冲销 ¥${money(r?.remainingForWriteoff)}`)
    await load()
  } catch (e: any) { toast('退款失败：' + (e?.message || e)) }
}

void reloadCtx()
</script>

<template>
  <section class="view on" id="v-loan">
    <div class="page-head">
      <div>
        <div class="page-title">借款<em>管理</em></div>
        <div class="page-sub">预算制提交即冻结预算行 · 审批链 R-MANAGER→R-FINANCE · 放款后冲销 / 退款结清</div>
      </div>
      <button class="btn seal" @click="openCreate">＋ 新建借款</button>
    </div>

    <div class="card">
      <div class="card-h">
        <h4>借款单（{{ rows.length }}）</h4>
        <span v-if="loading" style="font-size:12px;color:var(--ink-mute)">加载中…</span>
      </div>
      <div class="card-b" style="overflow:auto">
        <table class="tbl">
          <thead>
            <tr>
              <th>编号</th><th>项目</th><th>预算行</th>
              <th class="num" style="text-align:right">金额</th>
              <th class="num" style="text-align:right">已冲销</th>
              <th class="num" style="text-align:right">已退款</th>
              <th class="num" style="text-align:right">剩余可冲销</th>
              <th>状态</th><th>事由</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="l in rows" :key="l.id">
              <td class="mono">{{ l.code || ('#' + l.id) }}</td>
              <td>{{ projName(l.projectId) }}</td>
              <td class="mono" style="font-size:11px">{{ l.budgetLineId ? '预算行 #' + l.budgetLineId : '包干制' }}</td>
              <td class="mono num" style="text-align:right;font-weight:700">¥ {{ money(l.amount) }}</td>
              <td class="mono num" style="text-align:right">{{ money(l.writeOffAmount) }}</td>
              <td class="mono num" style="text-align:right">{{ money(l.refundedAmount) }}</td>
              <td class="mono num" style="text-align:right">{{ money(l.remainingForWriteoff) }}</td>
              <td><span class="tag" :class="stMeta(l.status).cls">{{ stMeta(l.status).tag }}</span></td>
              <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" :title="l.reason || ''">{{ l.reason || '—' }}</td>
              <td style="white-space:nowrap">
                <button v-if="l.status === 'DRAFT'" class="btn sm seal" @click="actSubmit(l)">提交审批</button>
                <button v-if="l.status === 'SUBMITTED'" class="btn sm seal" @click="actApprove(l)">审批</button>
                <button v-if="l.status === 'APPROVED'" class="btn sm seal" @click="actPay(l)">放款</button>
                <button v-if="l.status === 'PAID'" class="btn sm ghost" @click="actWriteOff(l)">冲销</button>
                <button v-if="l.status === 'PAID'" class="btn sm ghost" @click="actRefund(l)">退款</button>
                <span v-if="l.status === 'CLOSED' || l.status === 'REJECTED'" style="font-size:11px;color:var(--ink-mute)">—</span>
              </td>
            </tr>
            <tr v-if="!loading && !rows.length">
              <td colspan="10" style="text-align:center;color:var(--ink-mute)">暂无借款单；点击右上角「新建借款」创建。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 新建借款抽屉（与 FundingConfigView 的 drawer 交互保持一致） -->
    <div v-if="cDrawer.open" style="position:fixed;inset:0;background:rgba(15,23,42,.35);z-index:60" @click.self="cDrawer.open = false">
      <div style="position:absolute;right:0;top:0;bottom:0;width:420px;background:var(--paper);box-shadow:-12px 0 40px rgba(15,23,42,.18);padding:22px;overflow:auto">
        <div style="display:flex;align-items:center;justify-content:space-between">
          <h4 style="font-family:var(--serif);font-size:16px">新建借款</h4>
          <button class="btn ghost sm" @click="cDrawer.open = false">关闭</button>
        </div>
        <div class="hr-rule" style="margin:12px 0"></div>
        <div class="fld">借款项目</div>
        <select v-model.number="cForm.projectId" @change="onProjectChange" class="fg" style="width:100%">
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ projName(p.id) }}</option>
        </select>
        <div class="fld" style="margin-top:12px">预算行（留空 = 包干制）</div>
        <select v-model.number="cForm.budgetLineId" class="fg" style="width:100%">
          <option :value="null">包干制（不冻结预算行）</option>
          <option v-for="ln in cLines" :key="ln.id" :value="ln.id">预算行 #{{ ln.id }} · 科目 #{{ ln.subject_id }} · 余额 ¥{{ money(ln.remaining) }}</option>
        </select>
        <div class="fld" style="margin-top:12px">借款金额（元）</div>
        <input v-model="cForm.amount" class="fg money-input" inputmode="decimal" placeholder="如 5000.00" style="width:100%" />
        <div class="fld" style="margin-top:12px">借款事由</div>
        <textarea v-model="cForm.reason" class="fg" rows="3" placeholder="出差预支 / 设备采购预付款…" style="width:100%"></textarea>
        <div style="margin-top:16px;display:flex;gap:10px">
          <button class="btn seal" :disabled="cDrawer.saving" @click="saveLoan">{{ cDrawer.saving ? '保存中…' : '创建借款单' }}</button>
          <button class="btn ghost" @click="cDrawer.open = false">取消</button>
        </div>
        <p style="font-size:11.5px;color:var(--ink-mute);line-height:1.8;margin-top:14px">
          创建后为草稿；「提交审批」时预算制将冻结所选预算行余额（包干制不冻结）。审批链：项目负责人（R-MANAGER）→ 财务（R-FINANCE）。
        </p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.fld { font-size: 12px; color: var(--ink-mute); margin-top: 12px; letter-spacing: 1px; }
.mono { font-family: var(--mono); }
.num { font-variant-numeric: tabular-nums; }
.tag.muted { background: #eef1f6; color: #6b7280; }
</style>
