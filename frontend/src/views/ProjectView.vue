<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import type { CSSProperties } from 'vue'
import { useRoute } from 'vue-router'
import { api, list } from '@/api/client'
import { toNum, toWan, toPct } from '@/utils/money'

// —— 详情基础字段对齐后端 mapper.go ToAPIProject（snake_case）；
//    kpi / timeline / funding_lines / members / ethics 属视图扩展，仅 curated override（mock）提供，
//    真后端走 passthrough/缺省，故设为可选并以 ?? 兜底。——
interface Kpi { budget_exec_rate: string; milestone_completion_rate: string; output_count: number }
interface FundingLine { subject: string; approved: string; used: string; frozen: string; rate: string; status: string }
interface Member { name: string; role: string }
interface TimelineNode { node: string; occurred_at: string; actor: number }
interface EProjectDetail {
  id: number; code: string | null; status: string; title: string; project_type: string | null
  start_date?: string | null; end_date?: string | null; actual_end_date?: string | null
  total_budget: string; received_amount: string; spent_amount: string
  health_score: number; risk_level: string; security_level: string
  ai_summary?: string; kpi?: Kpi; timeline?: TimelineNode[]
  funding_lines?: FundingLine[]; members?: Member[]; ethics?: { case_id: string; status: string }
  [k: string]: any
}
// 任务/里程碑字段对齐 ToAPITask / ToAPIMilestone（snake_case）。
interface ETask {
  id: number; code?: string | null; project_id: number; status: string; name: string
  owner_user_id?: number | null; planned_start?: string | null; planned_end?: string | null
  actual_start?: string | null; actual_end?: string | null; progress_percent: number; weight?: string | null
  [k: string]: any
}
interface EMilestone {
  id: number; code?: string | null; project_id: number; status: string; name: string
  due_date?: string | null; actual_date?: string | null; weight?: string | null
  deliverable_type?: string | null; [k: string]: any
}
// risk-warnings / archive-checklist 真后端尚未实现（passthrough），字段名沿用 schema 契约（camelCase）。
interface ERiskWarning { warningId: number; level: string; source: string; title: string; suggestion: string; disposition: string }
interface ChecklistItem { item: string; required: boolean; mime: string; docId: number | null; uploaded: boolean }
interface EArchiveChecklist { checklistJson: ChecklistItem[]; requiredCount: number; completedCount: number; completeness: string; status: string; blockedItems: string[] }

const toast = (m: string) => (window as any).toast?.(m)
const route = useRoute()
// :id? 可选参数缺省时是空串，用 || 回落演示英雄项目
const id = String(route.params.id || '90001')

type TabKey = 'info' | 'mile' | 'fund' | 'member' | 'doc'
const TABS: { key: TabKey; label: string }[] = [
  { key: 'info', label: '基本信息' },
  { key: 'mile', label: '里程碑' },
  { key: 'fund', label: '经费' },
  { key: 'member', label: '成员' },
  { key: 'doc', label: '文档' },
]
const tab = ref<TabKey>('info')

const detail = ref<EProjectDetail | null>(null)
const risks = ref<ERiskWarning[]>([])
const tasks = ref<ETask[]>([])
const milestones = ref<EMilestone[]>([])
const checklist = ref<EArchiveChecklist | null>(null)
const loading = ref(true)
const tabLoading = ref<Record<TabKey, boolean>>({ info: false, mile: false, fund: false, member: false, doc: false })

const num = (s?: string | number | null) => toNum(s)
const wan = (s?: string | number | null) => toWan(s)
const pct = (r?: string | number | null) => toPct(r)

const execPct = computed(() => pct(detail.value?.kpi?.budget_exec_rate))
const msRatePct = computed(() => pct(detail.value?.kpi?.milestone_completion_rate))
const remainMonths = computed(() => {
  if (!detail.value?.end_date) return 0
  const end = new Date(detail.value.end_date).getTime()
  return Math.max(0, Math.round((end - Date.now()) / (1000 * 3600 * 24 * 30.4)))
})
const healthBand = computed(() => {
  const h = detail.value?.health_score ?? 0
  return h >= 80 ? 'var(--ok)' : h >= 60 ? 'var(--warn)' : 'var(--bad)'
})
const gaugeBg = computed(() => {
  const h = detail.value?.health_score ?? 0
  return `conic-gradient(${healthBand.value} 0 ${h}%, var(--paper-deep) ${h}% 100%)`
})

// —— 甘特条定位（相对项目起止）——
const MS_DAY = 1000 * 3600 * 24
function span(): { s: number; days: number } {
  const s = detail.value?.start_date ? new Date(detail.value.start_date).getTime() : Date.now()
  const e = detail.value?.end_date ? new Date(detail.value.end_date).getTime() : Date.now()
  return { s, days: Math.max(1, (e - s) / MS_DAY) }
}
function barStyle(t: ETask): CSSProperties {
  const { s, days } = span()
  const start = (new Date(t.planned_start || '').getTime() - s) / MS_DAY
  const end = (new Date(t.planned_end || '').getTime() - s) / MS_DAY
  const left = Math.min(96, Math.max(0, (start / days) * 100))
  const width = Math.min(100 - left, Math.max(6, ((end - start) / days) * 100))
  return { left: left + '%', width: width + '%' }
}
function ganttStyle(t: ETask): CSSProperties {
  return {
    position: 'absolute', top: '2px', bottom: '2px', borderRadius: '2px', display: 'block',
    background: TASK_COLOR[t.status] || 'var(--ink)', ...barStyle(t),
  }
}
const TASK_COLOR: Record<string, string> = {
  COMPLETED: 'var(--ok)', IN_PROGRESS: 'var(--ink)', OVERDUE: 'var(--warn)', PENDING: 'var(--line-hard)', CANCELLED: 'var(--line)',
}
const TASK_TEXT: Record<string, string> = {
  COMPLETED: '完成', IN_PROGRESS: '进行 {p}%', OVERDUE: '逾期', PENDING: '未开始', CANCELLED: '取消',
}
function taskLabel(t: ETask) {
  const base = TASK_TEXT[t.status] || t.status
  return base.replace('{p}', String(t.progress_percent))
}
function msColor(m: EMilestone) {
  if (m.status === 'ACHIEVED') return 'var(--ok)'
  if (m.status === 'OVERDUE') return 'var(--bad)'
  return 'var(--warn)'
}
function msWidth(m: EMilestone) {
  if (m.status === 'ACHIEVED') return '100%'
  if (m.status === 'OVERDUE') return '70%'
  return '6%'
}
const MS_LABEL: Record<string, string> = { ACHIEVED: '达成', PENDING: '未启', OVERDUE: '逾期', SKIPPED: '跳过' }
const completedMs = computed(() => milestones.value.filter((m) => m.status === 'ACHIEVED').length)

const MEMBER_COLORS = ['linear-gradient(135deg,#C2402C,#E0A06A)', 'linear-gradient(135deg,#41598C,#1C2B4A)', 'linear-gradient(135deg,#A8842F,#7a5f1f)', 'linear-gradient(135deg,#3E7C4B,#2b5a35)', 'linear-gradient(135deg,#5B4FA0,#3d3570)']

async function loadDetail() {
  loading.value = true
  try {
    const [d, r] = await Promise.all([
      api.get<EProjectDetail>(`/project/${id}`),
      api.get<ERiskWarning[]>(`/project/${id}/risk-warnings`).catch(() => [] as ERiskWarning[]),
    ])
    detail.value = d
    risks.value = Array.isArray(r) ? r : []
  } catch (e: any) {
    toast('项目详情加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
let mileLoaded = false, docLoaded = false
async function ensureTab(key: TabKey) {
  if (key === 'mile' && !mileLoaded) {
    tabLoading.value.mile = true
    try {
      // 任务：契约 GET /project/{id}/tasks 后端返回 {list}；兼容旧 {tasks,milestones} 结构。
      // 里程碑：新增契约 GET /project/{id}/milestones 返回 {list}。
      const [tk, ms] = await Promise.all([
        api.get<{ list?: ETask[]; tasks?: ETask[]; milestones?: EMilestone[] }>(`/project/${id}/tasks`, { view: 'GANTT' }),
        list<EMilestone>(`/project/${id}/milestones`).catch(() => ({ rows: [] as EMilestone[], total: 0 })),
      ])
      tasks.value = tk?.list ?? tk?.tasks ?? []
      milestones.value = ms?.rows ?? tk?.milestones ?? []
      mileLoaded = true
    } catch (e: any) { toast('里程碑加载失败：' + (e?.message || e)) }
    finally { tabLoading.value.mile = false }
  }
  if (key === 'doc' && !docLoaded) {
    tabLoading.value.doc = true
    try {
      checklist.value = await api.get<EArchiveChecklist>(`/project/${id}/archive-checklist`, { stage: 'FINAL' })
      docLoaded = true
    } catch (e: any) { toast('档案加载失败：' + (e?.message || e)) }
    finally { tabLoading.value.doc = false }
  }
}
function switchTab(key: TabKey) {
  tab.value = key
  ensureTab(key)
}
onMounted(async () => {
  await loadDetail()
  ensureTab(tab.value)
})
</script>

<template>
  <section class="view on" id="v-project" v-if="detail">
    <div class="page-head">
      <div>
        <div class="page-title" style="font-size:21px">{{ detail.title }}</div>
        <div class="page-sub mono">
          {{ detail.code }} · {{ detail.project_type }} · PI 周明远 · {{ detail.start_date }} → {{ detail.end_date }} ·
          剩余 <b style="color:var(--seal)">{{ remainMonths }} 个月</b>
        </div>
      </div>
      <div style="display:flex;gap:10px">
        <button class="btn ghost" @click="$router.push({ name: 'expense' })">＋ 发起报销</button>
        <button class="btn" @click="toast('变更申请向导（演示）')">发起变更</button>
      </div>
    </div>

    <div class="tabs">
      <div class="tab" :class="{ on: tab === t.key }" v-for="t in TABS" :key="t.key" @click="switchTab(t.key)">{{ t.label }}</div>
    </div>

    <!-- 基本信息 -->
    <div class="pane" v-show="tab === 'info'">
      <div class="grid g3">
        <div class="card">
          <div class="card-h"><h4>项目健康度</h4><span class="tag ai">AI 归因</span></div>
          <div class="card-b">
            <div class="gauge" :style="{ background: gaugeBg }"><div class="in"><b :style="{ color: healthBand }">{{ detail.health_score }}</b><span>{{ detail.risk_level }}</span></div></div>
            <div style="margin-top:14px;font-size:12px;line-height:1.9">{{ detail.ai_summary }}</div>
            <div class="alert-line b-add" style="margin-top:12px" v-for="r in risks" :key="r.warningId">
              ⚠ <b>{{ r.title }}：</b>{{ r.suggestion }}
            </div>
          </div>
        </div>
        <div class="card">
          <div class="card-h"><h4>经费概览</h4><a class="mono" style="font-size:11px;color:var(--ai);cursor:pointer" @click="switchTab('fund')">明细 →</a></div>
          <div class="card-b" style="display:flex;flex-direction:column;gap:14px">
            <div style="display:flex;justify-content:space-between">
              <div><div class="lbl" style="font-size:11px;color:var(--ink-mute)">总批复</div><div style="font-family:var(--serif);font-size:22px;font-weight:900">¥{{ wan(detail.total_budget) }}<small style="font-size:12px">万</small></div></div>
              <div style="text-align:right"><div style="font-size:11px;color:var(--ink-mute)">已到账</div><div style="font-family:var(--serif);font-size:22px;font-weight:900">¥{{ wan(detail.received_amount) }}<small style="font-size:12px">万</small></div></div>
            </div>
            <div>
              <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:5px"><span>执行 {{ execPct }}%</span><span class="mono">已用 ¥{{ wan(detail.spent_amount) }}万</span></div>
              <div class="bar" :class="detail.risk_level === 'LOW' ? 'b-ok' : 'b-warn'"><i :style="{ width: execPct + '%' }"></i></div>
            </div>
            <div style="font-size:11px;color:var(--ink-mute)" class="mono">成果 {{ detail.kpi?.output_count ?? 0 }} 项 · 里程碑完成 {{ msRatePct }}%</div>
          </div>
        </div>
        <div class="card">
          <div class="card-h"><h4>里程碑与团队</h4></div>
          <div class="card-b">
            <div class="hbar"><span class="nm" style="width:130px">里程碑达成</span><div class="track"><i :style="{ width: msRatePct + '%', background: 'var(--ok)' }"></i></div><span class="v">{{ completedMs || Math.round(msRatePct * 8 / 100) }}/8</span></div>
            <div class="hbar"><span class="nm" style="width:130px">经费执行</span><div class="track"><i :style="{ width: execPct + '%' }"></i></div><span class="v">{{ execPct }}%</span></div>
            <div class="divider-double"></div>
            <div style="display:flex;align-items:center;margin-bottom:10px">
              <span class="p-avatar" :style="{ width:'32px', height:'32px', fontSize:'13px', borderWidth:'2px', marginLeft: idx ? '-8px' : '0', background: MEMBER_COLORS[idx % MEMBER_COLORS.length] }" v-for="(m, idx) in (detail.members || []).slice(0, 8)" :key="idx">{{ m.name[0] }}</span>
              <span style="margin-left:12px;font-size:12px;color:var(--ink-soft)">课题组 {{ (detail.members || []).length }} 人</span>
            </div>
            <span class="tag info" v-if="detail.ethics">关联伦理批件 {{ detail.ethics?.case_id }} ✓ {{ detail.ethics?.status }}</span>
          </div>
        </div>
      </div>

      <div class="card" style="margin-top:16px">
        <div class="card-h"><h4>关键节点时间线</h4></div>
        <div class="card-b"><div class="timeline">
          <div class="tl-item" v-for="(n, i) in detail.timeline" :key="i">
            <div class="t">{{ n.occurred_at.slice(0, 10) }}</div>{{ n.node }}
          </div>
        </div></div>
      </div>
    </div>

    <!-- 里程碑 -->
    <div class="pane" v-show="tab === 'mile'">
      <div class="grid g2">
        <div class="card">
          <div class="card-h"><h4>任务分解 · 甘特</h4><span class="tag ai">拖拽可改期</span></div>
          <div class="card-b">
            <div v-if="tabLoading.mile" style="color:var(--ink-mute)">加载中…</div>
            <div v-else-if="!tasks.length" style="color:var(--ink-mute)">暂无任务</div>
            <div v-else style="display:flex;flex-direction:column;gap:10px">
              <div style="display:flex;align-items:center;gap:10px;font-size:12px" v-for="t in tasks" :key="t.id">
                <span style="width:190px">{{ t.name }}</span>
                <div style="flex:1;background:var(--paper-deep);height:16px;border-radius:3px;position:relative">
                  <i :style="ganttStyle(t)"></i>
                </div>
                <span class="mono" style="font-size:10px;color:var(--ink-mute)">{{ taskLabel(t) }}</span>
              </div>
            </div>
          </div>
        </div>
        <div class="card">
          <div class="card-h"><h4>里程碑清单</h4></div>
          <div class="card-b">
            <div v-if="tabLoading.mile" style="color:var(--ink-mute)">加载中…</div>
            <div v-else-if="!milestones.length" style="color:var(--ink-mute)">暂无里程碑</div>
            <div v-else class="timeline">
              <div class="tl-item" :class="{ red: m.status === 'OVERDUE' }" v-for="m in milestones" :key="m.id">
                <div class="t">{{ m.due_date }} · {{ MS_LABEL[m.status] || m.status }}</div>
                <b>{{ m.name }}</b> · {{ m.deliverable_type }}
                <div class="hbar" style="margin-top:6px"><div class="track"><i :style="{ width: msWidth(m), background: msColor(m) }"></i></div></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 经费 -->
    <div class="pane" v-show="tab === 'fund'">
      <div class="card">
        <div class="card-h"><h4>预算执行表</h4><button class="btn sm" @click="$router.push({ name: 'expense' })">＋ 报销</button></div>
        <div class="card-b" style="padding:0">
          <div v-if="!(detail.funding_lines && detail.funding_lines.length)" style="padding:24px;color:var(--ink-mute)">暂无经费明细</div>
          <table v-else class="tbl">
            <thead><tr><th>科目</th><th>批复</th><th>已用</th><th>冻结</th><th>执行率</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="(f, i) in detail.funding_lines" :key="i">
                <td>{{ f.subject }}</td>
                <td class="mono">{{ f.approved }}</td>
                <td class="mono">{{ f.used }}</td>
                <td class="mono">{{ f.frozen }}</td>
                <td><div class="bar" :class="f.status === 'warn' ? 'b-warn' : 'b-ok'" style="width:100px"><i :style="{ width: pct(f.rate) + '%' }"></i></div></td>
                <td><span class="tag" :class="f.status">{{ f.status === 'warn' ? 'AI：偏慢' : f.status === 'info' ? '计提' : '✓' }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 成员 -->
    <div class="pane" v-show="tab === 'member'">
      <div class="grid g3">
        <div class="card" v-for="(m, idx) in (detail.members || [])" :key="idx">
          <div class="card-b" style="display:flex;align-items:center;gap:14px">
            <span class="p-avatar" :style="{ width:'48px', height:'48px', fontSize:'18px', borderWidth:'2px', background: MEMBER_COLORS[idx % MEMBER_COLORS.length] }">{{ m.name[0] }}</span>
            <div><div style="font-family:var(--serif);font-size:15px;font-weight:600">{{ m.name }}</div><div style="font-size:11px;color:var(--ink-mute)">{{ m.role }}</div></div>
            <span v-if="m.role === 'PI'" class="tag seal" style="margin-left:auto">PI</span>
          </div>
        </div>
        <div v-if="!(detail.members && detail.members.length)" class="card"><div class="card-b" style="color:var(--ink-mute)">暂无成员信息</div></div>
      </div>
    </div>

    <!-- 文档 -->
    <div class="pane" v-show="tab === 'doc'">
      <div class="card">
        <div class="card-h"><h4>项目档案 · {{ checklist ? checklist.requiredCount : 0 }} 份</h4><span class="tag" :class="checklist && checklist.status === 'BLOCKED' ? 'bad' : 'info'">{{ checklist?.status || '—' }}</span></div>
        <div class="card-b" style="padding:0">
          <div v-if="tabLoading.doc" style="padding:24px;color:var(--ink-mute)">加载中…</div>
          <div v-else-if="!checklist || !checklist.checklistJson || !checklist.checklistJson.length" style="padding:24px;color:var(--ink-mute)">暂无档案</div>
          <table v-else class="tbl">
            <thead><tr><th>清单项</th><th>必交</th><th>状态</th><th></th></tr></thead>
            <tbody>
              <tr v-for="(c, i) in checklist.checklistJson" :key="i">
                <td>{{ c.item }}</td>
                <td><span class="tag" :class="c.required ? 'seal' : 'info'">{{ c.required ? '必交' : '选交' }}</span></td>
                <td><span class="tag" :class="c.uploaded ? 'ok' : 'warn'">{{ c.uploaded ? '✓ 已上传' : '缺' }}</span></td>
                <td><a style="color:var(--ai);cursor:pointer" @click="toast('预览档案（演示）')">{{ c.uploaded ? '预览' : '待补' }}</a></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>

  <section class="view on" v-else>
    <div class="card"><div class="card-b" style="padding:36px;text-align:center;color:var(--ink-mute)">{{ loading ? '项目加载中…' : '项目不存在或无权访问' }}</div></div>
  </section>
</template>

<style scoped>
.gauge .in span { text-transform: uppercase; }
</style>
