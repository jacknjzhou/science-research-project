/**
 * Curated overrides：为"英雄屏"提供贴合原型语义的拟真数据。
 * 未命中的接口仍由 generator 按 schema 现场造数——保证契约驱动 + 关键屏观感兼得。
 * 键：`METHOD /模板路径`（经 matchRoute 命中）或 `/去前缀请求路径`。
 * 值：静态对象，或 (url)=>data 的函数（用于 {code} 之类模板按参数分派）。
 */

// —— 工作台 KPI：走真实契约 GET /dash/metrics/{code}，按 code 返回不同 MetricValue ——
const metricByCode: Record<string, { name: string; unit: string; value: number }> = {
  in_research_projects: { name: '在研项目', unit: '项', value: 8 },
  available_funding: { name: '可支经费', unit: '万元', value: 312 },
  yearly_outputs: { name: '本年度成果', unit: '项', value: 23 },
  pending_applications: { name: '待办申报', unit: '项', value: 2 },
  pending_reviews: { name: '待评审', unit: '份', value: 3 },
}

function metricValue(url: string) {
  const code = decodeURIComponent(url.split('/metrics/')[1]?.split('?')[0] || '')
  const m = metricByCode[code] || { name: code, unit: '', value: 0 }
  return {
    code,
    name: m.name,
    unit: m.unit,
    version: 3,
    value: m.value,
    dims: { scope: 'PI:周明远' },
    data_as_of: '2026-10-12',
    dq_flag: 'OK',
    drill_available: true,
  }
}

export const overrides: Record<string, unknown> = {
  'GET /dash/metrics/{code}': metricValue,

  // 项目健康度分布（下钻样例，供驾驶舱 hbar）
  'GET /dash/report/instance/{id}/drill': {
    instance_id: 9001,
    level: 'ADS',
    parent_ref: 'PI:周明远',
    columns: [
      { name: 'health', label: '健康度' },
      { name: 'count', label: '项目数' },
    ],
    rows: [
      { health: '健康', count: 5 },
      { health: '关注', count: 2 },
      { health: '风险', count: 1 },
    ],
    next_level: 'DWS',
    masked: false,
  },

  // 近 6 月经费支出趋势（用趋势预测端点契约承载 sparkline 数据）
  'GET /dash/forecast': {
    list: [
      { target_metric: 'monthly_expense', predicted_value: 42, confidence_interval: { lower: 38, upper: 46, level: 0.9 }, model_type: 'PROPHET', forecast_date: '2026-05-01', generated_at: '2026-10-13T00:00:00Z' },
      { target_metric: 'monthly_expense', predicted_value: 55, confidence_interval: { lower: 50, upper: 60, level: 0.9 }, model_type: 'PROPHET', forecast_date: '2026-06-01', generated_at: '2026-10-13T00:00:00Z' },
      { target_metric: 'monthly_expense', predicted_value: 35, confidence_interval: { lower: 31, upper: 39, level: 0.9 }, model_type: 'PROPHET', forecast_date: '2026-07-01', generated_at: '2026-10-13T00:00:00Z' },
      { target_metric: 'monthly_expense', predicted_value: 70, confidence_interval: { lower: 63, upper: 77, level: 0.9 }, model_type: 'PROPHET', forecast_date: '2026-08-01', generated_at: '2026-10-13T00:00:00Z' },
      { target_metric: 'monthly_expense', predicted_value: 62, confidence_interval: { lower: 56, upper: 68, level: 0.9 }, model_type: 'PROPHET', forecast_date: '2026-09-01', generated_at: '2026-10-13T00:00:00Z' },
      { target_metric: 'monthly_expense', predicted_value: 88, confidence_interval: { lower: 80, upper: 96, level: 0.9 }, model_type: 'PROPHET', forecast_date: '2026-10-01', generated_at: '2026-10-13T00:00:00Z' },
    ],
  },
}
