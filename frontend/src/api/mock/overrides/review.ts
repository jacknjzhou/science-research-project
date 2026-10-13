/**
 * Curated overrides · 评审工作台（View V4）
 * 命中真实契约路径：
 *   GET  /apply/review/mytasks     → PageResult<ReviewTask>（专家视角，匿名化）
 *   POST /apply/ai/review-draft    → AiReviewDraftResult（AI 起草评审意见）
 * ReviewTask 契约字段之外，补充前端匿名正文展示所需的 doc / dims / load 语义字段
 * （generator 兜底时缺失，视图全部走可选链，绝不崩溃）。
 */

const TASK = {
  id: 7001,
  application_id: 5001,
  expert_user_id: 9,
  review_round: 1,
  dispatch_mode: 'AI',
  anonymous_view: true,
  conflict_flag: false,
  status: 'SCORING',
  score_total: null,
  score_detail: [] as unknown[],
  comment_text: '',
  ai_opinion_draft: null,
  deadline_at: '2026-10-20T17:00:00Z',
  submitted_at: null,
  load: '3/5',
  dims: ['创新性', '科学问题', '研究方案', '研究基础'],
  doc: {
    code: 'MS-2026-1187',
    apply_code: 'E0513-04',
    title: '基于生成式模型的多轴机床颤振主动抑制研究',
    sections: [
      {
        no: '§1', h: '立项依据',
        text: '颤振是限制切削效率的首要因素。现有传递函数在线辨识方法在变参数工况下收敛慢……申请人前期在本单位搭建了半物理仿真平台，具备研究基础。',
      },
      {
        no: '§2', h: '研究内容与技术路线',
        text: '拟提出「生成先验 + 在线微调」双阶段颤振预测框架：以扩散模型构建稳定性叶片的概率先验…技术路线见图 3（附仿真验证矩阵与考核指标：临界切深提升 ≥ 25%）。',
      },
    ],
    attachments: '报告正文.pdf（32 页）· 代表性论文 5 篇 · 基金委格式审查通过',
    dup: {
      similarity: '23.6%',
      text: '§2.3 与 2024 年某在研项目文本相似度 23.6%（重点段落 2.3.2「…概率叶片构建…」相似度 61%）。',
    },
  },
}

const AI_REVIEW_RESULT = {
  overall: '本项目面向多轴机床颤振主动抑制，选题紧扣高端制造共性瓶颈，科学意义与工程应用前景兼具，总体达到面上项目资助水平。',
  strengths: '创新性：将扩散模型引入稳定性叶片的概率先验构建，思路新颖；「生成先验 + 在线微调」双阶段框架逻辑清晰；考核指标（临界切深提升 ≥ 25%）明确可验证。',
  weaknesses: '科学问题凝练稍显宽泛；变参数工况下在线辨识收敛性的理论保证论证不足；§2.3 与在研项目存在一定文本相似，需强化差异化表述。',
  suggestions: '建议补充在线辨识收敛性分析，明确与已有阻抗控制方法的对比实验设计，并对查重高亮段落做实质性改写与引用标注。',
  adopted: false,
}

export const overrides: Record<string, unknown> = {
  'GET /apply/review/mytasks': { list: [TASK], total: 1, page: 1, size: 20 },
  'POST /apply/ai/review-draft': AI_REVIEW_RESULT,
}
