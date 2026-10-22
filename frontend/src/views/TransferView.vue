<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, list } from '@/api/client'

interface DiscCard {
  id: number
  code: string
  title: string
  output_code: string
  maturity_level: number
  expected_value: number
  status: string
  is_core_tech: boolean
}
interface DealRow {
  id: number
  code: string
  subject: string
  subject_code: string
  deal_type: string
  partner_name: string
  amount_text: string
  status: string
  stage: number
  risk?: string
}
interface Opp {
  enterpartner_id: number
  company_name: string
  match_score: number
  confidence: number
  reason: string
  suggestion: string
  budget?: string
}
interface Summary { year_income?: number; year_distributed?: number; split?: string }

const toast = (m: string) => (window as any).toast?.(m)

const disclosures = ref<DiscCard[]>([])
const deals = ref<DealRow[]>([])
const opps = ref<Opp[]>([])
const discTotal = ref(0)
const dealTotal = ref(0)
const income = ref(0)
const distributed = ref(0)
const split = ref('团队 70 / 院所 15 / 个人 15')
const loading = ref(true)
const busy = ref(false)

const STAGES = ['披露', '评估', '谈判', '签约', '到账', '分配']
const DEAL_CLS: Record<string, { label: string; cls: string }> = {
  DRAFT: { label: '起草中', cls: 'info' },
  VALUATED: { label: '外部评估中', cls: 'info' },
  NEGOTIATING: { label: '谈判中', cls: 'warn' },
  DRAFT_CONTRACT: { label: '合同起草', cls: 'warn' },
  UNDER_APPROVAL: { label: '合同审批 ⚠', cls: 'warn' },
  APPROVED: { label: '待签约', cls: 'info' },
  PUBLICIZED: { label: '已签约 · 公示中', cls: 'ok' },
  SIGNED: { label: '已签约', cls: 'ok' },
  EXECUTING: { label: '履约中', cls: 'ok' },
  INCOME_RECEIVED: { label: '已到账', cls: 'ok' },
  DISTRIBUTED: { label: '已分配', cls: 'ok' },
  CLOSED: { label: '已关闭', cls: 'info' },
  TERMINATED: { label: '已终止', cls: 'bad' },
}
// 可挂牌状态（T-05：后端 _guard 允许 VALUATED/NEGOTIATING，其余状态点按钮会 409）
const canPublish = (d: DealRow) => ['VALUATED', 'NEGOTIATING'].includes(d.status)
const dealMeta = (s: string) => DEAL_CLS[s] || { label: s, cls: 'info' }
const typeCls = (t: string) => (t === '作价投资' ? 'seal' : 'info')

const pipeline = computed(() =>
  STAGES.map((label, i) => {
    const reached = deals.value.filter((d) => d.stage >= i).length
    const total = deals.value.length || 1
    return { label, reached, pct: Math.round((reached / total) * 100) }
  }),
)

async function load() {
  loading.value = true
  try {
    const [d, dl] = await Promise.all([
      list<DiscCard>('/disclosure', { mine: true }),
      list<DealRow>('/deal'),
    ])
    disclosures.value = d.rows ?? []
    discTotal.value = d.total ?? d.rows?.length ?? 0
    deals.value = dl.rows ?? []
    dealTotal.value = dl.total ?? dl.rows?.length ?? 0

    const [opp, dist] = await Promise.all([
      api.post<{ list?: Opp[] }>('/ai/opportunity', { top_n: 5 }),
      api.get<{ summary?: Summary }>('/distribution/mine'),
    ])
    opps.value = opp?.list ?? []
    income.value = dist?.summary?.year_income ?? 412
    distributed.value = dist?.summary?.year_distributed ?? 247
    split.value = dist?.summary?.split || split.value
  } catch (e: any) {
    toast('数据加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
onMounted(load)

// —— 披露新成果向导（真实 POST /disclosure，T-01：选成果 + 摘要 + 预期价值）——
interface OutputOption { id: number; code?: string | null; title: string; output_type?: string }
const myOutputs = ref<OutputOption[]>([])
const discOpen = ref(false)
const discSubmitting = ref(false)
const discError = ref('')
const discResult = ref<{ code?: string | null; status?: string } | null>(null)
const fOutput = ref<number | ''>('')
const fDate = ref(new Date().toISOString().slice(0, 10))
const fSummary = ref('')
const fValue = ref<number | ''>('')
const fTrl = ref(5)
const fCore = ref(false)

async function loadOutputs() {
  try {
    const r = await list<OutputOption>('/output/mine', { page: 1, size: 50 })
    myOutputs.value = r.rows
  } catch { /* 静默 */ }
}
const discReady = computed(() => !!fOutput.value && !!fDate.value && !!fSummary.value.trim())

function openDisclosure() {
  discResult.value = null
  discError.value = ''
  fOutput.value = ''
  fDate.value = new Date().toISOString().slice(0, 10)
  fSummary.value = ''
  fValue.value = ''
  fTrl.value = 5
  fCore.value = false
  discOpen.value = true
  if (!myOutputs.value.length) loadOutputs()
}

async function submitDisclosure() {
  if (!discReady.value || discSubmitting.value) return
  discSubmitting.value = true
  discError.value = ''
  try {
    const r = await api.post<{ code?: string | null; status?: string }>('/disclosure', {
      output_id: fOutput.value,
      disclosure_date: fDate.value,
      tech_summary: fSummary.value.trim(),
      expected_value: fValue.value ? String(fValue.value) : null,
      maturity_level: fTrl.value,
      is_core_tech: fCore.value,
    })
    discResult.value = r
    toast('披露已提交，等待评估分派 ✓')
    await load()
  } catch (e: any) {
    discError.value = e?.message || String(e)
  } finally {
    discSubmitting.value = false
  }
}

async function publish(d: DealRow) {
  if (!canPublish(d)) {
    toast(`当前状态「${dealMeta(d.status).label}」不可挂牌（需外部评估中或谈判中）`)
    return
  }
  busy.value = true
  try {
    await api.post(`/deal/${d.id}/publish`, {})
    toast(`「${d.subject}」已挂牌发布，推送国家技术转移平台 ✓`)
    await load()
  } catch (e: any) {
    toast('挂牌失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}

async function pricing(d: DealRow) {
  busy.value = true
  try {
    const r = await api.post<{ price_low?: number; price_high?: number; currency?: string }>(
      `/deal/${d.id}/ai-pricing`,
      {},
    )
    toast(`AI 定价参考：${r?.price_low ?? '—'}–${r?.price_high ?? '—'}${r?.currency || '万'}（最终以评估与谈判为准）`)
  } catch (e: any) {
    toast('定价失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}

const ringPct = (o: Opp) => Math.round((o.match_score ?? 0) * 100)
const ringColor = (o: Opp) => ((o.match_score ?? 0) < 0.8 ? 'var(--warn)' : undefined)
</script>

<template>
  <section class="view on" id="v-transfer">
    <div class="page-head">
      <div>
        <div class="page-title">成果转化<em>看板</em></div>
        <div class="page-sub">披露 → 评估 → 谈判 → 签约 → 到账 → 分配 · 全流程留痕 · 年度公示自动</div>
      </div>
      <button class="btn seal" :disabled="busy" @click="openDisclosure">＋ 披露新成果</button>
    </div>

    <div class="kpi-strip" style="grid-template-columns:repeat(4,1fr)">
      <div class="card stat"><span class="corner">◇</span><div class="lbl">待评估披露</div><div class="num"><span v-if="loading" class="sk">0</span><template v-else>{{ discTotal }}</template></div></div>
      <div class="card stat gold"><span class="corner">◈</span><div class="lbl">谈判中交易</div><div class="num"><span v-if="loading" class="sk">0</span><template v-else>{{ dealTotal }}</template></div></div>
      <div class="card stat"><span class="corner">¥</span><div class="lbl">本年到账</div><div class="num">{{ income }}<small>万</small></div></div>
      <div class="card stat red"><span class="corner">✎</span><div class="lbl">奖励到人</div><div class="num">{{ distributed }}<small>万</small></div><div class="delta">{{ split }}</div></div>
    </div>

    <!-- 转化管道阶段 -->
    <div class="card" style="margin-bottom:16px">
      <div class="card-h"><h4>转化管道</h4><span class="mono" style="font-size:11px;color:var(--ink-mute)">按 {{ dealTotal }} 笔交易累计进度</span></div>
      <div class="card-b">
        <div v-for="p in pipeline" :key="p.label" style="display:flex;align-items:center;gap:12px;margin-bottom:10px;font-size:12px">
          <span style="width:44px;color:var(--ink-mute);flex-shrink:0">{{ p.label }}</span>
          <div class="bar" :class="p.pct >= 70 ? 'b-ok' : p.pct >= 40 ? 'b-warn' : 'b-bad'" style="flex:1"><i :style="{ width: p.pct + '%' }"></i></div>
          <span class="mono" style="width:44px;text-align:right;font-size:11px;color:var(--ink-mute)">{{ p.reached }}/{{ dealTotal }}</span>
        </div>
      </div>
    </div>

    <div class="grid g2" style="margin-bottom:16px">
      <!-- 待转化成果卡片 -->
      <div class="card">
        <div class="card-h"><h4>待转化成果池</h4><span class="tag info">披露 · {{ discTotal }}</span></div>
        <div class="card-b" style="display:flex;flex-direction:column;gap:12px">
          <div v-if="loading" style="color:var(--ink-mute);text-align:center;padding:16px">加载中…</div>
          <div v-else-if="!disclosures.length" style="color:var(--ink-mute);text-align:center;padding:16px">暂无待转化披露。</div>
          <div class="inv-card" v-for="d in disclosures" :key="d.id">
            <div class="conf-ring" :style="`--p:${(d.maturity_level / 9) * 100}%`"><b style="font-size:10px">TRL<br>{{ d.maturity_level }}</b></div>
            <div style="flex:1">
              <b style="font-size:13px">{{ d.title }}</b>
              <div style="font-size:11px;color:var(--ink-mute);margin-top:4px">
                <span class="mono">{{ d.code }} · {{ d.output_code }}</span> · 预期 <b style="color:var(--gold)">¥{{ d.expected_value }}万</b>
                <span v-if="d.is_core_tech" class="tag seal" style="margin-left:6px">核心技术</span>
              </div>
            </div>
            <div class="claim-actions"><button class="btn sm ghost" :disabled="busy" @click="toast('披露详情页尚未开放')">详情</button></div>
          </div>
        </div>
      </div>

      <!-- AI 撮合推荐 · 意向企业 -->
      <div class="card">
        <div class="card-h"><h4>AI 撮合推荐 · 潜在买家</h4><span class="tag ai">专利族 ↔ 企业需求</span></div>
        <div class="card-b" style="display:flex;flex-direction:column;gap:12px">
          <div v-if="loading" style="color:var(--ink-mute);text-align:center;padding:16px">撮合引擎计算中…</div>
          <div v-else-if="!opps.length" style="color:var(--ink-mute);text-align:center;padding:16px">暂无匹配线索。</div>
          <div class="inv-card" v-for="o in opps" :key="o.enterpartner_id">
            <div class="conf-ring" :style="`--p:${ringPct(o)}%`"><b :style="ringColor(o) ? `color:${ringColor(o)}` : undefined">{{ ringPct(o) }}%</b></div>
            <div style="flex:1">
              <b style="font-size:13px">{{ o.company_name }}</b>
              <div style="font-size:11px;color:var(--ink-mute);margin-top:4px">{{ o.reason }}<span v-if="o.budget"> · 预算 {{ o.budget }}</span></div>
              <div style="font-size:11px;color:var(--ai);margin-top:4px">✦ {{ o.suggestion }}</div>
              <div style="margin-top:6px"><button class="btn sm" @click="toast('推介材料生成尚未开放')">生成推介材料</button></div>
            </div>
          </div>
          <div class="hr-rule" style="margin:4px 0"></div>
          <div style="font-size:11.5px;color:var(--ink-mute)">撮合引擎每周基于 2.1 万条公开企业技术需求增量匹配，仅推送给你的成果；转化办拥有全部线索池视图。</div>
        </div>
      </div>
    </div>

    <!-- 进行中的交易 -->
    <div class="card">
      <div class="card-h"><h4>进行中的交易</h4><span class="tag ai">AI 风险条款审查</span></div>
      <div class="card-b" style="padding:0">
        <table class="tbl">
          <thead><tr><th>标的</th><th>方式</th><th>对方</th><th>金额</th><th>阶段</th><th></th></tr></thead>
          <tbody>
            <tr v-if="loading"><td colspan="6" style="text-align:center;color:var(--ink-mute)">加载中…</td></tr>
            <tr v-else-if="!deals.length"><td colspan="6" style="text-align:center;color:var(--ink-mute)">暂无进行中的交易。</td></tr>
            <tr v-for="d in deals" :key="d.id">
              <td>{{ d.subject }}<br><span class="mono" style="font-size:10px;color:var(--ink-mute)">{{ d.subject_code }}</span></td>
              <td><span class="tag" :class="typeCls(d.deal_type)">{{ d.deal_type }}</span></td>
              <td>{{ d.partner_name }}</td>
              <td class="mono">{{ d.amount_text }}</td>
              <td><span class="tag" :class="dealMeta(d.status).cls">{{ dealMeta(d.status).label }}</span></td>
              <td style="white-space:nowrap;text-align:right">
                <button class="btn sm ghost" :disabled="busy" @click="pricing(d)">AI 定价</button>
                <button v-if="canPublish(d)" class="btn sm seal" :disabled="busy" @click="publish(d)">挂牌</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="deals.some((x) => x.risk)" style="margin:0 18px 18px;padding:12px;background:var(--warn-soft);border-radius:5px;font-size:12px;line-height:1.7">
          ⚠ <b>AI 合同审查：</b>「{{ deals.find((x) => x.risk)?.subject }}」第 7.2 条约定<b>改进成果归受让方独有</b>，与院所知识产权政策冲突（参照院知发〔2024〕9号 第十二条），建议改为共有。<b style="cursor:pointer;color:var(--bad)" @click="toast('修订建议生成尚未开放（AI 审查仅输出风险清单）')">查看修订建议 →</b>
        </div>
      </div>
    </div>
  </section>

  <!-- 披露新成果向导（T-01：POST /disclosure，选成果 + 摘要 + 预期价值） -->
  <teleport to="body">
    <div class="tf-mask" v-if="discOpen" @click.self="discOpen = false" @keydown.esc="discOpen = false">
      <div class="tf-modal" role="dialog" aria-label="披露新成果">
        <header class="tf-head">
          <h3>披露新成果</h3>
          <button class="tf-x" @click="discOpen = false" aria-label="关闭">×</button>
        </header>

        <!-- 已提交：回执 -->
        <div class="tf-body" v-if="discResult">
          <div class="tf-line">
            <span class="tag info">{{ discResult.status || 'DRAFT' }}</span>
            <b class="mono">单号 {{ discResult.code || '—' }}</b>
          </div>
          <p class="tf-tip">披露已登记（T-01），后续评估分派（T-03/T-04）与撮合推荐将基于此披露展开。</p>
          <footer class="tf-foot">
            <button class="btn ghost" @click="discResult = null">再披露一条</button>
            <button class="btn" @click="discOpen = false">完成</button>
          </footer>
        </div>

        <!-- 表单 -->
        <div class="tf-body" v-else>
          <div class="tf-form">
            <div class="tf-field"><label>选择成果 *</label>
              <select v-model="fOutput">
                <option value="" disabled>从我的成果库选择</option>
                <option v-for="o in myOutputs" :key="o.id" :value="o.id">
                  {{ o.title }}<template v-if="o.code">（{{ o.code }}）</template>
                </option>
              </select>
              <span v-if="myOutputs.length === 0" style="font-size:11px;color:var(--ink-mute)">您的成果库为空，请先在「成果管理」中登记并认领成果</span>
            </div>
            <div class="tf-field"><label>披露日期 *</label><input type="date" v-model="fDate" /></div>
            <div class="tf-field"><label>技术摘要 *</label>
              <textarea rows="3" v-model="fSummary" placeholder="说明成果核心技术与潜在应用方向"></textarea>
            </div>
            <div class="tf-field"><label>预期转化价值（万元）</label><input type="number" min="0" step="0.01" v-model="fValue" placeholder="选填，如 120" /></div>
            <div class="tf-field"><label>技术成熟度 TRL（1–9）</label>
              <input type="number" min="1" max="9" v-model.number="fTrl" />
            </div>
            <div class="tf-field"><label style="display:flex;align-items:center;gap:6px;cursor:pointer">
              <input type="checkbox" v-model="fCore" style="width:auto" /> 属核心技术（披露与公示将按密级管控）
            </label></div>
          </div>
          <p class="tf-tip">提交后进入「披露 → 评估」管道；评估确认价值与方式后由转化办创建交易并挂牌。</p>
          <p class="tf-err" v-if="discError">✕ {{ discError }}</p>
          <footer class="tf-foot">
            <button class="btn ghost" @click="discOpen = false">取消</button>
            <button class="btn" :disabled="!discReady || discSubmitting" @click="submitDisclosure">{{ discSubmitting ? '提交中…' : '提交披露' }}</button>
          </footer>
        </div>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
.btn[disabled] { opacity: .55; cursor: default; transform: none; }

/* —— 披露新成果弹层 —— */
.tf-mask { position: fixed; inset: 0; background: rgba(28,25,23,.45); backdrop-filter: blur(2px); z-index: 90; display: flex; align-items: center; justify-content: center; padding: 24px; }
.tf-modal { width: min(560px, 94vw); max-height: 88vh; overflow: auto; background: var(--paper); border: 1px solid var(--line-hard); border-radius: 6px; box-shadow: 0 18px 50px rgba(28,25,23,.25); }
.tf-head { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px 12px; border-bottom: 1px solid var(--line); }
.tf-head h3 { margin: 0; font-family: var(--serif); font-size: 17px; }
.tf-x { border: none; background: none; font-size: 22px; line-height: 1; cursor: pointer; color: var(--ink-mute); }
.tf-body { padding: 18px 20px 20px; }
.tf-form { display: flex; flex-direction: column; gap: 12px; margin-bottom: 12px; }
.tf-field { display: flex; flex-direction: column; gap: 5px; }
.tf-field > label { font-size: 12px; color: var(--ink-mute); }
.tf-field input, .tf-field select, .tf-field textarea { border: 1px solid var(--line-hard); border-radius: 4px; padding: 8px 10px; font: inherit; font-size: 13px; background: var(--paper); color: var(--ink); }
.tf-field textarea { resize: vertical; }
.tf-line { display: flex; align-items: center; gap: 12px; }
.tf-tip { font-size: 12px; color: var(--ink-mute); margin: 10px 0 0; }
.tf-err { font-size: 12px; color: var(--bad); margin: 8px 0 0; }
.tf-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
</style>
