/**
 * Curated overrides · 专家与评审管理（module N）
 * 命中真实契约路径（键 = "METHOD /模板路径"，值 = ApiResponse.data）：
 *   GET /experts              → PageResult<Expert>   （mapper.go ToAPIExpert）
 *   GET /reviews              → PageResult<ReviewTask>（mapper.go ToAPIReviewTask）
 *   GET /reviews/{id}/detail  → { task, invitations, scores }（ToAPIReviewTask/ToAPIInvitation/ToAPIScore）
 * 字段名严格对齐后端 mapper snake_case；NUMERIC（total_score）以定标字符串承载，视图侧走 toNum。
 * typed list 结构对齐契约 PageResult：{ list, total, page, size }。
 */

const EXPERTS = [
  {
    id: 8101, code: 'EXR-2025-0001', tenant_id: 1, status: 'ACTIVE', name: '周明远',
    gender: 'M', title: '研究员 · 博导', org_name: '启元研究院', user_id: 90001, source: 'INTERNAL',
    field_tags: ['智能制造', '振动噪声', '高端装备'], expertise_level: 'EXPERT',
    avoid_orgs: ['某同业研究院'], avoid_person_ids: [], security_level: 'INTERNAL',
    last_review_at: '2026-05-12T08:00:00Z', review_count: 14,
    created_at: '2024-01-10T02:00:00Z', updated_at: '2026-06-01T02:00:00Z',
  },
  {
    id: 8102, code: 'EXR-2025-0002', tenant_id: 1, status: 'ACTIVE', name: '李慧敏',
    gender: 'F', title: '教授', org_name: '北方理工大学', user_id: null, source: 'EXTERNAL',
    field_tags: ['材料科学', '焊接工艺'], expertise_level: 'SENIOR',
    avoid_orgs: [], avoid_person_ids: [8101], security_level: 'PUBLIC',
    last_review_at: '2026-06-20T08:00:00Z', review_count: 9,
    created_at: '2024-03-05T02:00:00Z', updated_at: '2026-06-21T02:00:00Z',
  },
  {
    id: 8103, code: 'EXR-2025-0003', tenant_id: 1, status: 'CANDIDATE', name: '陈立群',
    gender: 'M', title: '高级工程师', org_name: '中机集团技术中心', user_id: null, source: 'EXTERNAL',
    field_tags: ['数字孪生', '装配质量'], expertise_level: 'JUNIOR',
    avoid_orgs: ['启元研究院'], avoid_person_ids: [], security_level: 'INTERNAL',
    last_review_at: null, review_count: 0,
    created_at: '2026-05-18T02:00:00Z', updated_at: '2026-05-18T02:00:00Z',
  },
  {
    id: 8104, code: 'EXR-2025-0004', tenant_id: 1, status: 'SUSPENDED', name: '王振国',
    gender: 'M', title: '研究员', org_name: '华东所', user_id: null, source: 'INTERNAL',
    field_tags: ['经费审计', '科研诚信'], expertise_level: 'EXPERT',
    avoid_orgs: [], avoid_person_ids: [], security_level: 'SECRET',
    last_review_at: '2025-11-02T08:00:00Z', review_count: 22,
    created_at: '2023-09-01T02:00:00Z', updated_at: '2026-02-10T02:00:00Z',
  },
  {
    id: 8105, code: 'EXR-2025-0005', tenant_id: 1, status: 'ACTIVE', name: '赵敏',
    gender: 'F', title: '副研究员', org_name: '启元研究院', user_id: 90077, source: 'INTERNAL',
    field_tags: ['无损检测', '电磁超声'], expertise_level: 'SENIOR',
    avoid_orgs: [], avoid_person_ids: [], security_level: 'PUBLIC',
    last_review_at: '2026-07-03T08:00:00Z', review_count: 6,
    created_at: '2025-01-20T02:00:00Z', updated_at: '2026-07-03T02:00:00Z',
  },
]

const REVIEWS = [
  {
    id: 8201, code: 'RVW-2026-0007', tenant_id: 1, biz_type: 'MID_CHECK',
    target_type: 'PROJECT', target_id: 90001, project_id: 90001,
    title: '国家重点研发计划 · 复杂曲面磨抛 · 中期检查', review_method: 'COMBINATION', plan_count: 3,
    draw_rule: { min_experts: 3, avoid_same_org: true, senior_ratio: 0.6 }, status: 'IN_REVIEW',
    conclusion: null, score_summary: null, security_level: 'INTERNAL',
    drawn_at: '2026-07-01T02:00:00Z', started_at: '2026-07-05T02:00:00Z', concluded_at: null,
    created_at: '2026-06-28T02:00:00Z', updated_at: '2026-07-05T02:00:00Z',
  },
  {
    id: 8202, code: 'RVW-2026-0008', tenant_id: 1, biz_type: 'FINAL_ACCEPT',
    target_type: 'PROJECT', target_id: 90006, project_id: 90006,
    title: '薄壁件低应力制造机理 · 结题验收评审', review_method: 'RANDOM', plan_count: 5,
    draw_rule: { min_experts: 5 }, status: 'DRAFT',
    conclusion: null, score_summary: null, security_level: 'PUBLIC',
    drawn_at: null, started_at: null, concluded_at: null,
    created_at: '2026-07-10T02:00:00Z', updated_at: '2026-07-10T02:00:00Z',
  },
  {
    id: 8203, code: 'RVW-2026-0009', tenant_id: 1, biz_type: 'OUTPUT_EVAL',
    target_type: 'OUTPUT', target_id: 4201, project_id: null,
    title: '2026 年度高水平成果评价（论文 + 专利）', review_method: 'MANUAL', plan_count: 3,
    draw_rule: { manual_ids: [8101, 8102, 8105] }, status: 'CONCLUDED',
    conclusion: 'PASS', score_summary: { avg: '86.33', max: '92.00', min: '78.00' }, security_level: 'PUBLIC',
    drawn_at: '2026-06-10T02:00:00Z', started_at: '2026-06-12T02:00:00Z', concluded_at: '2026-06-30T02:00:00Z',
    created_at: '2026-06-08T02:00:00Z', updated_at: '2026-06-30T02:00:00Z',
  },
  {
    id: 8204, code: 'RVW-2026-0010', tenant_id: 1, biz_type: 'PROJECT_APPLY',
    target_type: 'APPLICATION', target_id: 5001, project_id: null,
    title: '2026 院所自立项目申报评审', review_method: 'RANDOM', plan_count: 3,
    draw_rule: { min_experts: 3 }, status: 'DRAWN',
    conclusion: null, score_summary: null, security_level: 'INTERNAL',
    drawn_at: '2026-07-12T02:00:00Z', started_at: null, concluded_at: null,
    created_at: '2026-07-11T02:00:00Z', updated_at: '2026-07-12T02:00:00Z',
  },
]

// GET /reviews/{id}/detail 演示：以 8201（IN_REVIEW）为主体，含名单 + 打分。
const DETAIL_8201 = {
  task: REVIEWS[0],
  invitations: [
    { id: 9001, task_id: 8201, expert_id: 8101, expert_name: '周明远', seat_no: 1, avoid_hit: false, response: 'ACCEPT' },
    { id: 9002, task_id: 8201, expert_id: 8102, expert_name: '李慧敏', seat_no: 2, avoid_hit: false, response: 'ACCEPT' },
    { id: 9003, task_id: 8201, expert_id: 8105, expert_name: '赵敏', seat_no: 3, avoid_hit: false, response: 'PENDING' },
    { id: 9004, task_id: 8201, expert_id: 8104, expert_name: '王振国', seat_no: 4, avoid_hit: true, response: 'DECLINE' },
  ],
  scores: [
    {
      id: 9101, task_id: 8201, expert_id: 8101, target_type: 'PROJECT', target_id: 90001,
      dimension_scores: [
        { dimension: '创新性', score: '92.00', weight: '0.3' },
        { dimension: '研究方案', score: '86.00', weight: '0.4' },
        { dimension: '研究基础', score: '88.00', weight: '0.3' },
      ],
      total_score: '88.40', comment: '技术路线清晰，考核指标可验证；建议补充在线辨识收敛性论证。', status: 'SUBMITTED',
    },
    {
      id: 9102, task_id: 8201, expert_id: 8102, target_type: 'PROJECT', target_id: 90001,
      dimension_scores: [
        { dimension: '创新性', score: '80.00', weight: '0.3' },
        { dimension: '研究方案', score: '82.00', weight: '0.4' },
        { dimension: '研究基础', score: '85.00', weight: '0.3' },
      ],
      total_score: '82.30', comment: '经费执行偏慢，注意剩余周期。', status: 'SUBMITTED',
    },
  ],
}

export const overrides: Record<string, unknown> = {
  'GET /experts': { list: EXPERTS, total: EXPERTS.length, page: 1, size: 20 },
  'GET /reviews': { list: REVIEWS, total: REVIEWS.length, page: 1, size: 20 },
  'GET /reviews/{id}/detail': DETAIL_8201,
  // 演示态 POST（返回契约合规结构；视图动作后统一 reload 详情，此处仅保证 mock 下不报空）。
  'POST /reviews/{id}/draw': { drawn: [8101, 8102, 8105], count: 3 },
  'POST /reviews/{id}/conclude': REVIEWS[2],
  'POST /reviews/{id}/fees': { generated: 2 },
}
