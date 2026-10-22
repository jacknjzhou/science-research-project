<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { api, list } from '@/api/client'
import { toNum } from '@/utils/money'

// —— 模块 G 实体（snake_case，对齐 09-采购与合同管理-G.openapi.yaml）——
interface Requisition {
  id: number; code: string; status: string; category: string
  item_name: string; spec?: string | null
  est_amount: string; frozen_amount?: string; purchase_way?: string
  budget_subject_code?: string | null; project_id?: number | null
}
interface Supplier {
  id: number; code: string; name: string; type: string
  grade: string; status: string; blacklist: number; expire_date?: string | null
}
interface Contract {
  id: number; code: string; contract_type: string
  party_a?: string | null; party_b?: string | null
  amount: string; currency?: string; status: string
  sign_date?: string | null; end_date?: string | null; risk?: 'HIGH' | 'MED' | 'LOW' | null
}
interface Order {
  id: number; code: string; item_name: string; supplier_name: string
  amount: string; status: string; delivery_status: string
  converted_asset: number; saving?: string
}

const toast = (m: string) => (window as any).toast?.(m)

// —— 状态徽章映射（design/README §4 状态 token）——
const REQ_STATUS: Record<string, { l: string; c: string }> = {
  DRAFT: { l: '草稿', c: 'info' }, SUBMITTED: { l: '待审', c: 'warn' },
  WAY_DECIDED: { l: '方式已定', c: 'info' }, BIDDING: { l: '评标中', c: 'warn' },
  ORDERED: { l: '已下单', c: 'ok' }, CANCELLED: { l: '已取消', c: '' },
}
const CON_STATUS: Record<string, { l: string; c: string }> = {
  DRAFT: { l: '草稿', c: 'info' }, REVIEW: { l: '评审中', c: 'warn' },
  TO_SIGN: { l: '待签署', c: 'warn' }, ACTIVE: { l: '履约中', c: 'ok' },
  AMENDING: { l: '变更中', c: 'warn' }, SETTLING: { l: '结算中', c: 'info' },
  ARCHIVED: { l: '已归档', c: '' }, TERMINATED: { l: '已终止', c: 'bad' },
}
const SUP_STATUS: Record<string, { l: string; c: string }> = {
  PENDING: { l: '待审', c: 'warn' }, IN_LIBRARY: { l: '在库', c: 'ok' },
  REJECTED: { l: '已驳回', c: 'bad' }, EXPIRED: { l: '已过期', c: 'bad' },
}
const DELIVERY: Record<string, { l: string; c: string }> = {
  PENDING: { l: '待发货', c: 'info' }, SHIPPED: { l: '在途', c: 'warn' },
  ARRIVED: { l: '已到货', c: 'warn' }, ACCEPTED: { l: '已验收', c: 'ok' },
  REJECTED: { l: '已拒收', c: 'bad' },
}
const RISK: Record<string, { l: string; c: string }> = {
  HIGH: { l: '高风险', c: 'bad' }, MED: { l: '中风险', c: 'warn' }, LOW: { l: '低风险', c: 'info' },
}

const num = (v?: string | number | null) => toNum(v)
const fmtWan = (v?: string | number | null) =>
  (num(v) / 10000).toLocaleString('zh-CN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

// —— 状态 ——
const reqs = ref<Requisition[]>([])
const suppliers = ref<Supplier[]>([])
const contracts = ref<Contract[]>([])
const orders = ref<Order[]>([])
const loading = ref(true)
const reqFilter = ref('ALL')
const converting = ref<number | null>(null)

async function load() {
  loading.value = true
  try {
    const [re, su, co, or] = await Promise.all([
      list<Requisition>('/procurement/requisitions', { page: 1, size: 50 }),
      list<Supplier>('/supplier', { page: 1, size: 50 }),
      list<Contract>('/contract', { page: 1, size: 50 }),
      list<Order>('/procurement/orders', { page: 1, size: 50 }),
    ])
    reqs.value = re.rows
    suppliers.value = su.rows
    contracts.value = co.rows
    orders.value = or.rows
  } catch (e: any) {
    toast('数据加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
onMounted(() => { load(); loadAux() })

// —— 本地过滤：采购台账按状态 ——
const FILTERS = [
  { k: 'ALL', l: '全部' }, { k: 'SUBMITTED', l: '待审' }, { k: 'BIDDING', l: '评标中' },
  { k: 'WAY_DECIDED', l: '方式已定' }, { k: 'ORDERED', l: '已下单' },
]
const shownReqs = computed(() =>
  reqFilter.value === 'ALL' ? reqs.value : reqs.value.filter((r) => r.status === reqFilter.value))

// —— 概览卡片（由已加载列表派生）——
const PENDING_REQ = ['SUBMITTED', 'WAY_DECIDED', 'BIDDING']
const pendingReqs = computed(() => reqs.value.filter((r) => PENDING_REQ.includes(r.status)))
const frozenWan = computed(() => fmtWan(pendingReqs.value.reduce((a, r) => a + num(r.frozen_amount), 0)))
const ACTIVE_CON = ['ACTIVE', 'TO_SIGN', 'REVIEW', 'AMENDING', 'SETTLING']
const activeContracts = computed(() => contracts.value.filter((c) => ACTIVE_CON.includes(c.status)))
const contractMix = computed(() => {
  const m: Record<string, number> = {}
  activeContracts.value.forEach((c) => (m[c.contract_type] = (m[c.contract_type] || 0) + 1))
  return Object.entries(m).map(([k, v]) => `${k} ${v}`).join(' / ') || '暂无'
})
const highRisk = computed(() => contracts.value.filter((c) => c.risk === 'HIGH').length)
const savingWan = computed(() => fmtWan(orders.value.reduce((a, o) => a + num(o.saving), 0)))

// —— 采购方式判定引擎（G-03：按金额阈值本地推断，展示命中方式）——
function wayBand(est: number): { band: string; note: string } {
  if (est >= 2000000) return { band: '≥ 200万', note: '单价达公开招标限额（院采〔2024〕5号 §3）→ 强制公开招标，不可拆分规避' }
  if (est >= 500000) return { band: '50–200万', note: '服务/外协类 · 三家可比 → 竞争性谈判，已附供应商报价' }
  if (est >= 100000) return { band: '10–50万', note: '未达招标限额 → 询价采购，需 3 家询价单留痕' }
  return { band: '< 10万', note: '小额零星 → 自行采购/电子卖场，事后备案' }
}
const wayTop = computed(() =>
  [...reqs.value].sort((a, b) => num(b.est_amount) - num(a.est_amount)).slice(0, 2))

// —— 到货转资产（G-17 → 模块 A /asset/from-receipt，真实 G→A 契约）——
async function convert(o: Order) {
  if (o.delivery_status !== 'ACCEPTED' || o.converted_asset) return
  converting.value = o.id
  try {
    const r = await api.post<{ order_id?: number; converted_asset?: number }>('/asset/from-receipt', {
      order_id: o.id, target: 'ASSET',
    })
    o.converted_asset = r?.converted_asset ?? 1
    toast(`到货单 ${o.code} 已一键转入资产台账（G-17→A-03），自动生成资产卡与条码`)
  } catch (e: any) {
    toast('转资产失败：' + (e?.message || e))
  } finally {
    converting.value = null
  }
}

// —— 发起采购申请向导（G-01 创建即提交 + G-02 预算冻结 + G-03 方式判定）——
interface ProjectOption { id: number; title: string }
interface SubjectOption { code: string; name: string }
interface ReqResult { code?: string; status?: string; frozen_amount?: string; purchase_way?: string; clause_ref?: string | null }

const CATEGORIES = ['设备', '材料', '试剂耗材', '服务', '软件', '外协']
const myProjects = ref<ProjectOption[]>([])
const subjects = ref<SubjectOption[]>([])
const reqOpen = ref(false)
const reqSubmitting = ref(false)
const reqError = ref('')
const reqResult = ref<ReqResult | null>(null)
const fProject = ref<number | ''>('')
const fCategory = ref('')
const fName = ref('')
const fSpec = ref('')
const fAmount = ref<number | ''>('')
const fSubject = ref('')
const fRemark = ref('')

async function loadAux() {
  // 向导辅助数据：我的项目 + 经费科目（失败静默，不阻塞台账展示）
  try {
    const mine = await list<ProjectOption>('/project/mine', { page: 1, size: 50 })
    myProjects.value = mine.rows
  } catch { /* 静默 */ }
  try {
    const d = await api.get<{ list?: SubjectOption[] }>('/subjects')
    subjects.value = d?.list ?? []
  } catch { /* 静默 */ }
}

const reqReady = computed(() =>
  !!fProject.value && !!fCategory.value && !!fName.value.trim() &&
  Number(fAmount.value) > 0 && !!fSubject.value)

function openReq() {
  reqResult.value = null
  reqError.value = ''
  reqOpen.value = true
  if (!myProjects.value.length) loadAux()
}

const reqBand = computed(() =>
  Number(fAmount.value) > 0 ? wayBand(Number(fAmount.value)) : null)

async function submitRequisition() {
  if (!reqReady.value || reqSubmitting.value) return
  reqSubmitting.value = true
  reqError.value = ''
  try {
    const r = await api.post<ReqResult>('/procurement/requisitions', {
      project_id: fProject.value,
      category: fCategory.value,
      item_name: fName.value.trim(),
      spec: fSpec.value.trim() || null,
      est_amount: String(Number(fAmount.value)),
      budget_subject_code: fSubject.value,
      remark: fRemark.value.trim() || null,
    })
    reqResult.value = r
    toast(`采购申请已提交：${r?.code || ''} · 预算已冻结 · 方式判定「${r?.purchase_way || '—'}」`)
    await load()
  } catch (e: any) {
    reqError.value = e?.message || String(e)
  } finally {
    reqSubmitting.value = false
  }
}
</script>

<template>
  <section class="view on" id="v-procurement">
    <div class="page-head">
      <div>
        <div class="page-title">采购与合同<em>管理</em></div>
        <div class="page-sub">申请 → 预算冻结 → 采购方式判定 → 招标比价 → 订单验收 → 合同/签章 → 付款 → 转资产 · P2P 全链留痕</div>
      </div>
      <button class="btn seal" @click="openReq">＋ 发起采购申请</button>
    </div>

    <div style="display:flex;gap:14px;margin-bottom:18px;overflow-x:auto;padding-bottom:6px">
      <div class="card stat" style="min-width:170px">
        <div class="lbl">待审采购申请</div>
        <div class="num"><span v-if="loading" class="sk">{{ pendingReqs.length }}</span><template v-else>{{ pendingReqs.length }}</template></div>
        <div class="delta">已冻结预算 ¥{{ frozenWan }}万</div>
      </div>
      <div class="card stat gold" style="min-width:170px">
        <div class="lbl">进行中合同</div>
        <div class="num">{{ activeContracts.length }}</div>
        <div class="delta">{{ contractMix }}</div>
      </div>
      <div class="card stat red" style="min-width:170px">
        <div class="lbl">AI 风险条款命中</div>
        <div class="num">{{ highRisk }}</div>
        <div class="delta">需法务复核</div>
      </div>
      <div class="card stat ai" style="min-width:170px">
        <div class="lbl">本年采购节支</div>
        <div class="num">¥{{ savingWan }}<small>万</small></div>
        <div class="delta">比价优化 · {{ orders.length }} 单</div>
      </div>
    </div>

    <div class="grid g21" style="margin-bottom:16px">
      <!-- 采购台账（真实 GET /procurement/requisitions） -->
      <div class="card">
        <div class="card-h">
          <h4>采购台账</h4>
          <span class="tag info">制度包驱动 · 限额判定</span>
        </div>
        <div class="card-b" style="padding-top:14px">
          <div class="filter-row">
            <span v-for="f in FILTERS" :key="f.k" class="chip" :class="{ on: reqFilter === f.k }" @click="reqFilter = f.k">{{ f.l }}</span>
          </div>
        </div>
        <div class="card-b" style="padding:0">
          <table class="tbl">
            <thead><tr><th>申请</th><th>预算科目</th><th>金额</th><th>采购方式</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="r in shownReqs" :key="r.id">
                <td>{{ r.item_name }}<br><span class="mono" style="font-size:10px;color:var(--ink-mute)">{{ r.code }}</span></td>
                <td>{{ r.budget_subject_code || r.category }}</td>
                <td class="mono">¥{{ fmtWan(r.est_amount) }}万</td>
                <td><span class="tag seal">{{ r.purchase_way || '—' }}</span></td>
                <td><span class="tag" :class="REQ_STATUS[r.status]?.c">{{ REQ_STATUS[r.status]?.l || r.status }}</span></td>
              </tr>
              <tr v-if="!loading && !shownReqs.length"><td colspan="5" style="text-align:center;color:var(--ink-mute);padding:22px">暂无符合条件的采购申请</td></tr>
              <tr v-if="loading"><td colspan="5" style="text-align:center;color:var(--ink-mute);padding:22px">加载中…</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 采购方式判定引擎 + AI 风险 -->
      <div class="card">
        <div class="card-h"><h4>采购方式判定引擎</h4><span class="tag ai">G-03 制度包</span></div>
        <div class="card-b" style="display:flex;flex-direction:column;gap:10px">
          <div class="inv-card" v-for="r in wayTop" :key="r.id">
            <div class="conf-ring" style="--p:100%"><b>{{ wayBand(num(r.est_amount)).band }}</b></div>
            <div style="flex:1">
              <b style="font-size:13px">{{ r.item_name }}</b>
              <div style="font-size:11px;color:var(--ink-mute);margin-top:3px">{{ wayBand(num(r.est_amount)).note }} → <b>应走「{{ r.purchase_way }}」</b></div>
            </div>
          </div>
          <hr class="hr-rule" />
          <div class="ai-hint" v-if="highRisk">✦ <b>AI 合同风险审查：</b>{{ highRisk }} 份合同命中高风险条款（如「知识产权全部归外协方」与院所政策冲突），须法务人工签署意见方可放行。 <b style="cursor:pointer;color:var(--bad)" @click="toast('修订建议生成尚未开放（AI 审查仅输出风险清单）')">查看修订 →</b></div>
          <div class="ai-hint" v-else>✦ AI 合同风险审查：暂未发现高风险条款。</div>
          <div style="font-size:11.5px;color:var(--ink-mute)">到货合格后可一键转入资产台账（G-17 → A-03），自动生成资产卡与条码。</div>
        </div>
      </div>
    </div>

    <div class="grid g12" style="margin-bottom:16px">
      <!-- 供应商库（真实 GET /supplier） -->
      <div class="card">
        <div class="card-h"><h4>供应商 / 外协库</h4><span class="tag info">资质 · 黑名单硬拦截</span></div>
        <div class="card-b" style="display:flex;flex-direction:column;gap:10px">
          <div class="inv-card" v-for="s in suppliers" :key="s.id">
            <div class="conf-ring" :style="{ '--p': s.blacklist ? '0%' : '100%' }"><b>{{ s.grade }}</b></div>
            <div style="flex:1">
              <b style="font-size:13px">{{ s.name }}</b>
              <div style="font-size:11px;color:var(--ink-mute);margin-top:3px">
                <span class="mono">{{ s.code }}</span> · {{ s.type }} · 资质到期 {{ s.expire_date || '—' }}
              </div>
              <div style="margin-top:5px;display:flex;gap:6px">
                <span class="tag" :class="SUP_STATUS[s.status]?.c">{{ SUP_STATUS[s.status]?.l || s.status }}</span>
                <span class="tag bad" v-if="s.blacklist">黑名单</span>
              </div>
            </div>
          </div>
          <div v-if="!loading && !suppliers.length" style="color:var(--ink-mute);text-align:center;padding:16px">供应商库为空</div>
        </div>
      </div>

      <!-- 合同台账（G 契约无 GET 合同列表 → curated /contract） -->
      <div class="card">
        <div class="card-h"><h4>合同台账</h4><span class="tag ai">G-13/14 · AI 解析审查</span></div>
        <div class="card-b" style="padding:0">
          <table class="tbl">
            <thead><tr><th>合同</th><th>类型</th><th>相对方</th><th>金额</th><th>状态</th><th>AI 风险</th></tr></thead>
            <tbody>
              <tr v-for="c in contracts" :key="c.id">
                <td class="mono">{{ c.code }}</td>
                <td><span class="tag info">{{ c.contract_type }}</span></td>
                <td>{{ c.party_b || '—' }}</td>
                <td class="mono">¥{{ fmtWan(c.amount) }}万</td>
                <td><span class="tag" :class="CON_STATUS[c.status]?.c">{{ CON_STATUS[c.status]?.l || c.status }}</span></td>
                <td>
                  <span v-if="c.risk" class="tag" :class="RISK[c.risk ?? '']?.c">{{ RISK[c.risk ?? '']?.l }}</span>
                  <span v-else style="color:var(--ink-mute)">—</span>
                </td>
              </tr>
              <tr v-if="!loading && !contracts.length"><td colspan="6" style="text-align:center;color:var(--ink-mute);padding:22px">暂无合同记录</td></tr>
              <tr v-if="loading"><td colspan="6" style="text-align:center;color:var(--ink-mute);padding:22px">加载中…</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 采购订单 · 到货验收转资产（G-17 → 模块 A） -->
    <div class="card">
      <div class="card-h"><h4>采购订单 · 到货验收</h4><span class="tag seal">一键转资产 G-17 → A-03</span></div>
      <div class="card-b" style="padding:0">
        <table class="tbl">
          <thead><tr><th>订单</th><th>物品</th><th>供应商</th><th>金额</th><th>到货状态</th><th>转资产</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="o in orders" :key="o.id">
              <td class="mono">{{ o.code }}</td>
              <td>{{ o.item_name }}</td>
              <td>{{ o.supplier_name }}</td>
              <td class="mono">¥{{ fmtWan(o.amount) }}万</td>
              <td><span class="tag" :class="DELIVERY[o.delivery_status]?.c">{{ DELIVERY[o.delivery_status]?.l || o.delivery_status }}</span></td>
              <td>
                <span v-if="o.converted_asset" class="tag ok">已入账</span>
                <span v-else-if="o.delivery_status === 'ACCEPTED'" class="tag warn">待转</span>
                <span v-else style="color:var(--ink-mute)">—</span>
              </td>
              <td>
                <button
                  class="btn sm seal"
                  :disabled="o.delivery_status !== 'ACCEPTED' || !!o.converted_asset || converting === o.id"
                  :style="{ opacity: (o.delivery_status === 'ACCEPTED' && !o.converted_asset) ? 1 : .4 }"
                  @click="convert(o)"
                >{{ converting === o.id ? '转入中…' : '到货转资产' }}</button>
              </td>
            </tr>
            <tr v-if="!loading && !orders.length"><td colspan="7" style="text-align:center;color:var(--ink-mute);padding:22px">暂无采购订单</td></tr>
            <tr v-if="loading"><td colspan="7" style="text-align:center;color:var(--ink-mute);padding:22px">加载中…</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- 发起采购申请向导（G-01/G-02/G-03：创建即提交 + 预算冻结 + 方式判定） -->
  <teleport to="body">
    <div class="rq-mask" v-if="reqOpen" @click.self="reqOpen = false" @keydown.esc="reqOpen = false">
      <div class="rq-modal" role="dialog" aria-label="发起采购申请">
        <header class="rq-head">
          <h3>发起采购申请</h3>
          <button class="rq-x" @click="reqOpen = false" aria-label="关闭">×</button>
        </header>

        <!-- 已提交：回执 -->
        <div class="rq-body" v-if="reqResult">
          <div class="rq-receipt">
            <div class="rq-line">
              <span class="tag ok">方式已定</span>
              <b class="mono">单号 {{ reqResult.code || '—' }}</b>
            </div>
            <table class="tbl" style="margin-top:12px">
              <tbody>
                <tr><td>预算冻结</td><td class="mono">¥{{ fmtWan(reqResult.frozen_amount) }}万（G-02 联动 F-10）</td></tr>
                <tr><td>采购方式</td><td><span class="tag seal">{{ reqResult.purchase_way || '—' }}</span></td></tr>
                <tr><td>命中规则</td><td class="mono">{{ reqResult.clause_ref || '默认制度包' }}</td></tr>
              </tbody>
            </table>
            <p class="rq-tip">申请已进入审批流，后续招标比价 / 订单验收将同步此单；到货合格后可一键转入资产台账。</p>
            <footer class="rq-foot">
              <button class="btn ghost" @click="reqResult = null">再发一条</button>
              <button class="btn" @click="reqOpen = false">完成</button>
            </footer>
          </div>
        </div>

        <!-- 表单 -->
        <div class="rq-body" v-else>
          <div class="rq-form">
            <div class="rq-field"><label>关联项目 *</label>
              <select v-model="fProject">
                <option value="" disabled>选择项目</option>
                <option v-for="p in myProjects" :key="p.id" :value="p.id">{{ p.title }}</option>
              </select>
            </div>
            <div class="rq-field"><label>采购品类 *</label>
              <span class="rq-types">
                <button v-for="cg in CATEGORIES" :key="cg" type="button" class="rq-type" :class="{ on: fCategory === cg }" @click="fCategory = cg">{{ cg }}</button>
              </span>
            </div>
            <div class="rq-field"><label>品名 *</label><input type="text" v-model="fName" placeholder="如：高性能计算服务器" /></div>
            <div class="rq-field"><label>规格 / 型号</label><input type="text" v-model="fSpec" placeholder="选填" /></div>
            <div class="rq-field"><label>预估金额（元） *</label><input type="number" min="0" step="0.01" v-model="fAmount" placeholder="如 250000" /></div>
            <div class="rq-field"><label>占用预算科目 *</label>
              <select v-model="fSubject">
                <option value="" disabled>选择科目（G-02 冻结）</option>
                <option v-for="s in subjects" :key="s.code" :value="s.code">{{ s.code }} · {{ s.name }}</option>
              </select>
            </div>
            <div class="rq-field"><label>备注</label><textarea rows="2" v-model="fRemark" placeholder="采购背景与要求（选填）"></textarea></div>
            <div class="rq-band" v-if="reqBand">
              ✦ 方式预估：<b>{{ reqBand.band }}</b> — {{ reqBand.note }}
            </div>
          </div>
          <p class="rq-tip">提交后系统自动冻结预算科目额度（不足将拦截），并按制度包判定采购方式。</p>
          <p class="rq-err" v-if="reqError">✕ {{ reqError }}</p>
          <footer class="rq-foot">
            <button class="btn ghost" @click="reqOpen = false">取消</button>
            <button class="btn" :disabled="!reqReady || reqSubmitting" @click="submitRequisition">{{ reqSubmitting ? '提交中…' : '提交采购申请' }}</button>
          </footer>
        </div>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
.sk { opacity: 0.4; }
.inv-card { display: flex; gap: 14px; padding: 12px 14px; border: 1px solid var(--line); border-radius: 6px; background: #fff; align-items: center; }
.conf-ring { width: 54px; height: 54px; border-radius: 50%; flex-shrink: 0; display: grid; place-items: center; font-family: var(--mono); font-size: 11px; font-weight: 600; position: relative; background: var(--paper-deep); }
.conf-ring::before { content: ""; position: absolute; inset: 0; border-radius: 50%; background: conic-gradient(var(--ai) var(--p), var(--paper-deep) var(--p)); }
.conf-ring::after { content: ""; position: absolute; inset: 5px; border-radius: 50%; background: var(--paper-hi); }
.conf-ring b { position: relative; z-index: 1; }
.btn:disabled { cursor: not-allowed; }

/* —— 发起采购申请向导弹层 —— */
.rq-mask { position: fixed; inset: 0; background: rgba(28,25,23,.45); backdrop-filter: blur(2px); z-index: 90; display: flex; align-items: center; justify-content: center; padding: 24px; }
.rq-modal { width: min(620px, 94vw); max-height: 88vh; overflow: auto; background: var(--paper); border: 1px solid var(--line-hard); border-radius: 6px; box-shadow: 0 18px 50px rgba(28,25,23,.25); }
.rq-head { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px 12px; border-bottom: 1px solid var(--line); }
.rq-head h3 { margin: 0; font-family: var(--serif); font-size: 17px; }
.rq-x { border: none; background: none; font-size: 22px; line-height: 1; cursor: pointer; color: var(--ink-mute); }
.rq-body { padding: 18px 20px 20px; }
.rq-form { display: flex; flex-direction: column; gap: 12px; margin-bottom: 12px; }
.rq-field { display: flex; flex-direction: column; gap: 5px; }
.rq-field > label { font-size: 12px; color: var(--ink-mute); }
.rq-field input, .rq-field select, .rq-field textarea { border: 1px solid var(--line-hard); border-radius: 4px; padding: 8px 10px; font: inherit; font-size: 13px; background: var(--paper); color: var(--ink); }
.rq-field textarea { resize: vertical; }
.rq-types { display: flex; flex-wrap: wrap; gap: 6px; }
.rq-type { padding: 6px 12px; border: 1px solid var(--line); border-radius: 999px; background: transparent; cursor: pointer; font-size: 12.5px; font-family: inherit; }
.rq-type.on { border-color: var(--seal); background: rgba(194,64,44,.06); box-shadow: inset 0 0 0 1px var(--seal); font-weight: 700; }
.rq-band { font-size: 12px; color: var(--ink-mute); background: var(--paper-deep); border-radius: 4px; padding: 8px 10px; }
.rq-band b { color: var(--ink); }
.rq-tip { font-size: 12px; color: var(--ink-mute); margin: 10px 0 0; }
.rq-err { font-size: 12px; color: var(--bad); margin: 8px 0 0; }
.rq-receipt-line, .rq-line { display: flex; align-items: center; gap: 12px; }
.rq-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
</style>
