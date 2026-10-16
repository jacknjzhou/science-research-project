<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, list } from '@/api/client'
import { toPct } from '@/utils/money'
import { useDict, toRecord } from '@/composables/useDict'

// 数据模型严格对齐后端 mapper.go ToAPIOutput（design/04 Output）。
// 展示态字段（作者串、年份、来源标签、存疑说明）在视图层从契约字段派生。
interface AuthorItem { user_id: number | null; name: string; order?: number; is_corresponding?: boolean }
interface Output {
  id: number
  code: string | null
  tenant_id: number
  status: string
  output_type: string
  title: string
  title_en: string | null
  abstract: string | null
  publish_date: string | null
  authors: AuthorItem[]
  external_author_names?: { name: string; inst: string }[]
  affiliations?: { user_id: number | null; inst_id: number | null; is_primary: boolean }[]
  project_ids: number[]
  language: string | null
  source: string
  is_claimed: boolean
  claim_status: string
  match_confidence: number | null
  security_level: string
  remark: string | null
  [k: string]: any
}

const toast = (m: string) => (window as any).toast?.(m)

type FilterKey = 'all' | 'PAPER' | 'PATENT' | 'high' | 'doubt'

const items = ref<Output[]>([])
const pendingTotal = ref(0)
const mineTotal = ref(0)
const loading = ref(true)
const busy = ref(false)
const filter = ref<FilterKey>('all')

const CHIPS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'PAPER', label: '论文' },
  { key: 'PATENT', label: '专利' },
  { key: 'high', label: '高置信 ≥85%' },
  { key: 'doubt', label: '存疑待确认' },
]

const visible = computed(() => {
  const l = items.value
  switch (filter.value) {
    case 'PAPER':
    case 'PATENT':
      return l.filter((c) => c.output_type === filter.value)
    case 'high':
      return l.filter((c) => (c.match_confidence ?? 0) >= 0.85)
    case 'doubt':
      return l.filter((c) => c.claim_status === 'DOUBTFUL')
    default:
      return l
  }
})

// —— 派生展示助手（从契约字段计算，无 venue/year/suggest 等视图态字段）——
const confPct = (c: Output) => toPct(c.match_confidence ?? 0)
const confColor = (c: Output) =>
  c.claim_status === 'DOUBTFUL' || (c.match_confidence ?? 0) < 0.7 ? 'var(--warn)' : undefined
const ringStyle = (c: Output) => `--p:${confPct(c)}%`
const claimed = (c: Output) => c.is_claimed || c.claim_status === 'CLAIMED'

const authorsStr = (c: Output) => {
  const a = (c.authors || []).map((x) => x.name + (x.is_corresponding ? '*' : '')).join('，')
  if (a) return a
  const ext = (c.external_author_names || []).map((x) => x.name).join('，')
  return ext || '—'
}
const yearOf = (c: Output) => (c.publish_date ? c.publish_date.slice(0, 4) : '—')
const sourceLabel = (c: Output) => SOURCE_TEXT.value[c.source] || c.source
const typeLabel = (c: Output) => TYPE_TEXT[c.output_type] || c.output_type
const linked = (c: Output) => (c.project_ids || []).length > 0
const restCount = computed(() => Math.max(pendingTotal.value - items.value.length, 0))

// 成果来源：字典 output_source（PRD 2.8），useDict 拉取 + 硬编码 fallback
const { items: sourceDict } = useDict('output_source', [
  { code: 'WOS', label: 'WoS' }, { code: 'SCOPUS', label: 'Scopus' }, { code: 'CNKI', label: '知网' },
  { code: 'WANFANG', label: '万方' }, { code: 'CNIPA', label: '国家知识产权局' }, { code: 'CROSSREF', label: 'CrossRef' },
  { code: 'FETCH', label: '增量抓取' }, { code: 'MANUAL', label: '手动录入' }, { code: 'ALTMETRIC', label: 'Altmetric' },
])
const SOURCE_TEXT = computed(() => toRecord(sourceDict.value))
const TYPE_TEXT: Record<string, string> = {
  PAPER: '论文', PATENT: '专利', SOFTWARE: '软著', STANDARD: '标准',
  AWARD: '奖励', BOOK: '著作', DATASET: '数据集', CONFERENCE: '会议', HONOR: '荣誉',
}

async function load() {
  loading.value = true
  try {
    const { rows, total } = await list<Output>('/output/pending-claim', { min_confidence: 0 })
    items.value = rows ?? []
    pendingTotal.value = total ?? rows?.length ?? 0
    const mine = await list<Output>('/output/mine')
    mineTotal.value = mine?.total ?? 0
  } catch (e: any) {
    toast('数据加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function claimOne(c: Output) {
  if (busy.value || claimed(c)) return
  busy.value = true
  try {
    await api.post('/output/claim', { items: [{ output_id: c.id }] })
    c.is_claimed = true
    c.claim_status = 'CLAIMED'
    toast('已认领 → 待关联项目 ✓')
  } catch (e: any) {
    toast('认领失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}

async function claimHigh() {
  const hs = items.value.filter((c) => (c.match_confidence ?? 0) >= 0.85 && !claimed(c))
  if (!hs.length) return toast('暂无高置信记录可认领')
  busy.value = true
  try {
    await api.post('/output/claim', { items: hs.map((h) => ({ output_id: h.id })) })
    hs.forEach((h) => { h.is_claimed = true; h.claim_status = 'CLAIMED' })
    toast(`已批量认领 ${hs.length} 条高置信记录`)
  } catch (e: any) {
    toast('批量认领失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}

async function assignProject(c: Output) {
  busy.value = true
  try {
    // 归属到本人第一个真实项目（mock 时代的 90001 在真后端不存在）
    const mine = await list<{ id: number }>('/project/mine', { size: 1 })
    const pid = (mine.rows[0] as { id?: number })?.id
    if (!pid) { toast('暂无项目，请先完成项目立项'); return }
    await api.put(`/output/${c.id}/projects`, { project_ids: [pid], relation_type: 'ASSIGNED_TO_PROJECT' })
    c.project_ids = [pid]
    c.status = 'ASSIGNED_TO_PROJECT'
    toast('已归属项目 ✓')
  } catch (e: any) {
    toast('关联失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}

async function markNotMine(c: Output) {
  busy.value = true
  try {
    await api.post('/output/mark-not-mine', { items: [{ output_id: c.id }] })
    items.value = items.value.filter((x) => x.id !== c.id)
    toast('已反馈非本人，模型将学习此负例')
  } catch (e: any) {
    toast('操作失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="view on" id="v-claim">
    <div class="page-head">
      <div>
        <div class="page-title">成果<em>认领</em></div>
        <div class="page-sub">
          来自 WoS / Scopus / CNKI 增量抓取 <b style="color:var(--seal)">{{ pendingTotal }}</b> 条 ·
          匹配置信度排序 · 认领后自动进入绩效 · 本年度成果 <b style="color:var(--gold)">{{ mineTotal }}</b> 项
        </div>
      </div>
      <button class="btn seal" @click="claimHigh">⚡ 一键认领高置信</button>
    </div>

    <div class="filter-row">
      <span
        class="chip"
        :class="{ on: filter === c.key }"
        v-for="c in CHIPS"
        :key="c.key"
        @click="filter = c.key"
      >{{ c.label }}</span>
    </div>

    <div class="grid" style="gap:12px">
      <div v-if="loading" class="card"><div class="card-b" style="padding:28px;text-align:center;color:var(--ink-mute)">正在匹配增量成果…</div></div>

      <div v-else-if="!visible.length" class="card"><div class="card-b" style="padding:28px;text-align:center;color:var(--ink-mute)">当前筛选下暂无待认领成果。</div></div>

      <div class="claim-card" v-for="c in visible" :key="c.id" :style="claimed(c) ? 'opacity:.55' : undefined">
        <div class="conf-ring" :style="ringStyle(c)">
          <b :style="confColor(c) ? `color:${confColor(c)}` : undefined">{{ claimed(c) ? '✓' : confPct(c) + '%' }}</b>
        </div>

        <div style="flex:1">
          <div style="font-family:var(--serif);font-weight:700;font-size:14px">
            {{ c.title }}
            <span class="tag" style="margin-left:6px">{{ typeLabel(c) }}</span>
          </div>
          <div style="font-size:12px;color:var(--ink-mute);margin-top:4px">
            <b style="color:var(--ok)">{{ authorsStr(c) }}</b> — {{ sourceLabel(c) }} · {{ yearOf(c) }}
            <span v-if="linked(c)" class="tag ok" style="margin-left:6px">已关联 {{ c.project_ids.length }} 个项目</span>
          </div>
          <div v-if="c.claim_status === 'DOUBTFUL' && c.remark" style="font-size:11px;color:var(--warn);margin-top:5px">
            ⚠ {{ c.remark }}
          </div>
        </div>

        <div class="claim-actions">
          <button class="btn sm seal" :disabled="claimed(c)" @click="claimOne(c)">{{ claimed(c) ? '已认领' : '认领' }}</button>
          <button v-if="claimed(c) && !linked(c)" class="btn sm ghost" @click="assignProject(c)">归属项目</button>
          <button v-if="c.claim_status === 'DOUBTFUL'" class="btn sm ghost" @click="toast('已转交科研办仲裁')">仲裁</button>
          <button v-else class="btn sm ghost" @click="markNotMine(c)">不是我的</button>
        </div>
      </div>

      <div v-if="!loading && restCount > 0" class="claim-card" style="opacity:.6">
        <div class="conf-ring"><b style="font-size:10px;color:var(--ink-mute)">待办</b></div>
        <div style="flex:1">
          <div style="font-weight:700;font-size:13.5px">另有 {{ restCount }} 条低置信与外部成果池记录</div>
          <div style="font-size:12px;color:var(--ink-mute);margin-top:3px">系统持续增量抓取，每日 06:00 更新待认领清单。</div>
        </div>
        <button class="btn sm ghost" @click="toast(`展开其余 ${restCount} 条（演示）`)">展开全部</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.btn[disabled] { opacity: .55; cursor: default; transform: none; }
</style>
