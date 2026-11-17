/**
 * Curated overrides —— M1-c 经费域：拨款 / 到账 / 回单 OCR / 核算开户
 * 契约：03-科研经费管理-F.openapi.yaml（tag Disbursement / Income / Budget）
 *
 * 响应键对齐真实后端（M1-c Task 7 勘测结论）：
 *  - disbursement / open-account 域 camelCase（mappings.to_api_disbursement / api.open_project_account）；
 *  - income 域 snake_case（mappings.to_api_income 契约债）+ match_confidence / ocrWarnings（ocr handler）；
 *    视图侧已做「snake_case 主 + camelCase ?? 兜底」双读，两种形态均可渲染。
 * mock 不抛业务错误（envelope 恒 code:0）：40901/40903/42201 冲突以幂等返回兜底，
 * 提交前的同口径客户端预检由视图承担（FundingDisburseView / FundingIncomeView）。
 */

type DisbStatus =
  | 'DRAFT' | 'SUBMITTED' | 'APPROVED' | 'PAID'
  | 'VOUCHER_SYNCED' | 'REJECTED' | 'RETURNED'

// —— 拨款（camelCase，对齐 to_api_disbursement）——
interface DisbRec {
  id: number; code: string
  contractId: number; outsourceUnitId: number; projectId: number
  securityLevel: string; amount: string; phase: string
  voucherStatus: string
  contractAmount: string; remainContractAmount: string
  complianceFlags: string[]; status: DisbStatus; policyPackId: number | null
}

// —— 到账（snake_case，对齐 to_api_income）——
interface IncomeRec {
  id: number; code: string; project_id: number | null; legal_entity_id: number
  receipt_no: string; receipt_date: string | null; amount: string
  payer_name: string; payer_bank: string; purpose_text: string
  bank_flow_no: string | null; claim_status: 'UNCLAIMED' | 'AUTO_MATCHED' | 'CLAIMED' | 'DOUBTFUL'
  claimed_by: number | null; claimed_at: string | null
  mgmt_fee: string; created_at: string
}

const now = '2026-11-17T09:00:00Z'

// 合同额度表（对齐 procurement.ts contracts 英雄数据；G 契约无 GET 合同列表时 mock 用固定额度）
const CONTRACT_AMOUNT: Record<number, number> = {
  131: 180000, 72: 126000, 88: 620000, 142: 2800000, 59: 950000,
}

// 占用合同额度的状态（镜像后端 _DISB_COUNTED_STATUS：非 REJECTED/RETURNED）
const COUNTED: DisbStatus[] = ['SUBMITTED', 'APPROVED', 'PAID', 'VOUCHER_SYNCED']

const disbStore: DisbRec[] = [
  { id: 9101, code: 'DISB-2026-9101', contractId: 131, outsourceUnitId: 108, projectId: 90001, securityLevel: 'INTERNAL', amount: '50000.00', phase: '预付', voucherStatus: 'PENDING', contractAmount: '180000.00', remainContractAmount: '130000.00', complianceFlags: [], status: 'SUBMITTED', policyPackId: null },
  { id: 9102, code: 'DISB-2026-9102', contractId: 131, outsourceUnitId: 108, projectId: 90001, securityLevel: 'INTERNAL', amount: '60000.00', phase: '进度', voucherStatus: 'PENDING', contractAmount: '180000.00', remainContractAmount: '70000.00', complianceFlags: [], status: 'APPROVED', policyPackId: null },
  { id: 9103, code: 'DISB-2026-9103', contractId: 72, outsourceUnitId: 72, projectId: 90002, securityLevel: 'PUBLIC', amount: '40000.00', phase: '尾款', voucherStatus: 'PENDING', contractAmount: '126000.00', remainContractAmount: '86000.00', complianceFlags: [], status: 'PAID', policyPackId: null },
]

const incomeStore: IncomeRec[] = [
  { id: 9201, code: 'INC-2026-9201', project_id: null, legal_entity_id: 1, receipt_no: '', receipt_date: '2026-11-10', amount: '120000.00', payer_name: '省科技厅', payer_bank: '工行合肥高新区支行', purpose_text: '重点研发计划首期拨款', bank_flow_no: 'BK2026111000123', claim_status: 'UNCLAIMED', claimed_by: null, claimed_at: null, mgmt_fee: '0.00', created_at: now },
  { id: 9202, code: 'INC-2026-9202', project_id: null, legal_entity_id: 1, receipt_no: '', receipt_date: '2026-11-15', amount: '95000.00', payer_name: '某汽车模具厂', payer_bank: '建行城东支行', purpose_text: '横向课题进度款', bank_flow_no: 'BK2026111500456', claim_status: 'UNCLAIMED', claimed_by: null, claimed_at: null, mgmt_fee: '0.00', created_at: now },
  { id: 9203, code: 'INC-2026-9203', project_id: 90001, legal_entity_id: 1, receipt_no: 'RCP-2026-0091', receipt_date: '2026-10-22', amount: '61000.00', payer_name: '华鼎精密装备制造集团', payer_bank: '中行庐州支行', purpose_text: '设备外协预付款', bank_flow_no: 'BK2026102200789', claim_status: 'CLAIMED', claimed_by: 100, claimed_at: now, mgmt_fee: '0.00', created_at: now },
  { id: 9204, code: 'INC-2026-9204', project_id: 90002, legal_entity_id: 1, receipt_no: 'RCP-2026-0088', receipt_date: '2026-09-30', amount: '30800.00', payer_name: '中科智能系统股份有限公司', payer_bank: '交行滨湖支行', purpose_text: '技术服务尾款', bank_flow_no: 'BK2026093000321', claim_status: 'CLAIMED', claimed_by: 100, claimed_at: now, mgmt_fee: '616.00', created_at: now },
]

// —— 核算账号（open-account：camelCase OpenAccountResult；R-8 幂等：非 CLOSED 重复开户返回既有账号）——
const accountStore = new Map<number, {
  budgetId: number; budgetCode: string
  lines: { id: number; subjectId: number; subjectName: string }[]
}>()

let disbSeq = 9100
let incomeSeq = 9200
let budgetSeq = 9300
let lineSeq = 9400

const num2 = (n: number) => n.toFixed(2)
const toN = (v?: unknown): number => {
  const n = Number.parseFloat(String(v ?? '').replace(/[,\s¥￥]/g, ''))
  return Number.isFinite(n) ? n : 0
}
const q = (url: string): URLSearchParams => {
  try { return new URL(url, 'http://x.local').searchParams } catch { return new URLSearchParams() }
}
const idIn = (url: string, re: RegExp): number => {
  const m = url.match(re)
  return m ? Number(m[1]) : 0
}
// 合同已拨累计（镜像后端 _disbursed_before）
const disbursedBeforeOf = (contractId: number): number =>
  disbStore
    .filter((d) => d.contractId === contractId && COUNTED.includes(d.status))
    .reduce((a, d) => a + toN(d.amount), 0)
const codeOf = (prefix: string, id: number) => `${prefix}-2026-${id}`

type Ctx = { method: string; headers: Record<string, string>; body: unknown }
const asBody = (b: unknown): Record<string, unknown> =>
  b && typeof b === 'object' ? (b as Record<string, unknown>) : {}

export const overrides: Record<string, unknown> = {
  // ------------------------------------------------------------------
  // 拨款（Disbursement，camelCase）
  // ------------------------------------------------------------------
  'GET /disbursements': (url: string) => {
    const s = q(url)
    const contractId = Number(s.get('contractId') || 0)
    const projectId = Number(s.get('projectId') || 0)
    const status = s.get('status') || ''
    const rows = disbStore.filter((d) =>
      (!contractId || d.contractId === contractId)
      && (!projectId || d.projectId === projectId)
      && (!status || d.status === status))
    return { list: rows, total: rows.length, page: Number(s.get('page') || 1), size: Number(s.get('size') || 20) }
  },

  'POST /disbursements': (_url: string, ctx: Ctx) => {
    const b = asBody(ctx.body)
    const contractId = Number(b.contractId || 0)
    const amount = toN(b.amount)
    const phase = String(b.phase || '')
    // 幂等防重（镜像 40901 同口径）：同合同同阶段已有非 REJECTED/RETURNED 单 → 返回既有单
    const dup = disbStore.find(
      (d) => d.contractId === contractId && d.phase === phase && !['REJECTED', 'RETURNED'].includes(d.status))
    if (dup) return dup
    const ca = CONTRACT_AMOUNT[contractId] ?? 0
    const before = disbursedBeforeOf(contractId)
    const rec: DisbRec = {
      id: ++disbSeq, code: codeOf('DISB', disbSeq),
      contractId, outsourceUnitId: Number(b.outsourceUnitId || 0),
      projectId: Number(b.projectId || 0),
      securityLevel: String(b.securityLevel || 'INTERNAL'),
      amount: num2(amount), phase,
      voucherStatus: 'PENDING',
      contractAmount: num2(ca), remainContractAmount: num2(ca - before - amount),
      complianceFlags: [], status: 'SUBMITTED', policyPackId: null,
    }
    disbStore.unshift(rec)
    return rec
  },

  'POST /disbursements/check-contract': (_url: string, ctx: Ctx) => {
    const b = asBody(ctx.body)
    const contractId = Number(b.contractId || 0)
    const ca = CONTRACT_AMOUNT[contractId] ?? 0
    const before = disbursedBeforeOf(contractId)
    const remain = ca - before
    return {
      contractId,
      contractAmount: num2(ca),
      disbursedBefore: num2(before),
      remainContractAmount: num2(remain),
      canDisburse: toN(b.amount) <= remain,
      complianceFlags: [],
      ruleHits: [],
    }
  },

  'POST /disbursements/{id}/action': (url: string, ctx: Ctx) => {
    const id = idIn(url, /\/disbursements\/(\d+)\/action/)
    const b = asBody(ctx.body)
    const d = disbStore.find((x) => x.id === id)
    if (!d) return null
    // approve 仅 SUBMITTED→APPROVED；pay 仅 APPROVED→PAID（镜像后端状态机）
    if (b.action === 'approve' && d.status === 'SUBMITTED') d.status = 'APPROVED'
    else if (b.action === 'pay' && d.status === 'APPROVED') { d.status = 'PAID'; d.voucherStatus = 'PENDING' }
    return d
  },

  // ------------------------------------------------------------------
  // 到账（Income，snake_case 契约债 + ocr 附加键）
  // ------------------------------------------------------------------
  'GET /incomes': (url: string) => {
    const s = q(url)
    const claim = s.get('claim_status') || s.get('claimStatus') || ''
    const projectId = Number(s.get('project_id') || s.get('projectId') || 0)
    const kw = (s.get('kw') || '').toLowerCase()
    const rows = incomeStore.filter((i) =>
      (!claim || i.claim_status === claim)
      && (!projectId || i.project_id === projectId)
      && (!kw
        || i.payer_name.toLowerCase().includes(kw)
        || i.purpose_text.toLowerCase().includes(kw)
        || (i.bank_flow_no || '').toLowerCase().includes(kw)))
    return { list: rows, total: rows.length, page: Number(s.get('page') || 1), size: Number(s.get('size') || 20) }
  },

  'POST /incomes/ocr-receipt': (_url: string, ctx: Ctx) => {
    const b = asBody(ctx.body)
    const text = String(b.text ?? '').trim()
    const fileUrl = String(b.fileUrl ?? '').trim()

    // 规则引擎拟真（镜像 core/receipt_ocr 标签族：付款人/金额/日期/流水号/用途）
    const pick = (re: RegExp): string => {
      const m = text.match(re)
      return m && m[1] ? m[1].trim() : ''
    }
    const payerName = pick(/付款人[：:]\s*([^\n，,；;]+)/)
    const amountRaw = pick(/金额[：:]\s*([\d,]+(?:\.\d{1,2})?)/)
    const dateRaw = pick(/(20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2})/)
    const bankFlowNo = pick(/流水号[：:]\s*([A-Za-z0-9-]+)/)
    const purpose = pick(/(?:用途|摘要)[：:]\s*([^\n]+)/)
    const date = dateRaw ? dateRaw.replace(/[年月./]+/g, '-').replace(/-+$/, '') : null
    const hasFields = Boolean(payerName || amountRaw || bankFlowNo)

    const warnings: string[] = []
    if (!text && !fileUrl) warnings.push('ocr-engine-unavailable')
    else if (text && !hasFields) warnings.push('receipt-text-no-fields')

    const rec: IncomeRec = {
      id: ++incomeSeq, code: codeOf('INC', incomeSeq),
      project_id: null, legal_entity_id: 1,
      receipt_no: '',
      receipt_date: date,
      amount: hasFields ? num2(toN(amountRaw)) : '0.00',
      payer_name: payerName, payer_bank: '', purpose_text: purpose,
      bank_flow_no: bankFlowNo || null,
      claim_status: 'UNCLAIMED', claimed_by: null, claimed_at: null,
      mgmt_fee: '0.00', created_at: now,
    }
    incomeStore.unshift(rec)
    return {
      ...rec,
      // 契约 IncomeOcrResponse：Income 全字段 + ocrWarnings；置信度仅记录不阻断
      match_confidence: hasFields ? 0.8 : null,
      ocrWarnings: warnings,
    }
  },

  'POST /incomes/import-bank-flow': (_url: string, ctx: Ctx) => {
    const b = asBody(ctx.body)
    const flows = Array.isArray(b.flows) ? (b.flows as Array<Record<string, unknown>>) : []
    const started = Date.now()
    let unclaimed = 0
    for (const r of flows) {
      const flow = String(r.bankFlowNo ?? '').trim()
      const amount = toN(r.amount)
      if (!flow || amount <= 0) continue // 真后端整批 40001；视图侧已校验，mock 跳坏行
      if (incomeStore.some((x) => x.bank_flow_no === flow)) continue // 幂等 skip
      const rec: IncomeRec = {
        id: ++incomeSeq, code: codeOf('INC', incomeSeq),
        project_id: null, legal_entity_id: 1, receipt_no: '',
        receipt_date: (r.receiptDate as string) || null,
        amount: num2(amount),
        payer_name: String(r.payerName ?? ''), payer_bank: String(r.payerBank ?? ''),
        purpose_text: String(r.purposeText ?? ''),
        bank_flow_no: flow, claim_status: 'UNCLAIMED', claimed_by: null, claimed_at: null,
        mgmt_fee: '0.00', created_at: now,
      }
      incomeStore.unshift(rec)
      unclaimed++
    }
    return { total: flows.length, autoMatched: 0, doubtful: 0, unclaimed, elapsedMs: Math.max(1, Date.now() - started) }
  },

  'POST /incomes/{incomeId}/claim': (url: string, ctx: Ctx) => {
    const id = idIn(url, /\/incomes\/(\d+)\/claim/)
    const b = asBody(ctx.body)
    const inc = incomeStore.find((x) => x.id === id)
    if (!inc) return null
    if (inc.claim_status !== 'UNCLAIMED') return inc // 镜像后端 40901：仅 UNCLAIMED 可认领
    // 后端读 b.project_id（snake_case）；契约写 projectId —— 双键兜底
    const p = Number(b.project_id ?? b.projectId ?? 0)
    inc.claim_status = 'CLAIMED'
    inc.project_id = p || null
    inc.claimed_by = 100
    inc.claimed_at = now
    return inc
  },

  // ------------------------------------------------------------------
  // 核算开户（Budget B1，camelCase OpenAccountResult；幂等返回既有账号）
  // ------------------------------------------------------------------
  'POST /projects/{projectId}/open-account': (url: string) => {
    const p = idIn(url, /\/projects\/(\d+)\/open-account/)
    const exist = accountStore.get(p)
    if (exist) return exist
    const budgetId = ++budgetSeq
    const acc = {
      budgetId,
      budgetCode: codeOf('BUD', budgetId),
      lines: [
        { id: ++lineSeq, subjectId: 101, subjectName: '设备费' },
        { id: ++lineSeq, subjectId: 102, subjectName: '材料费' },
        { id: ++lineSeq, subjectId: 103, subjectName: '测试化验加工费' },
        { id: ++lineSeq, subjectId: 104, subjectName: '差旅费' },
      ],
    }
    accountStore.set(p, acc)
    return acc
  },
}
