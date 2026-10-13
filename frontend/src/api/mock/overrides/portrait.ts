/**
 * Curated overrides — PI 画像（module S）
 * 英雄学者：周明远（staff_id 90001）。键用模板路径，函数入参为完整请求 URL。
 * 字段名对齐 Staff / PortraitDetail(Portrait+RadarDimension) / CollabGraph（snake_case）。
 */

function staff(_url: string) {
  return {
    id: 90001, code: 'EMP-2016-0142', tenant_id: 1, status: 'ACTIVE', user_id: 90001,
    hr_code: '10086', name: '周明远', name_en: 'Zhou Mingyuan', gender: 'MALE', birth_year: 1978,
    email: 'zhou.my@lab.edu.cn', phone: '138****1234', department_id: 10,
    staff_type: 'FORMAL', position: 'RESEARCHER', title: '研究员 / 博导', education: '博士',
    hire_date: '2016-09-01', employment_status: 'ONBOARD',
    orcid: '0000-0002-1825-4471', wos_researcher_id: 'A-7788-2019', scopus_id: '56081234567',
    bio: '聚焦机器人化精密制造方向，主持国家重点研发计划、国自然面上等多项课题。',
    research_expertise: [{ tag: '机器人精密制造' }, { tag: '力位混合控制' }, { tag: '拓扑优化' }],
    is_pi: true, legal_entity_id: 1, security_level: 'INTERNAL',
  }
}

function portrait(_url: string) {
  return {
    latest: {
      staff_id: 90001, snapshot_date: '2026-10-12',
      project_count_total: 6, project_count_active: 4,
      funding_total: 13940000, funding_yearly: 4120000,
      output_count_papers: 41, output_count_patents: 11,
      h_index: 18, total_citations: 1860,
      top_journals: [{ name: 'RCIM Q1', count: 6 }, { name: '机械工程学报', count: 5 }],
      expertise_tags: [{ tag: '机器人精密制造' }, { tag: '智能磨抛' }, { tag: '数字孪生' }],
      collaboration_score: 0.86, mentoring_count: 7,
      career_stage: 'MATURE',
      ai_summary:
        '成熟期学者，方向聚焦机器人化精密制造；与多位校内外及企业伙伴长期合作，近 3 年引用稳步增长；承担国自然面上等在研课题，累计经费规模可观；获授权发明若干件，其中部分已实现许可转化。',
      integrity_flag: false,
    },
    radar: [
      { dimension: 'PROJECT', value: 6, normalized: 0.9 },
      { dimension: 'FUNDING', value: 1394, normalized: 0.82 },
      { dimension: 'OUTPUT', value: 41, normalized: 0.78 },
      { dimension: 'IMPACT', value: 18, normalized: 0.72 },
      { dimension: 'MENTORING', value: 7, normalized: 0.8 },
      { dimension: 'COLLAB', value: 0.86, normalized: 0.88 },
    ],
    timeline: [
      { year: 2026, type: 'OUTPUT', title: '论文《Diffusion-guided topo optimization》发表于 RCIM Q1' },
      { year: 2025, type: 'PROJECT', title: '主持国自然面上项目《机器人柔性抓取感知机制》立项' },
      { year: 2024, type: 'TALENT', title: '入选省级人才计划，团队梯队 2 博后 / 3 博 / 4 硕' },
      { year: 2023, type: 'OUTPUT', title: '授权发明「一种自适应减振结构」进入可转化池' },
    ],
    top_outputs: [
      { title: 'Adaptive polishing of freeform surfaces via diffusion priors', type: '论文', venue: 'RCIM Q1' },
      { title: '曲率时变的力位混合鲁棒控制', type: '论文', venue: '机械工程学报' },
      { title: '一种自适应磨抛末端执行器', type: '专利', venue: '已授权' },
      { title: '《复杂曲面机器人磨抛工艺规范》团标', type: '标准', venue: '发布' },
    ],
  }
}

function collabGraph(_url: string) {
  return {
    snapshot_date: '2026-10-12', center_staff_id: 90001,
    nodes: [
      { staff_id: 90001, name: '周', institution: '先进制造研究所', node_size: 42, community_id: 1, centrality: 0.92 },
      { staff_id: 90002, name: '李', institution: '智能机器人实验室', node_size: 18, community_id: 1, centrality: 0.41 },
      { staff_id: 90003, name: '王', institution: '某装备制造集团', node_size: 22, community_id: 2, centrality: 0.55 },
      { staff_id: 90004, name: '赵', institution: '某高校', node_size: 14, community_id: 2, centrality: 0.33 },
      { staff_id: 90005, name: '某企业', institution: '中科智能', node_size: 12, community_id: 3, centrality: 0.28 },
      { staff_id: 90006, name: '跨机构', institution: '中科院某所', node_size: 10, community_id: 3, centrality: 0.22 },
    ],
    edges: [
      { staff_a_id: 90001, staff_b_id: 90002, weight: 14, first_year: 2017, last_year: 2026 },
      { staff_a_id: 90001, staff_b_id: 90003, weight: 11, first_year: 2019, last_year: 2026 },
      { staff_a_id: 90001, staff_b_id: 90004, weight: 6, first_year: 2020, last_year: 2025 },
      { staff_a_id: 90001, staff_b_id: 90005, weight: 4, first_year: 2022, last_year: 2026 },
      { staff_a_id: 90001, staff_b_id: 90006, weight: 3, first_year: 2021, last_year: 2024 },
      { staff_a_id: 90002, staff_b_id: 90004, weight: 5, first_year: 2021, last_year: 2025 },
      { staff_a_id: 90003, staff_b_id: 90005, weight: 4, first_year: 2022, last_year: 2026 },
    ],
  }
}

export const overrides: Record<string, unknown> = {
  'GET /staff/{id}': staff,
  'GET /staff/{id}/portrait': portrait,
  'GET /staff/{id}/collab-graph': collabGraph,
}
