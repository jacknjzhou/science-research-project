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
  VALUATED: { label: '外部评估中', cls: 'info' },
  NEGOTIATING: { label: '谈判中', cls: 'warn' },
  UNDER_APPROVAL: { label: '合同审批 ⚠', cls: 'warn' },
  APPROVED: { label: '待签约', cls: 'info' },
  PUBLICIZED: { label: '已签约 · 公示中', cls: 'ok' },
  SIGNED: { label: '已签约', cls: 'ok' },
  INCOME_RECEIVED: { label: '已到账', cls: 'ok' },
}
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

async function newDisclosure() {
  busy.value = true
  try {
    await api.post('/disclosure', {
      output_id: 0,
      disclosure_date: new Date().toISOString().slice(0, 10),
      tech_summary: '一键拟转化披露（演示）',
    })
    toast('披露已提交，等待评估分派 ✓')
  } catch (e: any) {
    toast('披露失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}

async function publish(d: DealRow) {
  busy.value = true
  try {
    await api.post(`/deal/${d.id}/publish`, {})
    toast(`「${d.subject}」已挂牌发布，推送国家技术转移平台 ✓`)
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
      <button class="btn seal" :disabled="busy" @click="newDisclosure">＋ 披露新成果</button>
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
            <div class="claim-actions"><button class="btn sm ghost" :disabled="busy" @click="toast('披露详情已打开（演示）')">详情</button></div>
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
              <div style="margin-top:6px"><button class="btn sm" @click="toast('已生成推介材料草稿（演示）')">生成推介材料</button></div>
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
                <button class="btn sm seal" :disabled="busy" @click="publish(d)">挂牌</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="deals.some((x) => x.risk)" style="margin:0 18px 18px;padding:12px;background:var(--warn-soft);border-radius:5px;font-size:12px;line-height:1.7">
          ⚠ <b>AI 合同审查：</b>「{{ deals.find((x) => x.risk)?.subject }}」第 7.2 条约定<b>改进成果归受让方独有</b>，与院所知识产权政策冲突（参照院知发〔2024〕9号 第十二条），建议改为共有。<b style="cursor:pointer;color:var(--bad)" @click="toast('已生成修订建议（演示）')">查看修订建议 →</b>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.btn[disabled] { opacity: .55; cursor: default; transform: none; }
</style>
