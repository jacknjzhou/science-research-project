<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { list } from '@/api/client'
import { toPct } from '@/utils/money'
import { useDict, toRecord } from '@/composables/useDict'

// 成果台账（module R · GET /output）。数据模型对齐后端 ToAPIOutput（snake_case）。
interface AuthorItem { user_id: number | null; name: string; order?: number; is_corresponding?: boolean }
interface Output {
  id: number
  code: string | null
  status: string
  output_type: string
  title: string
  title_en: string | null
  publish_date: string | null
  authors: AuthorItem[]
  external_author_names?: { name: string; inst: string }[]
  project_ids: number[]
  source: string
  is_claimed: boolean
  claim_status: string
  match_confidence: number | null
  security_level: string
  remark: string | null
  [k: string]: any
}

const toast = (m: string) => (window as any).toast?.(m)

const rows = ref<Output[]>([])
const total = ref(0)
const loading = ref(true)

const page = ref(1)
const size = ref(12)
const outputType = ref('')
const status = ref('')
const kw = ref('')
const year = ref('')
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / size.value)))

const TYPE_FILTERS: { v: string; t: string }[] = [
  { v: '', t: '全部类型' },
  { v: 'PAPER', t: '论文' },
  { v: 'PATENT', t: '专利' },
  { v: 'SOFTWARE', t: '软著' },
  { v: 'STANDARD', t: '标准' },
  { v: 'AWARD', t: '奖励' },
  { v: 'BOOK', t: '著作' },
  { v: 'DATASET', t: '数据集' },
]

const STATUS_FILTERS: { v: string; t: string }[] = [
  { v: '', t: '全部状态' },
  { v: 'PENDING_CLAIM', t: '待认领' },
  { v: 'CLAIMED', t: '已认领' },
  { v: 'ASSIGNED_TO_PROJECT', t: '已归属项目' },
  { v: 'COUNTED_FOR_PERFORMANCE', t: '已计绩效' },
  { v: 'REJECTED', t: '已拒绝' },
]

const TYPE_TEXT: Record<string, string> = {
  PAPER: '论文', PATENT: '专利', SOFTWARE: '软著', STANDARD: '标准', AWARD: '奖励',
  BOOK: '著作', DATASET: '数据集', CONFERENCE: '会议', NEW_VARIETY: '新品种',
  LAYOUT: '版图', APPRAISAL: '鉴定', HONOR: '荣誉',
}
// 成果来源：字典 output_source（PRD 2.8），useDict 拉取 + 硬编码 fallback
const { items: sourceDict } = useDict('output_source', [
  { code: 'WOS', label: 'WoS' }, { code: 'SCOPUS', label: 'Scopus' }, { code: 'CNKI', label: '知网' },
  { code: 'WANFANG', label: '万方' }, { code: 'CNIPA', label: '国知局' }, { code: 'CROSSREF', label: 'CrossRef' },
  { code: 'FETCH', label: '抓取' }, { code: 'MANUAL', label: '手动' }, { code: 'ALTMETRIC', label: 'Altmetric' },
])
const SOURCE_TEXT = computed(() => toRecord(sourceDict.value))
const STATUS_TEXT: Record<string, string> = {
  AUTO_FETCHED: '已抓取', PENDING_CLAIM: '待认领', CLAIMED: '已认领',
  ASSIGNED_TO_PROJECT: '已归属项目', COUNTED_FOR_PERFORMANCE: '已计绩效',
  MANUAL_DRAFT: '手稿', PENDING_REVIEW: '待审核', REJECTED: '已拒绝',
}
const SEC_CLS: Record<string, string> = {
  PUBLIC: 'ok', INTERNAL: '', SECRET: 'warn', TOP_SECRET: 'risk',
}

const authorsStr = (c: Output) => {
  const a = (c.authors || []).map((x) => x.name + (x.is_corresponding ? '*' : '')).join('，')
  if (a) return a
  const ext = (c.external_author_names || []).map((x) => x.name).join('，')
  return ext || '—'
}
const yearOf = (c: Output) => (c.publish_date ? c.publish_date.slice(0, 4) : '—')
const confPct = (c: Output) => (c.match_confidence == null ? null : toPct(c.match_confidence))

const counts = computed(() => {
  const claimed = rows.value.filter((c) => c.is_claimed || c.claim_status === 'CLAIMED').length
  const pending = rows.value.filter((c) => c.status === 'PENDING_CLAIM' || c.claim_status === 'DOUBTFUL').length
  const perf = rows.value.filter((c) => c.status === 'COUNTED_FOR_PERFORMANCE').length
  return { claimed, pending, perf }
})

async function load() {
  loading.value = true
  try {
    const { rows: r, total: t } = await list<Output>('/output', {
      page: page.value,
      size: size.value,
      output_type: outputType.value || undefined,
      status: status.value || undefined,
      keyword: kw.value || undefined,
      year: year.value || undefined,
    })
    rows.value = r ?? []
    total.value = t ?? rows.value.length
  } catch (e: any) {
    toast('成果加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
onMounted(load)

function reload() {
  page.value = 1
  load()
}
function setType(v: string) { outputType.value = v; reload() }
function setStatus(v: string) { status.value = v; reload() }
function goPage(delta: number) {
  const next = page.value + delta
  if (next < 1 || next > pageCount.value) return
  page.value = next
  load()
}
</script>

<template>
  <section class="view on" id="v-output">
    <div class="page-head">
      <div>
        <div class="page-title">成果<em>台账</em></div>
        <div class="page-sub">
          共 <b style="color:var(--seal)">{{ total }}</b> 项 · 已认领 {{ counts.claimed }} · 待认领/存疑 {{ counts.pending }} · 已计绩效 {{ counts.perf }}
        </div>
      </div>
      <div class="seg">
        <select class="sel" v-model="outputType" @change="reload">
          <option v-for="t in TYPE_FILTERS" :key="t.v" :value="t.v">{{ t.t }}</option>
        </select>
      </div>
    </div>

    <div class="filter-row">
      <input class="sel" style="min-width:200px" v-model="kw" placeholder="搜索成果标题 / 编号" @keyup.enter="reload" />
      <input class="sel" style="min-width:90px" v-model="year" placeholder="年度 2026" @keyup.enter="reload" />
      <span class="chip" v-for="s in STATUS_FILTERS" :key="s.v" :class="{ on: status === s.v }" @click="setStatus(s.v)">{{ s.t }}</span>
      <button class="btn ghost sm" @click="reload">查询</button>
    </div>

    <div v-if="loading" class="card"><div class="card-b" style="color:var(--ink-mute)">成果加载中…</div></div>

    <div v-else-if="!rows.length" class="card">
      <div class="card-b" style="padding:36px;text-align:center;color:var(--ink-mute)">暂无符合条件的成果</div>
    </div>

    <template v-else>
      <div class="grid g3">
        <div class="card out-card" v-for="c in rows" :key="c.id">
          <div class="out-top">
            <span class="tag">{{ TYPE_TEXT[c.output_type] || c.output_type }}</span>
            <span class="tag" :class="SEC_CLS[c.security_level] || ''">{{ c.security_level }}</span>
            <span v-if="confPct(c) != null" class="conf-badge">{{ confPct(c) }}%</span>
          </div>
          <h5 class="out-title">{{ c.title }}</h5>
          <div class="out-sub">{{ c.code || '—' }} · {{ (SOURCE_TEXT[c.source] || c.source) }} · {{ yearOf(c) }}</div>

          <div class="rows">
            <div class="r"><span>完成人</span><span class="mono" style="max-width:60%;text-align:right">{{ authorsStr(c) }}</span></div>
            <div class="r"><span>状态</span><span class="tag" :class="c.is_claimed ? 'ok' : (c.claim_status === 'DOUBTFUL' ? 'warn' : '')">{{ STATUS_TEXT[c.status] || c.status }}</span></div>
            <div class="r"><span>归属项目</span><span class="mono">{{ c.project_ids && c.project_ids.length ? c.project_ids.length + ' 个' : '未关联' }}</span></div>
          </div>

          <div v-if="c.remark" class="out-remark">{{ c.remark }}</div>
        </div>
      </div>

      <div class="pager">
        <button class="btn ghost sm" :disabled="page <= 1" @click="goPage(-1)">← 上一页</button>
        <span class="mono pg-info">第 {{ page }} / {{ pageCount }} 页 · 共 {{ total }} 项</span>
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
.out-top { display:flex; align-items:center; gap:6px; margin-bottom:6px; }
.conf-badge { margin-left:auto; font-size:12px; font-weight:700; color:var(--seal); }
.out-title { font-family:var(--serif); font-weight:700; font-size:14px; line-height:1.4; }
.out-sub { font-size:12px; color:var(--ink-mute); margin:4px 0 8px; }
.out-remark { font-size:11px; color:var(--ink-mute); margin-top:8px; border-top:1px dashed var(--line-hard, #e5e0d4); padding-top:6px; }
</style>
