<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { toNum, toWan } from '@/utils/money'

interface EProject {
  id: number; code: string; status: string; title: string; projectType: string
  startDate: string; endDate: string; actualEndDate?: string | null
  totalBudget: string; receivedAmount: string; spentAmount: string
  healthScore: number; riskLevel: string; securityLevel: string
}

const toast = (m: string) => (window as any).toast?.(m)
const router = useRouter()

const projects = ref<EProject[]>([])
const total = ref(0)
const loading = ref(true)
const viewMode = ref<'card' | 'list' | 'gantt'>('card')

const num = (s?: string | number | null) => toNum(s)
const wan = (s?: string | number | null) => toWan(s)
const ym = (d?: string) => (d ? d.slice(0, 7).replace('-', '.') : '—')
const execPct = (p: EProject) => {
  const r = num(p.receivedAmount)
  return r > 0 ? Math.round((num(p.spentAmount) / r) * 100) : 0
}
const healthCls = (p: EProject) =>
  p.healthScore >= 80 ? 'h-ok' : p.healthScore >= 60 ? 'h-warn' : 'h-bad'
const barCls = (p: EProject) => (p.riskLevel === 'LOW' ? 'b-ok' : 'b-warn')

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
    const data = await api.get<{ list: EProject[]; total: number }>('/project/mine', { size: 50, role: 'ALL' })
    projects.value = data?.list ?? []
    total.value = data?.total ?? projects.value.length
  } catch (e: any) {
    toast('项目加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
onMounted(load)

function open(p: EProject) {
  if (p.status === 'CLOSED') { toast('打开归档项目（演示）'); return }
  router.push({ name: 'project', params: { id: p.id } })
}
function pick(v: 'card' | 'list' | 'gantt') {
  viewMode.value = 'card'
  if (v !== 'card') toast(v === 'list' ? '表格视图（演示）' : '甘特视图（演示）')
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

    <div v-if="loading" class="card"><div class="card-b" style="color:var(--ink-mute)">项目加载中…</div></div>

    <div v-else-if="!projects.length" class="card">
      <div class="card-b" style="padding:36px;text-align:center;color:var(--ink-mute)">暂无在研项目</div>
    </div>

    <div v-else class="grid g3">
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
            <div class="v" :class="healthCls(p)">{{ p.healthScore }}</div>
            <div class="l">HEALTH</div>
          </template>
        </div>
        <h5>{{ p.title }}</h5>
        <div class="no">{{ p.code }} · {{ p.projectType }} · {{ ym(p.startDate) }}–{{ ym(p.endDate) }}</div>

        <div class="rows">
          <div class="r"><span>经费执行</span><span class="mono">¥{{ wan(p.spentAmount) }}万/{{ wan(p.receivedAmount) }}万 · {{ execPct(p) }}%</span></div>
          <div class="bar" :class="barCls(p)"><i :style="{ width: execPct(p) + '%' }"></i></div>

          <template v-if="p.status === 'CLOSED'">
            <div class="r" style="margin-top:8px"><span>结题结论</span><span class="tag ok">优秀</span></div>
            <div class="r"><span>成果</span><span class="mono">累计归档</span></div>
          </template>
          <template v-else>
            <div class="r" style="margin-top:8px"><span>状态 / 风险</span><span class="mono">{{ p.status }} · {{ p.riskLevel }}</span></div>
          </template>
        </div>

        <div v-if="p.status !== 'CLOSED' && RISK_TEXT[p.riskLevel]?.txt" :class="RISK_TEXT[p.riskLevel].cls">
          {{ RISK_TEXT[p.riskLevel].txt }}
        </div>
        <div v-else-if="p.status !== 'CLOSED'" class="tag ok" style="margin-top:10px">✓ 一切正常 · 无需干预</div>
      </div>
    </div>
  </section>
</template>

<style scoped>
</style>
