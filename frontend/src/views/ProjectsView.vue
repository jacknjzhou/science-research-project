<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { list } from '@/api/client'
import { toNum, toWan } from '@/utils/money'

// 字段对齐后端 mapper.go ToAPIProject（snake_case，NUMERIC→string）。
interface EProject {
  id: number
  code: string | null
  status: string
  title: string
  project_type: string | null
  pi_user_id: number
  department_id?: number | null
  start_date?: string | null
  end_date?: string | null
  actual_end_date?: string | null
  total_budget: string
  received_amount: string
  spent_amount: string
  health_score: number
  risk_level: string
  security_level: string
  [k: string]: any
}

const toast = (m: string) => (window as any).toast?.(m)
const router = useRouter()

const projects = ref<EProject[]>([])
const total = ref(0)
const loading = ref(true)
const viewMode = ref<'card' | 'list' | 'gantt'>('card')

// —— 分页 / 筛选 / 搜索响应式参数 ——
const page = ref(1)
const size = ref(12)
const status = ref('')
const kw = ref('')
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / size.value)))

const STATUS_FILTERS: { v: string; t: string }[] = [
  { v: '', t: '全部' },
  { v: 'EXECUTING', t: '在研' },
  { v: 'MID_CHECK', t: '中检' },
  { v: 'CHANGING', t: '变更中' },
  { v: 'CLOSED', t: '已结题' },
]

const num = (s?: string | number | null) => toNum(s)
const wan = (s?: string | number | null) => toWan(s)
const ym = (d?: string | null) => (d ? d.slice(0, 7).replace('-', '.') : '—')
const execPct = (p: EProject) => {
  const r = num(p.received_amount)
  return r > 0 ? Math.round((num(p.spent_amount) / r) * 100) : 0
}
const healthCls = (p: EProject) =>
  (p.health_score ?? 0) >= 80 ? 'h-ok' : (p.health_score ?? 0) >= 60 ? 'h-warn' : 'h-bad'
const barCls = (p: EProject) => (p.risk_level === 'LOW' ? 'b-ok' : 'b-warn')

const counts = computed(() => {
  const active = projects.value.filter((p) => p.status !== 'CLOSED').length
  const mid = projects.value.filter((p) => p.status === 'MID_CHECK' || p.status === 'CHANGING').length
  const closed = projects.value.filter((p) => p.status === 'CLOSED').length
  return { active, mid, closed }
})

const RISK_TEXT: Record<string, { cls: string; txt: string }> = {
  HIGH: { cls: 'risk', txt: '⚠ AI：经费执行偏离，剩余周期存在突击支出风险' },
  MED: { cls: 'risk warn', txt: '⚠ 状态波动，建议关注里程碑与协议变更' },
  LOW: { cls: '', txt: '' },
}

async function load() {
  loading.value = true
  try {
    const { rows, total: t } = await list<EProject>('/project/mine', {
      page: page.value,
      size: size.value,
      status: status.value || undefined,
      kw: kw.value || undefined,
    })
    projects.value = rows ?? []
    total.value = t ?? projects.value.length
  } catch (e: any) {
    toast('项目加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
onMounted(load)

function reload() {
  page.value = 1
  load()
}
function setStatus(v: string) {
  status.value = v
  reload()
}
function goPage(delta: number) {
  const next = page.value + delta
  if (next < 1 || next > pageCount.value) return
  page.value = next
  load()
}

function open(p: EProject) {
  if (p.status === 'CLOSED') { toast('打开归档项目（演示）'); return }
  router.push({ name: 'project', params: { id: p.id } })
}
function pick(v: 'card' | 'list' | 'gantt') {
  viewMode.value = 'card'
  if (v !== 'card') toast(v === 'list' ? '表格视图（演示）' : '甘特视图见项目详情')
}
</script>

<template>
  <section class="view on" id="v-projects">
    <div class="page-head">
      <div>
        <div class="page-title">我的<em>项目</em></div>
        <div class="page-sub">在研 {{ counts.active }} · 中检 {{ counts.mid }} · 已结题 {{ counts.closed }} · 健康度每日刷新</div>
      </div>
      <div style="display:flex;gap:8px">
        <span class="chip" :class="{ on: viewMode === 'card' }" @click="pick('card')">卡片</span>
        <span class="chip" @click="pick('list')">列表</span>
        <span class="chip" @click="pick('gantt')">甘特</span>
      </div>
    </div>

    <div class="filter-row">
      <input class="sel" style="min-width:180px" v-model="kw" placeholder="搜索项目名称 / 编号" @keyup.enter="reload" />
      <span class="chip" v-for="s in STATUS_FILTERS" :key="s.v" :class="{ on: status === s.v }" @click="setStatus(s.v)">{{ s.t }}</span>
      <button class="btn ghost sm" @click="reload">查询</button>
    </div>

    <div v-if="loading" class="card"><div class="card-b" style="color:var(--ink-mute)">项目加载中…</div></div>

    <div v-else-if="!projects.length" class="card">
      <div class="card-b" style="padding:36px;text-align:center;color:var(--ink-mute)">暂无在研项目</div>
    </div>

    <template v-else>
      <div class="grid g3">
        <div
          class="card proj-card"
          :style="p.status === 'CLOSED' ? 'opacity:.65' : undefined"
          v-for="p in projects"
          :key="p.id"
          @click="open(p)"
        >
          <div class="health-badge">
            <template v-if="p.status === 'CLOSED'">
              <div class="v" style="color:var(--ink-mute);font-size:16px">归档</div>
            </template>
            <template v-else>
              <div class="v" :class="healthCls(p)">{{ p.health_score }}</div>
              <div class="l">HEALTH</div>
            </template>
          </div>
          <h5>{{ p.title }}</h5>
          <div class="no">{{ p.code }} · {{ p.project_type }} · {{ ym(p.start_date) }}–{{ ym(p.end_date) }}</div>

          <div class="rows">
            <div class="r"><span>经费执行</span><span class="mono">¥{{ wan(p.spent_amount) }}万/{{ wan(p.received_amount) }}万 · {{ execPct(p) }}%</span></div>
            <div class="bar" :class="barCls(p)"><i :style="{ width: execPct(p) + '%' }"></i></div>

            <template v-if="p.status === 'CLOSED'">
              <div class="r" style="margin-top:8px"><span>结题结论</span><span class="tag ok">优秀</span></div>
              <div class="r"><span>成果</span><span class="mono">累计归档</span></div>
            </template>
            <template v-else>
              <div class="r" style="margin-top:8px"><span>状态 / 风险</span><span class="mono">{{ p.status }} · {{ p.risk_level }}</span></div>
            </template>
          </div>

          <div v-if="p.status !== 'CLOSED' && RISK_TEXT[p.risk_level]?.txt" :class="RISK_TEXT[p.risk_level].cls">
            {{ RISK_TEXT[p.risk_level].txt }}
          </div>
          <div v-else-if="p.status !== 'CLOSED'" class="tag ok" style="margin-top:10px">✓ 一切正常 · 无需干预</div>
        </div>
      </div>

      <div class="pager">
        <button class="btn ghost sm" :disabled="page <= 1" @click="goPage(-1)">← 上一页</button>
        <span class="mono pg-info">第 {{ page }} / {{ pageCount }} 页 · 共 {{ total }} 个</span>
        <button class="btn ghost sm" :disabled="page >= pageCount" @click="goPage(1)">下一页 →</button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.sel { font-size:12px; padding:5px 10px; border:1px solid var(--line-hard, #d8d2c4); border-radius:6px; background:#fff; outline:none; }
.sel:focus { border-color:var(--ink); }
.pager { display:flex; align-items:center; gap:14px; justify-content:center; margin-top:18px; }
.pg-info { font-size:12px; color:var(--ink-mute); }
.pager .btn:disabled { opacity:.4; cursor:not-allowed; }
</style>
