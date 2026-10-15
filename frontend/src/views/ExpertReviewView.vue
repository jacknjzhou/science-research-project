<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, list } from '@/api/client'
import { toNum } from '@/utils/money'
import { auth } from '@/api/auth'

// —— 数据模型严格对齐后端 mapper.go ToAPI*（snake_case，NUMERIC→定标字符串）——
interface Expert {
  id: number; code: string | null; tenant_id: number; status: string; name: string
  gender: string | null; title: string | null; org_name: string | null; user_id: number | null
  source: string; field_tags: string[]; expertise_level: string; avoid_orgs: string[]
  avoid_person_ids: number[]; security_level: string; last_review_at: string | null
  review_count: number; created_at: string; updated_at: string; [k: string]: any
}
interface ReviewTask {
  id: number; code: string | null; tenant_id: number; biz_type: string; target_type: string | null
  target_id: number | null; project_id: number | null; title: string; review_method: string
  plan_count: number; draw_rule: Record<string, any>; status: string; conclusion: string | null
  score_summary: Record<string, any> | null; security_level: string; drawn_at: string | null
  started_at: string | null; concluded_at: string | null; created_at: string; updated_at: string
  [k: string]: any
}
interface Invitation {
  id: number; task_id: number; expert_id: number; expert_name: string | null
  seat_no: number; avoid_hit: boolean; response: string; [k: string]: any
}
interface DimScore { dimension?: string; score?: string; weight?: string; [k: string]: any }
interface Score {
  id: number; task_id: number; expert_id: number; target_type: string | null; target_id: number | null
  dimension_scores: DimScore[]; total_score: string | null; comment: string | null
  status: string; [k: string]: any
}
interface ReviewDetail { task: ReviewTask; invitations: Invitation[]; scores: Score[] }

const toast = (m: string) => (window as any).toast?.(m)

type TabKey = 'experts' | 'reviews' | 'detail'
const TABS: { key: TabKey; label: string }[] = [
  { key: 'experts', label: '专家库' },
  { key: 'reviews', label: '评审任务' },
  { key: 'detail', label: '评审详情 · 打分/结论/评审费' },
]
const tab = ref<TabKey>('experts')

// 角色门控（计划 §3.10：打分仅 R-EXPERT，抽取/结论 R-MANAGER）
const canManage = computed(() => auth.hasAnyRole(['R-MANAGER', 'R-LEADER', 'R-ADMIN']))
const canScore = computed(() => auth.hasAnyRole(['R-EXPERT']))

// —— 字典 ——
const EXPERT_STATUS: Record<string, { cls: string; txt: string }> = {
  CANDIDATE: { cls: 'info', txt: '候选' }, ACTIVE: { cls: 'ok', txt: '启用' },
  SUSPENDED: { cls: 'warn', txt: '暂停' }, BLACKLIST: { cls: 'bad', txt: '黑名单' },
}
const LEVEL_TXT: Record<string, string> = { JUNIOR: '初级', SENIOR: '高级', EXPERT: '资深' }
const BIZ_TXT: Record<string, string> = {
  MID_CHECK: '中期检查', FINAL_ACCEPT: '结题验收', OUTPUT_EVAL: '成果评价',
  PROJECT_APPLY: '申报评审', OTHER: '其他',
}
const METHOD_TXT: Record<string, string> = { RANDOM: '随机抽取', COMBINATION: '组合抽取', MANUAL: '手动指派' }
const RV_STATUS: Record<string, { cls: string; txt: string }> = {
  DRAFT: { cls: 'info', txt: '草稿' }, DRAWN: { cls: 'info', txt: '已抽取' },
  INVITING: { cls: 'warn', txt: '邀请中' }, QUORUM: { cls: 'warn', txt: '达法定人数' },
  IN_REVIEW: { cls: '', txt: '评审中' }, COLLECTING: { cls: '', txt: '汇总中' },
  CONCLUDED: { cls: 'ok', txt: '已结论' }, CANCELLED: { cls: 'bad', txt: '已取消' },
}
const RESP_TXT: Record<string, { cls: string; txt: string }> = {
  PENDING: { cls: 'info', txt: '待响应' }, ACCEPT: { cls: 'ok', txt: '已接受' },
  DECLINE: { cls: 'bad', txt: '已拒绝' }, EXPIRED: { cls: 'warn', txt: '已过期' },
}

const fmtTime = (d?: string | null) => (d ? d.replace('T', ' ').slice(0, 16) + 'Z' : '—')
const num = (s?: string | number | null) => toNum(s)

// ============ 专家台账 ============
const experts = ref<Expert[]>([])
const exTotal = ref(0)
const exLoading = ref(false)
const exPage = ref(1)
const exSize = ref(10)
const exStatus = ref('')
const exKw = ref('')
const exPageCount = computed(() => Math.max(1, Math.ceil(exTotal.value / exSize.value)))

async function loadExperts() {
  exLoading.value = true
  try {
    const { rows, total } = await list<Expert>('/experts', {
      page: exPage.value, size: exSize.value,
      status: exStatus.value || undefined, kw: exKw.value || undefined,
    })
    experts.value = rows ?? []
    exTotal.value = total ?? experts.value.length
  } catch (e: any) {
    toast('专家加载失败：' + (e?.message || e))
  } finally {
    exLoading.value = false
  }
}
function exReload() { exPage.value = 1; loadExperts() }
function exSetStatus(v: string) { exStatus.value = v; exReload() }
function exGo(delta: number) {
  const n = exPage.value + delta
  if (n < 1 || n > exPageCount.value) return
  exPage.value = n; loadExperts()
}

const busy = ref(false)
async function toggleExpert(e: Expert, status: string) {
  if (busy.value || !canManage.value) return
  busy.value = true
  try {
    await api.post<Expert>(`/experts/${e.id}/status`, { status })
    e.status = status
    toast(`专家 ${e.name} 已置为「${EXPERT_STATUS[status]?.txt || status}」✓`)
  } catch (err: any) {
    toast('状态更新失败：' + (err?.message || err))
  } finally {
    busy.value = false
  }
}

// ============ 评审列表 ============
const reviews = ref<ReviewTask[]>([])
const rvTotal = ref(0)
const rvLoading = ref(false)
const rvPage = ref(1)
const rvSize = ref(10)
const rvStatus = ref('')
const rvBiz = ref('')
const rvPageCount = computed(() => Math.max(1, Math.ceil(rvTotal.value / rvSize.value)))

async function loadReviews() {
  rvLoading.value = true
  try {
    const { rows, total } = await list<ReviewTask>('/reviews', {
      page: rvPage.value, size: rvSize.value,
      status: rvStatus.value || undefined, biz_type: rvBiz.value || undefined,
    })
    reviews.value = rows ?? []
    rvTotal.value = total ?? reviews.value.length
  } catch (e: any) {
    toast('评审任务加载失败：' + (e?.message || e))
  } finally {
    rvLoading.value = false
  }
}
function rvReload() { rvPage.value = 1; loadReviews() }
function rvSet(v: 'status' | 'biz', val: string) {
  if (v === 'status') rvStatus.value = val; else rvBiz.value = val
  rvReload()
}
function rvGo(delta: number) {
  const n = rvPage.value + delta
  if (n < 1 || n > rvPageCount.value) return
  rvPage.value = n; loadReviews()
}

async function openDetail(r: ReviewTask) {
  selectedId.value = r.id
  await loadDetail()
  tab.value = 'detail'
}

// ============ 评审详情 + 动作（状态机） ============
const selectedId = ref<number | null>(null)
const detail = ref<ReviewDetail | null>(null)
const detailLoading = ref(false)

async function loadDetail() {
  if (selectedId.value == null) return
  detailLoading.value = true
  try {
    detail.value = await api.get<ReviewDetail>(`/reviews/${selectedId.value}/detail`)
  } catch (e: any) {
    toast('评审详情加载失败：' + (e?.message || e))
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

const status = computed(() => detail.value?.task?.status ?? '')
// 抽取面板可编辑参数
const drawMethod = ref<string>('COMBINATION')
const drawCount = ref<number>(3)

// 状态机门禁（对齐 N.ddl 状态 token 流转）
const gate = computed(() => {
  const s = status.value
  return {
    draw: s === 'DRAFT',
    invite: s === 'DRAWN',
    respond: s === 'INVITING',
    start: s === 'QUORUM',
    score: s === 'IN_REVIEW' || s === 'COLLECTING',
    conclude: s === 'IN_REVIEW' || s === 'COLLECTING',
    fees: s === 'CONCLUDED',
  }
})

const acceptCount = computed(() => (detail.value?.invitations || []).filter((i) => i.response === 'ACCEPT').length)
const scoreDoneCount = computed(() => (detail.value?.scores || []).filter((s) => s.status === 'SUBMITTED').length)

async function runAction(name: string, fn: () => Promise<any>, okMsg: string) {
  if (busy.value || selectedId.value == null) return
  busy.value = true
  try {
    await fn()
    toast(okMsg)
    await loadDetail()
    await loadReviews()
  } catch (e: any) {
    toast(`${name}失败：` + (e?.message || e))
  } finally {
    busy.value = false
  }
}

function doDraw() {
  runAction('抽取', () => api.post(`/reviews/${selectedId.value}/draw`, {
    method: drawMethod.value, plan_count: drawCount.value,
  }), `已按回避规则抽取 ${drawCount.value} 位专家 → DRAWN ✓`)
}
function doInvite() {
  runAction('邀请', () => api.post(`/reviews/${selectedId.value}/invite`), '邀请已发出 → INVITING ✓')
}
function doRespond(expertId: number, accept: boolean) {
  runAction(accept ? '接受' : '拒绝', () =>
    api.post(`/reviews/${selectedId.value}/${accept ? 'accept' : 'decline'}`, { expert_id: expertId }),
    accept ? '已接受邀请 ✓' : '已拒绝邀请 ✓')
}
function doStart() {
  runAction('开始', () => api.post(`/reviews/${selectedId.value}/start`), '评审已开始 → IN_REVIEW ✓')
}
function doConclude() {
  const concl = detail.value?.task?.biz_type === 'MID_CHECK' ? 'CONTINUE' : 'PASS'
  runAction('结论', () => api.post(`/reviews/${selectedId.value}/conclude`, { conclusion: concl }), `已汇总结论「${concl}」→ CONCLUDED ✓`)
}
function doFees() {
  runAction('评审费', () => api.post(`/reviews/${selectedId.value}/fees`, { amount: '2000.00', pay_channel: 'BANK' }), '评审费生成请求已提交（联动 F）✓')
}

// 打分演示（R-EXPERT）
const scoreModal = ref(false)
const scoreTotal = ref('88.00')
function openScore() { if (canScore.value && gate.value.score) scoreModal.value = true }
function submitScore() {
  const expertId = detail.value?.invitations?.find((i) => i.response === 'ACCEPT')?.expert_id ?? 8101
  runAction('打分', () => api.post(`/reviews/${selectedId.value}/scores`, {
    expert_id: expertId,
    dimension_scores: [{ dimension: '创新性', score: scoreTotal.value, weight: '1.0' }],
    total_score: String(num(scoreTotal.value).toFixed(2)),
    comment: '演示打分', status: 'SUBMITTED',
  }), '打分已提交 ✓')
  scoreModal.value = false
}

function switchTab(k: TabKey) {
  tab.value = k
  if (k === 'experts' && !experts.value.length) loadExperts()
  if (k === 'reviews' && !reviews.value.length) loadReviews()
  if (k === 'detail' && selectedId.value == null && reviews.value.length) {
    selectedId.value = reviews.value[0].id
    loadDetail()
  }
}

onMounted(async () => {
  await Promise.all([loadExperts(), loadReviews()])
  if (reviews.value.length) selectedId.value = reviews.value[0].id
})
</script>

<template>
  <section class="view on" id="v-expert-review">
    <div class="page-head">
      <div>
        <div class="page-title">专家与<em>评审</em></div>
        <div class="page-sub">
          专家台账 {{ exTotal }} 人 · 评审任务 {{ rvTotal }} 项 · 抽取回避 · 在线打分 · 结论回写 E/R
        </div>
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <span class="tag info">角色：{{ auth.roles.join(' / ') || '访客' }}</span>
        <span v-if="!canManage && !canScore" class="tag warn">当前角色仅可查看</span>
      </div>
    </div>

    <div class="tabs">
      <div class="tab" :class="{ on: tab === t.key }" v-for="t in TABS" :key="t.key" @click="switchTab(t.key)">{{ t.label }}</div>
    </div>

    <!-- 专家库 -->
    <div class="pane" v-show="tab === 'experts'">
      <div class="filter-row">
        <input class="sel" style="min-width:200px" v-model="exKw" placeholder="搜索专家姓名 / 编号" @keyup.enter="exReload" />
        <span class="chip" :class="{ on: exStatus === '' }" @click="exSetStatus('')">全部</span>
        <span class="chip" v-for="(v, k) in EXPERT_STATUS" :key="k" :class="{ on: exStatus === k }" @click="exSetStatus(k)">{{ v.txt }}</span>
        <button class="btn ghost sm" @click="exReload">查询</button>
      </div>

      <div v-if="exLoading" class="card"><div class="card-b" style="color:var(--ink-mute)">专家加载中…</div></div>
      <div v-else-if="!experts.length" class="card"><div class="card-b" style="padding:32px;text-align:center;color:var(--ink-mute)">暂无专家记录</div></div>

      <template v-else>
        <div class="card" style="padding:0">
          <table class="tbl">
            <thead><tr><th>编号</th><th>姓名</th><th>单位</th><th>层级</th><th>领域标签</th><th>状态</th><th>评审次数</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="e in experts" :key="e.id">
                <td class="mono">{{ e.code || '—' }}</td>
                <td><b>{{ e.name }}</b><div style="font-size:11px;color:var(--ink-mute)">{{ e.title || '—' }}</div></td>
                <td>{{ e.org_name || '—' }}</td>
                <td><span class="tag seal">{{ LEVEL_TXT[e.expertise_level] || e.expertise_level }}</span></td>
                <td>
                  <span class="tag info" style="margin-right:4px" v-for="t in (e.field_tags || [])" :key="t">{{ t }}</span>
                  <span v-if="!(e.field_tags && e.field_tags.length)" style="color:var(--ink-mute)">—</span>
                </td>
                <td><span class="tag" :class="(EXPERT_STATUS[e.status]||{}).cls">{{ (EXPERT_STATUS[e.status]||{}).txt || e.status }}</span></td>
                <td class="mono">{{ e.review_count }}</td>
                <td>
                  <template v-if="canManage">
                    <button class="btn sm ghost" :disabled="busy || e.status === 'ACTIVE'" @click="toggleExpert(e, 'ACTIVE')">启用</button>
                    <button class="btn sm ghost" :disabled="busy || e.status === 'SUSPENDED'" @click="toggleExpert(e, 'SUSPENDED')" style="margin-left:6px">暂停</button>
                  </template>
                  <span v-else style="color:var(--ink-mute);font-size:11px">只读</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="pager">
          <button class="btn ghost sm" :disabled="exPage <= 1" @click="exGo(-1)">← 上一页</button>
          <span class="mono pg-info">第 {{ exPage }} / {{ exPageCount }} 页 · 共 {{ exTotal }} 人</span>
          <button class="btn ghost sm" :disabled="exPage >= exPageCount" @click="exGo(1)">下一页 →</button>
        </div>
      </template>
    </div>

    <!-- 评审任务列表 -->
    <div class="pane" v-show="tab === 'reviews'">
      <div class="filter-row">
        <select class="sel" v-model="rvBiz" @change="rvSet('biz', rvBiz)">
          <option value="">全部类型</option>
          <option v-for="(v, k) in BIZ_TXT" :key="k" :value="k">{{ v }}</option>
        </select>
        <span class="chip" :class="{ on: rvStatus === '' }" @click="rvSet('status', '')">全部状态</span>
        <span class="chip" v-for="(v, k) in RV_STATUS" :key="k" :class="{ on: rvStatus === k }" @click="rvSet('status', k)">{{ v.txt }}</span>
        <button class="btn ghost sm" @click="rvReload">查询</button>
      </div>

      <div v-if="rvLoading" class="card"><div class="card-b" style="color:var(--ink-mute)">评审任务加载中…</div></div>
      <div v-else-if="!reviews.length" class="card"><div class="card-b" style="padding:32px;text-align:center;color:var(--ink-mute)">暂无评审任务</div></div>

      <template v-else>
        <div class="card rv-card" v-for="r in reviews" :key="r.id" @click="openDetail(r)">
          <div class="card-b" style="display:flex;align-items:center;gap:16px">
            <div style="flex:1">
              <div style="font-family:var(--serif);font-weight:700;font-size:14px">
                {{ r.title }}
                <span class="tag seal" style="margin-left:6px">{{ BIZ_TXT[r.biz_type] || r.biz_type }}</span>
              </div>
              <div class="mono" style="font-size:11px;color:var(--ink-mute);margin-top:4px">
                {{ r.code || '—' }} · {{ METHOD_TXT[r.review_method] || r.review_method }} · 拟抽 {{ r.plan_count }} 人 · 安全级别 {{ r.security_level }}
              </div>
            </div>
            <div style="text-align:right">
              <span class="tag" :class="(RV_STATUS[r.status]||{}).cls">{{ (RV_STATUS[r.status]||{}).txt || r.status }}</span>
              <div style="font-size:11px;color:var(--ink-mute);margin-top:6px">{{ fmtTime(r.concluded_at || r.started_at || r.created_at) }}</div>
            </div>
            <button class="btn sm ghost" @click.stop="openDetail(r)">进入评审台 →</button>
          </div>
        </div>
        <div class="pager">
          <button class="btn ghost sm" :disabled="rvPage <= 1" @click="rvGo(-1)">← 上一页</button>
          <span class="mono pg-info">第 {{ rvPage }} / {{ rvPageCount }} 页 · 共 {{ rvTotal }} 项</span>
          <button class="btn ghost sm" :disabled="rvPage >= rvPageCount" @click="rvGo(1)">下一页 →</button>
        </div>
      </template>
    </div>

    <!-- 评审详情 · 抽取 / 邀请 / 打分 / 结论 / 评审费 -->
    <div class="pane" v-show="tab === 'detail'">
      <div v-if="!selectedId" class="card"><div class="card-b" style="padding:32px;text-align:center;color:var(--ink-mute)">请先在「评审任务」中选择一项。</div></div>
      <div v-else-if="detailLoading" class="card"><div class="card-b" style="color:var(--ink-mute)">评审详情加载中…</div></div>
      <div v-else-if="!detail" class="card"><div class="card-b" style="padding:32px;text-align:center;color:var(--ink-mute)">评审不存在或无权访问</div></div>

      <template v-else>
        <div class="grid g3">
          <!-- 概要 + 状态机时间轴 -->
          <div class="card">
            <div class="card-h"><h4>评审概要</h4><span class="tag" :class="(RV_STATUS[status]||{}).cls">{{ (RV_STATUS[status]||{}).txt || status }}</span></div>
            <div class="card-b" style="display:flex;flex-direction:column;gap:10px">
              <div class="rv-title">{{ detail.task.title }}</div>
              <div class="mono" style="font-size:11px;color:var(--ink-mute)">{{ detail.task.code || '—' }} · {{ BIZ_TXT[detail.task.biz_type] || detail.task.biz_type }}</div>
              <div class="divider-double"></div>
              <div class="hbar"><span class="nm" style="width:96px">抽取</span><div class="track"><i :style="{ width: gate.draw ? '0%' : '20%', background:'var(--ink)' }"></i></div><span class="v">{{ detail.task.drawn_at ? '✓' : '—' }}</span></div>
              <div class="hbar"><span class="nm" style="width:96px">已接受</span><div class="track"><i :style="{ width: Math.min(100, acceptCount*33) + '%', background:'var(--ok)' }"></i></div><span class="v">{{ acceptCount }}</span></div>
              <div class="hbar"><span class="nm" style="width:96px">已打分</span><div class="track"><i :style="{ width: Math.min(100, scoreDoneCount*33) + '%', background:'var(--ai)' }"></i></div><span class="v">{{ scoreDoneCount }}</span></div>
              <div v-if="detail.task.conclusion" class="tag ok" style="margin-top:4px">结论：{{ detail.task.conclusion }}</div>
            </div>
          </div>

          <!-- 抽取面板（R-MANAGER，DRAFT 时可用） -->
          <div class="card">
            <div class="card-h"><h4>抽取与发起</h4><span class="tag ai" v-if="!canManage">需主管</span></div>
            <div class="card-b" style="display:flex;flex-direction:column;gap:12px">
              <div style="display:flex;gap:8px">
                <select class="sel" v-model="drawMethod" :disabled="!gate.draw || !canManage">
                  <option v-for="(v, k) in METHOD_TXT" :key="k" :value="k">{{ v }}</option>
                </select>
                <input class="sel" style="width:80px" type="number" min="1" v-model.number="drawCount" :disabled="!gate.draw || !canManage" />
              </div>
              <div style="display:flex;flex-direction:column;gap:8px">
                <button class="btn sm" :disabled="busy || !gate.draw || !canManage" @click="doDraw">① 抽取专家（→DRAWN）</button>
                <button class="btn sm ghost" :disabled="busy || !gate.invite || !canManage" @click="doInvite">② 发出邀请（→INVITING）</button>
                <button class="btn sm ghost" :disabled="busy || !gate.start || !canManage" @click="doStart">③ 开始评审（→IN_REVIEW）</button>
              </div>
              <div style="font-size:11px;color:var(--ink-mute)">抽取按回避规则（avoid_orgs / avoid_person_ids）确定性随机。</div>
            </div>
          </div>

          <!-- 打分 / 结论 / 评审费 -->
          <div class="card">
            <div class="card-h"><h4>打分 · 结论 · 评审费</h4></div>
            <div class="card-b" style="display:flex;flex-direction:column;gap:8px">
              <button class="btn sm ai" :disabled="busy || !gate.score || !canScore" @click="openScore">专家提交打分</button>
              <button class="btn sm seal" :disabled="busy || !gate.conclude || !canManage" @click="doConclude">汇总结论（回写 E/R）</button>
              <button class="btn sm ghost" :disabled="busy || !gate.fees || !canManage" @click="doFees">生成评审费（联动 F）</button>
              <div v-if="!canScore && gate.score" style="font-size:11px;color:var(--warn)">打分仅评审专家（R-EXPERT）可操作。</div>
              <div style="border-top:1px dashed var(--line-hard,#e5e0d4);padding-top:8px;font-size:12px">
                <div class="r" style="display:flex;justify-content:space-between;margin-bottom:4px"><span>平均分</span><span class="mono">{{ detail.task.score_summary ? num(detail.task.score_summary.avg).toFixed(2) : '—' }}</span></div>
                <div class="r" style="display:flex;justify-content:space-between"><span>打分条数</span><span class="mono">{{ (detail.scores || []).length }}</span></div>
              </div>
            </div>
          </div>
        </div>

        <!-- 邀请名单 -->
        <div class="card" style="margin-top:16px;padding:0">
          <div class="card-h"><h4>邀请名单（{{ (detail.invitations || []).length }}）</h4><span class="tag info">回避命中 {{ (detail.invitations||[]).filter(i=>i.avoid_hit).length }}</span></div>
          <table class="tbl">
            <thead><tr><th>座次</th><th>专家</th><th>专家 ID</th><th>回避命中</th><th>响应</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="inv in detail.invitations" :key="inv.id">
                <td class="mono">{{ inv.seat_no }}</td>
                <td>{{ inv.expert_name || ('#' + inv.expert_id) }}</td>
                <td class="mono">{{ inv.expert_id }}</td>
                <td><span class="tag" :class="inv.avoid_hit ? 'bad' : 'ok'">{{ inv.avoid_hit ? '命中' : '无' }}</span></td>
                <td><span class="tag" :class="(RESP_TXT[inv.response]||{}).cls">{{ (RESP_TXT[inv.response]||{}).txt || inv.response }}</span></td>
                <td>
                  <template v-if="canScore && gate.respond && inv.response === 'PENDING'">
                    <button class="btn sm ghost" :disabled="busy" @click="doRespond(inv.expert_id, true)">接受</button>
                    <button class="btn sm ghost" :disabled="busy" @click="doRespond(inv.expert_id, false)" style="margin-left:6px">拒绝</button>
                  </template>
                  <span v-else style="color:var(--ink-mute);font-size:11px">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 打分明细 -->
        <div class="card" style="margin-top:16px;padding:0">
          <div class="card-h"><h4>在线打分（{{ (detail.scores || []).length }}）</h4></div>
          <div v-if="!(detail.scores && detail.scores.length)" style="padding:24px;color:var(--ink-mute)">尚无打分记录。</div>
          <table v-else class="tbl">
            <thead><tr><th>专家 ID</th><th>维度得分</th><th>总分</th><th>评语</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="s in detail.scores" :key="s.id">
                <td class="mono">{{ s.expert_id }}</td>
                <td>
                  <span class="tag info" style="margin-right:4px" v-for="(d, di) in (s.dimension_scores || [])" :key="di">{{ d.dimension }} · {{ d.score }}</span>
                </td>
                <td class="mono" style="font-weight:700;color:var(--seal)">{{ s.total_score == null ? '—' : num(s.total_score).toFixed(2) }}</td>
                <td style="font-size:12px;color:var(--ink-soft)">{{ s.comment || '—' }}</td>
                <td><span class="tag" :class="s.status === 'SUBMITTED' ? 'ok' : 'warn'">{{ s.status === 'SUBMITTED' ? '已提交' : '弃权' }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>

    <!-- 打分浮层（演示） -->
    <div v-if="scoreModal" class="mask" @click.self="scoreModal = false">
      <div class="card" style="width:320px">
        <div class="card-h"><h4>提交打分</h4></div>
        <div class="card-b" style="display:flex;flex-direction:column;gap:12px">
          <label style="font-size:12px">总分（0-100）</label>
          <input class="sel" v-model="scoreTotal" />
          <div style="display:flex;gap:8px;justify-content:flex-end">
            <button class="btn sm ghost" @click="scoreModal = false">取消</button>
            <button class="btn sm" :disabled="busy" @click="submitScore">提交</button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.sel { font-size:12px; padding:5px 10px; border:1px solid var(--line-hard,#d8d2c4); border-radius:6px; background:#fff; outline:none; }
.sel:focus { border-color:var(--ink); }
.sel:disabled { opacity:.5; cursor:not-allowed; }
.pager { display:flex;align-items:center;gap:14px;justify-content:center;margin-top:18px; }
.pg-info { font-size:12px;color:var(--ink-mute); }
.pager .btn:disabled { opacity:.4;cursor:not-allowed; }
.btn[disabled] { opacity:.5;cursor:not-allowed;transform:none; }
.rv-card { cursor:pointer;transition:.15s; }
.rv-card:hover { box-shadow:var(--sh1,0 4px 14px rgba(0,0,0,.08)); }
.rv-title { font-family:var(--serif);font-weight:700;font-size:15px;line-height:1.4; }
.mask { position:fixed;inset:0;background:rgba(20,20,20,.4);display:grid;place-items:center;z-index:60; }
</style>
