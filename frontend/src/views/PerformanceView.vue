<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, list } from '@/api/client'
import { auth } from '@/api/auth'
import { toNum } from '@/utils/money'

type SchemeStatus = 'DRAFT' | 'ACTIVE' | 'SUPERSEDED'
type RecordStatus = 'CALCULATED' | 'CONFIRMED' | 'APPROVED' | 'PAID' | 'APPEAL' | 'VOID'
type PayoutStatus = 'DRAFT' | 'APPROVING' | 'APPROVED' | 'PAID' | 'REJECTED'
type DataSource = 'R_OUTPUT' | 'F_INCOME' | 'E_PROJECT' | 'T_DEAL' | 'MANUAL'

interface Scheme { id: number; code?: string | null; name: string; period_type: string; effective_period: string; version: number; active: boolean; status: SchemeStatus; scope_dept_id?: number | null; scope_staff_type?: string | null }
interface Factor { id: number; scheme_id: number; factor_code: string; factor_name?: string | null; weight: string; max_score?: string | null; data_source: DataSource; scoring_rule?: unknown; sort_no?: number }
interface SchemeDetail extends Scheme { factors?: Factor[] }
interface RecordItem { id: number; record_id: number; factor_code: string; factor_name?: string | null; metric_value: string; raw_score: string; weighted_score: string; evidence?: unknown[] }
interface PerfRecord { id: number; scheme_id: number; scheme_name?: string | null; staff_user_id: number; staff_name?: string | null; period: string; total_score: string; rank?: number | null; status: RecordStatus }
interface RecordDetail extends PerfRecord { items?: RecordItem[] }
interface Payout { id: number; code?: string | null; record_id: number; payee_user_id: number; payee_name?: string | null; amount: string; period?: string | null; status: PayoutStatus; voucher_code?: string | null }
interface RankItem { rank: number; staff_user_id: number; staff_name?: string | null; total_score: string }

const toast = (m: string) => (window as any).toast?.(m)

const canManage = computed(() => auth.hasAnyRole(['R-MANAGER', 'R-LEADER']))
const canApprove = computed(() => auth.hasAnyRole(['R-MANAGER', 'R-LEADER']))
const canFinance = computed(() => auth.hasAnyRole(['R-FINANCE', 'R-MANAGER']))
const canStaffAct = computed(() => auth.hasAnyRole(['R-STAFF', 'R-MANAGER']))

const REC_CN: Record<RecordStatus, string> = { CALCULATED: '已计算', CONFIRMED: '已确认', APPROVED: '已批准', PAID: '已发放', APPEAL: '申诉中', VOID: '已作废' }
const PAY_CN: Record<PayoutStatus, string> = { DRAFT: '草稿', APPROVING: '审批中', APPROVED: '已批准', PAID: '已发放', REJECTED: '已驳回' }
const SCHEME_CN: Record<SchemeStatus, string> = { DRAFT: '草稿', ACTIVE: '启用中', SUPERSEDED: '已停用' }
const DS_CN: Record<DataSource, string> = { R_OUTPUT: '成果', F_INCOME: '到账经费', E_PROJECT: '在研项目', T_DEAL: '转化合同', MANUAL: '手工' }
function recCls(s: RecordStatus) { return s === 'APPROVED' || s === 'PAID' ? 'ok' : s === 'VOID' ? 'warn' : s === 'APPEAL' ? 'info' : '' }

const tabs = ['scheme', 'record', 'payout', 'me', 'ranking'] as const
type Tab = typeof tabs[number]
const TAB_CN: Record<Tab, string> = { scheme: '考核方案', record: '考核记录', payout: '绩效发放', me: '我的绩效', ranking: '排行榜' }
const tab = ref<Tab>('scheme')
const busy = ref(false)

// —— 方案 tab ——
const schemes = ref<Scheme[]>([])
const curScheme = ref<SchemeDetail | null>(null)
async function loadSchemes() {
  const { rows } = await list<Scheme>('/perf/schemes', { size: 100 })
  schemes.value = rows ?? []
}
async function selectScheme(id: number) {
  curScheme.value = await api.get<SchemeDetail>(`/perf/schemes/${id}`)
}
async function activate(s: Scheme) {
  busy.value = true
  try { await api.post(`/perf/schemes/${s.id}/activate`); toast('方案已启用 ✓'); await loadSchemes(); if (curScheme.value?.id === s.id) await selectScheme(s.id) }
  catch (e: any) { toast('启用失败：' + (e?.message || e)) } finally { busy.value = false }
}
// 触发计算
const calcPeriod = ref('2026Q3')
async function runCalculate(s: Scheme) {
  busy.value = true
  try {
    const r = await api.post<{ computed?: number; inserted?: number }>(`/perf/schemes/${s.id}/calculate`, { period: calcPeriod.value })
    toast(`计算完成：${r?.computed ?? 0} 人 / 落库 ${r?.inserted ?? 0} 条`)
    await loadRecords()
  } catch (e: any) { toast('计算失败：' + (e?.message || e)) } finally { busy.value = false }
}

// —— 记录 tab ——
const records = ref<PerfRecord[]>([])
const curRecord = ref<RecordDetail | null>(null)
async function loadRecords() {
  const { rows } = await list<PerfRecord>('/perf/records', { size: 100 })
  records.value = rows ?? []
}
async function openRecord(id: number) { curRecord.value = await api.get<RecordDetail>(`/perf/records/${id}/detail`) }
async function recAction(rec: PerfRecord, verb: 'confirm' | 'appeal' | 'approve' | 'void', body?: unknown) {
  busy.value = true
  try { await api.post(`/perf/records/${rec.id}/${verb}`, body ?? {}); toast('操作成功 ✓'); await loadRecords(); if (curRecord.value?.id === rec.id) await openRecord(rec.id) }
  catch (e: any) { toast('失败：' + (e?.message || e)) } finally { busy.value = false }
}

// —— 发放 tab ——
const payouts = ref<Payout[]>([])
async function loadPayouts() { const { rows } = await list<Payout>('/perf/payouts', { size: 100 }); payouts.value = rows ?? [] }
async function createPayout(rec: PerfRecord) {
  busy.value = true
  try { await api.post('/perf/payouts', { record_id: rec.id, amount: rec.total_score }); toast('已生成发放单 ✓'); await loadPayouts() }
  catch (e: any) { toast('生成失败：' + (e?.message || e)) } finally { busy.value = false }
}
async function payoutAction(p: Payout, verb: 'approve' | 'pay' | 'reject') {
  busy.value = true
  try { await api.post(`/perf/payouts/${p.id}/${verb}`, {}); toast('发放单已' + verb + ' ✓'); await loadPayouts() }
  catch (e: any) { toast('失败：' + (e?.message || e)) } finally { busy.value = false }
}

// —— 我的绩效 tab ——
const mine = ref<RecordDetail[]>([])
async function loadMine() {
  const d = await api.get<{ list?: RecordDetail[] }>('/perf/me')
  mine.value = d?.list ?? []
}

// —— 排行 tab ——
const rankSchemeId = ref<number | ''>('')
const rankPeriod = ref('2026Q3')
const ranking = ref<RankItem[]>([])
async function loadRanking() {
  if (!rankSchemeId.value) return toast('请先选择方案')
  const d = await api.get<{ list?: RankItem[] }>('/perf/ranking', { scheme_id: rankSchemeId.value, period: rankPeriod.value, top: 20 })
  ranking.value = d?.list ?? []
}

function switchTab(t: Tab) {
  tab.value = t
  const boot: Partial<Record<Tab, () => Promise<void>>> = { scheme: loadSchemes, record: loadRecords, payout: loadPayouts, me: loadMine, ranking: () => Promise.resolve() }
  boot[t]?.().catch((e) => toast('加载失败：' + (e?.message || e)))
}
onMounted(() => { loadSchemes().catch(() => {}); loadRecords().catch(() => {}); rankSchemeId.value && loadRanking().catch(() => {}) })
</script>

<template>
  <section class="view on" id="v-performance">
    <div class="page-head">
      <div>
        <div class="page-title">科研<em>绩效评价</em></div>
        <div class="page-sub">方案 → 计算 → 确认/审批 → 发放 · 指标数据源直连 R/F/E/T 实绩</div>
      </div>
    </div>

    <div class="tabs">
      <span v-for="t in tabs" :key="t" class="tab" :class="{ on: tab === t }" @click="switchTab(t)">{{ TAB_CN[t] }}</span>
    </div>

    <!-- 方案 -->
    <div v-if="tab === 'scheme'" class="panel">
      <div class="card"><div class="card-b">
        <div v-if="!schemes.length" style="color:var(--ink-mute)">暂无方案。</div>
        <div class="row" v-for="s in schemes" :key="s.id" @click="selectScheme(s.id)">
          <div style="flex:1">
            <b>{{ s.name }}</b> <span class="tag" :class="s.status === 'ACTIVE' ? 'ok' : s.status === 'DRAFT' ? '' : 'warn'">{{ SCHEME_CN[s.status] }}</span>
            <div style="font-size:12px;color:var(--ink-mute)">{{ s.code || ('#' + s.id) }} · {{ s.period_type }} · 周期 {{ s.effective_period }} · v{{ s.version }}</div>
          </div>
          <div class="rowact">
            <input class="sel sm" v-model="calcPeriod" style="width:96px" @click.stop />
            <button v-if="s.status !== 'ACTIVE'" class="btn sm ghost" :disabled="busy" @click.stop="activate(s)">启用</button>
            <button class="btn sm seal" :disabled="busy || !canManage" @click.stop="runCalculate(s)">计算</button>
          </div>
        </div>
      </div></div>

      <div class="card" v-if="curScheme"><div class="card-b">
        <div class="sec-title">「{{ curScheme.name }}」指标（{{ curScheme.factors?.length ?? 0 }}）</div>
        <table class="tbl">
          <thead><tr><th>编码</th><th>名称</th><th>数据源</th><th>权重</th><th>上限</th></tr></thead>
          <tbody>
            <tr v-for="f in curScheme.factors" :key="f.id">
              <td>{{ f.factor_code }}</td><td>{{ f.factor_name || '—' }}</td>
              <td><span class="tag info">{{ DS_CN[f.data_source] }}</span></td>
              <td>{{ toNum(f.weight) }}</td><td>{{ f.max_score ? toNum(f.max_score) : '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div></div>
    </div>

    <!-- 记录 -->
    <div v-if="tab === 'record'" class="panel">
      <div class="card"><div class="card-b">
        <div v-if="!records.length" style="color:var(--ink-mute)">暂无记录（先在“方案”页触发计算）。</div>
        <table class="tbl" v-else>
          <thead><tr><th>人员</th><th>周期</th><th>方案</th><th>总分</th><th>排名</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="r in records" :key="r.id">
              <td>{{ r.staff_name || ('用户#' + r.staff_user_id) }}</td>
              <td>{{ r.period }}</td><td>{{ r.scheme_name || '#' + r.scheme_id }}</td>
              <td><b style="color:var(--seal)">{{ toNum(r.total_score).toFixed(2) }}</b></td>
              <td>{{ r.rank ?? '—' }}</td>
              <td><span class="tag" :class="recCls(r.status)">{{ REC_CN[r.status] }}</span></td>
              <td class="rowact">
                <button class="btn xs ghost" @click="openRecord(r.id)">明细</button>
                <button v-if="r.status === 'CALCULATED' && canStaffAct" class="btn xs seal" :disabled="busy" @click="recAction(r, 'confirm')">确认</button>
                <button v-if="r.status === 'CALCULATED' && canStaffAct" class="btn xs ghost" :disabled="busy" @click="recAction(r, 'appeal', { reason: '对指标口径有异议' })">申诉</button>
                <button v-if="(r.status === 'CONFIRMED' || r.status === 'APPEAL') && canApprove" class="btn xs seal" :disabled="busy" @click="recAction(r, 'approve')">审批</button>
                <button v-if="r.status === 'APPROVED' && canFinance" class="btn xs seal" :disabled="busy" @click="createPayout(r)">发放</button>
                <button v-if="r.status !== 'VOID' && canManage" class="btn xs ghost" :disabled="busy" @click="recAction(r, 'void', { reason: '数据修正' })">作废</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div></div>

      <div class="card" v-if="curRecord"><div class="card-b">
        <div class="sec-title">记录 #{{ curRecord.id }} 得分明细</div>
        <table class="tbl">
          <thead><tr><th>指标</th><th>测度值</th><th>原始分</th><th>加权分</th></tr></thead>
          <tbody>
            <tr v-for="it in curRecord.items" :key="it.id">
              <td>{{ it.factor_name || it.factor_code }}</td>
              <td>{{ toNum(it.metric_value) }}</td><td>{{ toNum(it.raw_score).toFixed(2) }}</td>
              <td><b>{{ toNum(it.weighted_score).toFixed(2) }}</b></td>
            </tr>
            <tr v-if="!curRecord.items?.length"><td colspan="4" style="color:var(--ink-mute)">无明细</td></tr>
          </tbody>
        </table>
        <button class="btn sm ghost" style="margin-top:8px" @click="curRecord = null">收起</button>
      </div></div>
    </div>

    <!-- 发放 -->
    <div v-if="tab === 'payout'" class="panel">
      <div class="card"><div class="card-b">
        <div v-if="!payouts.length" style="color:var(--ink-mute)">暂无发放单。</div>
        <table class="tbl" v-else>
          <thead><tr><th>单号</th><th>收款人</th><th>金额</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="p in payouts" :key="p.id">
              <td>{{ p.code || '#' + p.id }}</td>
              <td>{{ p.payee_name || ('用户#' + p.payee_user_id) }}</td>
              <td><b>¥ {{ toNum(p.amount).toFixed(2) }}</b></td>
              <td><span class="tag" :class="p.status === 'PAID' ? 'ok' : p.status === 'REJECTED' ? 'warn' : 'info'">{{ PAY_CN[p.status] }}</span></td>
              <td class="rowact">
                <button v-if="p.status === 'DRAFT' && canFinance" class="btn xs seal" :disabled="busy" @click="payoutAction(p, 'approve')">审批</button>
                <button v-if="p.status === 'APPROVED' && canFinance" class="btn xs seal" :disabled="busy" @click="payoutAction(p, 'pay')">付款</button>
                <button v-if="(p.status === 'DRAFT' || p.status === 'APPROVING') && canFinance" class="btn xs ghost" :disabled="busy" @click="payoutAction(p, 'reject')">驳回</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div></div>
    </div>

    <!-- 我的 -->
    <div v-if="tab === 'me'" class="panel">
      <div class="card" v-for="m in mine" :key="m.id"><div class="card-b">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <b>{{ m.period }} · 总分 <span style="color:var(--seal);font-size:18px">{{ toNum(m.total_score).toFixed(2) }}</span></b>
          <span class="tag" :class="recCls(m.status)">{{ REC_CN[m.status] }}</span>
        </div>
        <table class="tbl" style="margin-top:8px">
          <thead><tr><th>指标</th><th>加权分</th></tr></thead>
          <tbody><tr v-for="it in m.items" :key="it.id"><td>{{ it.factor_name || it.factor_code }}</td><td>{{ toNum(it.weighted_score).toFixed(2) }}</td></tr></tbody>
        </table>
      </div></div>
      <div v-if="!mine.length" class="card"><div class="card-b" style="text-align:center;color:var(--ink-mute);padding:24px">暂无属于你的绩效记录。</div></div>
    </div>

    <!-- 排行 -->
    <div v-if="tab === 'ranking'" class="panel">
      <div class="filter-row">
        <select class="sel" v-model="rankSchemeId">
          <option :value="''">选择方案…</option>
          <option v-for="s in schemes" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
        <input class="sel" v-model="rankPeriod" style="width:110px" />
        <button class="btn sm seal" :disabled="busy" @click="loadRanking">查询</button>
      </div>
      <div class="card"><div class="card-b">
        <table class="tbl">
          <thead><tr><th>名次</th><th>人员</th><th>总分</th></tr></thead>
          <tbody>
            <tr v-for="rk in ranking" :key="rk.rank">
              <td><b :style="rk.rank <= 3 ? 'color:var(--gold)' : undefined">{{ rk.rank }}</b></td>
              <td>{{ rk.staff_name || ('用户#' + rk.staff_user_id) }}</td>
              <td>{{ toNum(rk.total_score).toFixed(2) }}</td>
            </tr>
            <tr v-if="!ranking.length"><td colspan="3" style="color:var(--ink-mute)">选择方案后点“查询”</td></tr>
          </tbody>
        </table>
      </div></div>
    </div>
  </section>
</template>

<style scoped>
.tabs { display:flex; gap:6px; margin:6px 0 14px; flex-wrap:wrap; }
.tab { padding:6px 14px; border:1px solid var(--line,#d8d2c4); border-radius:20px; font-size:13px; cursor:pointer; background:#fff; }
.tab.on { background:var(--seal,#b5462f); color:#fff; border-color:var(--seal,#b5462f); }
.panel { display:flex; flex-direction:column; gap:12px; }
.row { display:flex; justify-content:space-between; align-items:center; padding:10px 6px; border-bottom:1px dashed var(--line,#eee); cursor:pointer; }
.row:hover { background:var(--hover,#fbf8f0); }
.rowact { display:flex; gap:6px; align-items:center; }
.btn.xs { font-size:11px; padding:2px 8px; }
.tbl { width:100%; border-collapse:collapse; font-size:12.5px; }
.tbl th { text-align:left; color:var(--ink-mute); font-weight:600; padding:6px; border-bottom:1px solid var(--line,#e5e0d5); }
.tbl td { padding:6px; border-bottom:1px solid var(--line,#f2eee4); }
.sel { font-size:12px; padding:5px 8px; border:1px solid var(--line,#d8d2c4); border-radius:6px; background:#fff; }
.sel.sm { padding:3px 6px; }
.sec-title { font-family:var(--serif); font-weight:700; margin-bottom:8px; font-size:13px; }
.filter-row { display:flex; gap:10px; align-items:center; margin-bottom:12px; flex-wrap:wrap; }
</style>
