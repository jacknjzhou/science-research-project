/**
 * Curated overrides —— 科研档案管理屏（module O）
 * 契约：16-科研档案管理-O.openapi.yaml（tag archive）。键 = `METHOD /模板路径`（{var} 占位符严格对齐契约 path）。
 * 值 = ApiResponse.data。列表 typed：{ list, total, page, size }（PageResult）；
 *   GET /archives/{id}/items → 契约 data 仅 { list }（非 PageResult，忠实镜像契约）；
 *   POST /archives/{id}/check → CheckReport { list, passed }。
 * 字段名严格对齐后端 mapper snake_case（Archive/Document/ArchiveItem/ArchiveCheck/Borrow），
 *   与 backend-go/testdata/seed_o.sql 一致：2 文档(STORED)、1 ARCHIVED 项目档案(PRJ-2024-0001)、
 *   3 门类(2 FILLED 挂 doc、1 MISSING)、4 项四性检测(均 PASS)、若干借阅。
 * 迁移类（create/submit/check/file/destroy/ingest + borrow approve/reject/return）改写内存 store，
 *   使 mock 下 reload 后状态可见（override 函数仅能拿 url、拿不到请求体，故 create 落占位标题）。
 * 无金额字段（本域不涉及钱），时间一律 ISO 字符串。
 */

// —— 记录类型（仅内部约束 store，字段名 = 契约 snake_case）——
interface ArchRec {
  id: number; code: string | null; title: string; archive_type: string
  source_module: string | null; source_id: number | null; source_code: string | null
  owner_dept_id: number | null; retention_years: number; status: string
  security_level: string; submitter_id: number | null; submit_at: string | null
  archivist_id: number | null; filed_at: string | null; created_at: string; updated_at: string
  [k: string]: any
}
interface DocRec {
  id: number; code: string | null; tenant_id: number; status: string; name: string
  doc_type: string | null; size_bytes: number | null; bucket: string | null; object_key: string | null
  checksum_sha256: string | null; source_module: string | null; source_id: number | null
  security_level: string; uploaded_at: string | null; created_at: string
  [k: string]: any
}
interface ItemRec {
  id: number; archive_id: number; category_code: string; category_name: string | null
  required: boolean; doc_id: number | null; status: string; sort_no: number
  [k: string]: any
}
interface CheckRec {
  id: number; archive_id: number; check_type: string; result: string
  detail: Record<string, any>; checked_at: string | null; checker_id: number | null
  [k: string]: any
}
interface BorrowRec {
  id: number; code: string | null; archive_id: number; archive_title: string | null
  borrower_user_id: number; purpose: string | null; borrow_type: string; status: string
  approved_by: number | null; approved_at: string | null; due_at: string | null
  returned_at: string | null; created_at: string; [k: string]: any
}

const T = '2026-09-01T08:00:00Z'

// —— 2 电子件（STORED）；text_content 不外泄，检索正文仅用于 mock snippet ——
const DOCS: DocRec[] = [
  {
    id: 7001, code: 'DOC-2024-0001', tenant_id: 1, status: 'STORED', name: '医学影像分割论文',
    doc_type: 'pdf', size_bytes: 4096, bucket: 'ark-docs', object_key: 'tenant/1/doc-cnn.pdf',
    checksum_sha256: 'a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90',
    source_module: 'O', source_id: null, security_level: 'INTERNAL', uploaded_at: T, created_at: T,
  },
  {
    id: 7002, code: 'DOC-2024-0002', tenant_id: 1, status: 'STORED', name: '项目结题报告',
    doc_type: 'pdf', size_bytes: 8192, bucket: 'ark-docs', object_key: 'tenant/1/doc-final-report.pdf',
    checksum_sha256: '0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0',
    source_module: 'E', source_id: null, security_level: 'INTERNAL', uploaded_at: T, created_at: T,
  },
]
const DOC_TEXT: Record<number, string> = {
  7001: '卷积神经网络 医学图像 分割：提出多尺度注意力解码器，提升小目标边界分割精度。',
  7002: '项目结题报告 经费决算：对照任务书考核指标逐项核验，经费执行率 98.6%。',
}

// —— 案卷台账：忠实含 seed 的 1 条 ARCHIVED 项目档案，另附各状态样例以驱动状态机演示 ——
const ARCHIVES: ArchRec[] = [
  {
    id: 7101, code: 'ARC-2024-0001', title: 'O 项目科研档案-已入库', archive_type: 'PROJECT',
    source_module: 'E', source_id: null, source_code: 'PRJ-2024-0001', owner_dept_id: null,
    retention_years: 10, status: 'ARCHIVED', security_level: 'INTERNAL',
    submitter_id: 1001, submit_at: T, archivist_id: 1001, filed_at: T, created_at: T, updated_at: T,
  },
  {
    id: 7102, code: 'ARC-2026-0002', title: '2026 高水平成果归档（论文+专利）', archive_type: 'OUTPUT',
    source_module: 'R', source_id: 4201, source_code: 'OUT-2026-0088', owner_dept_id: 10,
    retention_years: 30, status: 'PENDING_SUBMIT', security_level: 'PUBLIC',
    submitter_id: null, submit_at: null, archivist_id: null, filed_at: null, created_at: T, updated_at: T,
  },
  {
    id: 7103, code: 'ARC-2026-0003', title: '国家重点研发计划 · 经费决算归档', archive_type: 'EXPENSE',
    source_module: 'F', source_id: 6101, source_code: 'BUD-2024-0012', owner_dept_id: 11,
    retention_years: 15, status: 'SUBMITTED', security_level: 'INTERNAL',
    submitter_id: 1002, submit_at: T, archivist_id: null, filed_at: null, created_at: T, updated_at: T,
  },
  {
    id: 7104, code: 'ARC-2026-0004', title: '装备研制合同归档', archive_type: 'CONTRACT',
    source_module: 'C', source_id: 5301, source_code: 'CON-2025-0031', owner_dept_id: 12,
    retention_years: 10, status: 'REJECTED', security_level: 'SECRET',
    submitter_id: 1003, submit_at: T, archivist_id: null, filed_at: null, created_at: T, updated_at: T,
  },
]

// —— 门类清单（按 archive_id 归组）：seed 的 7101 → C1/C2 FILLED(挂 doc)、C3 MISSING ——
const ITEMS: Record<number, ItemRec[]> = {
  7101: [
    { id: 7201, archive_id: 7101, category_code: 'C1', category_name: '结题材料', required: true, doc_id: 7001, status: 'FILLED', sort_no: 1 },
    { id: 7202, archive_id: 7101, category_code: 'C2', category_name: '经费决算', required: true, doc_id: 7002, status: 'FILLED', sort_no: 2 },
    { id: 7203, archive_id: 7101, category_code: 'C3', category_name: '补充附件', required: true, doc_id: null, status: 'MISSING', sort_no: 3 },
  ],
  7103: [
    { id: 7211, archive_id: 7103, category_code: 'C1', category_name: '预算批复', required: true, doc_id: null, status: 'MISSING', sort_no: 1 },
    { id: 7212, archive_id: 7103, category_code: 'C2', category_name: '决算报告', required: true, doc_id: null, status: 'MISSING', sort_no: 2 },
  ],
}
let itemIdSeq = 7290

// —— 四性检测报告（seed 均 PASS；detail 忠实镜像 seed jsonb）——
const CHECKS: Record<number, CheckRec[]> = {
  7101: [
    { id: 7301, archive_id: 7101, check_type: 'AUTHENTICITY', result: 'PASS', detail: { mismatch_doc_ids: [], checked: 2 }, checked_at: T, checker_id: 1001 },
    { id: 7302, archive_id: 7101, check_type: 'INTEGRITY', result: 'PASS', detail: { required_total: 3, required_filled: 3 }, checked_at: T, checker_id: 1001 },
    { id: 7303, archive_id: 7101, check_type: 'USABILITY', result: 'PASS', detail: { total: 2, unusable: 0 }, checked_at: T, checker_id: 1001 },
    { id: 7304, archive_id: 7101, check_type: 'SECURITY', result: 'PASS', detail: { security_ok: true }, checked_at: T, checker_id: 1001 },
  ],
}

// —— 借阅申请：archive_title 后端无 join 恒为 null，视图侧从已加载台账按 archive_id 反查 ——
const BORROWS: BorrowRec[] = [
  {
    id: 7401, code: 'BORROW-2026-0001', archive_id: 7101, archive_title: null, borrower_user_id: 1001,
    purpose: '项目审计取证', borrow_type: 'READ', status: 'APPROVED', approved_by: 1001, approved_at: T,
    due_at: '2026-09-30T08:00:00Z', returned_at: null, created_at: T,
  },
  {
    id: 7402, code: 'BORROW-2026-0002', archive_id: 7102, archive_title: null, borrower_user_id: 1002,
    purpose: '成果申报佐证（需复制）', borrow_type: 'COPY', status: 'SUBMITTED', approved_by: null, approved_at: null,
    due_at: '2026-10-15T08:00:00Z', returned_at: null, created_at: T,
  },
  {
    id: 7403, code: 'BORROW-2026-0003', archive_id: 7101, archive_title: null, borrower_user_id: 1003,
    purpose: '合同履约核查', borrow_type: 'READ', status: 'RETURNED', approved_by: 1001, approved_at: T,
    due_at: '2026-08-20T08:00:00Z', returned_at: '2026-08-18T08:00:00Z', created_at: T,
  },
]

// —— 工具 ——
function qs(url: string, key: string): string {
  try {
    return new URL(url, 'http://x.local').searchParams.get(key) || ''
  } catch {
    return ''
  }
}
const RE = { archive: /\/archives\/(\d+)/, borrow: /\/borrows\/(\d+)/, doc: /\/documents\/(\d+)/ }
function idFrom(url: string, kind: keyof typeof RE): number {
  const m = url.match(RE[kind])
  return m ? Number(m[1]) : 0
}
function findArch(id: number): ArchRec | undefined {
  return ARCHIVES.find((a) => a.id === id)
}
function findBorrow(id: number): BorrowRec | undefined {
  return BORROWS.find((b) => b.id === id)
}

export const overrides: Record<string, unknown> = {
  // ===== 案卷台账（含筛选，反映状态机迁移） =====
  'GET /archives': (url: string) => {
    const st = qs(url, 'status')
    const tp = qs(url, 'archive_type')
    const kw = qs(url, 'kw')
    const list = ARCHIVES.filter(
      (a) =>
        (!st || a.status === st) &&
        (!tp || a.archive_type === tp) &&
        (!kw || a.title.includes(kw) || (a.code || '').includes(kw) || (a.source_code || '').includes(kw)),
    )
    return { list, total: list.length, page: 1, size: 20 }
  },
  'POST /archives': () => {
    const nid = Math.max(...ARCHIVES.map((a) => a.id)) + 1
    const rec: ArchRec = {
      id: nid, code: `ARC-2026-${String(nid).padStart(4, '0')}`, title: '新建案卷（mock）', archive_type: 'OTHER',
      source_module: null, source_id: null, source_code: null, owner_dept_id: null,
      retention_years: 10, status: 'PENDING_SUBMIT', security_level: 'INTERNAL',
      submitter_id: null, submit_at: null, archivist_id: null, filed_at: null, created_at: T, updated_at: T,
    }
    ARCHIVES.push(rec)
    return rec
  },

  // 门类清单（契约 data 仅 { list }，忠实镜像 → 不带 total/page/size）
  'GET /archives/{id}/items': (url: string) => ({ list: ITEMS[idFrom(url, 'archive')] ?? [] }),
  'POST /archives/{id}/ingest': (url: string) => {
    const aid = idFrom(url, 'archive')
    const it: ItemRec = { id: ++itemIdSeq, archive_id: aid, category_code: `ING-${itemIdSeq}`, category_name: '来源摄取件', required: true, doc_id: null, status: 'MISSING', sort_no: (ITEMS[aid]?.length ?? 0) + 1 }
    ;(ITEMS[aid] ||= []).push(it)
    return it
  },

  // 状态机：提交 → SUBMITTED
  'POST /archives/{id}/submit': (url: string) => {
    const a = findArch(idFrom(url, 'archive'))
    if (a) { a.status = 'SUBMITTED'; a.submit_at = T; a.updated_at = T }
    return { id: a?.id ?? 0, status: a?.status ?? null }
  },
  // 四性检测 → CheckReport { list, passed }（SUBMITTED → PASSED/REJECTED）
  'POST /archives/{id}/check': (url: string) => {
    const aid = idFrom(url, 'archive')
    const a = findArch(aid)
    const list = CHECKS[aid] ?? CHECKS[7101]
    const passed = list.every((c) => c.result === 'PASS')
    if (a) { a.status = passed ? 'PASSED' : 'REJECTED'; a.updated_at = T }
    return { list, passed }
  },
  // 入库（PASSED → ARCHIVED，仅 R-ADMIN）
  'POST /archives/{id}/file': (url: string) => {
    const a = findArch(idFrom(url, 'archive'))
    if (a) { a.status = 'ARCHIVED'; a.archivist_id = 1001; a.filed_at = T; a.updated_at = T }
    return { id: a?.id ?? 0, status: a?.status ?? null }
  },
  // 销毁（ARCHIVED → DESTROYED，留痕，仅 R-ADMIN）
  'POST /archives/{id}/destroy': (url: string) => {
    const a = findArch(idFrom(url, 'archive'))
    if (a) { a.status = 'DESTROYED'; a.updated_at = T }
    return { id: a?.id ?? 0, status: a?.status ?? null }
  },

  // ===== 全文检索（命中 Document + snippet/rank） =====
  'GET /documents/search': (url: string) => {
    const q = qs(url, 'q')
    const all = DOCS.map((d) => ({ ...d, snippet: DOC_TEXT[d.id] || d.name, rank: 1 }))
    const list = q
      ? all.filter((d) => (d.name + ' ' + (d.snippet || '')).toLowerCase().includes(q.toLowerCase()))
      : all
    return { list, total: list.length, page: 1, size: 20 }
  },
  // 下载（presigned GET URL + 过期时刻）
  'GET /documents/{id}/download': (url: string) => {
    const id = idFrom(url, 'doc')
    const d = DOCS.find((x) => x.id === id)
    return {
      url: `https://ark-minio.example/${d?.bucket || 'ark-docs'}/${d?.object_key || 'tenant/1/doc.pdf'}?X-Amz-Expires=900`,
      expires_at: '2026-09-01T08:15:00Z',
    }
  },

  // ===== 借阅 =====
  'GET /borrows': (url: string) => {
    const st = qs(url, 'status')
    const aid = qs(url, 'archive_id')
    const list = BORROWS.filter((b) => (!st || b.status === st) && (!aid || String(b.archive_id) === aid))
    return { list, total: list.length, page: 1, size: 20 }
  },
  'POST /borrows': () => {
    const nid = Math.max(...BORROWS.map((b) => b.id)) + 1
    const rec: BorrowRec = {
      id: nid, code: `BORROW-2026-${String(nid).padStart(4, '0')}`, archive_id: ARCHIVES[0]?.id ?? 0, archive_title: null,
      borrower_user_id: 1001, purpose: '新建借阅申请（mock）', borrow_type: 'READ', status: 'SUBMITTED',
      approved_by: null, approved_at: null, due_at: '2026-10-31T08:00:00Z', returned_at: null, created_at: T,
    }
    BORROWS.push(rec)
    return rec
  },
  'POST /borrows/{id}/approve': (url: string) => {
    const b = findBorrow(idFrom(url, 'borrow'))
    if (b) { b.status = 'APPROVED'; b.approved_by = 1001; b.approved_at = T }
    return { id: b?.id ?? 0, status: b?.status ?? null }
  },
  'POST /borrows/{id}/reject': (url: string) => {
    const b = findBorrow(idFrom(url, 'borrow'))
    if (b) { b.status = 'REJECTED' }
    return { id: b?.id ?? 0, status: b?.status ?? null }
  },
  'POST /borrows/{id}/return': (url: string) => {
    const b = findBorrow(idFrom(url, 'borrow'))
    if (b) { b.status = 'RETURNED'; b.returned_at = T }
    return { id: b?.id ?? 0, status: b?.status ?? null }
  },
}
