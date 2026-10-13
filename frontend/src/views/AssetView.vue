<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { api, list } from '@/api/client'
import { toNum } from '@/utils/money'

// —— 模块 A 实体（Asset 为 camelCase，对齐 10-资产与耗材管理-A.openapi.yaml）——
interface Asset {
  id: number; code: string; name: string; brand?: string; model?: string; serialNo?: string
  assetType: string; categoryCode?: string
  value: number; netValue: number; deprAccum?: number; deprMethod?: string; deprYears?: number
  status: string; location?: string; custodianId?: number | null; deptId?: number | null
  shareFlag?: boolean; openFlag?: boolean; usageRate?: number; inDate?: string
}
interface Consumable {
  sku: string; name: string; category: string; qty: number; unit: string
  safe_stock: number; status: string; expire_date?: string; is_hazard?: boolean
  consumed_30d?: number; location?: string
}

const toast = (m: string) => (window as any).toast?.(m)

// —— 状态映射 ——
const ASSET_STATUS: Record<string, { l: string; c: string }> = {
  PENDING_RECEIPT: { l: '到货验收中', c: 'warn' }, IN_USE: { l: '在用', c: 'ok' },
  IDLE: { l: '闲置', c: 'info' }, UNDER_MAINT: { l: '维修中', c: 'warn' },
  TRANSFERRING: { l: '调拨中', c: 'warn' }, PENDING_DISPOSE: { l: '待处置', c: '' },
  DISPOSED: { l: '已处置', c: 'bad' },
}
const CONS_STATUS: Record<string, { l: string; c: string; bar: string }> = {
  IN_STOCK: { l: '有货', c: 'ok', bar: 'b-ok' },
  LOW_STOCK: { l: '低于安全线', c: 'warn', bar: 'b-warn' },
  NEAR_EXPIRY: { l: '临期', c: 'warn', bar: 'b-warn' },
  EXPIRED: { l: '已过期', c: 'bad', bar: 'b-bad' },
  STAGNANT: { l: '呆滞', c: 'info', bar: 'b-ok' },
}
const DEPT: Record<number, string> = { 10: '制造所', 20: '材料所', 30: '信息室', 40: '生物室' }
const CUST: Record<number, string> = { 4501: '李工', 4510: '王工', 4490: '周明远', 4522: '张工' }
const custName = (id?: number | null) => (id ? CUST[id] || `#${id}` : '待认领')
const deptName = (id?: number | null) => (id ? DEPT[id] || `#${id}` : '—')

const num = (v?: number | string | null) => toNum(v)
const fmtWan = (v?: number | string | null) =>
  (num(v) / 10000).toLocaleString('zh-CN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

// —— 状态 ——
const assets = ref<Asset[]>([])
const consumables = ref<Consumable[]>([])
const loading = ref(true)
const statusFilter = ref('ALL')
const keyword = ref('')
const issuing = ref<number | null>(null)

async function load() {
  loading.value = true
  try {
    const [la, lc] = await Promise.all([
      list<Asset>('/asset/ledger', { page: 1, size: 50 }),
      list<Consumable>('/consumable', { page: 1, size: 50 }),
    ])
    assets.value = la.rows
    consumables.value = lc.rows
  } catch (e: any) {
    toast('数据加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
onMounted(load)

// —— 本地过滤（状态 chips + 关键字）——
const FILTERS = [
  { k: 'ALL', l: '全部' }, { k: 'IN_USE', l: '在用' }, { k: 'PENDING_RECEIPT', l: '待验收' },
  { k: 'IDLE', l: '闲置' }, { k: 'PENDING_DISPOSE', l: '待处置' },
]
const shownAssets = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return assets.value.filter((a) => {
    if (statusFilter.value !== 'ALL' && a.status !== statusFilter.value) return false
    if (kw) {
      const hay = `${a.name}${a.code}${a.brand || ''}${a.model || ''}${a.serialNo || ''}`.toLowerCase()
      if (!hay.includes(kw)) return false
    }
    return true
  })
})

// —— 概览卡片（由资产台账 / 耗材库存派生）——
const totalValue = computed(() => fmtWan(assets.value.reduce((s, a) => s + num(a.value), 0)))
const totalNet = computed(() => fmtWan(assets.value.reduce((s, a) => s + num(a.netValue), 0)))
const totalDepr = computed(() => fmtWan(assets.value.reduce((s, a) => s + num(a.deprAccum), 0)))
const inUse = computed(() => assets.value.filter((a) => a.status === 'IN_USE').length)
const shared = computed(() => assets.value.filter((a) => a.shareFlag || a.openFlag).length)
const WARN_STATUS = ['LOW_STOCK', 'NEAR_EXPIRY', 'EXPIRED']
const warnStock = computed(() => consumables.value.filter((c) => WARN_STATUS.includes(c.status)))
const hazardWarn = computed(() => warnStock.value.filter((c) => c.is_hazard).length)

// —— 折旧进度（累计折旧 / 原值）——
function deprRatio(a: Asset): number {
  const v = num(a.value)
  return v ? Math.min(100, Math.round((num(a.deprAccum) / v) * 100)) : 0
}
function deprBar(a: Asset): string {
  const r = deprRatio(a)
  return r < 40 ? 'b-ok' : r < 80 ? 'b-warn' : 'b-bad'
}

// —— 耗材库存水位（qty / safe_stock）——
function stockPct(c: Consumable): number {
  const s = num(c.safe_stock)
  return s ? Math.max(4, Math.min(100, Math.round((num(c.qty) / s) * 100))) : 100
}

// —— 项目/部门成本分摊（按 deptId 归集净值 Top3）——
const alloc = computed(() => {
  const m: Record<number, number> = {}
  assets.value.forEach((a) => { if (a.deptId) m[a.deptId] = (m[a.deptId] || 0) + num(a.netValue) })
  const arr = Object.entries(m).map(([id, v]) => ({ dept: DEPT[Number(id)] || `#${id}`, v }))
    .sort((x, y) => y.v - x.v).slice(0, 3)
  const max = Math.max(...arr.map((x) => x.v), 1)
  return arr.map((x) => ({ ...x, pct: Math.round((x.v / max) * 100) }))
})
const ALLOC_COLOR = ['var(--ai)', 'var(--gold)', 'var(--seal)']

// —— 资产领用（真实 A 契约 POST /asset/{id}/issue）——
async function issue(a: Asset) {
  issuing.value = a.id
  try {
    await api.post<{ code?: string }>(`/asset/${a.id}/issue`, { projectId: 87, usageRate: 1 })
    a.status = 'IN_USE'
    toast(`资产「${a.name}」领用已受理（A-05），生成出入库流水并留痕`)
  } catch (e: any) {
    toast('领用失败：' + (e?.message || e))
  } finally {
    issuing.value = null
  }
}
const canIssue = (a: Asset) => ['IDLE', 'IN_USE', 'PENDING_RECEIPT'].includes(a.status)
</script>

<template>
  <section class="view on" id="v-asset">
    <div class="page-head">
      <div>
        <div class="page-title">资产与耗材<em>台账</em></div>
        <div class="page-sub">建卡 → 领用/调拨 → 折旧计提 → 盘点 → 处置 · 项目全成本分摊 · 危化品双人双锁</div>
      </div>
      <button class="btn ghost" @click="toast('盘点表导入向导已打开（演示）')">⇪ 盘点导入</button>
    </div>

    <div style="display:flex;gap:14px;margin-bottom:18px;overflow-x:auto;padding-bottom:6px">
      <div class="card stat" style="min-width:170px">
        <div class="lbl">固定资产原值</div>
        <div class="num"><span v-if="loading" class="sk">{{ totalValue }}</span><template v-else>¥{{ totalValue }}<small>万</small></template></div>
        <div class="delta">净值 ¥{{ totalNet }} 万</div>
      </div>
      <div class="card stat gold" style="min-width:170px">
        <div class="lbl">累计折旧计提</div>
        <div class="num">¥{{ totalDepr }}<small>万</small></div>
        <div class="delta">已归集 F-20 成本池</div>
      </div>
      <div class="card stat red" style="min-width:170px">
        <div class="lbl">库存预警</div>
        <div class="num">{{ warnStock.length }}</div>
        <div class="delta">危化品 {{ hazardWarn }} 项</div>
      </div>
      <div class="card stat ai" style="min-width:170px">
        <div class="lbl">在用 / 共享资产</div>
        <div class="num">{{ inUse }}<small>/ {{ assets.length }}</small></div>
        <div class="delta">对外共享 {{ shared }} 台</div>
      </div>
    </div>

    <div class="grid g21">
      <!-- 资产台账（真实 GET /asset/ledger · 卡片+表格双视图数据源） -->
      <div class="card">
        <div class="card-h"><h4>资产台账</h4><span class="tag info">RFID · 账实一致</span></div>
        <div class="card-b" style="padding-top:14px">
          <div class="filter-row" style="margin-bottom:0;align-items:center">
            <span v-for="f in FILTERS" :key="f.k" class="chip" :class="{ on: statusFilter === f.k }" @click="statusFilter = f.k">{{ f.l }}</span>
            <div class="fld" style="margin:0;margin-left:auto;min-width:180px">
              <input v-model="keyword" placeholder="搜索名称 / 编号 / 序列号" />
            </div>
          </div>
        </div>
        <div class="card-b" style="padding:0">
          <table class="tbl">
            <thead><tr><th>资产</th><th>存放 / 责任人</th><th>原值</th><th>净值</th><th>折旧进度</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="a in shownAssets" :key="a.id">
                <td>
                  {{ a.name }}
                  <span v-if="a.shareFlag || a.openFlag" class="tag ai" style="margin-left:6px;font-size:10px">共享</span>
                  <br><span class="mono" style="font-size:10px;color:var(--ink-mute)">{{ a.code }} · {{ a.brand }} {{ a.model }}</span>
                </td>
                <td>{{ a.location || deptName(a.deptId) }}<br><span style="font-size:11px;color:var(--ink-mute)">{{ custName(a.custodianId) }}</span></td>
                <td class="mono">¥{{ fmtWan(a.value) }}万</td>
                <td class="mono">{{ a.status === 'PENDING_RECEIPT' && !num(a.deprAccum) ? '—' : '¥' + fmtWan(a.netValue) + '万' }}</td>
                <td style="width:96px">
                  <div class="bar" :class="deprBar(a)"><i :style="{ width: deprRatio(a) + '%' }"></i></div>
                  <span class="mono" style="font-size:10px;color:var(--ink-mute)">{{ deprRatio(a) }}%</span>
                </td>
                <td><span class="tag" :class="ASSET_STATUS[a.status]?.c">{{ ASSET_STATUS[a.status]?.l || a.status }}</span></td>
                <td>
                  <button class="btn sm" :disabled="!canIssue(a) || issuing === a.id"
                    :style="{ opacity: canIssue(a) ? 1 : .4 }" @click="issue(a)">
                    {{ issuing === a.id ? '受理中…' : '领用' }}
                  </button>
                </td>
              </tr>
              <tr v-if="!loading && !shownAssets.length"><td colspan="7" style="text-align:center;color:var(--ink-mute);padding:22px">无匹配资产</td></tr>
              <tr v-if="loading"><td colspan="7" style="text-align:center;color:var(--ink-mute);padding:22px">加载中…</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 右列：耗材库存预警 + 成本分摊 -->
      <div style="display:flex;flex-direction:column;gap:16px">
        <div class="card">
          <div class="card-h"><h4>耗材 / 试剂库存</h4><span class="tag ai">A-07 · 智能补货</span></div>
          <div class="card-b" style="display:flex;flex-direction:column;gap:12px">
            <div v-for="c in consumables" :key="c.sku">
              <div style="display:flex;justify-content:space-between;align-items:center;font-size:12.5px;margin-bottom:5px">
                <span>
                  <b>{{ c.name }}</b>
                  <span v-if="c.is_hazard" class="tag bad" style="margin-left:6px;font-size:10px">危化 · 双锁</span>
                </span>
                <span class="tag" :class="CONS_STATUS[c.status]?.c">{{ CONS_STATUS[c.status]?.l || c.status }}</span>
              </div>
              <div class="bar" :class="CONS_STATUS[c.status]?.bar"><i :style="{ width: stockPct(c) + '%' }"></i></div>
              <div class="mono" style="font-size:10px;color:var(--ink-mute);margin-top:4px;display:flex;justify-content:space-between">
                <span>库存 {{ c.qty }}{{ c.unit }} / 安全线 {{ c.safe_stock }}{{ c.unit }}</span>
                <span>近30日耗 {{ c.consumed_30d ?? 0 }} · 效期 {{ c.expire_date || '—' }}</span>
              </div>
            </div>
            <div v-if="!loading && !consumables.length" style="color:var(--ink-mute);text-align:center;padding:12px">暂无耗材库存数据</div>
          </div>
        </div>

        <div class="card">
          <div class="card-h"><h4>项目成本分摊</h4><span class="tag seal">A-12 ↔ F-20</span></div>
          <div class="card-b">
            <div class="hbar" v-for="(x, i) in alloc" :key="x.dept">
              <span class="nm">{{ x.dept }}</span>
              <div class="track"><i :style="{ width: x.pct + '%', background: ALLOC_COLOR[i] }"></i></div>
              <span class="v">¥{{ fmtWan(x.v) }}万</span>
            </div>
            <div style="margin-top:10px;font-size:11.5px;color:var(--ink-mute)">按使用机时 / 领用单自动归集部门全成本池，供决算与绩效评价（D-03）取数。</div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.sk { opacity: 0.4; }
.fld { display: flex; }
.fld input { padding: 6px 12px; font-size: 12px; }
.btn:disabled { cursor: not-allowed; }
.bar { margin-top: 2px; }
</style>
