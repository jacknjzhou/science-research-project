<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api } from '@/api/client'
import { auth } from '@/api/auth'
import { toWan } from '@/utils/money'

interface RadarDimension { dimension: string; value: number; normalized: number }
interface Portrait {
  staff_id: number; snapshot_date: string; project_count_total: number; project_count_active: number
  funding_total: number; output_count_papers: number; output_count_patents: number; h_index: number
  total_citations: number; collaboration_score: number; mentoring_count: number; career_stage: string
  ai_summary: string; integrity_flag: boolean; expertise_tags: { tag: string }[]
}
interface PortraitDetail { latest: Portrait; radar: RadarDimension[]; timeline: { year: number; type: string; title: string }[]; top_outputs: { title: string; type: string; venue: string }[] }
interface CollabNode { staff_id: number; name: string; institution: string | null; node_size: number; community_id: number | null; centrality: number | null }
interface CollabEdge { staff_a_id: number; staff_b_id: number; weight: number }
interface CollabGraph { snapshot_date: string; center_staff_id: number; nodes: CollabNode[]; edges: CollabEdge[] }

const toast = (m: string) => (window as any).toast?.(m)
// 默认展示当前登录用户画像（mock 时代的 90001 已废弃）
const STAFF_ID = String(auth.user?.id ?? '')

const portrait = ref<PortraitDetail | null>(null)
const graph = ref<CollabGraph | null>(null)
const loading = ref(true)

const DIM_LABEL: Record<string, string> = {
  PROJECT: '项目承担', FUNDING: '经费规模', OUTPUT: '成果产出', IMPACT: '影响力', MENTORING: '人才培养', COLLAB: '合作网络',
}
const STAGE: Record<string, string> = { RISING: '上升期', STABLE: '稳定期', MATURE: '成熟期' }

const CX = 120, CY = 105, MAXR = 85
function polar(angleDeg: number, r: number) {
  const rad = (angleDeg * Math.PI) / 180
  return { x: +(CX + r * Math.cos(rad)).toFixed(1), y: +(CY + r * Math.sin(rad)).toFixed(1) }
}
const radar = computed<RadarDimension[]>(() => portrait.value?.radar ?? [])
const n = computed(() => Math.max(radar.value.length, 1))
function angleAt(i: number) { return -90 + (i * 360) / n.value }
const dataPolygon = computed(() =>
  radar.value.map((d, i) => { const p = polar(angleAt(i), MAXR * Math.min(1, d.normalized || 0)); return `${p.x},${p.y}` }).join(' '),
)
const guideOuter = computed(() =>
  Array.from({ length: n.value }, (_, i) => { const p = polar(angleAt(i), MAXR); return `${p.x},${p.y}` }).join(' '),
)
const guideMid = computed(() =>
  Array.from({ length: n.value }, (_, i) => { const p = polar(angleAt(i), MAXR / 2); return `${p.x},${p.y}` }).join(' '),
)
const radarLabels = computed(() =>
  radar.value.map((d, i) => { const p = polar(angleAt(i), MAXR + 18); return { x: p.x, y: p.y + 3, text: DIM_LABEL[d.dimension] || d.dimension } }),
)
const score = computed(() => {
  if (!radar.value.length) return '0.0'
  const avg = radar.value.reduce((a, d) => a + Math.min(1, d.normalized || 0), 0) / radar.value.length
  return (avg * 100).toFixed(1)
})

// —— 合作网络：中心 + 环形布局 ——
const GCX = 150, GCY = 105, GR = 82
const nodePos = computed(() => {
  const nodes = graph.value?.nodes ?? []
  const map: Record<number, { x: number; y: number }> = {}
  if (!nodes.length) return map
  map[nodes[0].staff_id] = { x: GCX, y: GCY }
  const others = nodes.slice(1)
  others.forEach((o, i) => {
    const ang = (-90 + (i * 360) / Math.max(1, others.length)) * Math.PI / 180
    map[o.staff_id] = { x: +(GCX + GR * Math.cos(ang)).toFixed(1), y: +(GCY + GR * Math.sin(ang)).toFixed(1) }
  })
  return map
})
const NODE_COLORS = ['#41598C', '#A8842F', '#7C869E', '#3E7C4B', '#C2402C', '#5B4FA0']
function nodeRadius(size: number) { return Math.min(20, Math.max(7, Math.round(size / 2.2))) }

// —— 关键数字（均由画像快照派生）——
const wan = (v: number | string | null) => toWan(v)
const keyNumbers = computed(() => {
  const p = portrait.value?.latest
  if (!p) return []
  return [
    { nm: '在研 / 主持', v: `${p.project_count_active} / ${p.project_count_total}`, w: p.project_count_total ? (p.project_count_active / p.project_count_total) * 100 : 0, color: undefined },
    { nm: '累计经费', v: `${wan(p.funding_total)}万`, w: Math.min(100, (p.funding_total / 20000000) * 100), color: undefined },
    { nm: 'SCI 论文', v: String(p.output_count_papers), w: Math.min(100, (p.output_count_papers / 60) * 100), color: undefined },
    { nm: 'H 指数', v: String(p.h_index), w: Math.min(100, (p.h_index / 30) * 100), color: 'var(--seal)' },
    { nm: '授权发明', v: String(p.output_count_patents), w: Math.min(100, (p.output_count_patents / 20) * 100), color: 'var(--gold)' },
    { nm: '培养博士', v: String(p.mentoring_count), w: Math.min(100, (p.mentoring_count / 10) * 100), color: 'var(--ok)' },
  ]
})

async function load() {
  loading.value = true
  try {
    const [p, g] = await Promise.all([
      api.get<PortraitDetail>(`/staff/${STAFF_ID}/portrait`),
      api.get<CollabGraph>(`/staff/${STAFF_ID}/collab-graph`).catch(() => null),
    ])
    portrait.value = p
    graph.value = g
  } catch (e: any) {
    toast('画像加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<template>
  <section class="view on" id="v-portrait">
    <div class="page-head">
      <div>
        <div class="page-title">PI <em>画像</em></div>
        <div class="page-sub">每周自动刷新 · 数据源：项目 / 经费 / 成果 / 合作 / 诚信 · 供评审、引才、梯队决策参考</div>
      </div>
      <button class="btn ghost" @click="toast('导出简历 PDF（演示）')">⇩ 导出简历</button>
    </div>

    <div v-if="loading" class="card"><div class="card-b" style="color:var(--ink-mute)">画像加载中…</div></div>

    <div v-else-if="!portrait" class="card"><div class="card-b" style="padding:36px;text-align:center;color:var(--ink-mute)">暂无画像数据</div></div>

    <template v-else>
      <div class="portrait-head" style="margin-bottom:18px">
        <div class="p-avatar">周</div>
        <div>
          <div style="font-family:var(--serif);font-size:24px;font-weight:900">周明远 <span style="font-size:13px;font-weight:400;opacity:.75">研究员 / 博导 · 先进制造所</span></div>
          <div style="font-size:12px;opacity:.85;margin-top:8px;line-height:1.9;max-width:640px">✦ <b>AI 画像摘要：</b>{{ portrait.latest.ai_summary }}</div>
          <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
            <span class="tag" style="background:rgba(255,255,255,.12);border-color:rgba(255,255,255,.3);color:#fff">{{ STAGE[portrait.latest.career_stage] || portrait.latest.career_stage }}</span>
            <span class="tag" style="background:rgba(255,255,255,.12);border-color:rgba(255,255,255,.3);color:#fff">ORCID 0000-…-4471</span>
            <span class="tag" v-for="(t, i) in portrait.latest.expertise_tags" :key="i" style="background:rgba(255,255,255,.12);border-color:rgba(255,255,255,.3);color:#fff">{{ t.tag }}</span>
            <span class="tag" :style="portrait.latest.integrity_flag ? 'background:rgba(176,58,46,.3);border-color:rgba(176,58,46,.5);color:#f3b7ad' : 'background:rgba(62,124,75,.3);border-color:rgba(62,124,75,.5);color:#9fd3ab'">诚信档案 · {{ portrait.latest.integrity_flag ? '风险提示' : '无失信' }}</span>
          </div>
        </div>
        <div style="margin-left:auto;text-align:center"><div style="font-family:var(--serif);font-size:44px;font-weight:900">{{ score }}</div><div style="font-size:11px;opacity:.7;letter-spacing:2px">综合画像分</div></div>
      </div>

      <div class="grid g3">
        <div class="card">
          <div class="card-h"><h4>能力雷达</h4></div>
          <div class="card-b radar-wrap">
            <svg width="240" height="210" viewBox="0 0 240 210">
              <g stroke="#D8CFBC" fill="none"><polygon :points="guideOuter"/><polygon :points="guideMid"/></g>
              <g stroke="#E4DAC6"><line v-for="(lb, i) in radarLabels" :key="'ax'+i" :x1="CX" :y1="CY" :x2="lb.x" :y2="lb.y - 3" /></g>
              <polygon :points="dataPolygon" fill="rgba(194,64,44,.16)" stroke="var(--seal)" stroke-width="1.5"/>
              <g font-size="9" fill="#7C869E" text-anchor="middle"><text v-for="(lb, i) in radarLabels" :key="'lb'+i" :x="lb.x" :y="lb.y">{{ lb.text }}</text></g>
            </svg>
          </div>
        </div>

        <div class="card">
          <div class="card-h"><h4>合作网络</h4><span class="tag ai">力导向</span></div>
          <div class="card-b">
            <svg width="100%" height="210" viewBox="0 0 300 210">
              <g stroke="#C9BFAC" stroke-width="1">
                <line v-for="(e, i) in (graph?.edges || [])" :key="'ed'+i"
                  :x1="nodePos[e.staff_a_id]?.x" :y1="nodePos[e.staff_a_id]?.y"
                  :x2="nodePos[e.staff_b_id]?.x" :y2="nodePos[e.staff_b_id]?.y" />
              </g>
              <g v-for="(node, i) in (graph?.nodes || [])" :key="'nd'+i">
                <circle :cx="nodePos[node.staff_id]?.x" :cy="nodePos[node.staff_id]?.y" :r="nodeRadius(node.node_size)"
                  :fill="i === 0 ? 'var(--seal)' : NODE_COLORS[(i - 1) % NODE_COLORS.length]" />
                <text :x="nodePos[node.staff_id]?.x" :y="(nodePos[node.staff_id]?.y ?? 0) + 3" text-anchor="middle" font-size="8" fill="#fff">{{ node.name }}</text>
              </g>
            </svg>
          </div>
        </div>

        <div class="card">
          <div class="card-h"><h4>关键数字</h4></div>
          <div class="card-b" style="display:flex;flex-direction:column;gap:2px">
            <div class="hbar" v-for="(k, i) in keyNumbers" :key="i">
              <span class="nm" style="width:130px">{{ k.nm }}</span>
              <div class="track"><i :style="{ width: k.w + '%', background: k.color || undefined }"></i></div>
              <span class="v">{{ k.v }}</span>
            </div>
            <div class="divider-double"></div>
            <div style="font-size:11.5px;color:var(--ink-mute)">总引用 <b class="mono" style="color:var(--ok)">{{ portrait.latest.total_citations }}</b> · 合作评分 <b class="mono">{{ (portrait.latest.collaboration_score * 100).toFixed(0) }}</b> · 快照 {{ portrait.latest.snapshot_date }}</div>
          </div>
        </div>
      </div>

      <div class="grid g2" style="margin-top:16px">
        <div class="card">
          <div class="card-h"><h4>学术轨迹</h4><span class="tag info">时间轴</span></div>
          <div class="card-b"><div class="timeline">
            <div class="tl-item" v-for="(t, i) in portrait.timeline" :key="i">
              <div class="t">{{ t.year }} · {{ t.type }}</div>{{ t.title }}
            </div>
          </div></div>
        </div>
        <div class="card">
          <div class="card-h"><h4>代表作 Top {{ portrait.top_outputs.length }}</h4><span class="tag ok">可引用</span></div>
          <div class="card-b" style="padding:0">
            <table class="tbl"><tbody>
              <tr v-for="(o, i) in portrait.top_outputs" :key="i"><td><span class="tag info">{{ o.type }}</span></td><td>{{ o.title }}</td><td class="mono" style="color:var(--ink-mute)">{{ o.venue }}</td></tr>
            </tbody></table>
          </div>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.p-avatar { border-width: 3px; }
</style>
