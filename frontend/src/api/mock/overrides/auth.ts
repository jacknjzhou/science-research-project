/**
 * 认证链路 curated override（mock 模式专用）：
 *
 * 契约生成器会为 /auth/me 现场编造随机角色、为 /page-grants 编造随机矩阵——
 * 随机角色命中不了矩阵任何行 → canSeePage 全 false → 登录必被守卫弹 /forbidden，
 * mock 模式实际不可用。此文件把认证三端点钉到与真实后端种子/策略同源的数据：
 *
 * · /auth/login  → 发 `mock-<username>` 令牌（任意用户名放行，mock 免摩擦）
 * · /auth/me     → 按令牌回 curated 用户 + 角色 + caps（角色镜像 seed_demo.USERS，
 *                  caps 镜像 casbin policy.csv 铁律：admin 全量、auditor/finance 只读）
 * · /page-grants → 静态返回 seed_demo.PAGE_GRANTS 35 行矩阵（页面可见性与真实后端一致）
 */
import type { OverrideCtx } from '../index'

// —— 演示账号（镜像 backend-django/apps/sysadmin/management/commands/seed_demo.py）——
interface Account { id: number; real_name: string; email: string; staff_no: string; level: string; roles: string[] }
const ACCOUNTS: Record<string, Account> = {
  admin:   { id: 1, real_name: '系统管理员', email: 'admin@eplugger.com',   staff_no: 'A0001', level: 'TOP_SECRET', roles: ['R-ADMIN'] },
  manager: { id: 2, real_name: '科研管理岗', email: 'manager@eplugger.com', staff_no: 'A0002', level: 'SECRET',     roles: ['R-MANAGER', 'R-LEADER'] },
  staff:   { id: 3, real_name: '一线研究员', email: 'staff@eplugger.com',   staff_no: 'A0003', level: 'INTERNAL',   roles: ['R-STAFF'] },
  finance: { id: 4, real_name: '财务专员',   email: 'finance@eplugger.com', staff_no: 'A0004', level: 'SECRET',     roles: ['R-FINANCE'] },
  // 真实后端未建号、mock 额外提供（探索 expert-review / 伦理视图用）：
  leader:  { id: 5, real_name: '单位领导',   email: 'leader@eplugger.com',  staff_no: 'A0005', level: 'SECRET',     roles: ['R-LEADER'] },
  expert:  { id: 6, real_name: '评审专家',   email: 'expert@eplugger.com',  staff_no: 'A0006', level: 'INTERNAL',   roles: ['R-EXPERT'] },
  auditor: { id: 7, real_name: '审计员',     email: 'auditor@eplugger.com', staff_no: 'A0007', level: 'SECRET',     roles: ['R-AUDITOR'] },
  ethics:  { id: 8, real_name: '伦理委员会', email: 'ethics@eplugger.com',  staff_no: 'A0008', level: 'INTERNAL',   roles: ['R-ETHICS'] },
}

// —— 能力集（镜像 policy.csv 铁律：U 管理写仅 admin；auditor 全量只读；业务角色域级读写）——
const W = (acts: string[]) => acts.map((a) => `/api/v1/* ${a}`)
const ROLE_CAPS: Record<string, string[]> = {
  'R-ADMIN': W(['GET', 'POST', 'PUT', 'DELETE']),
  'R-AUDITOR': W(['GET']),
  'R-FINANCE': [
    ...W(['GET']),
    // M1-a（policy.csv:371-403）：财务可发起借款、维护差旅标准、登记发票
    '/api/v1/loans POST', '/api/v1/loans/* POST',
    '/api/v1/travel-standards POST', '/api/v1/travel-standards PUT', '/api/v1/travel-standards DELETE',
    '/api/v1/invoices POST', '/api/v1/invoices/* POST', '/api/v1/invoices/* PUT',
    // M1-b（policy.csv:414-440）：凭证推送、成本池核算发起、决算生成与审批
    '/api/v1/vouchers/sync POST', '/api/v1/vouchers/sync-callback POST',
    '/api/v1/cost-pools POST', '/api/v1/cost-pools/* POST',
    '/api/v1/settlements POST', '/api/v1/settlements/* POST',
    // M1-c（policy.csv:443-458）：拨款管理、合同预检、回单识别、核算开户
    '/api/v1/disbursements POST', '/api/v1/disbursements/*/action POST',
    '/api/v1/disbursements/check-contract POST',
    '/api/v1/incomes/ocr-receipt POST',
    '/api/v1/projects/*/open-account POST',
  ], // 只读为主 + M1-a 经费写（与 policy.csv 同口径）
  'R-ETHICS': W(['GET']),
  'R-EXPERT': [...W(['GET']), '/api/v1/review* POST', '/api/v1/review* PUT',
    // M2-c（policy.csv:911-915）：外部专家自助申请 + 专家门户只读
    '/api/v1/portal/expert-apply POST',
    '/api/v1/portal/expert/credit GET',
    '/api/v1/portal/expert/reviews GET',
    '/api/v1/portal/expert/activities GET',
  ],
  'R-LEADER': [...W(['GET']), '/api/v1/apply/* PUT',
    // M1-b（policy.csv:414-440）：领导可审批决算（approve 由 /settlements/* 通配覆盖）
    '/api/v1/settlements/* POST',
    // M1-c（policy.csv:443-458）：领导只读拨款 + 回单识别 + 核算开户
    '/api/v1/incomes/ocr-receipt POST',
    '/api/v1/projects/*/open-account POST',
    // M2-c（policy.csv:918-919）：领导可看专家信用档案（门户三条属专家本人，不授予领导）
    '/api/v1/experts/*/credit GET',
  ],
  'R-MANAGER': [
    ...W(['GET']),
    '/api/v1/apply/* POST', '/api/v1/apply/* PUT',
    '/api/v1/subjects POST', '/api/v1/subjects PUT',
    '/api/v1/budgets POST', '/api/v1/budgets PUT',
    '/api/v1/projects POST', '/api/v1/procurement/* POST', '/api/v1/asset/* POST',
    // M1-a（policy.csv:371-403）：借款发起/审批、差旅标准维护、发票登记/绑定
    '/api/v1/loans POST', '/api/v1/loans/* POST',
    '/api/v1/travel-standards POST', '/api/v1/travel-standards PUT',
    '/api/v1/invoices POST', '/api/v1/invoices/* POST', '/api/v1/invoices/* PUT',
    // M1-b（policy.csv:414-440）：成本池核算发起（calculate 由 /cost-pools/* 通配覆盖）
    '/api/v1/cost-pools POST', '/api/v1/cost-pools/* POST',
    // M1-c（policy.csv:443-458）：拨款创建/预检、回单识别、核算开户（action 由 R-FINANCE 专属，无行）
    '/api/v1/disbursements POST', '/api/v1/disbursements/check-contract POST',
    '/api/v1/incomes/ocr-receipt POST',
    '/api/v1/projects/*/open-account POST',
    // M2-a（policy.csv:859-862）：外部机构资质审核台
    '/api/v1/partner-orgs GET', '/api/v1/partner-orgs/*/audit POST',
    // —— M2-c：专家申请审核 + 信用档案 ——
    '/api/v1/expert-applications GET',
    '/api/v1/expert-applications/*/audit POST',
    '/api/v1/experts/*/credit GET',
    '/api/v1/portal/supplier/inquiries GET',
  ],
  // M2-a：外部机构用户——仅本机构门户与公开面（镜像 policy.csv R-PARTNER 段）
  'R-PARTNER': [
    '/api/v1/auth/me GET',
    '/api/v1/portal/org GET', '/api/v1/portal/org PUT',
    '/api/v1/portal/home GET',
    '/api/v1/apply/guidelines GET', '/api/v1/apply/guidelines/* GET',
    '/api/v1/notifications GET', '/api/v1/notifications/* POST',
    '/api/v1/notifications/read-all POST',
    '/api/v1/dicts/* GET',
    // —— M2-b：开放课题全流程（镜像 policy.csv M2-b R-PARTNER 段）——
    '/api/v1/apply/guide-suggestions GET', '/api/v1/apply/guide-suggestions POST',
    '/api/v1/apply/applications GET', '/api/v1/apply/applications POST',
    '/api/v1/apply/applications/* GET', '/api/v1/apply/applications/* PUT',
    '/api/v1/apply/applications/* POST',
    '/api/v1/apply/applications/*/sections/* PUT',
    '/api/v1/apply/task-books GET', '/api/v1/apply/task-books/* GET',
    '/api/v1/apply/task-books/* POST',
    '/api/v1/project/*/progress-report GET', '/api/v1/project/*/progress-report POST',
    '/api/v1/project/*/final-accept GET', '/api/v1/project/*/final-accept POST',
    // —— M2-c：专家申请与供应商门户（镜像 policy.csv M2-c 段）——
    '/api/v1/portal/expert-apply POST',
    '/api/v1/portal/supplier/inquiries GET',
    '/api/v1/portal/supplier/inquiries/*:quote POST',
    '/api/v1/portal/supplier/contracts GET',
  ],
  'R-STAFF': [
    ...W(['GET']),
    '/api/v1/apply/* POST', '/api/v1/apply/* PUT',
    '/api/v1/expenses POST', '/api/v1/borrows POST',
  ],
}

// —— 页面可见性矩阵（镜像 seed_demo.PAGE_GRANTS；page_name = 前端路由 name）——
const PAGE_GRANTS: Array<[string, string]> = [
  ['dash', '*'], ['guide', '*'], ['project', '*'],
  ['bigscreen', 'R-LEADER'], ['bigscreen', 'R-FINANCE'], ['bigscreen', 'R-AUDITOR'], ['bigscreen', 'R-ADMIN'],
  ['editor', 'R-STAFF'], ['editor', 'R-MANAGER'], ['editor', 'R-LEADER'],
  ['review', 'R-MANAGER'], ['review', 'R-EXPERT'], ['review', 'R-ETHICS'], ['review', 'R-LEADER'], ['review', 'R-ADMIN'],
  ['projects', 'R-STAFF'], ['projects', 'R-MANAGER'], ['projects', 'R-LEADER'],
  ['expense', 'R-STAFF'], ['expense', 'R-MANAGER'], ['expense', 'R-FINANCE'],
  ['loan', 'R-MANAGER'], ['loan', 'R-FINANCE'], // M1-a A2 借款管理（meta.roles 同口径）
  ['claim', 'R-STAFF'], ['claim', 'R-MANAGER'], ['claim', 'R-LEADER'],
  ['output', 'R-STAFF'], ['output', 'R-MANAGER'], ['output', 'R-LEADER'],
  ['transfer', 'R-MANAGER'], ['transfer', 'R-LEADER'], ['transfer', 'R-ADMIN'],
  ['procurement', 'R-MANAGER'], ['procurement', 'R-FINANCE'], ['procurement', 'R-ADMIN'],
  ['asset', 'R-MANAGER'], ['asset', 'R-FINANCE'], ['asset', 'R-ADMIN'],
  ['portrait', 'R-LEADER'], ['portrait', 'R-MANAGER'], ['portrait', 'R-ADMIN'],
  ['activity', 'R-STAFF'], ['activity', 'R-MANAGER'], ['activity', 'R-LEADER'], ['activity', 'R-AUDITOR'],
  ['performance', 'R-MANAGER'], ['performance', 'R-LEADER'],
  ['performance', 'R-FINANCE'], ['performance', 'R-AUDITOR'],
  ['expert-review', 'R-EXPERT'], ['expert-review', 'R-MANAGER'], ['expert-review', 'R-LEADER'],
  ['expert-review', 'R-AUDITOR'],
  ['archive', 'R-ADMIN'], ['archive', 'R-MANAGER'], ['archive', 'R-AUDITOR'], ['archive', 'R-STAFF'],
  ['admin-users', 'R-ADMIN'], ['admin-roles', 'R-ADMIN'], ['admin-roles', 'R-AUDITOR'],
  ['admin-dicts', 'R-ADMIN'],
  ['funding-config', 'R-MANAGER'], ['funding-config', 'R-FINANCE'],
  // M1-b：成本池核算 + 项目决算（policy.csv:414-440 三角色同口径）
  ['funding-cost-pool', 'R-MANAGER'], ['funding-cost-pool', 'R-FINANCE'], ['funding-cost-pool', 'R-LEADER'],
  ['funding-settle', 'R-MANAGER'], ['funding-settle', 'R-FINANCE'], ['funding-settle', 'R-LEADER'],
  // M1-c：拨款管理 + 到账认领与回单识别（policy.csv:443-458 三角色同口径；
  // import-bank-flow / incomes claim 由 R-MANAGER/R-FINANCE 既有 /incomes/* 通配覆盖，R-LEADER 无）
  ['funding-disburse', 'R-MANAGER'], ['funding-disburse', 'R-FINANCE'], ['funding-disburse', 'R-LEADER'],
  ['funding-income', 'R-MANAGER'], ['funding-income', 'R-FINANCE'], ['funding-income', 'R-LEADER'],
  // M2-a：外部机构门户 + 资质审核台（policy.csv R-PARTNER / R-MANAGER 行同口径）
  ['portal', 'R-PARTNER'],
  ['admin-partner-orgs', 'R-MANAGER'], ['admin-partner-orgs', 'R-ADMIN'],
  // —— M2-b：开放课题全流程页（seed_demo.PAGE_GRANTS 同口径）——
  ['portal-applications', 'R-PARTNER'],
  ['portal-guide-suggest', 'R-PARTNER'],
  ['portal-task-book', 'R-PARTNER'], ['portal-task-book', 'R-MANAGER'], ['portal-task-book', 'R-LEADER'],
  ['portal-project-report', 'R-PARTNER'], ['portal-project-report', 'R-STAFF'], ['portal-project-report', 'R-MANAGER'],
  ['admin-guide-suggestions', 'R-MANAGER'],
  ['admin-expert-applications', 'R-MANAGER'],
  ['portal-expert-apply', 'R-PARTNER'],
  ['portal-expert-apply', 'R-EXPERT'],
  ['portal-expert', 'R-EXPERT'],
  ['portal-supplier', 'R-PARTNER'], ['admin-guide-suggestions', 'R-ADMIN'],
]

function usernameFromToken(token: string): string {
  return token.startsWith('mock-') ? token.slice('mock-'.length) : ''
}

export const overrides: Record<string, unknown> = {
  'POST /auth/login': (_url: string, ctx: OverrideCtx) => {
    const b = ctx.body as Record<string, unknown> | null
    const username = (typeof b?.username === 'string' && b.username) || 'staff'
    return { access_token: `mock-${username}`, token_type: 'Bearer', expires_in: 86400 }
  },

  'GET /auth/me': (_url: string, ctx: OverrideCtx) => {
    const token = (ctx.headers['authorization'] || '').replace(/^Bearer\s+/i, '')
    const name = usernameFromToken(token) || 'staff'
    const acc = ACCOUNTS[name] ?? ACCOUNTS.staff
    const caps = new Set<string>()
    for (const r of acc.roles) for (const c of ROLE_CAPS[r] ?? []) caps.add(c)
    return {
      user: {
        id: acc.id,
        username: name,
        real_name: acc.real_name,
        email: acc.email,
        staff_no: acc.staff_no,
        security_level: acc.level,
        status: 'ACTIVE',
      },
      roles: acc.roles,
      caps: [...caps],
    }
  },

  // 静态矩阵：页面可见性与真实后端种子一致（RBAC 演示同口径）。
  // 双键注册：前端 U 契约 yaml 是旧版（无 /page-grants）→ matchRoute 不命中 →
  // 走 cleanPath 键 '/page-grants'；若后续同步了契约 → 走 op 键 'GET /page-grants'。
  '/page-grants': { grants: PAGE_GRANTS.map(([page_name, role_code]) => ({ page_name, role_code })) },
  'GET /page-grants': { grants: PAGE_GRANTS.map(([page_name, role_code]) => ({ page_name, role_code })) },
}
