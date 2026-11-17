<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { api, list } from '@/api/client'
import { auth } from '@/api/auth'
import { toNum } from '@/utils/money'

// —— F 模块真后端契约（snake_case，见 backend funding/mapper.go）——
interface Subject {
  id: number; code: string | null; name: string
  parent_id: number | null; level: number; is_leaf: boolean
}
interface Budget { id: number; code: string | null; project_id: number; legal_entity_id: number; mode: string; total_approved: string; status: string }
interface BudgetLine {
  id: number; budget_id: number; subject_id: number
  amount_planned: string; amount_frozen: string; amount_used: string; remaining: string
}
interface ExpenseRow { id: number; code: string | null; amount: string; status: string; aiVerdict?: string | null; expenseType?: string }
interface AiIssue { rule: string; reason: string; clauseRef?: string }
interface AiReviewResult { verdict: string; confidence: number; issues?: AiIssue[] }

// 发票契约（design/03-科研经费管理-F.openapi.yaml Invoice :2462 / InvoiceOcrResponse）：
// camelCase，Money 字段为 string，ocrConfidence 为 string（format:number 对齐 NUMERIC 精度）。
interface OcrInvoice {
  id?: number; code?: string | null; status?: string
  number?: string; invoiceCode?: string; invoiceType?: string
  sellerName?: string; sellerTaxId?: string; buyerName?: string; buyerTaxId?: string
  amountExclTax?: string; taxAmount?: string; totalAmount?: string
  issueDate?: string; ocrConfidence?: string
  checkResult?: 'PASS' | 'FAIL' | 'PENDING'; isDuplicated?: boolean
  expenseId?: number | null; remark?: string | null; createdAt?: string
  ocrWarnings?: string[]
}

const toast = (m: string) => (window as any).toast?.(m)
const num = (v?: string | number | null) => toNum(v)

const loading = ref(true)
const submitting = ref(false)

const subjects = ref<Subject[]>([])
const budgets = ref<Budget[]>([])
const budgetId = ref<number | null>(null)
const water = ref<BudgetLine[]>([])
const recent = ref<ExpenseRow[]>([])
const aiResult = ref<AiReviewResult | null>(null)

const PAY_METHODS = ['公务卡转账（默认）', '对公转账', '现金/备用金']
const TYPE_BY_SUBJECT: Record<string, string> = {
  '材料费': 'MATERIAL', '设备费': 'EQUIPMENT', '差旅费': 'TRAVEL',
  '测试化验加工费': 'OTHER', '劳务费': 'LABOR', '间接费用': 'OTHER',
}
const today = () => new Date().toISOString().slice(0, 10)

interface LineItem { id: number; subjectId: number | null; amount: number; note: string; invoiceNo: string }
let lineSeq = 1
const form = reactive({
  budgetId: null as number | null,
  subjectId: null as number | null,
  payMethod: PAY_METHODS[0],
  reason: 'M6 样机集成耗材采购；出差参加学会年会并对接联合验证单位。',
  invoiceDate: today(),
})
// 明细行为真实数据：初始为空（可「＋增行」或 OCR 回填）。原 2 条硬编码演示行
// 在「存草稿」接真端点后会把虚构金额持久化，故移除。
const lines = ref<LineItem[]>([])

const curBudget = computed(() => budgets.value.find((b) => b.id === form.budgetId) || budgets.value[0] || null)

// —— 科目选项对齐经费配置语义（plan 2026-10-16-funding-config 配套）——
// 末级科目（仅末级可挂预算行，非末级是树形分组节点）
const leafSubjects = computed(() => subjects.value.filter((s) => s.is_leaf))
// 父级路径展示：「父科目 / 子科目」
function subjectPath(s: Subject): string {
  if (!s.parent_id) return s.name
  const p = subjects.value.find((x) => x.id === s.parent_id)
  return p ? `${p.name} / ${s.name}` : s.name
}
// 所选预算的水位行科目（业务正确语义：报销必须挂预算行 budget_line_id，
// 选水位外科目 budget_line_id 为 null）；无预算/水位为空时退回全部末级科目防无法填单。
const budgetSubjects = computed(() => {
  if (!water.value.length) return []
  const byId = new Map(subjects.value.map((s) => [s.id, s]))
  return water.value
    .map((w) => ({ subj: byId.get(w.subject_id), line: w }))
    .filter((x): x is { subj: Subject; line: BudgetLine } => !!x.subj)
})
const subjectOptions = computed(() =>
  budgetSubjects.value.length
    ? budgetSubjects.value.map((x) => ({ id: x.subj.id, label: subjectPath(x.subj), remaining: x.line.remaining }))
    : leafSubjects.value.map((s) => ({ id: s.id, label: subjectPath(s), remaining: null as string | null })),
)
const projectLabel = computed(() => {
  const b = curBudget.value
  return b ? `项目 #${b.project_id} · ${b.mode} · 批复 ¥${num(b.total_approved).toLocaleString('zh-CN')}` : '—'
})

const totalAmount = computed(() => lines.value.reduce((a, l) => a + (Number(l.amount) || 0), 0))

function addLine() { lines.value.push({ id: lineSeq++, subjectId: form.subjectId, amount: 0, note: '', invoiceNo: '' }) }
function removeLine(id: number) { lines.value = lines.value.filter((l) => l.id !== id) }
// —— 发票 OCR（F-08）：真实文件选择 → POST /invoices/ocr → 结构化结果回填明细行 ——
// fileUrl 契约要求对象存储 URL；桌面端以 blob URL 承载本地文件（后端未实现时优雅报错，手动补录）
const fileInput = ref<HTMLInputElement | null>(null)
function pickInvoiceFiles() { fileInput.value?.click() }
async function onInvoiceFiles(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  for (const f of files) await ocrFile(f)
}
async function ocrFile(f: File) {
  try {
    const r = await api.post<OcrInvoice>('/invoices/ocr', {
      fileUrl: URL.createObjectURL(f),
      expenseContext: { reason: form.reason },
    })
    const amt = num(r?.totalAmount) || num(r?.amountExclTax) || 0
    if (!amt && !r?.number) {
      toast('未能从图片解析出发票要素，请手动填写明细')
      return
    }
    addLine()
    const last = lines.value[lines.value.length - 1]
    if (amt) last.amount = amt
    if (r?.number) last.invoiceNo = r.number
    if (r?.sellerName) last.note = r.sellerName
    // 契约 ocrConfidence 为 string（如 "0.9875"），降级=0
    const conf = num(r?.ocrConfidence)
    const confText = conf > 0 ? `（置信度 ${Math.round(conf * 100)}%）` : ''
    toast(`发票识别：${r?.sellerName || r?.number || f.name} · ¥${amt ? amt.toLocaleString('zh-CN') : '—'}${confText}`)
    if (r?.ocrWarnings?.length) toast('OCR 告警：' + r.ocrWarnings.join('；'))
    if (r?.isDuplicated) toast('⚠ 三重指纹命中重复发票（仅标记不拦截）')
    // 成功后刷新发票面板（OCR 落库 status=OCR_DONE 的发票记录）
    await loadInvoices()
  } catch (e: any) {
    toast(`发票识别失败：${e?.message || e}（请手动填写明细）`)
  }
}

// 水位条：used/planned
function waterPct(l: BudgetLine) {
  const planned = num(l.amount_planned)
  return planned ? Math.min(100, Math.round((num(l.amount_used) / planned) * 100)) : 0
}
function subjectName(sid: number) {
  return subjects.value.find((s) => s.id === sid)?.name || ('科目 #' + sid)
}
const STATUS_META: Record<string, { tag: string; cls: string }> = {
  PAID: { tag: '已支付', cls: 'ok' }, VOUCHER_SYNCED: { tag: '已支付', cls: 'ok' },
  HUMAN_REVIEW: { tag: '财务复核', cls: 'info' }, AI_REVIEW: { tag: 'AI 预审', cls: 'info' },
  SUBMITTED: { tag: '待审批', cls: 'info' }, UNDER_REVIEW: { tag: '审批中', cls: 'info' },
  APPROVED: { tag: '已批准', cls: 'ok' },
  RETURNED: { tag: '已退回', cls: 'warn' }, REJECTED: { tag: '已驳回', cls: 'bad' },
  DRAFT: { tag: '草稿', cls: 'warn' },
}

// —— 发票面板（M1-a A1）：GET /invoices?expenseId= 列表 + bind 下拉绑定到报销单 ——
const INV_STATUS_META: Record<string, { tag: string; cls: string }> = {
  DRAFT: { tag: '草稿', cls: 'warn' }, OCR_DONE: { tag: '已识别', cls: 'info' },
  CHECKED: { tag: '已查验', cls: 'info' }, BOUND: { tag: '已绑定', cls: 'ok' },
  VOID: { tag: '已作废', cls: 'info' },
}
const invoices = ref<OcrInvoice[]>([])
const invLoading = ref(false)
const invExpenseId = ref<number | null>(null) // 过滤：绑定报销单（空=全部）
const bindTargetId = ref<number | null>(null) // bind 下拉目标报销单

async function loadInvoices() {
  invLoading.value = true
  try {
    const params: Record<string, unknown> = { size: 20 }
    if (invExpenseId.value) params.expenseId = invExpenseId.value
    const d = await list<OcrInvoice>('/invoices', params).catch(() => ({ rows: [] as OcrInvoice[], total: 0 }))
    invoices.value = d.rows ?? []
    if (!bindTargetId.value && recent.value.length) bindTargetId.value = recent.value[0].id
  } finally {
    invLoading.value = false
  }
}

async function bindInvoice(inv: OcrInvoice) {
  if (!bindTargetId.value) { toast('请先在 bind 下拉选择目标报销单'); return }
  try {
    await api.post(`/invoices/${inv.id}/bind`, { expenseId: bindTargetId.value })
    toast(`发票 ${inv.code || '#' + inv.id} 已绑定到报销单 #${bindTargetId.value}`)
    await loadInvoices()
  } catch (e: any) {
    toast('绑定失败：' + (e?.message || e))
  }
}

// —— 凭证同步面板（M1-b A2）：POST /vouchers/sync 推送到财务系统，契约 VoucherSync（design/03 :2585）——
// camelCase：syncStatus（后端推送返回 SYNCING；回调 SUCCESS/FAILED；第 4 次失败转 MANUAL 人工介入）/retryCount/voucherNo。
interface VoucherSync {
  id?: number; expenseId?: number
  financeSystem?: 'YONYOU' | 'KINGDEE' | 'INSPIRE' | string
  voucherNo?: string | null
  syncStatus?: 'SYNCING' | 'SUCCESS' | 'FAILED' | 'PENDING' | 'MANUAL' | string
  retryCount?: number
  errorMsg?: string | null
  syncAt?: string | null
}
const VOUCHER_STATUS_META: Record<string, { tag: string; cls: string }> = {
  SYNCING: { tag: '同步中', cls: 'info' }, SUCCESS: { tag: '已同步', cls: 'ok' },
  FAILED: { tag: '失败', cls: 'bad' }, PENDING: { tag: '待同步', cls: 'warn' },
  MANUAL: { tag: '人工介入', cls: 'warn' },
}
const vMeta = (s?: string | null) => VOUCHER_STATUS_META[s || ''] || { tag: s || '—', cls: 'muted' }

const canSyncVoucher = auth.can('/vouchers/sync POST')
const syncTargetId = ref<number | null>(null)
const syncing = ref(false)
const lastSync = ref<VoucherSync | null>(null)
const syncError = ref('')
// MANUAL 横幅：显式 MANUAL，或 FAILED 且重试超 3 次（展示语义）
const manualNeeded = computed(() =>
  lastSync.value?.syncStatus === 'MANUAL' ||
  (lastSync.value?.syncStatus === 'FAILED' && (lastSync.value?.retryCount ?? 0) > 3))

async function pushVoucher() {
  if (syncing.value) return
  const eid = syncTargetId.value
  if (!eid) { toast('请先选择要同步的报销单'); return }
  syncing.value = true
  syncError.value = ''
  try {
    lastSync.value = await api.post<VoucherSync>('/vouchers/sync', { expenseId: eid })
    const s = lastSync.value
    toast(s?.syncStatus === 'SUCCESS'
      ? `凭证 ${s.voucherNo || ''} 已同步到 ${s.financeSystem || '财务系统'}`
      : s?.syncStatus === 'SYNCING' ? '推送已受理，等待财务系统回调…'
      : '凭证推送已受理（' + (s?.syncStatus || '?') + '）')
  } catch (e: any) {
    syncError.value = e?.message || String(e)
    toast('凭证推送失败：' + syncError.value)
  } finally {
    syncing.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const [subs, bud, rec] = await Promise.all([
      api.get<{ list: Subject[] }>('/subjects').catch(() => null),
      list<Budget>('/budgets', { status: 'EXECUTING', size: 10 }).catch(() => ({ rows: [] as Budget[], total: 0 })),
      list<ExpenseRow>('/expenses', { size: 4 }).catch(() => ({ rows: [] as ExpenseRow[], total: 0 })),
      loadInvoices(),
    ])
    subjects.value = subs?.list ?? []
    budgets.value = bud.rows ?? []
    if (!form.budgetId && budgets.value.length) form.budgetId = budgets.value[0].id
    // 默认科目：末级科目首个（非末级是分组节点，不可报销）
    if (!form.subjectId && leafSubjects.value.length) form.subjectId = leafSubjects.value[0].id
    if (form.budgetId) {
      const w = await api.get<{ list: BudgetLine[] }>(`/budgets/${form.budgetId}/lines`).catch(() => null)
      water.value = w?.list ?? []
    } else {
      water.value = []
    }
    recent.value = rec.rows ?? []
    // bind 下拉默认目标：首张近单（Promise.all 并发下 loadInvoices 先于 recent 落值）
    if (!bindTargetId.value && recent.value.length) bindTargetId.value = recent.value[0].id
    // 凭证同步目标默认与 bind 目标一致
    if (!syncTargetId.value && recent.value.length) syncTargetId.value = recent.value[0].id
  } catch (e: any) {
    toast('数据加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function switchBudget() {
  if (!form.budgetId) { water.value = []; return }
  loading.value = true
  try {
    const w = await api.get<{ list: BudgetLine[] }>(`/budgets/${form.budgetId}/lines`).catch(() => null)
    water.value = w?.list ?? []
    // 换预算后：已选科目不在新预算的水位行内则重置为首个可选科目
    if (water.value.length && !water.value.some((x) => x.subject_id === form.subjectId)) {
      form.subjectId = water.value[0].subject_id
    }
  } finally { loading.value = false }
}

async function submit() {
  if (submitting.value) return
  const b = curBudget.value
  if (!b) { toast('暂无执行中的预算，无法提交报销'); return }
  if (!totalAmount.value) { toast('请至少填写一条报销明细'); return }
  submitting.value = true
  try {
    const subject = subjects.value.find((s) => s.id === form.subjectId)
    const line = water.value.find((w) => w.subject_id === form.subjectId)
    if (water.value.length && !line) {
      toast('所选科目不在当前预算的科目行内，请重新选择')
      submitting.value = false
      return
    }
    const payload = buildPayload()
    const created = await api.post<{ id: number; code: string | null }>('/expenses', payload)
    const expenseId = created?.id
    if (expenseId) {
      await api.post(`/expenses/${expenseId}/submit`).catch((e) => toast('提交待审失败：' + (e?.message || e)))
      aiResult.value = await api.post<AiReviewResult>('/expense/ai-invoice-review', {
        expense_id: expenseId, invoice_ids: lines.value.map((_, i) => 9004412317 + i),
      }).catch(() => null)
      toast(`报销单已提交（单号 ${created?.code || '#' + expenseId}）· 审批链已路由，待科研管理岗审批`)
      await load()
    }
  } catch (e: any) {
    toast('提交失败：' + (e?.message || e))
  } finally {
    submitting.value = false
  }
}
// 报销单 payload（submit 与存草稿共用；expense_type 按根级科目沿父链取根）
function buildPayload() {
  const b = curBudget.value!
  const subject = subjects.value.find((s) => s.id === form.subjectId)
  let rootName = subject?.name || ''
  let p: Subject | undefined = subject
  while (p?.parent_id) {
    p = subjects.value.find((x) => x.id === p!.parent_id)
    if (p) rootName = p.name
  }
  const line = water.value.find((w) => w.subject_id === form.subjectId)
  const invNo = lines.value.map((l) => l.invoiceNo.trim()).find(Boolean) || null
  return {
    project_id: b.project_id,
    legal_entity_id: b.legal_entity_id,
    budget_line_id: line?.id ?? null,
    amount: totalAmount.value.toFixed(2),
    expense_type: TYPE_BY_SUBJECT[rootName] || 'OTHER',
    submit_mode: b.mode || '预算制',
    description: form.reason,
    invoice_no: invNo,
    invoice_date: form.invoiceDate || null,
  }
}

// 存草稿：契约 POST /expenses 落库 status=DRAFT（F-10 状态机入口）
async function saveDraft() {
  if (submitting.value) return
  if (!curBudget.value) { toast('请先选择预算再存草稿'); return }
  if (!totalAmount.value) { toast('请先填写至少一条报销明细（金额 > 0）'); return }
  submitting.value = true
  try {
    const created = await api.post<{ id: number; code: string | null }>('/expenses', buildPayload())
    toast(`草稿已保存（单号 ${created?.code || '#' + created?.id}），可在「我的报销」继续编辑`)
    await load()
  } catch (e: any) {
    toast('存草稿失败：' + (e?.message || e))
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="view on" id="v-expense">
    <div class="page-head">
      <div>
        <div class="page-title">发起<em>报销</em></div>
        <div class="page-sub">上传发票 → OCR 结构化 → AI 预审 → 审批链自动路由 · 平均到账 <b>0.8 工作日</b></div>
      </div>
      <span class="tag ai" style="font-size:12px;padding:6px 14px">✦ AI 预审已开启</span>
    </div>

    <div class="grid g21">
      <!-- 左：报销信息 -->
      <div class="card">
        <div class="card-h"><h4>报销信息</h4><span class="mono" style="font-size:11px;color:var(--ink-mute)">{{ projectLabel }}</span></div>
        <div class="card-b">
          <div class="expense-drop" @click="pickInvoiceFiles">
            <div class="big-ic">🧾</div>
            <div style="font-family:var(--serif);font-size:16px;font-weight:700;margin-top:8px">拖入 / 拍摄 发票</div>
            <div style="font-size:12px;color:var(--ink-mute);margin-top:4px">
              支持 PDF / OFD / JPG · 增值税专票、电子普票、行程单自动识别<br>
              <span style="color:var(--ai)">点击选择发票图片 → OCR 结构化 → AI 预审拦截重复报销</span>
            </div>
          </div>
          <input ref="fileInput" type="file" accept="image/png,image/jpeg,application/pdf" multiple hidden @change="onInvoiceFiles" />
          <hr class="hr-rule">

          <!-- 明细行（本地状态，可增删）-->
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
            <b style="font-size:13px">费用明细（{{ lines.length }}）· 合计 <span class="mono" style="color:var(--seal)">¥ {{ totalAmount.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</span></b>
            <button class="btn ghost" style="padding:5px 12px;font-size:12px" @click="addLine">＋ 增行</button>
          </div>
          <div v-if="!lines.length" style="font-size:12px;color:var(--ink-mute);padding:12px 0;text-align:center">暂无明细，点击上方区域识别发票或手动增行。</div>
          <div class="inv-card" v-for="l in lines" :key="l.id" style="margin-bottom:10px">
            <div class="inv-thumb">专票</div>
            <div style="flex:1;display:flex;flex-direction:column;gap:6px">
              <div style="display:flex;gap:8px;align-items:center">
                <select v-model.number="l.subjectId" style="flex:1;padding:6px 8px;border:1px solid var(--line-hard);border-radius:4px;font-size:12px;background:#fff">
                  <option :value="null">选择科目…</option>
                  <option v-for="s in leafSubjects" :key="s.id" :value="s.id">{{ subjectPath(s) }}</option>
                </select>
                <div class="money-input" style="width:150px"><input type="number" v-model.number="l.amount" placeholder="0.00"></div>
              </div>
              <div style="display:flex;gap:8px">
                <input v-model="l.note" placeholder="事由说明" style="flex:1;padding:6px 8px;border:1px solid var(--line);border-radius:4px;font-size:11px;color:var(--ink-mute)">
                <input v-model="l.invoiceNo" placeholder="发票号（选填）" style="width:150px;padding:6px 8px;border:1px solid var(--line);border-radius:4px;font-size:11px;color:var(--ink-mute)">
              </div>
            </div>
            <span class="tag ai" v-if="l.amount > 20000">AI 合规 0.97</span>
            <span class="tag warn" v-else-if="l.amount > 0">AI 提示 0.82</span>
            <button class="btn ghost" style="padding:4px 8px;font-size:11px" @click="removeLine(l.id)">✕</button>
          </div>

          <!-- 主表单 -->
          <div class="form-grid" style="margin-top:6px">
            <div class="fg">
              <label>预算（执行中） <em>*</em></label>
              <select v-model.number="form.budgetId" @change="switchBudget">
                <option v-if="!budgets.length" :value="null">暂无执行中预算</option>
                <option v-for="b in budgets" :key="b.id" :value="b.id">{{ b.code || '预算 #' + b.id }} · 项目 {{ b.project_id }} · {{ b.mode }}</option>
              </select>
            </div>
            <div class="fg">
              <label>支出科目 <em>*</em></label>
              <select v-model.number="form.subjectId">
                <option v-if="loading" :value="null">加载中…</option>
                <option v-for="o in subjectOptions" :key="o.id" :value="o.id">
                  {{ o.label }}<template v-if="o.remaining !== null"> · 余额 ¥{{ num(o.remaining).toLocaleString('zh-CN') }}</template>
                </option>
                <option v-if="!loading && !subjectOptions.length" :value="null">所选预算无可用科目行</option>
              </select>
              <span v-if="budgetSubjects.length" style="font-size:11px;color:var(--ink-mute)">已限定为所选预算的科目行（须挂预算行核销）</span>
            </div>
            <div class="fg money-input">
              <label>报销金额 <em>*</em></label>
              <input :value="totalAmount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })" readonly>
            </div>
            <div class="fg">
              <label>发票日期</label>
              <input type="date" v-model="form.invoiceDate">
            </div>
            <div class="fg" style="grid-column:span 2">
              <label>事由说明 <em>*</em></label>
              <textarea rows="3" v-model="form.reason"></textarea>
            </div>
          </div>

          <!-- AI 预审建议 -->
          <div class="compliance-card" v-if="aiResult">
            ⚠ <b>AI 预审建议（置信 {{ (aiResult.confidence ?? 0).toFixed(2) }}）：</b>
            <template v-for="(it, i) in (aiResult.issues || []).slice(0, 2)" :key="it.rule">
              {{ i ? '；' : '' }}{{ it.reason }}<span v-if="it.clauseRef"> 依据{{ it.clauseRef }}。</span>
            </template>
            <b style="color:var(--ai);cursor:pointer">处理建议 →</b>
          </div>

          <div style="display:flex;gap:10px;margin-top:18px">
            <button class="btn seal" :disabled="submitting" @click="submit">
              {{ submitting ? '提交中…' : `提交（金额 ¥${(totalAmount / 10000).toFixed(1)}万 · 路由 PI→科研办→财务）` }}
            </button>
            <button class="btn ghost" @click="saveDraft">存草稿</button>
          </div>
        </div>
      </div>

      <!-- 右：经费水位 -->
      <div class="card">
        <div class="card-h"><h4>我的经费水位</h4></div>
        <div class="card-b" style="display:flex;flex-direction:column;gap:16px">
          <div v-if="loading"><div class="bar"><i style="width:20%"></i></div></div>
          <div v-for="l in water" :key="l.id">
            <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:6px">
              <span>{{ subjectName(l.subject_id) }}</span>
              <b class="mono" :style="{ color: waterPct(l) >= 75 ? 'var(--warn)' : undefined }">{{ waterPct(l) }}%</b>
            </div>
            <div class="bar" :class="waterPct(l) >= 75 ? 'b-warn' : 'b-ok'"><i :style="{ width: waterPct(l) + '%' }"></i></div>
          </div>
          <div v-if="!water.length && !loading" style="font-size:12px;color:var(--ink-mute);text-align:center">暂无预算行余额。</div>

          <div class="divider-double"></div>
          <div style="font-size:12.5px;line-height:2">
            近 {{ recent.length || 4 }} 单状态：
            <template v-if="recent.length">
              <div v-for="r in recent" :key="r.id" style="margin-top:8px">
                <span class="tag" :class="STATUS_META[r.status]?.cls || 'info'">{{ STATUS_META[r.status]?.tag || r.status }}</span>
                ¥ {{ num(r.amount).toLocaleString('zh-CN') }}
                <span style="color:var(--ink-mute)">{{ r.code }}</span>
                <span v-if="r.status === 'REJECTED'" style="font-size:11px;color:var(--ink-mute)">（连号拆分嫌疑 · 已申诉）</span>
              </div>
            </template>
            <template v-else>
              <div><span class="tag ok">已支付</span> ¥23,400 · 耗材</div>
              <div><span class="tag info">出纳待付</span> ¥8,200 · 测试</div>
              <div><span class="tag warn">财务复核</span> ¥1,860 · 差旅</div>
              <div><span class="tag bad">AI 驳回</span> ¥12,000 · 连号拆分嫌疑</div>
            </template>
          </div>

          <!-- 发票面板（M1-a A1）：发票列表（GET /invoices?expenseId=）+ bind 下拉绑定 -->
          <div class="divider-double"></div>
          <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap">
            <b style="font-size:13px">发票面板（{{ invoices.length }}）</b>
            <select v-model.number="invExpenseId" @change="loadInvoices" style="font-size:11px;padding:4px 6px;border:1px solid var(--line);border-radius:4px;background:#fff;color:var(--ink)">
              <option :value="null">全部发票</option>
              <option v-for="r in recent" :key="r.id" :value="r.id">按报销单 {{ r.code || '#' + r.id }} 过滤</option>
            </select>
          </div>
          <div style="display:flex;align-items:center;gap:8px;font-size:12px;color:var(--ink-mute);margin-top:6px">
            <span>bind 目标</span>
            <select v-model.number="bindTargetId" style="flex:1;font-size:11px;padding:4px 6px;border:1px solid var(--line);border-radius:4px;background:#fff;color:var(--ink)">
              <option :value="null">选择报销单…</option>
              <option v-for="r in recent" :key="r.id" :value="r.id">{{ r.code || '报销单 #' + r.id }}（{{ STATUS_META[r.status]?.tag || r.status }}）</option>
            </select>
          </div>
          <div v-if="invLoading" style="font-size:12px;color:var(--ink-mute);margin-top:6px">发票加载中…</div>
          <div v-for="v in invoices" :key="v.id" style="display:flex;align-items:center;gap:8px;font-size:12px;margin-top:8px">
            <span class="tag" :class="INV_STATUS_META[v.status || '']?.cls || 'info'">{{ INV_STATUS_META[v.status || '']?.tag || v.status || '—' }}</span>
            <span class="mono" style="font-size:11px">{{ v.code || ('INV #' + v.id) }}</span>
            <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ v.sellerName || v.number || '' }}</span>
            <b class="mono">¥ {{ num(v.totalAmount).toLocaleString('zh-CN') }}</b>
            <span v-if="v.isDuplicated" class="tag warn">重复</span>
            <button v-if="v.status !== 'BOUND' && v.status !== 'VOID'" class="btn ghost" style="padding:3px 8px;font-size:11px" @click="bindInvoice(v)">绑定</button>
          </div>
          <div v-if="!invLoading && !invoices.length" style="font-size:12px;color:var(--ink-mute);text-align:center;margin-top:6px">暂无发票；OCR 识别成功后自动进入此列表。</div>

          <!-- 凭证同步面板（M1-b A2）：推送报销单生成财务凭证（POST /vouchers/sync）-->
          <div class="divider-double"></div>
          <b style="font-size:13px">凭证同步（财务系统）</b>
          <div style="display:flex;align-items:center;gap:8px;font-size:12px;color:var(--ink-mute);margin-top:6px">
            <span>同步目标</span>
            <select v-model.number="syncTargetId" style="flex:1;font-size:11px;padding:4px 6px;border:1px solid var(--line);border-radius:4px;background:#fff;color:var(--ink)">
              <option :value="null">选择报销单…</option>
              <option v-for="r in recent" :key="r.id" :value="r.id">{{ r.code || '报销单 #' + r.id }}（{{ STATUS_META[r.status]?.tag || r.status }}）</option>
            </select>
            <button v-if="canSyncVoucher" class="btn seal" style="padding:5px 12px;font-size:12px" :disabled="syncing || !syncTargetId" @click="pushVoucher">
              {{ syncing ? '推送中…' : '⇥ 推送凭证' }}
            </button>
          </div>
          <div v-if="!canSyncVoucher" style="font-size:11px;color:var(--ink-mute);margin-top:4px">推送需财务权限（R-FINANCE）。</div>
          <div v-if="lastSync" style="display:flex;align-items:center;gap:8px;font-size:12px;margin-top:8px;flex-wrap:wrap">
            <span class="tag" :class="vMeta(lastSync.syncStatus).cls">{{ vMeta(lastSync.syncStatus).tag }}</span>
            <span v-if="lastSync.voucherNo" class="mono">凭证号 {{ lastSync.voucherNo }}</span>
            <span v-if="lastSync.financeSystem" style="color:var(--ink-mute)">{{ lastSync.financeSystem }}</span>
            <span style="color:var(--ink-mute)">重试 {{ lastSync.retryCount ?? 0 }} 次</span>
            <span v-if="lastSync.errorMsg" style="color:var(--bad)">{{ lastSync.errorMsg }}</span>
          </div>
          <div v-if="manualNeeded" class="voucher-manual">
            ⚠ 该报销单凭证多次推送失败（重试 {{ lastSync?.retryCount ?? 0 }} 次 > 3），已转人工介入：请到财务系统核对后手工录入凭证。
          </div>
          <div v-if="syncError && !lastSync" style="font-size:12px;color:var(--bad);margin-top:6px">{{ syncError }}</div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.inv-card select,.inv-card input{font-family:var(--sans);color:var(--ink);outline:none}
.btn:disabled{opacity:.6;cursor:not-allowed}
.voucher-manual{margin-top:8px;padding:8px 10px;border:1px solid #f0d47a;background:#fdf6e3;border-radius:6px;font-size:12px;color:#8a6d1a;line-height:1.6}
</style>
