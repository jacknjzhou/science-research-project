<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, list } from '@/api/client'

interface Badge { label: string; cls: string }
interface ClaimCard {
  id: number
  code: string
  output_type: 'PAPER' | 'PATENT' | 'SOFTWARE'
  title: string
  authors: string
  venue: string
  year: number
  source: string
  match_confidence: number
  claim_status: string
  doubt?: string
  badges?: Badge[]
  suggest?: string
  suggest_id?: number
}

const toast = (m: string) => (window as any).toast?.(m)

type FilterKey = 'all' | 'PAPER' | 'PATENT' | 'high' | 'doubt'

const items = ref<ClaimCard[]>([])
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
      return l.filter((c) => c.match_confidence >= 0.85)
    case 'doubt':
      return l.filter((c) => c.claim_status === 'DOUBTFUL')
    default:
      return l
  }
})

const confPct = (c: ClaimCard) => Math.round((c.match_confidence ?? 0) * 100)
const confColor = (c: ClaimCard) =>
  c.claim_status === 'DOUBTFUL' || (c.match_confidence ?? 0) < 0.7 ? 'var(--warn)' : undefined
const ringStyle = (c: ClaimCard) => `--p:${confPct(c)}%`
const claimed = (c: ClaimCard) => c.claim_status === 'CLAIMED'
const restCount = computed(() => Math.max(pendingTotal.value - items.value.length, 0))

async function load() {
  loading.value = true
  try {
    const { rows, total } = await list<ClaimCard>('/output/pending-claim', { min_confidence: 0 })
    items.value = rows ?? []
    pendingTotal.value = total ?? rows?.length ?? 0
    const mine = await api.get<{ total?: number }>('/output/mine')
    mineTotal.value = mine?.total ?? 0
  } catch (e: any) {
    toast('数据加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function claimOne(c: ClaimCard) {
  if (busy.value || claimed(c)) return
  busy.value = true
  try {
    await api.post('/output/claim', { action: 'CLAIM', items: [{ output_id: c.id }] })
    c.claim_status = 'CLAIMED'
    toast('已认领 → 待关联项目 ✓')
  } catch (e: any) {
    toast('认领失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}

async function claimHigh() {
  const hs = items.value.filter((c) => c.match_confidence >= 0.85 && !claimed(c))
  if (!hs.length) return toast('暂无高置信记录可认领')
  busy.value = true
  try {
    await api.post('/output/claim', { action: 'CLAIM', items: hs.map((h) => ({ output_id: h.id })) })
    hs.forEach((h) => (h.claim_status = 'CLAIMED'))
    toast(`已批量认领 ${hs.length} 条高置信记录`)
  } catch (e: any) {
    toast('批量认领失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}

async function assignProject(c: ClaimCard) {
  busy.value = true
  try {
    await api.put(`/output/${c.id}/projects`, {
      project_ids: [c.suggest_id ?? 87],
      relation_type: 'PRIMARY',
    })
    toast('已归属项目：' + (c.suggest?.split('（')[0] || 'PRJ-2024-00087') + ' ✓')
  } catch (e: any) {
    toast('关联失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}

async function markNotMine(c: ClaimCard) {
  busy.value = true
  try {
    await api.post('/output/mark-not-mine', { action: 'MARK_NOT_MINE', items: [{ output_id: c.id }] })
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
            <span v-if="c.doubt" style="font-weight:400;color:var(--warn)">（{{ c.doubt }}）</span>
          </div>
          <div style="font-size:12px;color:var(--ink-mute);margin-top:4px">
            <b style="color:var(--ok)">{{ c.authors }}</b> — <i>{{ c.venue }}</i> · {{ c.year }}
            <span v-for="b in c.badges" :key="b.label" class="tag" :class="b.cls" style="margin-left:6px">{{ b.label }}</span>
          </div>
          <div v-if="c.suggest" style="font-size:11px;color:var(--ai);margin-top:5px">✦ 建议关联：{{ c.suggest }}</div>
          <div v-if="c.claim_status === 'DOUBTFUL'" style="margin-top:6px">
            <button class="btn sm ghost" @click="toast('展开对比：合作者/单位/摘要相似度（演示）')">查看匹配证据</button>
          </div>
        </div>

        <div class="claim-actions">
          <button class="btn sm seal" :disabled="claimed(c)" @click="claimOne(c)">{{ claimed(c) ? '已认领' : '认领' }}</button>
          <button v-if="c.suggest_id || c.suggest" class="btn sm ghost" @click="assignProject(c)">归属项目</button>
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
