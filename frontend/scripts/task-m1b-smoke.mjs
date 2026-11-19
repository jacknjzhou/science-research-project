// Task M1-b headless smoke: /funding/cost-pool, /funding/settle, expense voucher-sync panel.
// Contract assertions (design/03-科研经费管理-F.openapi.yaml): money fields are strings, camelCase keys.
// Mirror of task11-smoke.mjs (login → navigate → locator count → fetch shape checks).
// 支持两种模式：默认 mock（VITE_USE_MOCK 未关，任意密码放行）；
//   SMOKE_REAL=1 时走真实后端（本地 :8787，finance 账号有 M1-b 全部写权）。
// 注意：page.evaluate 内无法引用外部变量，探针统一从 localStorage(ark_token) 取 token 带 Authorization。
import { chromium } from 'playwright'

// E-8：脚本不内置演示口令——口令由部署方通过 ARK_SEED_PASSWORD 指定。
const smokePwd = (who) => {
  const pwd = process.env.ARK_SMOKE_PASSWORD;
  if (!pwd) {
    console.error('缺少 ARK_SMOKE_PASSWORD（演示账号口令由部署方指定，脚本不内置）');
    process.exit(1);
  }
  return pwd;
};

const BASE = 'http://localhost:5199'
const REAL = process.env.SMOKE_REAL === '1'
const LOGIN_USER = REAL ? 'finance' : 'manager'
const LOGIN_PASS = REAL ? smokePwd('finance') : smokePwd('manager')
const results = []
const ok = (name, cond, extra = '') => { results.push(`${cond ? 'PASS' : 'FAIL'} ${name}${extra ? ' — ' + extra : ''}`) }

const browser = await chromium.launch({
  // 本机 playwright 1.38 缺 chromium-1080；复用缓存里新版 Chrome for Testing（协议兼容）
  executablePath: `${process.env.HOME}/Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`,
})
const page = await browser.newPage()
page.on('pageerror', (e) => results.push(`PAGEERROR ${e.message.slice(0, 160)}`))

// 1) login (mock: any password 放行, manager = R-MANAGER; real: finance = R-FINANCE)
// 真实后端首登偶发 409（幂等中间件 40909，锁未获取——预置设施行为，非本任务改动）；重试一次。
await page.goto(`${BASE}/#/dash?needLogin=1`, { waitUntil: 'networkidle' })
await page.fill('#loginScreen input[placeholder="请输入登录账号"]', LOGIN_USER)
await page.fill('#loginScreen input[type="password"]', LOGIN_PASS)
await page.click('#loginScreen .login-btn')
await page.waitForTimeout(1500)
if (await page.locator('#loginScreen.on').count()) {
  await page.click('#loginScreen .login-btn')
  await page.waitForTimeout(1500)
}
ok(`login ${LOGIN_USER}`, !(await page.locator('#loginScreen.on').count()))

// 2) /funding/cost-pool: page renders + GET /cost-pools shape (money=string, indirectAlloc array)
await page.goto(`${BASE}/#/funding/cost-pool`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)
const poolRendered = await page.locator('#v-cost-pool').count()
ok('cost-pool view rendered', poolRendered >= 1, `count=${poolRendered}`)
const calcBtn = await page.locator('#v-cost-pool button:has-text("全成本核算")').count()
ok('cost-pool calculate button visible (manager)', calcBtn >= 1, `count=${calcBtn}`)
const poolShape = await page.evaluate(async () => {
  const t = localStorage.getItem('ark_token') || ''
  const H = { 'Content-Type': 'application/json' }
  if (t) H['Authorization'] = 'Bearer ' + t
  const res = await fetch('/api/v1/cost-pools?size=5', { headers: H })
  const text = await res.text()
  let r = null
  try { r = JSON.parse(text) } catch { return `RAW status=${res.status} body=${text.slice(0, 120)}` }
  const first = r?.data?.list?.[0] || null
  if (!first) return `EMPTY status=${res.status} code=${r?.code} body=${text.slice(0, 120)}`
  const moneyOk = ['directCost', 'fullCost'].every((k) => typeof first[k] === 'string')
  const keysOk = ['projectId', 'period', 'status', 'indirectAlloc'].every((k) => k in first)
  const allocOk = !Array.isArray(first.indirectAlloc) || first.indirectAlloc.every((a) => 'type' in a && 'basis' in a && typeof a.amount === 'string')
  return `keys=${keysOk} moneyString=${moneyOk} allocShape=${allocOk} status=${first.status}`
})
ok('cost-pool contract shape', String(poolShape).includes('keys=true') && String(poolShape).includes('moneyString=true') && String(poolShape).includes('allocShape=true'), String(poolShape))

// calculate 幂等 POST：契约返回 CostPool 形状（directCost/fullCost Money-string）
const calcShape = await page.evaluate(async () => {
  const t = localStorage.getItem('ark_token') || ''
  const H = { 'Content-Type': 'application/json' }
  if (t) H['Authorization'] = 'Bearer ' + t
  const res = await fetch('/api/v1/cost-pools/calculate', { method: 'POST', headers: H, body: JSON.stringify({ projectId: 1, period: '202611' }) })
  const text = await res.text()
  let r = null
  try { r = JSON.parse(text) } catch { return `RAW status=${res.status} body=${text.slice(0, 120)}` }
  const d = r?.data ?? {}
  const keysOk = ['directCost', 'fullCost', 'status', 'indirectAlloc'].every((k) => k in d)
  const moneyOk = typeof d.directCost === 'string' && typeof d.fullCost === 'string'
  return `keys=${keysOk} moneyString=${moneyOk} status=${d.status}`
})
ok('cost-pools/calculate POST shape', String(calcShape).includes('keys=true') && String(calcShape).includes('moneyString=true'), String(calcShape))

// 3) /funding/settle: page renders + POST /settlements shape (incomeTotal/expenseTotal/remaining string)
//    真实后端：决算单可能已存在（幂等返回既有单）；mock：生成器出形状。
await page.goto(`${BASE}/#/funding/settle`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)
const settleRendered = await page.locator('#v-funding-settle').count()
ok('settle view rendered', settleRendered >= 1, `count=${settleRendered}`)
const settleShape = await page.evaluate(async () => {
  const t = localStorage.getItem('ark_token') || ''
  const H = { 'Content-Type': 'application/json' }
  if (t) H['Authorization'] = 'Bearer ' + t
  const res = await fetch('/api/v1/settlements', { method: 'POST', headers: H, body: JSON.stringify({ projectId: 1, closingDate: '2026-11-17' }) })
  const text = await res.text()
  let r = null
  try { r = JSON.parse(text) } catch { return `RAW status=${res.status} body=${text.slice(0, 120)}` }
  const d = r?.data ?? null
  if (!d) return `EMPTY status=${res.status} code=${r?.code} msg=${r?.message} body=${text.slice(0, 120)}`
  const moneyOk = ['incomeTotal', 'expenseTotal', 'remaining'].every((k) => typeof d[k] === 'string')
  const keysOk = ['projectId', 'closingDate', 'status', 'code'].every((k) => k in d)
  return `keys=${keysOk} moneyString=${moneyOk} status=${d.status}`
})
ok('settlement POST shape', String(settleShape).includes('keys=true') && String(settleShape).includes('moneyString=true'), String(settleShape))
const approveShape = await page.evaluate(async () => {
  const t = localStorage.getItem('ark_token') || ''
  const H = { 'Content-Type': 'application/json' }
  if (t) H['Authorization'] = 'Bearer ' + t
  // approve：真实后端对未创建的决算单 404（信封 code=40401）；判定"有 code 信封即可达"。
  const res = await fetch('/api/v1/settlements/1/approve', { method: 'POST', headers: H, body: JSON.stringify({ action: 'APPROVE', treatment: '结转' }) })
  const text = await res.text()
  let r = null
  try { r = JSON.parse(text) } catch { return `RAW status=${res.status} body=${text.slice(0, 120)}` }
  return `code=${r?.code} hasData=${'data' in (r ?? {})}`
})
ok('settlement approve POST reachable', String(approveShape).includes('code='), String(approveShape))

// 4) expense voucher-sync panel: renders + POST /vouchers/sync shape
await page.goto(`${BASE}/#/expense`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)
const syncPanel = await page.locator('text=凭证同步').count()
ok('expense voucher-sync panel rendered', syncPanel >= 1, `count=${syncPanel}`)
const voucherShape = await page.evaluate(async () => {
  const t = localStorage.getItem('ark_token') || ''
  const H = { 'Content-Type': 'application/json' }
  if (t) H['Authorization'] = 'Bearer ' + t
  const res = await fetch('/api/v1/vouchers/sync', { method: 'POST', headers: H, body: JSON.stringify({ expenseId: 1 }) })
  const text = await res.text()
  let r = null
  try { r = JSON.parse(text) } catch { return `RAW status=${res.status} body=${text.slice(0, 120)}` }
  const d = r?.data ?? null
  if (!d) return `EMPTY status=${res.status} code=${r?.code} body=${text.slice(0, 120)}`
  const keysOk = ['expenseId', 'syncStatus', 'retryCount'].every((k) => k in d)
  return `keys=${keysOk} syncStatus=${d.syncStatus} retryCount=${d.retryCount}`
})
ok('voucher sync POST shape', String(voucherShape).includes('keys=true'), String(voucherShape))

console.log(results.join('\n'))
const failed = results.filter((l) => l.startsWith('FAIL') || l.startsWith('PAGEERROR'))
await browser.close()
process.exit(failed.length ? 1 : 0)
