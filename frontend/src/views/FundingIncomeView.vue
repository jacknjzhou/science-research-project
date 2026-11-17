<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, list } from '@/api/client'
import { auth } from '@/api/auth'
import { toNum } from '@/utils/money'

// —— 到账认领与回单识别（M1-c A8/F-05/F-06/F-15）——
// 契约 Income 为 camelCase，但后端 to_api_income 现输出 snake_case（契约债）：
// 本视图统一「snake_case 主 + camelCase ?? 兜底」双读；请求体按后端实际读键（claim 后端读 project_id）。
interface Income {
  id: number
  code: string
  project_id?: number | null; projectId?: number | null
  receipt_no?: string; receiptNo?: string
  receipt_date?: string | null; receiptDate?: string | null
  amount: string
  payer_name?: string; payerName?: string
  payer_bank?: string; payerBank?: string
  purpose_text?: string; purposeText?: string
  bank_flow_no?: string | null; bankFlowNo?: string | null
  claim_status?: 'UNCLAIMED' | 'AUTO_MATCHED' | 'CLAIMED' | 'DOUBTFUL'; claimStatus?: string
  match_confidence?: number | null; matchConfidence?: number | null
  claimed_by?: string | number | null; claimedBy?: number | null; claimed_at?: string | null; claimedAt?: string | null
  mgmt_fee?: string
  created_at?: string
  ocrWarnings?: string[]
}
interface BankFlowImportResult { total: number; autoMatched: number; doubtful: number; unclaimed: number; elapsedMs: number }
interface MyProject { id: number; name?: string; code?: string; title?: string; [k: string]: unknown }

const toast = (m: string) => (window as any).toast?.(m)
const num = (v?: string | number | null) => toNum(v)
const money = (v?: string | number | null) =>
  num(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const CLAIM_META: Record<string, { tag: string; cls: string }> = {
  UNCLAIMED: { tag: '未认领', cls: 'warn' }, AUTO_MATCHED: { tag: '自动匹配', cls: 'info' },
  CLAIMED: { tag: '已认领', cls: 'ok' }, DOUBTFUL: { tag: '存疑', cls: 'bad' },
}
const stMeta = (s?: string | null) => CLAIM_META[s || ''] || { tag: s || '—', cls: 'muted' }

// 键双读 helper（snake_case 主 + camelCase 兜底）
const kOf = <T,>(i: Income, snake: keyof Income, camel: keyof Income): T =>
  ((i[snake] ?? i[camel]) as unknown as T)
const projIdOf = (i: Income) => kOf<number | null>(i, 'project_id', 'projectId')
const claimOf = (i: Income) => kOf<string>(i, 'claim_status', 'claimStatus')
const payerOf = (i: Income) => kOf<string>(i, 'payer_name', 'payerName') || '—'
const flowOf = (i: Income) => kOf<string | null>(i, 'bank_flow_no', 'bankFlowNo')
const dateOf = (i: Income) => kOf<string | null>(i, 'receipt_date', 'receiptDate') || '—'
const confOf = (i: Income) => kOf<number | null>(i, 'match_confidence', 'matchConfidence')

const canOcr = computed(() => auth.can('/incomes/ocr-receipt POST'))
const canImport = computed(() => auth.can('/incomes/import-bank-flow POST') || auth.can('/incomes/* POST'))
const canClaim = computed(() => auth.can('/incomes POST') || auth.can('/incomes/* POST'))

const loading = ref(false)
const ocring = ref(false)
const importing = ref(false)
const claiming = ref<number | null>(null)

const projects = ref<MyProject[]>([])
const rows = ref<Income[]>([])
const claimFilter = ref('')
const kw = ref('')

const projName = (id?: number | null) => {
  const p = projects.value.find(x => x.id === id)
  return p ? (p.name || p.title || p.code || `项目 #${id}`) : id ? `项目 #${id}` : '（未挂项目）'
}

// —— 回单 OCR（fileUrl/text 至少其一；双缺省 → 降级骨架，HTTP 200 恒定）——
const ocrFileUrl = ref('')
const ocrText = ref('')
const ocrRes = ref<Income | null>(null)

// —— 流水导入（{flows:[BankFlowItem]} 信封，bankFlowNo/amount 必填）——
const flowText = ref('')
// 单行格式：流水号,金额,日期,付款人,银行,用途（逗号分隔；日期/付款人等可缺省）
const parseFlows = () => flowText.value.trim().split('\n').filter(l => l.trim()).map(l => {
  const [bankFlowNo, amount, receiptDate, payerName, payerBank, purposeText] = l.split(',').map(s => s.trim())
  return { bankFlowNo, amount, ...(receiptDate ? { receiptDate } : {}), ...(payerName ? { payerName } : {}), ...(payerBank ? { payerBank } : {}), ...(purposeText ? { purposeText } : {}) }
}).filter(f => f.bankFlowNo && f.amount && num(f.amount) > 0)
const flowCount = computed(() => parseFlows().length)

async function reloadCtx() {
  const ps = await list<MyProject>('/project/mine', { page: 1, size: 50 }).catch(() => ({ rows: [] as MyProject[], total: 0 }))
  projects.value = ps.rows
}

async function load() {
  loading.value = true
  try {
    // 后端 list_incomes 读 snake_case query（claim_status/project_id/kw，契约债）；kw 为本地搜索
    const params: Record<string, unknown> = { page: 1, size: 100 }
    if (claimFilter.value) params.claim_status = claimFilter.value
    rows.value = (await list<Income>('/incomes', params)).rows
  } catch (e: any) {
    toast('到账列表加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

const shown = computed(() => {
  const kwv = kw.value.trim().toLowerCase()
  if (!kwv) return rows.value
  return rows.value.filter(i =>
    payerOf(i).toLowerCase().includes(kwv)
    || (kOf<string>(i, 'purpose_text', 'purposeText') || '').toLowerCase().includes(kwv)
    || (flowOf(i) || '').toLowerCase().includes(kwv)
    || (kOf<string>(i, 'receipt_no', 'receiptNo') || '').toLowerCase().includes(kwv))
})

async function ocr() {
  if (ocring.value) return
  if (!ocrFileUrl.value.trim() && !ocrText.value.trim()) { toast('请粘贴回单文本或填写回单图 URL（两者皆空将返回降级骨架）'); return }
  ocring.value = true
  ocrRes.value = null
  try {
    // 契约 IncomeOcrRequest {fileUrl?, text?}；响应 IncomeOcrResponse = Income + ocrWarnings（后端键 snake_case）
    ocrRes.value = await api.post<Income>('/incomes/ocr-receipt', {
      ...(ocrFileUrl.value.trim() ? { fileUrl: ocrFileUrl.value.trim() } : {}),
      ...(ocrText.value.trim() ? { text: ocrText.value.trim() } : {}),
    })
    const w = ocrRes.value?.ocrWarnings || []
    if (w.includes('ocr-engine-unavailable')) toast('识别引擎不可用，已创建降级骨架（amount=0，可人工补录）')
    else toast(`回单识别完成${confOf(ocrRes.value!) != null ? `，置信度 ${confOf(ocrRes.value!)}` : ''}${w.length ? '；告警 ' + w.join(' / ') : ''}`)
    await load()
  } catch (e: any) {
    // 40903 流水号已存在 —— 后端文案直接透出
    toast('回单识别失败：' + (e?.message || e))
  } finally {
    ocring.value = false
  }
}

async function importFlows() {
  if (importing.value) return
  const flows = parseFlows()
  if (!flows.length) { toast('请按「流水号,金额,日期,付款人,银行,用途」每行一条填写'); return }
  importing.value = true
  try {
    const r = await api.post<BankFlowImportResult>('/incomes/import-bank-flow', { flows })
    toast(`导入完成：共 ${r?.total ?? flows.length} 条 · 未认领 ${r?.unclaimed ?? 0} 条 · 耗时 ${r?.elapsedMs ?? 0}ms（已存在流水号幂等跳过）`)
    flowText.value = ''
    await load()
  } catch (e: any) {
    toast('导入失败：' + (e?.message || e))
  } finally {
    importing.value = false
  }
}

// 认领挂接项目（请求体按后端实际读键 project_id；契约写 projectId —— 双键同发保兼容）
async function claim(i: Income, projectId: number | null) {
  if (claiming.value !== null) return
  if (!projectId) { toast('请选择要挂接的项目'); return }
  if (claimOf(i) !== 'UNCLAIMED') { toast('仅 UNCLAIMED 状态可认领'); return }
  claiming.value = i.id
  try {
    await api.post<Income>(`/incomes/${i.id}/claim`, { projectId, project_id: projectId, action: 'CONFIRM' })
    toast(`到账 ${i.code} 已认领挂接 ${projName(projectId)}（触发平行记账，可支余额已更新）`)
    await load()
  } catch (e: any) {
    // 40901 仅 UNCLAIMED 可认领 / 404 —— 后端文案直接透出
    toast('认领失败：' + (e?.message || e))
  } finally {
    claiming.value = null
  }
}

onMounted(async () => { await reloadCtx(); await load() })
</script>

<template>
  <section class="view on" id="v-funding-income">
    <div class="page-head">
      <div>
        <div class="page-title">到账认领<em>回单识别</em></div>
        <div class="page-sub">银行回单 OCR 三级回落（LLM→规则→降级）· 流水批量导入 · UNCLAIMED→CLAIMED 人工认领（触发平行记账）</div>
      </div>
    </div>

    <!-- 回单 OCR（canOcr：三角色均有） -->
    <div v-if="canOcr" class="card">
      <div class="card-h"><h4>回单识别</h4><span style="font-size:12px;color:var(--ink-mute)">POST /incomes/ocr-receipt · {fileUrl?, text?} 至少其一</span></div>
      <div class="card-b" style="display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap">
        <div style="flex:1;min-width:300px">
          <div class="fld" style="margin-top:0">回单原始文本（规则引擎入口）</div>
          <textarea v-model="ocrText" class="fg" rows="4" style="width:100%" placeholder="示例：&#10;付款人：华鼎精密装备制造集团&#10;金额：61000.00&#10;日期：2026-11-10&#10;流水号：BK2026111000123&#10;用途：设备外协预付款"></textarea>
        </div>
        <div style="width:280px">
          <div class="fld" style="margin-top:0">回单图 URL（LLM 入口，可选）</div>
          <input v-model="ocrFileUrl" class="fg" placeholder="https://oss/.../receipt.jpg" style="width:100%" />
          <button class="btn seal" style="margin-top:12px" :disabled="ocring" @click="ocr">{{ ocring ? '识别中…' : '识别并登记到账' }}</button>
          <p style="font-size:11px;color:var(--ink-mute);line-height:1.7;margin-top:8px">
            置信度仅记录不阻断（R-6）；识别出流水号且已存在 → 40903 硬拦；未识别流水号 → 不带流水号创建（可重复提交）。
          </p>
        </div>
      </div>
      <!-- OCR 结果卡片 -->
      <div v-if="ocrRes" class="card-b" style="padding-top:0">
        <div class="ocr-card">
          <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
            <b class="mono">{{ ocrRes.code }}</b>
            <span class="tag" :class="stMeta(claimOf(ocrRes)).cls">{{ stMeta(claimOf(ocrRes)).tag }}</span>
            <span v-if="confOf(ocrRes) != null" class="tag info">置信度 {{ confOf(ocrRes) }}</span>
            <span class="tag" :class="num(ocrRes.amount) > 0 ? 'ok' : 'warn'">¥ {{ money(ocrRes.amount) }}</span>
          </div>
          <div style="font-size:12px;color:var(--ink-mute);margin-top:6px">
            付款人 {{ payerOf(ocrRes) }} · 日期 {{ dateOf(ocrRes) }} · 流水号 <span class="mono">{{ flowOf(ocrRes) || '—' }}</span>
            <template v-if="kOf<string>(ocrRes, 'purpose_text', 'purposeText')"> · {{ kOf<string>(ocrRes, 'purpose_text', 'purposeText') }}</template>
          </div>
          <div v-if="ocrRes.ocrWarnings?.length" style="font-size:11.5px;color:var(--ink-mute);margin-top:6px">
            ⚠ ocrWarnings：<span class="mono">{{ ocrRes.ocrWarnings.join(' / ') }}</span>
            <template v-if="num(ocrRes.amount) === 0">—— 降级骨架，可人工补录后走流水导入或重新识别</template>
          </div>
        </div>
      </div>
    </div>

    <!-- 流水导入（canImport：R-MANAGER / R-FINANCE 经 /incomes/* 通配） -->
    <div v-if="canImport" class="card">
      <div class="card-h"><h4>银行流水批量导入</h4><span style="font-size:12px;color:var(--ink-mute)">POST /incomes/import-bank-flow · {flows:[BankFlowItem]}</span></div>
      <div class="card-b" style="display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap">
        <div style="flex:1;min-width:300px">
          <div class="fld" style="margin-top:0">流水明细（每行一条：流水号,金额,日期,付款人,银行,用途 —— 后四项可缺省）</div>
          <textarea v-model="flowText" class="fg" rows="4" style="width:100%" placeholder="BK2026111800001,120000.00,2026-11-18,省科技厅,工行合肥高新区支行,重点研发计划首期拨款&#10;BK2026111800002,95000.00"></textarea>
        </div>
        <div style="display:flex;flex-direction:column;gap:10px;align-items:flex-start">
          <span class="tag" :class="flowCount ? 'info' : 'muted'">{{ flowCount }} 条有效流水</span>
          <button class="btn seal" :disabled="importing || !flowCount" @click="importFlows">{{ importing ? '导入中…' : '批量导入' }}</button>
          <p style="font-size:11px;color:var(--ink-mute);line-height:1.7">
            bankFlowNo/amount 必填；金额最多 2 位小数（否则后端 40001 整批拒绝）；同流水号幂等跳过。
          </p>
        </div>
      </div>
    </div>

    <!-- 到账台账 + 认领 -->
    <div class="card">
      <div class="card-h">
        <h4>到账台账（挂账池）</h4>
        <div style="display:flex;gap:8px;align-items:center">
          <select v-model="claimFilter" class="fg" style="width:130px" @change="load">
            <option value="">全部状态</option>
            <option v-for="(m, k) in CLAIM_META" :key="k" :value="k">{{ m.tag }}（{{ k }}）</option>
          </select>
          <input v-model="kw" class="fg" style="width:180px" placeholder="搜索付款人/用途/流水号" @keyup.enter="load" />
          <button class="btn ghost sm" @click="load">刷新</button>
        </div>
      </div>
      <div class="card-b" style="overflow:auto;min-width:0">
        <table class="tbl" style="border-collapse:collapse;font-size:12.5px;table-layout:fixed;width:100%">
          <thead>
            <tr style="text-align:left">
              <th style="width:11%">单号</th>
              <th style="width:9%" class="num">金额</th>
              <th style="width:14%">付款人</th>
              <th style="width:10%">日期</th>
              <th style="width:13%">流水号</th>
              <th style="width:8%">认领状态</th>
              <th style="width:14%">挂接项目</th>
              <th v-if="canClaim" style="width:14%">认领操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="i in shown" :key="i.id">
              <td class="mono">{{ i.code }}</td>
              <td class="mono num">¥{{ money(i.amount) }}</td>
              <td style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ payerOf(i) }}</td>
              <td class="mono">{{ dateOf(i) }}</td>
              <td class="mono" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ flowOf(i) || '—' }}</td>
              <td>
                <span class="tag" :class="stMeta(claimOf(i)).cls">{{ stMeta(claimOf(i)).tag }}</span>
                <div v-if="confOf(i) != null" style="margin-top:3px"><span class="tag info" style="font-size:10px">置信 {{ confOf(i) }}</span></div>
              </td>
              <td style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ projName(projIdOf(i)) }}</td>
              <td v-if="canClaim">
                <select
                  v-if="claimOf(i) === 'UNCLAIMED'"
                  class="fg" style="width:100%;font-size:11.5px"
                  :disabled="claiming !== null"
                  @change="claim(i, Number(($event.target as HTMLSelectElement).value) || null)"
                >
                  <option :value="null">选择项目认领…</option>
                  <option v-for="p in projects" :key="p.id" :value="p.id">{{ projName(p.id) }}</option>
                </select>
                <span v-else-if="kOf<string | null>(i, 'claimed_at', 'claimedAt')" style="font-size:11px;color:var(--ink-mute)">已挂接 ✓</span>
                <span v-else style="color:var(--ink-mute);font-size:11px">—</span>
              </td>
            </tr>
            <tr v-if="!shown.length && !loading"><td :colspan="canClaim ? 8 : 7" style="color:var(--ink-mute);padding:18px;text-align:center">暂无到账记录</td></tr>
          </tbody>
        </table>
        <span v-if="loading" style="font-size:12px;color:var(--ink-mute)">加载中…</span>
      </div>
    </div>

    <p style="font-size:11.5px;color:var(--ink-mute);line-height:1.8;margin-top:10px">
      认领幂等：仅 UNCLAIMED→CLAIMED（后端 40901；重复认领被拒）。认领触发 income.claimed 平行记账
      （借 1002 银行存款 / 贷 4601 非同级财政拨款收入）并刷新项目可支余额；管理费按项目分类费率计提（mgmt_fee）。
      自动匹配引擎（AUTO_MATCHED/DOUBTFUL）M2 接入，本期 autoMatched/doubtful 恒 0。
    </p>
  </section>
</template>

<style scoped>
.fld { font-size: 12px; color: var(--ink-mute); margin-top: 12px; letter-spacing: 1px; }
.mono { font-family: var(--mono); }
.num { text-align: right; }
.tag.muted { background: #eef1f6; color: #6b7280; }
.tag.info { background: #e8f1fd; color: #2563eb; }
.tag.ok { background: #e7f6ec; color: #15803d; }
.tag.warn { background: #fdf3e2; color: #b45309; }
.tag.bad { background: #fdecec; color: #b91c1c; }
.btn:disabled { opacity: .6; cursor: not-allowed; }
.tbl tbody tr:hover { background: rgba(0,0,0,.03); }
.ocr-card { border: 1px solid var(--line, #e5e9f2); border-radius: 10px; padding: 12px 14px; background: #f6fbf8; margin-top: 12px; }
</style>
