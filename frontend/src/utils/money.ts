/**
 * 金额 / 数值解析工具：兼容契约以 string 承载的 NUMERIC(18,2) 精度。
 * 后端与 mock 都可能把金额发成字符串（如 "6800000.00"、"¥1,234.50"、"12 万"），
 * 直接 Number() 会得到 NaN。这里统一做「清洗 → 解析 → 兜底 0」，避免视图层出现 ¥NaN万。
 */

/** 把任意输入稳健地转成有限数字；无法解析时返回 0（绝不返回 NaN）。 */
export function toNum(v?: string | number | null | undefined): number {
  if (v == null) return 0
  if (typeof v === 'number') return Number.isFinite(v) ? v : 0
  const s = String(v).trim()
  if (!s) return 0
  // 去掉货币符号、千分位逗号、空格、以及常见单位后缀；保留数字/小数点/正负号
  const cleaned = s.replace(/[¥￥$,\s]/g, '').replace(/(元|万元|万|分|CNY|RMB)$/i, '')
  const n = Number.parseFloat(cleaned)
  if (!Number.isFinite(n)) return 0
  // 「万 / 万元」单位内嵌时（如 "12万"）上面的正则只剥离了后缀，未乘回 1e4：
  // 单独识别一次带万单位的写法。
  if (/(万元|万)$/.test(s)) return n * 10000
  return n
}

/** 金额折算成「万元」并四舍五入为整数（用于 ¥xx万 展示）。 */
export function toWan(v?: string | number | null | undefined): number {
  return Math.round(toNum(v) / 10000)
}

/** 比率（0~1 的小数字符串或数字）转百分比整数。 */
export function toPct(v?: string | number | null | undefined): number {
  return Math.round(toNum(v) * 100)
}

/** 保留精度的金额字符串：千分位 + 固定两位小数，输入是字符串也不丢精度位。 */
export function fmtMoney(v?: string | number | null | undefined, digits = 2): string {
  return toNum(v).toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}
