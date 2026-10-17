<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { api } from '@/api/client'
import { auth } from '@/api/auth'

interface MetricValue {
  code: string; name: string; unit: string; version: number
  value: number; data_as_of: string; dq_flag: string; drill_available: boolean
}
interface ForecastRow {
  target_metric: string; predicted_value: number; forecast_date: string
  confidence_interval: { lower: number; upper: number; level: number }
}
interface DrillRow { health: string; count: number }

const toast = (m: string) => (window as any).toast?.(m)

const kpi = ref<Record<string, MetricValue>>({})
const spark = ref<ForecastRow[]>([])
const health = ref<DrillRow[]>([])
const loading = ref(true)
// T20 今日待办卡（/tasks/summary 真数据；接口失败静默回退 0）
const summary = ref<{ todo: number; message: number; warning: number }>({ todo: 0, message: 0, warning: 0 })

async function loadSummary() {
  try {
    const d = await api.get<{ todo: number; message: number; warning: number }>('/tasks/summary')
    if (d) summary.value = d
  } catch { /* 静默 */ }
}

const KPI_CODES = [
  { code: 'in_research_projects', icon: '◫', cls: '',        delta: '▲ 本季新增 2', dir: 'up' },
  { code: 'available_funding',    icon: '¥', cls: ' red',    delta: '▼ 执行率 54%', dir: 'down' },
  { code: 'yearly_outputs',       icon: '✧', cls: ' gold',   delta: '▲ SCI Q1 ×6',  dir: 'up' },
  { code: 'pending_applications', icon: '✎', cls: ' ai',     delta: '国自然面上 · 剩 12 天', dir: 'down' },
  { code: 'pending_reviews',      icon: '☰', cls: '',        delta: '截止 10 月 20 日', dir: '' },
]

const sparkMax = computed(() => Math.max(...spark.value.map((s) => s.predicted_value), 1))
function sparkH(s: ForecastRow) {
  return Math.round((s.predicted_value / sparkMax.value) * 100) + '%'
}
const healthPct = (r: DrillRow) => {
  const total = health.value.reduce((a, b) => a + b.count, 0) || 1
  return Math.round((r.count / total) * 100) + '%'
}
const HEALTH_COLOR = ['', 'var(--warn)', 'var(--bad)']

async function load() {
  loading.value = true
  try {
    const [metrics, fc, drill] = await Promise.all([
      Promise.all(KPI_CODES.map((k) => api.get<MetricValue>(`/dash/metrics/${k.code}`))),
      api.get<{ list: ForecastRow[] }>('/dash/forecast', { target_metric: 'monthly_expense' }),
      api.get<{ rows: DrillRow[] }>('/dash/report/instance/1/drill'),
    ])
    metrics.forEach((m, i) => (kpi.value[KPI_CODES[i].code] = m))
    spark.value = fc?.list ?? []
    health.value = drill?.rows ?? []
  } catch (e: any) {
    toast('数据加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
onMounted(() => {
  // 未认证时挂载（登录页覆盖期）不发无 token 请求（401 白打）；认证就绪后由 watch 触发
  if (auth.isAuthed) { load(); loadSummary() }
})
// 登录成功（含登录页覆盖期挂载的场景）后自动加载数据与今日待办
watch(() => auth.isAuthed, (ok) => {
  if (ok) { load(); loadSummary() }
})
</script>

<template>
  <section class="view on" id="v-dash">
    <div class="page-head">
      <div>
        <div class="page-title">早安，<em>周明远</em> 研究员</div>
        <div class="page-sub mono">2026 年 10 月 13 日 · 星期二 · 今日待办 <b style="color:var(--seal)">{{ summary.todo }}</b> · 消息 <b style="color:var(--ai)">{{ summary.message }}</b> · 预警 <b style="color:var(--bad)">{{ summary.warning }}</b></div>
      </div>
      <button class="btn seal" @click="$router.push({ name: 'editor' })">＋ 新申报</button>
    </div>

    <div class="kpi-strip">
      <div class="card stat" :class="meta.cls" v-for="meta in KPI_CODES" :key="meta.code">
        <span class="corner">{{ meta.icon }}</span>
        <div class="lbl">{{ kpi[meta.code]?.name || meta.code }}</div>
        <div class="num">
          <span v-if="loading" class="sk">00</span>
          <template v-else>{{ kpi[meta.code]?.value ?? 0 }}<small>{{ kpi[meta.code]?.unit }}</small></template>
        </div>
        <div class="delta" :class="meta.dir">{{ meta.delta }}</div>
      </div>
    </div>

    <div class="grid g21">
      <div class="card">
        <div class="card-h"><h4>AI 科研助手 · 今日态势</h4><span class="tag ai">大模型生成</span></div>
        <div class="card-b">
          <div class="alert-line b-add">⚠ <b>风险提醒：</b>重点研发计划《面向高端装备的…》(PRJ-2024-00087) 经费执行率 <b>31%</b>，距结题 5 个月，存在<b>突击支出风险</b>，建议尽快安排设备采购。<a class="lnk-seal" @click="$router.push({ name: 'project' })">查看项目 →</a></div>
          <div class="alert-line b-med">◷ <b>截止提醒：</b>省自然科学基金集中申报将于 <b>10 月 25 日 17:00</b> 截止，你有一份申报书尚未完成形式审查。</div>
          <div class="alert-line b-info">✧ <b>成果匹配：</b>系统为你的团队发现 <b>4 篇</b>疑似新发表论文（Web of Science 增量），等待认领。<a class="lnk-ai" @click="$router.push({ name: 'claim' })">前往认领 →</a></div>
          <div class="divider-double"></div>
          <div style="display:flex;gap:26px">
            <div style="flex:1">
              <div class="mini-lbl">近 6 月经费支出趋势</div>
              <div class="spark">
                <i v-for="(s, i) in spark" :key="i" :class="{ hl: i === spark.length - 1 }" :style="{ height: sparkH(s) }"></i>
              </div>
              <div class="mono spark-x"><span>5月</span><span>10月 ▲ 支出加速</span></div>
            </div>
            <div style="flex:1">
              <div class="mini-lbl">项目健康度分布</div>
              <div class="hbar" v-for="(r, i) in health" :key="r.health">
                <span class="nm">{{ r.health }} ({{ ['绿','黄','红'][i] || '' }})</span>
                <div class="track"><i :style="{ width: healthPct(r), background: HEALTH_COLOR[i] || undefined }"></i></div>
                <span class="v">{{ r.count }} 项</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-h"><h4>关键动态</h4><span class="mono recent-30">近 30 天</span></div>
        <div class="card-b">
          <div class="timeline">
            <div class="tl-item"><div class="t">10-12 09:30</div>报销单 EXP-2026-1187 <b>已支付</b>，凭证同步财务系统</div>
            <div class="tl-item"><div class="t">10-10 15:12</div>论文《Diffusion-guided topo optimization》<b>被认领入库</b>，JCR Q1</div>
            <div class="tl-item red"><div class="t">10-08 11:00</div>项目《面向高端装备…》健康度 <b>由 78 → 64</b>，扣分来源：经费执行偏离</div>
            <div class="tl-item"><div class="t">10-05 10:00</div>伦理批件 ETH-2026-023 <b>年度复审通过</b>，有效期至 2027-10</div>
            <div class="tl-item"><div class="t">09-28 16:40</div>专利「一种自适应减振结构」<b>获授权</b>，进入可转化池</div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.mini-lbl { font-size: 12px; color: var(--ink-mute); margin-bottom: 8px; }
.spark-x { font-size: 10px; color: var(--ink-mute); margin-top: 6px; display: flex; justify-content: space-between; }
.recent-30 { font-size: 11px; color: var(--ink-mute); }
.lnk-seal { color: var(--seal); cursor: pointer; text-decoration: underline; }
.lnk-ai { color: var(--ai); cursor: pointer; text-decoration: underline; }
</style>
