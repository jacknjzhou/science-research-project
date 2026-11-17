<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, list } from '@/api/client'
import { auth } from '@/api/auth'
import { toNum } from '@/utils/money'

// —— 拨款管理（M1-c A6/F-22）：契约 Disbursement camelCase、Money string（design/03 :2789）——
// create 直落 SUBMITTED；approve 仅 SUBMITTED→APPROVED、pay 仅 APPROVED→PAID（R-FINANCE 专属，40301 时按钮隐藏）；
// check-contract 创建前预检（canDisburse=false 对应 42201 超额硬拦）；同合同同阶段重复创建 40901。
interface Disbursement {
  id: number
  code: string
  contractId: number
  outsourceUnitId: number
  projectId: number
  securityLevel: string
  amount: string
  phase: string
  voucherStatus: string
  contractAmount: string
  remainContractAmount: string
  complianceFlags: string[]
  status: 'DRAFT' | 'SUBMITTED' | 'APPROVED' | 'PAID' | 'VOUCHER_SYNCED' | 'REJECTED' | 'RETURNED'
  policyPackId: number | null
}
interface CheckResult {
  contractId: number
  contractAmount: string
  disbursedBefore: string
  remainContractAmount: string
  canDisburse: boolean
  complianceFlags: string[]
  ruleHits: unknown[]
}
// G 合同（procure list_contracts，snake_case 契约债）与供应商拟真数据源
interface GContract {
  id: number; code: string; contract_type: string; amount: number | string
  status: string; party_b?: string | null; project_id?: number | null
  [k: string]: unknown
}
interface GSupplier { id: number; code: string; name: string; type: string; status: string; blacklist: number; [k: string]: unknown }
interface MyProject { id: number; name?: string; code?: string; title?: string; [k: string]: unknown }

const toast = (m: string) => (window as any).toast?.(m)
const num = (v?: string | number | null) => toNum(v)
const money = (v?: string | number | null) =>
  num(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const DISB_STATUS_META: Record<string, { tag: string; cls: string }> = {
  DRAFT: { tag: '草稿', cls: 'warn' }, SUBMITTED: { tag: '待审批', cls: 'info' },
  APPROVED: { tag: '已审批', cls: 'ok' }, PAID: { tag: '已付款', cls: 'seal' },
  VOUCHER_SYNCED: { tag: '凭证已同步', cls: 'ok' }, REJECTED: { tag: '已驳回', cls: 'bad' },
  RETURNED: { tag: '已退回', cls: 'bad' },
}
const stMeta = (s?: string | null) => DISB_STATUS_META[s || ''] || { tag: s || '—', cls: 'muted' }
const VOUCHER_META: Record<string, { tag: string; cls: string }> = {
  PENDING: { tag: '待推送', cls: 'info' }, SUCCESS: { tag: '已同步', cls: 'ok' },
  FAILED: { tag: '失败', cls: 'bad' }, MANUAL: { tag: '手工', cls: 'muted' },
}
const vMeta = (s?: string | null) => VOUCHER_META[s || ''] || { tag: s || '—', cls: 'muted' }

// 门控：action 为 R-FINANCE 专属（后端 40301 闸；R-ADMIN 不代行 → 角色直判）
const canCreate = computed(() => auth.can('/disbursements POST'))
const canCheck = computed(() => auth.can('/disbursements/check-contract POST'))
const canAction = computed(() => auth.roles.includes('R-FINANCE'))
const canIncomePage = computed(() => auth.can('/incomes/ocr-receipt POST'))

const loading = ref(false)
const submitting = ref(false)
const checking = ref(false)
const acting = ref<number | null>(null)

const projects = ref<MyProject[]>([])
const contracts = ref<GContract[]>([])
const suppliers = ref<GSupplier[]>([])

const statusFilter = ref('')
const rows = ref<Disbursement[]>([])

// 创建表单（契约 DisbursementCreateRequest required [contractId,outsourceUnitId,projectId,amount,phase]）
const fContractId = ref<number | null>(null)
const fOutsourceUnitId = ref<number | null>(null)
const fProjectId = ref<number | null>(null)
const fSecurityLevel = ref('INTERNAL')
const fAmount = ref('')
const fPhase = ref<'预付' | '进度' | '尾款'>('预付')
const fInvoiceUrl = ref('')
const checkRes = ref<CheckResult | null>(null)

const projName = (id?: number | null) => {
  const p = projects.value.find(x => x.id === id)
  return p ? (p.name || p.title || p.code || `项目 #${id}`) : `项目 #${id}`
}
const contractLabel = (id?: number | null) => {
  const c = contracts.value.find(x => x.id === id)
  return c ? `${c.code}（${money(c.amount)}）` : `合同 #${id}`
}
const supplierName = (id?: number | null) => {
  const s = suppliers.value.find(x => x.id === id)
  return s ? s.name : `外协 #${id}`
}
// 同一合同同阶段是否存在占用中的拨款单（镜像后端 40901 防重口径，客户端预检）
const dupPhase = computed(() =>
  rows.value.some((d) =>
    d.contractId === fContractId.value
    && d.phase === fPhase.value
    && !['REJECTED', 'RETURNED'].includes(d.status)))

async function reloadCtx() {
  const [ps, cs, ss] = await Promise.all([
    list<MyProject>('/project/mine', { page: 1, size: 50 }).catch(() => ({ rows: [] as MyProject[], total: 0 })),
    list<GContract>('/contract', { page: 1, size: 50 }).catch(() => ({ rows: [] as GContract[], total: 0 })),
    list<GSupplier>('/supplier', { page: 1, size: 50 }).catch(() => ({ rows: [] as GSupplier[], total: 0 })),
  ])
  projects.value = ps.rows
  contracts.value = cs.rows
  suppliers.value = ss.rows
}

async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: 1, size: 50 }
    if (statusFilter.value) params.status = statusFilter.value
    rows.value = (await list<Disbursement>('/disbursements', params)).rows
  } catch (e: any) {
    toast('拨款列表加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

// 创建前预检（POST /disbursements/check-contract {contractId, amount}）
async function precheck() {
  const cid = fContractId.value
  if (!cid || !fAmount.value.trim()) { toast('请先选择合同并填写金额'); return }
  checking.value = true
  try {
    checkRes.value = await api.post<CheckResult>('/disbursements/check-contract', {
      contractId: cid, amount: fAmount.value.trim(),
    })
    if (!checkRes.value.canDisburse) toast('预检不通过：金额超出合同剩余可拨额（创建将被 42201 硬拦）')
  } catch (e: any) {
    toast('预检失败：' + (e?.message || e))
  } finally {
    checking.value = false
  }
}

async function create() {
  if (submitting.value) return
  if (!fContractId.value || !fOutsourceUnitId.value || !fProjectId.value) { toast('请选择合同 / 外协单位 / 项目'); return }
  if (!fAmount.value.trim() || num(fAmount.value) <= 0) { toast('请填写正数金额'); return }
  if (!fPhase.value) { toast('请选择拨款阶段'); return }
  if (dupPhase.value) { toast('该合同同阶段已存在拨款单（40901 防重）；可先驳回/退回既有单'); return }
  submitting.value = true
  try {
    const d = await api.post<Disbursement>('/disbursements', {
      contractId: fContractId.value,
      outsourceUnitId: fOutsourceUnitId.value,
      projectId: fProjectId.value,
      ...(fSecurityLevel.value ? { securityLevel: fSecurityLevel.value } : {}),
      amount: fAmount.value.trim(),
      phase: fPhase.value,
      ...(fInvoiceUrl.value.trim() ? { invoiceUrl: fInvoiceUrl.value.trim() } : {}),
    })
    toast(`拨款单 ${d?.code || ''} 已创建（SUBMITTED）`)
    fAmount.value = ''
    fInvoiceUrl.value = ''
    checkRes.value = null
    await load()
  } catch (e: any) {
    // 40901 重复拨款 / 42201 超额 / 404 合同不存在 —— 后端文案直接透出
    toast('创建失败：' + (e?.message || e))
  } finally {
    submitting.value = false
  }
}

async function act(d: Disbursement, action: 'approve' | 'pay') {
  if (acting.value !== null) return
  if (action === 'approve' && d.status !== 'SUBMITTED') { toast('仅 SUBMITTED 单可审批'); return }
  if (action === 'pay' && d.status !== 'APPROVED') { toast('仅 APPROVED 单可付款'); return }
  acting.value = d.id
  try {
    await api.post<Disbursement>(`/disbursements/${d.id}/action`, { action })
    toast(action === 'approve' ? `拨款单 ${d.code} 已审批（APPROVED）` : `拨款单 ${d.code} 已付款（PAID，凭证待推送）`)
    await load()
  } catch (e: any) {
    toast('操作失败：' + (e?.message || e))
  } finally {
    acting.value = null
  }
}

onMounted(async () => { await reloadCtx(); await load() })
</script>

<template>
  <section class="view on" id="v-funding-disburse">
    <div class="page-head">
      <div>
        <div class="page-title">拨款管理<em>外拨经费</em></div>
        <div class="page-sub">外拨合同额度预检 · 创建直落 SUBMITTED · approve/pay 状态机（R-FINANCE 专属）· 超额 42201 / 同阶段重复 40901</div>
      </div>
    </div>

    <!-- 创建（canCreate：R-MANAGER / R-FINANCE） -->
    <div v-if="canCreate" class="card">
      <div class="card-h"><h4>发起拨款</h4><span style="font-size:12px;color:var(--ink-mute)">POST /disbursements · DisbursementCreateRequest</span></div>
      <div class="card-b" style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
        <div>
          <div class="fld" style="margin-top:0">合同（G_CONTRACT）</div>
          <select v-model.number="fContractId" class="fg" style="width:250px">
            <option :value="null" disabled>请选择合同</option>
            <option v-for="c in contracts" :key="c.id" :value="c.id">{{ c.code }} · {{ c.contract_type }}</option>
          </select>
        </div>
        <div>
          <div class="fld" style="margin-top:0">外协单位（G_SUPPLIER）</div>
          <select v-model.number="fOutsourceUnitId" class="fg" style="width:220px">
            <option :value="null" disabled>请选择外协单位</option>
            <option v-for="s in suppliers.filter(x => x.type === '外协单位' || x.type === '供应商')" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
        </div>
        <div>
          <div class="fld" style="margin-top:0">项目</div>
          <select v-model.number="fProjectId" class="fg" style="width:220px">
            <option :value="null" disabled>请选择项目</option>
            <option v-for="p in projects" :key="p.id" :value="p.id">{{ projName(p.id) }}</option>
          </select>
        </div>
        <div>
          <div class="fld" style="margin-top:0">拨款阶段 phase</div>
          <select v-model="fPhase" class="fg" style="width:110px">
            <option value="预付">预付</option>
            <option value="进度">进度</option>
            <option value="尾款">尾款</option>
          </select>
        </div>
        <div>
          <div class="fld" style="margin-top:0">密级</div>
          <select v-model="fSecurityLevel" class="fg" style="width:110px">
            <option value="PUBLIC">PUBLIC</option>
            <option value="INTERNAL">INTERNAL</option>
            <option value="SECRET">SECRET</option>
            <option value="TOP_SECRET">TOP_SECRET</option>
          </select>
        </div>
        <div>
          <div class="fld" style="margin-top:0">金额（元）</div>
          <input v-model="fAmount" class="fg money-input" inputmode="decimal" placeholder="如 50000.00" style="width:150px" />
        </div>
        <div>
          <div class="fld" style="margin-top:0">发票 URL（可选）</div>
          <input v-model="fInvoiceUrl" class="fg" placeholder="https://…" style="width:180px" />
        </div>
        <button v-if="canCheck" class="btn ghost" :disabled="checking || !fContractId || !fAmount.trim()" @click="precheck">
          {{ checking ? '预检中…' : '预检额度' }}
        </button>
        <button class="btn seal" :disabled="submitting" @click="create">{{ submitting ? '创建中…' : '创建拨款单' }}</button>
      </div>

      <!-- 预检结果 / 客户端防重提示 -->
      <div v-if="checkRes" class="card-b" style="padding-top:0">
        <div class="sum-row">
          <div class="sum-card"><div class="sum-lbl">合同金额</div><div class="sum-val">¥ {{ money(checkRes.contractAmount) }}</div></div>
          <div class="sum-card"><div class="sum-lbl">已拨累计</div><div class="sum-val">¥ {{ money(checkRes.disbursedBefore) }}</div></div>
          <div class="sum-card hi"><div class="sum-lbl">剩余可拨</div><div class="sum-val">¥ {{ money(checkRes.remainContractAmount) }}</div></div>
          <div class="sum-card">
            <div class="sum-lbl">预检结论 canDisburse</div>
            <div class="sum-val" :style="{ fontSize: '15px' }">
              <span class="tag" :class="checkRes.canDisburse ? 'ok' : 'bad'">{{ checkRes.canDisburse ? '✓ 可拨' : '✗ 超额（42201）' }}</span>
            </div>
          </div>
        </div>
      </div>
      <div v-else-if="dupPhase" class="card-b" style="padding-top:0">
        <span class="tag warn">⚠ 该合同同阶段已存在拨款单（后端 40901 防重），请先处理既有单或换阶段</span>
      </div>
    </div>

    <!-- 台账 -->
    <div class="card">
      <div class="card-h">
        <h4>拨款台账</h4>
        <div style="display:flex;gap:8px;align-items:center">
          <select v-model="statusFilter" class="fg" style="width:130px" @change="load">
            <option value="">全部状态</option>
            <option v-for="(m, k) in DISB_STATUS_META" :key="k" :value="k">{{ m.tag }}（{{ k }}）</option>
          </select>
          <button class="btn ghost sm" @click="load">刷新</button>
        </div>
      </div>
      <div class="card-b" style="overflow:auto;min-width:0">
        <table class="tbl" style="border-collapse:collapse;font-size:12.5px;table-layout:fixed;width:100%">
          <thead>
            <tr style="text-align:left">
              <th style="width:11%">单号</th>
              <th style="width:15%">合同</th>
              <th style="width:14%">外协单位</th>
              <th style="width:13%">项目</th>
              <th style="width:7%">阶段</th>
              <th style="width:10%" class="num">金额</th>
              <th style="width:10%" class="num">拨后剩余</th>
              <th style="width:8%">状态</th>
              <th style="width:12%">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in rows" :key="d.id">
              <td class="mono">{{ d.code }}</td>
              <td style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" :title="contractLabel(d.contractId)">{{ contractLabel(d.contractId) }}</td>
              <td style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ supplierName(d.outsourceUnitId) }}</td>
              <td style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ projName(d.projectId) }}</td>
              <td>{{ d.phase }}</td>
              <td class="mono num">¥{{ money(d.amount) }}</td>
              <td class="mono num">¥{{ money(d.remainContractAmount) }}</td>
              <td>
                <span class="tag" :class="stMeta(d.status).cls">{{ stMeta(d.status).tag }}</span>
                <div v-if="d.status === 'PAID' || d.voucherStatus !== 'PENDING'" style="margin-top:3px">
                  <span class="tag" :class="vMeta(d.voucherStatus).cls" style="font-size:10px">凭证 {{ vMeta(d.voucherStatus).tag }}</span>
                </div>
              </td>
              <td v-if="canAction">
                <button v-if="d.status === 'SUBMITTED'" class="btn seal sm" :disabled="acting !== null" @click="act(d, 'approve')">审批</button>
                <button v-else-if="d.status === 'APPROVED'" class="btn seal sm" :disabled="acting !== null" @click="act(d, 'pay')">付款</button>
                <span v-else style="color:var(--ink-mute);font-size:11px">—</span>
              </td>
              <td v-else style="color:var(--ink-mute);font-size:11px">R-FINANCE</td>
            </tr>
            <tr v-if="!rows.length && !loading"><td colspan="9" style="color:var(--ink-mute);padding:18px;text-align:center">暂无拨款单</td></tr>
          </tbody>
        </table>
        <span v-if="loading" style="font-size:12px;color:var(--ink-mute)">加载中…</span>
      </div>
    </div>

    <p style="font-size:11.5px;color:var(--ink-mute);line-height:1.8;margin-top:10px">
      状态机：create→SUBMITTED → approve→APPROVED → pay→PAID（落 DISBURSEMENT 平行记账，凭证 PENDING）。
      审批/付款仅 R-FINANCE（后端 40301 闸，R-ADMIN 不代行）；快照语义：remain = 合同额 − 已拨 − 本单金额。
      <template v-if="canIncomePage">到账认领与回单识别见「到账认领」页。</template>
    </p>
  </section>
</template>

<style scoped>
.fld { font-size: 12px; color: var(--ink-mute); margin-top: 12px; letter-spacing: 1px; }
.mono { font-family: var(--mono); }
.num { text-align: right; }
.sum-row { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 12px; }
.sum-card { flex: 1; min-width: 170px; border: 1px solid var(--line, #e5e9f2); border-radius: 10px; padding: 12px 14px; background: #fafbfd; }
.sum-card.hi { background: #f4f8ff; }
.sum-lbl { font-size: 11px; color: var(--ink-mute); letter-spacing: 1px; }
.sum-val { font-size: 20px; font-weight: 800; margin-top: 6px; font-family: var(--mono); font-variant-numeric: tabular-nums; }
.tag.muted { background: #eef1f6; color: #6b7280; }
.tag.seal { background: var(--seal, #8b2e2e); color: #fff; }
.btn:disabled { opacity: .6; cursor: not-allowed; }
.tbl tbody tr:hover { background: rgba(0,0,0,.03); }
</style>
