<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, list } from '@/api/client'
import { toNum, toWan } from '@/utils/money'

// —— F-18 大屏聚合（camelCase + 演示扩展字段）——
interface Dept { departmentId: number; deptName: string; executionRate: number; amount: string }
interface Trend { month: string; executionRate: number }
interface Bucket { name: string; count: number }
interface CostPool { name: string; direct: number; indirect: number; amount: string; tone: string }
interface Alert { level: string; tag: string; text: string }
interface Funding {
  totalBudget: string; yearIncome: string; executionRate: number; violationCount: number
  verticalRatio?: number; horizontalRatio?: number; selfRatio?: number
  expectedRate?: number; deviatedProjects?: number; aiRejectedAmount?: string
  auditTraceRate?: number; evidenceMissing?: number; evidenceFixed?: number
  aiBreakdown?: Bucket[]; deptHeatmap?: Dept[]; trend12Months?: Trend[]
  costPool?: CostPool[]
  alerts?: { during?: Alert[]; pre?: Alert[]; post?: Alert[] }
}
interface Screen { id: number; code: string; name: string; theme?: string; status?: string; data_as_of_expr?: string }
interface MetricValue { code: string; name: string; unit: string; value: number }

const toast = (m: string) => (window as any).toast?.(m)
const num = (v?: string | number | null) => toNum(v)
const wan = (s?: string | number | null) => toWan(s)

const loading = ref(true)
const f = ref<Funding>({} as Funding)
const screenName = ref('科研经费监督 · 一舱三预警')
const dataAsOf = ref('2026-10-12')
const metrics = ref<MetricValue[]>([])

const DEPT_NAMES = ['制造所', '机器人所', '传感所', '材料所', '信息室', '工艺', '联合']
const HOT_THRESHOLD = 50

// 后端 alerts 为 {pre:{count},during:{count},post:{count}} 计数桶（mock 下可能是数组形式，双向兼容）。
const ALERT_STAGE: Array<{ key: string; tag: string }> = [
  { key: 'pre', tag: '事前·预算' },
  { key: 'during', tag: '事中·支出' },
  { key: 'post', tag: '事后·决算' },
]
const mergedAlerts = computed<Alert[]>(() => {
  const a = f.value.alerts as any
  if (!a) return []
  const out: Alert[] = []
  for (const { key, tag } of ALERT_STAGE) {
    const v = a[key]
    if (Array.isArray(v)) {
      out.push(...(v as Alert[]))
    } else if (v && typeof v === 'object' && typeof v.count === 'number') {
      if (v.count > 0) out.push({ level: v.count > 10 ? 'p1' : 'p2', tag, text: `${tag}环节待处理事项 ${v.count} 项，请及时跟进` })
    }
  }
  return out
})
const aiBuckets = computed(() => f.value.aiBreakdown || [])
const aiBucketTotal = computed(() => aiBuckets.value.reduce((s, b) => s + (b.count || 0), 0))

async function load() {
  loading.value = true
  try {
    const [funding, screens, metricRes] = await Promise.all([
      api.get<Funding>('/dashboard/funding').catch(() => null),
      list<Screen>('/dash/screens', { size: 1 }).catch(() => ({ rows: [] as Screen[], total: 0 })),
      Promise.all(
        ['in_research_projects', 'available_funding', 'yearly_outputs'].map((code) =>
          api.get<MetricValue>(`/dash/metrics/${code}`).catch(() => null),
        ),
      ),
    ])
    f.value = (funding || {}) as Funding
    const sc = screens?.rows?.[0]
    if (sc?.name) screenName.value = sc.name
    if (sc?.data_as_of_expr) dataAsOf.value = '2026-10-12 · ' + sc.data_as_of_expr
    metrics.value = metricRes.filter((m): m is MetricValue => !!m)
  } catch (e: any) {
    toast('大屏数据加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<template>
  <section class="view on" id="v-bigscreen">
    <div class="screen-view">
      <div class="scr-title">
        <h3>{{ screenName }}</h3>
        <div class="stsub">SUPERVISION COCKPIT · 数据截至 {{ dataAsOf }} · 演示租户：启元研究院</div>
      </div>

      <!-- 顶部 4 KPI -->
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:16px">
        <div class="scr-card">
          <h6>经费总盘子</h6>
          <div class="scr-kpi">¥ {{ loading ? '—' : wan(f.totalBudget).toLocaleString('zh-CN') }}<small> 万</small></div>
          <div style="font-size:11px;color:#8FA9CD;margin-top:6px">纵向 {{ f.verticalRatio ?? 0 }}% · 横向 {{ f.horizontalRatio ?? 0 }}% · 自立 {{ f.selfRatio ?? 0 }}%</div>
        </div>
        <div class="scr-card">
          <h6>本年度支出执行</h6>
          <div class="scr-kpi">{{ loading ? '—' : (f.executionRate ?? 0) }}<small>%</small> <span style="font-size:14px;color:#F0B43C">应达 {{ f.expectedRate ?? 0 }}%</span></div>
          <div style="font-size:11px;color:#8FA9CD;margin-top:6px">偏离项目 <b style="color:#E05645">{{ f.deviatedProjects ?? 0 }}</b> 个</div>
        </div>
        <div class="scr-card">
          <h6>AI 拦截可疑支出</h6>
          <div class="scr-kpi" style="color:#F0B43C">{{ loading ? '—' : (f.violationCount ?? 0) }}<small> 单 · 拒付 ¥{{ wan(f.aiRejectedAmount) }}万</small></div>
          <div style="font-size:11px;color:#8FA9CD;margin-top:6px">{{ aiBuckets.map(b => b.name + ' ' + b.count).join(' · ') || '—' }}</div>
        </div>
        <div class="scr-card">
          <h6>审计追溯完整率</h6>
          <div class="scr-kpi" style="color:#3FA0DC">{{ loading ? '—' : (f.auditTraceRate ?? 0) }}<small>%</small></div>
          <div style="font-size:11px;color:#8FA9CD;margin-top:6px">证据链缺项 {{ f.evidenceMissing ?? 0 }} → 已整改 {{ f.evidenceFixed ?? 0 }}</div>
        </div>
      </div>

      <!-- 预警 + 部门热力 + 项目分布 -->
      <div style="display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:16px;margin-bottom:16px">
        <div class="scr-card">
          <h6>预警滚动 · 事前(预算) 事中(支出) 事后(决算)</h6>
          <div class="scr-alert" :class="a.level || 'p1'" v-for="(a, i) in mergedAlerts" :key="i">
            <span>{{ a.level === 'p1' ? '●' : a.level === 'p2' ? '◐' : '○' }}</span>
            <div><b>[{{ a.tag }}]</b> {{ a.text }}</div>
          </div>
          <div v-if="!mergedAlerts.length && !loading" style="font-size:12px;color:#5F7DAB">暂无预警。</div>
        </div>

        <div class="scr-card">
          <h6>部门执行率热力</h6>
          <div class="scr-bars">
            <i v-for="(d, i) in (f.deptHeatmap || [])" :key="i"
               :class="{ hot: d.executionRate < HOT_THRESHOLD }"
               :data-v="d.executionRate + '%'"
               :style="{ height: d.executionRate + '%' }"
               @click="toast('下钻：' + (d.deptName || DEPT_NAMES[i]) + ' 项目清单')"></i>
          </div>
          <div style="display:flex;gap:6px;font-size:9px;color:#5F7DAB;margin-top:8px;justify-content:space-between">
            <span v-for="(d, i) in (f.deptHeatmap || [])" :key="i">{{ d.deptName || DEPT_NAMES[i] }}{{ d.executionRate < HOT_THRESHOLD ? '▲' : '' }}</span>
          </div>
          <div style="margin-top:14px;font-size:11px;color:#8FA9CD">▲ = 偏离阈值 · 点击柱体下钻项目清单</div>
        </div>

        <div class="scr-card">
          <h6>全院项目分布</h6>
          <div class="scr-map" style="height:170px">
            <svg width="100%" height="100%" viewBox="0 0 300 170">
              <g stroke="#1E3350" fill="none">
                <path d="M20,150 L60,90 L110,110 L150,60 L200,95 L250,40 L285,80"/>
                <path d="M40,150 L90,120 L140,140 L190,110 L240,130 L290,90"/>
              </g>
              <circle cx="60" cy="90" r="4" fill="#3FA0DC"/>
              <circle cx="150" cy="60" r="6" fill="#F0B43C"/>
              <circle cx="200" cy="95" r="4" fill="#3FA0DC"/>
              <circle cx="250" cy="40" r="5" fill="#E05645"/>
            </svg>
            <div class="pulse" style="left:50%;top:36%"></div>
            <div class="pulse" style="left:66%;top:55%;animation-delay:.8s"></div>
            <div style="position:absolute;bottom:4px;left:0;right:0;text-align:center;font-size:10px;color:#5F7DAB">研究集群地理分布（虚构演示）</div>
          </div>
          <div style="display:flex;gap:10px;margin-top:10px;flex-wrap:wrap">
            <div v-for="m in metrics" :key="m.code" style="flex:1;min-width:80px">
              <div style="font-size:10px;color:#8FA9CD">{{ m.name }}</div>
              <div style="font-family:var(--serif);font-weight:900;color:#fff;font-size:18px">{{ m.value }}<small style="font-size:11px;color:#5F7DAB">{{ m.unit }}</small></div>
            </div>
          </div>
        </div>
      </div>

      <!-- 全成本分摊 + 12 月趋势 -->
      <div class="scr-card" style="margin-bottom:16px">
        <h6>项目全成本分摊 · F-20 ↔ A-12（折旧/耗材/仪器工时/间接费用）</h6>
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:6px">
          <div v-for="(c, i) in (f.costPool || [])" :key="i">
            <div style="font-size:11px;color:#8FA9CD">{{ c.name }}</div>
            <div class="scr-bars" style="height:70px">
              <i :data-v="'直接' + c.direct + '%'" :style="{ height: c.direct + '%' }"></i>
              <i class="hot" :data-v="'间接' + c.indirect + '%'" :style="{ height: c.indirect + '%' }"></i>
            </div>
            <div class="scr-kpi" :style="{ fontSize: '18px', marginTop: '4px', color: c.tone === 'blue' ? '#3FA0DC' : c.tone === 'gold' ? '#F0B43C' : '#fff' }">
              ¥{{ wan(c.amount) }}<small> 万</small>
            </div>
          </div>
        </div>
        <div style="margin-top:12px;font-size:11px;color:#8FA9CD">全成本口径（政府会计制度平行记账）自动归集，为决算审计与绩效评价（D-03）提供可追溯的成本证据链。</div>
      </div>

      <div class="scr-card" style="margin-bottom:16px">
        <h6>近 12 月执行率走势（D-01 投影）</h6>
        <div class="scr-bars" style="height:90px">
          <i v-for="(t, i) in (f.trend12Months || [])" :key="i"
             :class="{ hot: t.executionRate >= 90 }"
             :data-v="t.executionRate + '%'" :style="{ height: t.executionRate + '%' }"></i>
        </div>
        <div style="display:flex;font-size:9px;color:#5F7DAB;margin-top:8px;justify-content:space-between">
          <span v-for="t in (f.trend12Months || [])" :key="t.month">{{ t.month }}</span>
        </div>
      </div>

      <!-- 底部条：AI 拦截构成 -->
      <div class="scr-card" style="font-size:11px;color:#8FA9CD;display:flex;gap:24px;align-items:center;flex-wrap:wrap">
        <span>① 一图：全量数据概览</span>
        <span>② 一舱：预警监督驾驶舱</span>
        <span>③ 三预警：事前 / 事中 / 事后</span>
        <span style="margin-left:auto" class="mono">等保三级 · 不可篡改日志 · 哈希链校验 ✓</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.scr-bars i{cursor:pointer}
</style>
