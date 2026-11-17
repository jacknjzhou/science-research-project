<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { api, list } from '@/api/client'
import { auth } from '@/api/auth'
import { toNum } from '@/utils/money'

// —— 成本池 / 全成本核算（M1-b A4 / F-20）：契约 CostPool camelCase、Money string（design/03 :2689）——
// 生命周期：DRAFT→(calculate)CALCULATED→LOCKED（锁定后复算 40901）/REVERSED
interface IndirectAllocRow { type: string; basis: string; amount: string }
interface CostPool {
  id: number
  code: string
  projectId: number
  period: string
  directCost: string
  indirectAlloc: IndirectAllocRow[]
  fullCost: string
  status: 'DRAFT' | 'CALCULATED' | 'LOCKED' | 'REVERSED'
  basisRuleId: number | null
  policyPackId: number | null
}
interface MyProject { id: number; name?: string; code?: string; title?: string; [k: string]: unknown }

const toast = (m: string) => (window as any).toast?.(m)
const num = (v?: string | number | null) => toNum(v)
const money = (v?: string | number | null) => num(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const POOL_STATUS_META: Record<string, { tag: string; cls: string }> = {
  DRAFT: { tag: '草稿', cls: 'warn' }, CALCULATED: { tag: '已核算', cls: 'ok' },
  LOCKED: { tag: '已锁定', cls: 'info' }, REVERSED: { tag: '已冲销', cls: 'muted' },
}
const stMeta = (s?: string | null) => POOL_STATUS_META[s || ''] || { tag: s || '—', cls: 'muted' }

const canCalculate = computed(() => auth.can('/cost-pools/calculate POST'))

const loading = ref(true)
const calculating = ref(false)
const rows = ref<CostPool[]>([])
const projects = ref<MyProject[]>([])

// 查询条件：期间（YYYYMM）+ 项目选择器
const period = ref('') // 空 = 全部期间
const projectId = ref<number | null>(null)

const projName = (id?: number | null) => {
  const p = projects.value.find(x => x.id === id)
  return p ? (p.name || p.title || p.code || `项目 #${id}`) : `项目 #${id}`
}

const PERIOD_RE = /^\d{6}$/

async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { size: 50 }
    if (period.value.trim()) params.period = period.value.trim()
    if (projectId.value) params.projectId = projectId.value
    const d = await list<CostPool>('/cost-pools', params).catch(() => ({ rows: [] as CostPool[], total: 0 }))
    rows.value = d.rows ?? []
  } finally {
    loading.value = false
  }
}

async function reloadCtx() {
  const ps = await list<MyProject>('/project/mine').catch(() => ({ rows: [] as MyProject[], total: 0 }))
  projects.value = (ps.rows ?? []) as MyProject[]
}

// 期间默认值：当前月份（YYYYMM）
function currentPeriod(): string {
  const d = new Date()
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}`
}

async function calculate() {
  if (calculating.value) return
  const pid = projectId.value
  if (!pid) { toast('请先选择要核算的项目'); return }
  const p = period.value.trim()
  if (!PERIOD_RE.test(p)) { toast('期间格式须为 YYYYMM（如 202611）'); return }
  calculating.value = true
  try {
    const created = await api.post<CostPool>('/cost-pools/calculate', { projectId: pid, period: p })
    toast(`全成本核算完成：直接 ¥${money(created?.directCost)} + 间接 ¥${money(created?.fullCost && created?.directCost ? num(created.fullCost) - num(created.directCost) : 0)} = 全成本 ¥${money(created?.fullCost)}（${stMeta(created?.status).tag}）`)
    await load()
  } catch (e: any) {
    // LOCKED 复算 → 409/40901 冲突文案直接透出
    toast('核算失败：' + (e?.message || e))
  } finally {
    calculating.value = false
  }
}

onMounted(() => { period.value = currentPeriod(); void reloadCtx(); void load() })
</script>

<template>
  <section class="view on" id="v-cost-pool">
    <div class="page-head">
      <div>
        <div class="page-title">成本池<em>全成本核算</em></div>
        <div class="page-sub">直接费用汇总 + 间接费分摊 → 全成本 · 幂等复算 · LOCKED 后禁止复算（40901）</div>
      </div>
    </div>

    <!-- 查询条：期间 + 项目 -->
    <div class="card">
      <div class="card-b" style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
        <div>
          <div class="fld" style="margin-top:0">期间（YYYYMM）</div>
          <input v-model="period" class="fg" inputmode="numeric" placeholder="如 202611" style="width:140px" />
        </div>
        <div>
          <div class="fld" style="margin-top:0">项目</div>
          <select v-model.number="projectId" class="fg" style="width:260px">
            <option :value="null">全部项目</option>
            <option v-for="p in projects" :key="p.id" :value="p.id">{{ projName(p.id) }}</option>
          </select>
        </div>
        <button class="btn ghost" @click="load">查询</button>
        <button v-if="canCalculate" class="btn seal" :disabled="calculating" @click="calculate">
          {{ calculating ? '核算中…' : '⚙ 全成本核算' }}
        </button>
        <span v-if="!canCalculate" style="font-size:11.5px;color:var(--ink-mute)">核算需财务权限（R-FINANCE / R-MANAGER）</span>
      </div>
    </div>

    <!-- 成本池列表 -->
    <div class="card">
      <div class="card-h">
        <h4>成本池（{{ rows.length }}）</h4>
        <span v-if="loading" style="font-size:12px;color:var(--ink-mute)">加载中…</span>
      </div>
      <div class="card-b" style="overflow:auto">
        <table class="tbl">
          <thead>
            <tr>
              <th>编号</th><th>项目</th><th>期间</th>
              <th class="num" style="text-align:right">直接费用</th>
              <th class="num" style="text-align:right">间接分摊 Σ</th>
              <th class="num" style="text-align:right">全成本</th>
              <th>状态</th><th>分摊明细</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in rows" :key="p.id">
              <td class="mono">{{ p.code || ('#' + p.id) }}</td>
              <td>{{ projName(p.projectId) }}</td>
              <td class="mono">{{ p.period || '—' }}</td>
              <td class="mono num" style="text-align:right;font-weight:700">¥ {{ money(p.directCost) }}</td>
              <td class="mono num" style="text-align:right">¥ {{ money((p.indirectAlloc || []).reduce((a, r) => a + num(r.amount), 0)) }}</td>
              <td class="mono num" style="text-align:right;font-weight:700;color:var(--seal)">¥ {{ money(p.fullCost) }}</td>
              <td><span class="tag" :class="stMeta(p.status).cls">{{ stMeta(p.status).tag }}</span></td>
              <td>
                <div v-for="(r, i) in (p.indirectAlloc || [])" :key="i" style="font-size:11px;color:var(--ink-mute)">
                  {{ r.type }}（{{ r.basis }}）¥ {{ money(r.amount) }}
                </div>
                <span v-if="!(p.indirectAlloc || []).length" style="font-size:11px;color:var(--ink-mute)">—</span>
              </td>
            </tr>
            <tr v-if="!loading && !rows.length">
              <td colspan="8" style="text-align:center;color:var(--ink-mute)">
                暂无成本池；选择项目与期间后点击「全成本核算」（幂等：同期间复算覆盖旧值）。
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <p style="font-size:11.5px;color:var(--ink-mute);line-height:1.8;margin-top:10px">
      直接费用 = 已支付报销（PAID / VOUCHER_SYNCED）+ 已批复外拨（APPROVED）；间接分摊取间接费用计提（管理费等），
      分摊依据 basis 可复算。核算单被锁定（LOCKED）后复算将被 40901 拒绝。
    </p>
  </section>
</template>

<style scoped>
.fld { font-size: 12px; color: var(--ink-mute); margin-top: 12px; letter-spacing: 1px; }
.mono { font-family: var(--mono); }
.num { font-variant-numeric: tabular-nums; }
.tag.muted { background: #eef1f6; color: #6b7280; }
.btn:disabled { opacity: .6; cursor: not-allowed; }
</style>
