<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { api, list } from '@/api/client'
import { toNum } from '@/utils/money'

// —— F 模块真后端契约（snake_case，见 backend funding/mapper.go）——
interface Subject { id: number; code: string; name: string }
interface Budget { id: number; code: string | null; project_id: number; legal_entity_id: number; mode: string; total_approved: string; status: string }
interface BudgetLine {
  id: number; budget_id: number; subject_id: number
  amount_planned: string; amount_frozen: string; amount_used: string; remaining: string
}
interface ExpenseRow { id: number; code: string | null; amount: string; status: string; ai_verdict: string | null; expense_type: string }
interface AiIssue { rule: string; reason: string; clauseRef?: string }
interface AiReviewResult { verdict: string; confidence: number; issues?: AiIssue[] }

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
const lines = ref<LineItem[]>([
  { id: lineSeq++, subjectId: null, amount: 23400, note: '砂轮耗材 · XX精密工具公司', invoiceNo: '' },
  { id: lineSeq++, subjectId: null, amount: 1860, note: '北京→沈阳往返机票', invoiceNo: '' },
])

const curBudget = computed(() => budgets.value.find((b) => b.id === form.budgetId) || budgets.value[0] || null)
const projectLabel = computed(() => {
  const b = curBudget.value
  return b ? `项目 #${b.project_id} · ${b.mode} · 批复 ¥${num(b.total_approved).toLocaleString('zh-CN')}` : '—'
})

const totalAmount = computed(() => lines.value.reduce((a, l) => a + (Number(l.amount) || 0), 0))

function addLine() { lines.value.push({ id: lineSeq++, subjectId: form.subjectId, amount: 0, note: '', invoiceNo: '' }) }
function removeLine(id: number) { lines.value = lines.value.filter((l) => l.id !== id) }
function simulateOcr() {
  addLine()
  const last = lines.value[lines.value.length - 1]
  last.note = '新识别发票 · 待补充事由'
  toast('已识别 2 张发票 · 自动填单成功（演示）')
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

async function load() {
  loading.value = true
  try {
    const [subs, bud, rec] = await Promise.all([
      api.get<{ list: Subject[] }>('/subjects').catch(() => null),
      list<Budget>('/budgets', { status: 'EXECUTING', size: 10 }).catch(() => ({ rows: [] as Budget[], total: 0 })),
      list<ExpenseRow>('/expenses', { size: 4 }).catch(() => ({ rows: [] as ExpenseRow[], total: 0 })),
    ])
    subjects.value = subs?.list ?? []
    budgets.value = bud.rows ?? []
    if (!form.budgetId && budgets.value.length) form.budgetId = budgets.value[0].id
    if (!form.subjectId && subjects.value.length) form.subjectId = subjects.value[0].id
    if (form.budgetId) {
      const w = await api.get<{ list: BudgetLine[] }>(`/budgets/${form.budgetId}/lines`).catch(() => null)
      water.value = w?.list ?? []
    } else {
      water.value = []
    }
    recent.value = rec.rows ?? []
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
    const invNo = lines.value.map((l) => l.invoiceNo.trim()).find(Boolean) || null
    const payload = {
      project_id: b.project_id,
      legal_entity_id: b.legal_entity_id,
      budget_line_id: water.value.find((w) => w.subject_id === form.subjectId)?.id ?? null,
      amount: totalAmount.value.toFixed(2),
      expense_type: TYPE_BY_SUBJECT[subject?.name || ''] || 'OTHER',
      submit_mode: b.mode || '预算制',
      description: form.reason,
      invoice_no: invNo,
      invoice_date: form.invoiceDate || null,
    }
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
function saveDraft() { toast('草稿已保存，可在「我的报销」继续编辑') }
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
          <div class="expense-drop" @click="simulateOcr">
            <div class="big-ic">🧾</div>
            <div style="font-family:var(--serif);font-size:16px;font-weight:700;margin-top:8px">拖入 / 拍摄 发票</div>
            <div style="font-size:12px;color:var(--ink-mute);margin-top:4px">
              支持 PDF / OFD / JPG · 增值税专票、电子普票、行程单自动识别<br>
              <span style="color:var(--ai)">同一商家连号发票、重复报销将在 AI 预审拦截</span>
            </div>
          </div>
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
                  <option v-for="s in subjects" :key="s.id" :value="s.id">{{ s.name }}</option>
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
                <option v-for="s in subjects" :key="s.id" :value="s.id">{{ s.name }}</option>
              </select>
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
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.inv-card select,.inv-card input{font-family:var(--sans);color:var(--ink);outline:none}
.btn:disabled{opacity:.6;cursor:not-allowed}
</style>
