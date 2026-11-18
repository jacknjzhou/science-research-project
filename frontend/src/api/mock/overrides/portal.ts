/**
 * Curated overrides · 机构注册 / 门户 / 资质审核（M2-a C1）
 * 真实契约：12-用户与权限-U.openapi.yaml（6 路径，全 snake_case）
 *   POST /portal/register（公开）、GET|PUT /portal/org、GET /portal/home、
 *   GET /partner-orgs、POST /partner-orgs/{id}/audit
 */

interface MockOrg {
  id: number
  code: string
  tenant_id: number
  name: string
  short_name: string | null
  credit_code: string
  org_type: string
  contact_name: string
  contact_phone: string
  contact_email: string
  address: string | null
  status: string
  audit_user_id: number | null
  audited_at: string | null
  reject_reason: string | null
  created_at: string
}

const ORGS: MockOrg[] = [
  {
    id: 1, code: 'PTN-2026-000001', tenant_id: 1, name: '合作示例大学',
    short_name: '示例大', credit_code: '91310000MA1K3XY12A', org_type: 'UNIVERSITY',
    contact_name: '张联系', contact_phone: '13800000001', contact_email: 'partner@example.edu.cn',
    address: '上海市杨浦区示例路 1 号', status: 'APPROVED', audit_user_id: 2,
    audited_at: '2026-11-01T02:00:00Z', reject_reason: null, created_at: '2026-10-28T02:00:00Z',
  },
  {
    id: 2, code: 'PTN-2026-000002', tenant_id: 1, name: '待审核协作单位',
    short_name: null, credit_code: '91110000MA2C4AB34B', org_type: 'COLLAB',
    contact_name: '李经办', contact_phone: '13800000002', contact_email: 'pending@example.com',
    address: null, status: 'PENDING', audit_user_id: null,
    audited_at: null, reject_reason: null, created_at: '2026-11-17T06:00:00Z',
  },
]

const HOME = {
  org: ORGS[0],
  announcements: [
    {
      id: 9001, typ: 'ANNOUNCE', title: '机构资质审核通过',
      content: '贵单位资质已通过审核，账号已激活，可查看本单位相关数据与申报指南。',
      created_at: '2026-11-01T02:00:00Z',
    },
    {
      id: 9002, typ: 'ANNOUNCE', title: '2026 年度开放课题征集启动',
      content: '本年度开放课题指南已发布，请在申报期内在线填报。',
      created_at: '2026-11-10T01:00:00Z',
    },
  ],
  guidelines: [
    {
      id: 3003, title: '启元研究院 2026 年度「探索者计划」自立项目（第三批）',
      project_type: 'ZIGE', apply_start_at: '2026-09-20T00:00:00Z',
      apply_end_at: '2026-12-18T00:00:00Z', publish_at: '2026-09-18T00:00:00Z',
    },
    {
      id: 3001, title: '2027 年度国家自然科学基金 · 面上项目 / 青年科学基金',
      project_type: 'NSFC', apply_start_at: '2026-09-01T00:00:00Z',
      apply_end_at: '2026-12-25T00:00:00Z', publish_at: '2026-08-30T00:00:00Z',
    },
  ],
  todos: { unread_notifications: 2 },
}

function idOf(url: string): number {
  const m = url.match(/partner-orgs\/(\d+)/)
  return Number(m?.[1] || 0)
}

export const overrides: Record<string, unknown> = {
  // 注册：返回新建的 PENDING 机构（mock 不回写 ORGS，避免污染演示数据）
  'POST /portal/register': ((_url: string, ctx: { body: unknown }) => {
    const b = (ctx.body || {}) as Record<string, any>
    return {
      ...ORGS[1],
      id: 99,
      code: 'PTN-2026-000099',
      name: b.name || '新注册机构',
      short_name: b.short_name ?? null,
      credit_code: b.credit_code || '91310000MA1K3XY99Z',
      org_type: b.org_type || 'COLLAB',
      contact_name: b.contact_name || '—',
      contact_phone: b.contact_phone || null,
      contact_email: b.contact_email || null,
      status: 'PENDING',
      created_at: new Date().toISOString(),
    }
  }) as unknown,

  'GET /portal/home': HOME,

  'GET /portal/org': ORGS[0],

  'PUT /portal/org': ((_url: string, ctx: { body: unknown }) => {
    const b = (ctx.body || {}) as Record<string, any>
    // 只接受四个联系字段（镜像后端白名单）
    for (const k of ['contact_name', 'contact_phone', 'contact_email', 'address']) {
      if (b[k] !== undefined) (ORGS[0] as any)[k] = b[k]
    }
    return ORGS[0]
  }) as unknown,

  'GET /partner-orgs': {
    list: ORGS,
    total: ORGS.length,
    page: 1,
    size: 20,
  },

  'POST /partner-orgs/{id}/audit': ((url: string, ctx: { body: unknown }) => {
    const id = idOf(url)
    const o = ORGS.find((x) => x.id === id) || ORGS[1]
    const b = (ctx.body || {}) as Record<string, any>
    if (b.action === 'APPROVE') {
      o.status = 'APPROVED'
      o.audit_user_id = 2
      o.audited_at = new Date().toISOString()
      o.reject_reason = null
    } else if (b.action === 'REJECT') {
      o.status = 'REJECTED'
      o.audit_user_id = 2
      o.audited_at = new Date().toISOString()
      o.reject_reason = b.reason || '资质不符'
    }
    return o
  }) as unknown,
}
