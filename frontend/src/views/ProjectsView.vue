<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { list } from '@/api/client'
import { auth } from '@/api/auth'
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

// 管理员全量视角：后端 /project/mine 对 R-ADMIN 返回租户全部项目
const isAdmin = computed(() => auth.roles.includes('R-ADMIN'))

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
  // 含 CLOSED 归档项目：正常进入详情（只读视图）
  router.push({ name: 'project', params: { id: p.id } })
}
function pick(v: 'card' | 'list' | 'gantt') {
  viewMode.value = v
}

// —— 列表视图 ——
const STATUS_ZH: Record<string, string> = {
  EXECUTING: '在研', MID_CHECK: '中检', CHANGING: '变更中', CLOSED: '已结题', APPROVED: '已立项',
}

// —— 甘特视图：时间轴取列表项目 min(start) ~ max(end)，条按起止定位，今日线标注 ——
const gantt = computed(() => {
  const items = projects.value.filter((p) => p.start_date && p.end_date)
  if (!items.length) return null
  const t = (d: string) => new Date(d).getTime()
  const min = Math.min(...items.map((p) => t(p.start_date!)))
  const max = Math.max(...items.map((p) => t(p.end_date!)))
  const span = Math.max(1, max - min)
  const now = Date.now()
  const todayPct = now <= min ? 0 : now >= max ? 100 : ((now - min) / span) * 100
  const bars = items.map((p) => ({
    p,
    leftPct: ((t(p.start_date!) - min) / span) * 100,
    widthPct: Math.max(1.5, ((t(p.end_date!) - t(p.start_date!)) / span) * 100),
    active: now >= t(p.start_date!) && now <= t(p.end_date!),
  }))
  const fmtMonth = (ts: number) => {
    const d = new Date(ts)
    return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}`
  }
  return { bars, todayPct, axis: [0, 25, 50, 75, 100].map((pct) => ({ pct, label: fmtMonth(min + (span * pct) / 100) })) }
})
</script>

<template>
  <section class="view on" id="v-projects">
    <div class="page-head">
      <div>
        <div class="page-title" v-if="isAdmin">全部<em>项目</em></div>
        <div class="page-title" v-else>我的<em>项目</em></div>
        <div class="page-sub">{{ isAdmin ? '管理员视角：显示系统内全部项目 · ' : '' }}在研 {{ counts.active }} · 中检 {{ counts.mid }} · 已结题 {{ counts.closed }} · 健康度每日刷新</div>
      </div>
      <div style="display:flex;gap:8px">
        <span class="chip" :class="{ on: viewMode === 'card' }" @click="pick('card')">卡片</span>
        <span class="chip" :class="{ on: viewMode === 'list' }" @click="pick('list')">列表</span>
        <span class="chip" :class="{ on: viewMode === 'gantt' }" @click="pick('gantt')">甘特</span>
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

    <!-- 列表视图 -->
    <div v-else-if="viewMode === 'list'" class="card" style="overflow:auto;min-width:0">
      <table class="tbl" style="border-collapse:collapse;font-size:13px;table-layout:fixed;width:100%">
        <thead>
          <tr style="text-align:left">
            <th style="width:16%">编号</th>
            <th style="width:30%">项目名称</th>
            <th style="width:10%">状态</th>
            <th style="width:8%;text-align:center">健康度</th>
            <th style="width:16%" class="num">经费执行</th>
            <th style="width:12%">起止</th>
            <th style="width:8%">风险</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in projects" :key="p.id" style="cursor:pointer" @click="open(p)">
            <td class="mono">{{ p.code || '—' }}</td>
            <td style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" :title="p.title">{{ p.title }}</td>
            <td><span class="tag" :class="p.status === 'CLOSED' ? 'muted' : 'ok'">{{ STATUS_ZH[p.status] || p.status }}</span></td>
            <td style="text-align:center" :class="healthCls(p)">{{ p.health_score }}</td>
            <td class="mono num">{{ wan(p.spent_amount) }}万 / {{ wan(p.received_amount) }}万 · {{ execPct(p) }}%</td>
            <td class="mono" style="font-size:12px">{{ ym(p.start_date) }}–{{ ym(p.end_date) }}</td>
            <td>{{ p.risk_level }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 甘特视图 -->
    <div v-else-if="viewMode === 'gantt' && gantt" class="card">
      <div class="card-b" style="padding:16px">
        <div class="g-axis">
          <span v-for="a in gantt.axis" :key="a.pct" class="mono g-tick" :style="{ left: a.pct + '%' }">{{ a.label }}</span>
        </div>
        <div class="g-body" style="position:relative">
          <div class="g-today" :style="{ left: gantt.todayPct + '%' }"><i>今日</i></div>
          <div v-for="b in gantt.bars" :key="b.p.id" class="g-row" @click="open(b.p)" :title="b.p.title">
            <div class="g-name" :style="b.p.status === 'CLOSED' ? 'opacity:.55' : undefined">{{ b.p.title }}</div>
            <div class="g-track">
              <div class="g-bar" :class="{ done: b.p.status === 'CLOSED' }" :style="{ left: b.leftPct + '%', width: b.widthPct + '%' }">
                <span class="mono">{{ b.p.status === 'CLOSED' ? '已结题' : b.active ? '进行中' : '未开始' }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div v-else-if="viewMode === 'gantt'" class="card"><div class="card-b" style="color:var(--ink-mute)">当前页项目缺少起止日期，无法绘制甘特图</div></div>

    <template v-else-if="viewMode === 'card'">
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
.num { text-align:right; }
.tbl tbody tr:hover { background:rgba(0,0,0,.03); }
.tag.muted { background:#f0f0f0; color:#666; }
/* —— 甘特视图 —— */
.g-axis { position:relative; height:20px; margin-left:220px; border-bottom:1px dashed var(--line-hard, #d8d2c4); }
.g-tick { position:absolute; transform:translateX(-50%); font-size:11px; color:var(--ink-mute); top:2px; }
.g-body { padding:10px 0 4px; }
.g-row { display:flex; align-items:center; gap:10px; padding:7px 0; cursor:pointer; }
.g-row:hover .g-bar { filter:brightness(1.08); }
.g-name { width:210px; flex:none; font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.g-track { position:relative; flex:1; min-width:0; height:22px; background:repeating-linear-gradient(90deg, transparent, transparent calc(25% - 1px), var(--line, #eee) calc(25% - 1px), var(--line, #eee) 25%); border-radius:4px; }
.g-bar { position:absolute; top:3px; height:16px; border-radius:8px; background:var(--seal, #8b2e2e); color:#fff; font-size:10px; line-height:16px; padding:0 8px; overflow:hidden; white-space:nowrap; }
.g-bar.done { background:var(--ink-mute, #999); }
.g-today { position:absolute; top:6px; bottom:6px; width:2px; background:var(--ai, #7a5cff); z-index:1; }
.g-today i { position:absolute; top:-16px; left:-12px; font-size:10px; font-style:normal; color:var(--ai, #7a5cff); }
</style>
