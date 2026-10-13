<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { list } from '@/api/client'

interface GuideTag { text: string; cls: string }
interface Guideline {
  id: number
  code?: string
  title?: string
  project_type?: string
  funding_source?: string
  status?: string
  apply_end_at?: string | null
  total_envelope?: string
  ico?: string
  ico_color?: string
  notes?: string[]
  tags?: GuideTag[]
  ai_match?: number
}

const toast = (m: string) => (window as any).toast?.(m)

// 原型时间锚点（与驾驶舱"2026-10-13"一致），倒计时基于 apply_end_at 计算。
const NOW = new Date('2026-10-13T00:00:00Z').getTime()
const DAY = 86400000

const rows = ref<Guideline[]>([])
const total = ref(0)
const loading = ref(true)
const activeType = ref('全部')
const aiOnly = ref(false)

const TYPES = ['全部', '国家自然科学基金', '重点研发计划', '院自立项目', '省部级', '横向委托']
const ICO_COLOR: Record<string, string> = {
  国家自然科学基金: 'var(--seal)',
  重点研发计划: 'var(--ink)',
  院自立项目: 'var(--gold)',
  省部级: '#41598C',
  横向委托: 'var(--ai)',
}

const visible = computed(() => {
  let r = rows.value
  if (activeType.value !== '全部') r = r.filter((g) => g.project_type === activeType.value)
  if (aiOnly.value) r = r.filter((g) => (g.ai_match ?? 0) >= 0.8)
  return r
})

const aiMatched = computed(() => rows.value.filter((g) => (g.ai_match ?? 0) >= 0.8).length)

function daysLeft(g: Guideline): string {
  if (g.status === 'CLOSED' || !g.apply_end_at) return '—'
  const d = Math.round((new Date(g.apply_end_at).getTime() - NOW) / DAY)
  return d > 0 ? String(d) : '—'
}
const countdownDim = (g: Guideline) => g.status === 'CLOSED' || !g.apply_end_at
function icoColor(g: Guideline) {
  return g.ico_color || ICO_COLOR[g.project_type || ''] || 'var(--ink)'
}
function icoText(g: Guideline) {
  return g.ico || (g.project_type || '').slice(0, 2)
}

async function load() {
  loading.value = true
  try {
    const res = await list<Guideline>('/apply/guidelines', { size: 20, status: 'PUBLISHED' })
    rows.value = res.rows
    total.value = res.total || res.rows.length
  } catch (e: any) {
    toast('指南加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
onMounted(load)

function openGuide(g: Guideline) {
  if ((g.ai_match ?? 0) >= 0.8) {
    toast('已匹配高相关指南，进入申报书撰写')
  } else {
    toast('查看指南详情：' + (g.title || ''))
  }
}
</script>

<template>
  <section class="view on" id="v-guide">
    <div class="page-head">
      <div>
        <div class="page-title">申报<em>指南</em></div>
        <div class="page-sub">
          根据你的研究方向（先进制造 · 机器人学）智能排序 ·
          <span style="color:var(--ai)">AI 已为你匹配 {{ aiMatched }} 条高相关指南</span>
        </div>
      </div>
      <button class="btn ghost" @click="toast('订阅推送设置（演示）')">✉ 订阅推送</button>
    </div>

    <div class="filter-row">
      <span
        class="chip"
        :class="{ on: activeType === t && !aiOnly }"
        v-for="t in TYPES"
        :key="t"
        @click="activeType = t; aiOnly = false"
        >{{ t === '全部' ? `全部 (${total})` : t }}</span
      >
      <span class="chip" :class="{ on: aiOnly }" style="border-style:dashed;color:var(--ai)" @click="aiOnly = !aiOnly">◈ AI 推荐匹配</span>
    </div>

    <div v-if="loading" class="card"><div class="card-b" style="text-align:center;color:var(--ink-mute)">正在加载指南…</div></div>

    <div v-else-if="visible.length === 0" class="card">
      <div class="card-b" style="text-align:center;color:var(--ink-mute);padding:36px">该筛选条件下暂无指南，试试切换方向或关闭 AI 推荐。</div>
    </div>

    <div v-else class="grid" style="gap:12px">
      <div class="card guide-card" v-for="g in visible" :key="g.id" @click="openGuide(g)">
        <div class="ico" :style="{ background: icoColor(g) }">{{ icoText(g) }}</div>
        <div>
          <h5>{{ g.title }}</h5>
          <div class="meta"><span v-for="(n, i) in g.notes || []" :key="i">{{ n }}</span></div>
          <div style="margin-top:8px">
            <span class="tag" :class="tag.cls" v-for="(tag, i) in g.tags || []" :key="i">{{ tag.text }}</span>
          </div>
        </div>
        <div class="count-down" :style="{ opacity: countdownDim(g) ? 0.45 : 1 }">
          <div class="d" :style="countdownDim(g) ? { color: 'var(--ink-mute)' } : undefined">{{ daysLeft(g) }}</div>
          <div class="l">{{ countdownDim(g) ? '未开放' : '天后截止' }}</div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.guide-card .meta span { white-space: nowrap; }
</style>
