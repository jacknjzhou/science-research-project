<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { api, list } from '@/api/client'

// —— F 模块契约类型（camelCase）——
interface Subject { id: number; code: string; name: string; category: string; isLeaf?: boolean }
interface BudgetLine {
  id: number; subjectId: number; subjectName: string
  amountPlanned: string; amountUsed: string; remaining: string
}
interface ExpenseRow { id: number; code: string; amount: string; status: string; aiVerdict?: string | null }
interface AiIssue { rule: string; reason: string; clauseRef?: string }
interface AiReviewResult { verdict: string; confidence: number; issues?: AiIssue[] }

const toast = (m: string) => (window as any).toast?.(m)
const num = (v?: string | number | null) => (v == null || v === '' ? 0 : Number(v) || 0)

const loading = ref(true)
const submitting = ref(false)

const subjects = ref<Subject[]>([])
const water = ref<BudgetLine[]>([])
const recent = ref<ExpenseRow[]>([])
const aiResult = ref<AiReviewResult | null>(null)

const PROJECTS = [
  { id: 87, label: 'PRJ-2024-00087 磨抛关键技术（可支 ¥268万）' },
  { id: 103, label: 'PRJ-2025-00103 触觉感知（可支 ¥19万）' },
]
const PAY_METHODS = ['公务卡转账（默认）', '对公转账', '现金/备用金']
const TYPE_BY_SUBJECT: Record<string, string> = {
  '材料费': 'MATERIAL', '设备费': 'EQUIPMENT', '差旅费': 'TRAVEL',
  '测试化验加工费': 'OTHER', '劳务费': 'LABOR', '间接费用': 'OTHER',
}

interface LineItem { id: number; subjectId: number | null; amount: number; note: string }
let lineSeq = 1
const form = reactive({
  projectId: 87,
  subjectId: null as number | null,
  payMethod: PAY_METHODS[0],
  reason: 'M6 样机集成耗材采购（砂轮/夹柄/冷却液）；出差参加学会年会并对接联合验证单位。',
})
const lines = ref<LineItem[]>([
  { id: lineSeq++, subjectId: null, amount: 23400, note: '砂轮耗材 · XX精密工具公司（专票 04412317）' },
  { id: lineSeq++, subjectId: null, amount: 1860, note: '北京→沈阳往返机票（行程单 20260928）' },
])

const totalAmount = computed(() => lines.value.reduce((a, l) => a + (Number(l.amount) || 0), 0))

function addLine() { lines.value.push({ id: lineSeq++, subjectId: form.subjectId, amount: 0, note: '' }) }
function removeLine(id: number) { lines.value = lines.value.filter((l) => l.id !== id) }
function simulateOcr() {
  addLine()
  const last = lines.value[lines.value.length - 1]
  last.note = '新识别发票 · 待补充事由'
  toast('已识别 2 张发票 · 自动填单成功（演示）')
}

// 水位条：used/planned
function waterPct(l: BudgetLine) {
  const planned = num(l.amountPlanned)
  return planned ? Math.min(100, Math.round((num(l.amountUsed) / planned) * 100)) : 0
}
const STATUS_META: Record<string, { tag: string; cls: string }> = {
  PAID: { tag: '已支付', cls: 'ok' }, VOUCHER_SYNCED: { tag: '已支付', cls: 'ok' },
  HUMAN_REVIEW: { tag: '财务复核', cls: 'info' }, AI_REVIEW: { tag: 'AI 预审', cls: 'info' },
  SUBMITTED: { tag: '出纳待付', cls: 'info' },
  RETURNED: { tag: '财务复核', cls: 'warn' }, REJECTED: { tag: 'AI 驳回', cls: 'bad' },
  DRAFT: { tag: '草稿', cls: 'warn' },
}

async function load() {
  loading.value = true
  try {
    const [subs, w, rec] = await Promise.all([
      api.get<Subject[]>('/subjects', { category: 'DIRECT' }).catch(() => [] as Subject[]),
      api.get<BudgetLine[]>('/budgets/8801/lines').catch(() => [] as BudgetLine[]),
      list<ExpenseRow>('/expenses', { applicantUserId: 1001, size: 4 }).catch(() => ({ rows: [] as ExpenseRow[], total: 0 })),
    ])
    subjects.value = Array.isArray(subs) ? subs.filter((s) => s.isLeaf !== false) : []
    if (!form.subjectId && subjects.value.length) form.subjectId = subjects.value[0].id
    water.value = Array.isArray(w) ? w : []
    recent.value = rec.rows ?? []
  } catch (e: any) {
    toast('数据加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function submit() {
  if (submitting.value) return
  if (!totalAmount.value) { toast('请至少填写一条报销明细'); return }
  submitting.value = true
  try {
    const subject = subjects.value.find((s) => s.id === form.subjectId)
    const payload = {
      projectId: form.projectId,
      budgetLineId: subject ? subject.id : null,
      amount: totalAmount.value.toFixed(2),
      expenseType: TYPE_BY_SUBJECT[subject?.name || ''] || 'OTHER',
      submitMode: '预算制',
      description: form.reason,
      invoiceIds: lines.value.map((_, i) => 9004412317 + i),
    }
    const created = await api.post<{ id: number; code: string }>('/expenses', payload)
    const expenseId = created?.id
    if (expenseId) {
      await api.post(`/expenses/${expenseId}/submit`).catch(() => null)
      aiResult.value = await api.post<AiReviewResult>('/expense/ai-invoice-review', {
        expenseId, invoiceIds: payload.invoiceIds,
      }).catch(() => null)
    }
    toast(`报销单已提交，AI 预审…${created?.code ? '（' + created.code + '）' : ''}`)
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
        <div class="card-h"><h4>报销信息</h4><span class="mono" style="font-size:11px;color:var(--ink-mute)">单号 EXP-2026-1204（草稿）</span></div>
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
              <input v-model="l.note" placeholder="事由 / 发票号" style="padding:6px 8px;border:1px solid var(--line);border-radius:4px;font-size:11px;color:var(--ink-mute)">
            </div>
            <span class="tag ai" v-if="l.amount > 20000">AI 合规 0.97</span>
            <span class="tag warn" v-else-if="l.amount > 0">AI 提示 0.82</span>
            <button class="btn ghost" style="padding:4px 8px;font-size:11px" @click="removeLine(l.id)">✕</button>
          </div>

          <!-- 主表单 -->
          <div class="form-grid" style="margin-top:6px">
            <div class="fg">
              <label>归属项目 <em>*</em></label>
              <select v-model.number="form.projectId">
                <option v-for="p in PROJECTS" :key="p.id" :value="p.id">{{ p.label }}</option>
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
              <label>支付方式</label>
              <select v-model="form.payMethod">
                <option v-for="m in PAY_METHODS" :key="m" :value="m">{{ m }}</option>
              </select>
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
              <span>{{ l.subjectName }}</span>
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
