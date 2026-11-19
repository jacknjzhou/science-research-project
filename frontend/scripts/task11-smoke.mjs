// Task 11 headless smoke: /loan list, funding-config 差旅标准 tab, expense invoice panel.
// Contract assertions: money fields are strings, camelCase keys present (design/03).
import { chromium } from 'playwright'

// E-8：演示口令不再写死在脚本里（部署方用 ARK_SEED_PASSWORD 指定）。
const DEMO_PASSWORDS = {admin: 'Admin@123456', manager: 'Manager@123456',
  staff: 'Staff@123456', finance: 'Finance@123456'};
const smokePwd = (who) => process.env.ARK_SMOKE_PASSWORD || DEMO_PASSWORDS[who];

const BASE = 'http://localhost:5199'
const results = []
const ok = (name, cond, extra = '') => { results.push(`${cond ? 'PASS' : 'FAIL'} ${name}${extra ? ' — ' + extra : ''}`) }

const browser = await chromium.launch({
  // 本机 playwright 1.38 缺 chromium-1080；复用缓存里新版 Chrome for Testing（协议兼容）
  executablePath: `${process.env.HOME}/Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`,
})
const page = await browser.newPage()
page.on('pageerror', (e) => results.push(`PAGEERROR ${e.message.slice(0, 160)}`))

// 1) login as manager (mock override: any password放行, manager = R-MANAGER)
await page.goto(`${BASE}/#/dash?needLogin=1`, { waitUntil: 'networkidle' })
await page.fill('#loginScreen input[placeholder="请输入登录账号"]', 'manager')
await page.fill('#loginScreen input[type="password"]', smokePwd('manager'))
await page.click('#loginScreen .login-btn')
await page.waitForTimeout(1500)
ok('login manager', !(await page.locator('#loginScreen.on').count()))

// 2) /loan list non-empty + contract shape (money=string, camelCase)
await page.goto(`${BASE}/#/loan`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)
const loanRows = await page.locator('#v-loan table.tbl tbody tr').count()
ok('loan list rows >= 1', loanRows >= 1, `rows=${loanRows}`)
const loanShape = await page.evaluate(async () => {
  const res = await fetch('/api/v1/loans?size=5')
  const text = await res.text()
  let r = null
  try { r = JSON.parse(text) } catch { return `RAW status=${res.status} ct=${res.headers.get('content-type')} body=${text.slice(0, 120)}` }
  const first = r?.data?.list?.[0] || null
  if (!first) return `EMPTY status=${res.status} code=${r?.code} body=${text.slice(0, 120)}`
  const moneyOk = ['amount', 'writeOffAmount', 'refundedAmount', 'remainingForWriteoff'].every((k) => typeof first[k] === 'string')
  const keysOk = ['projectId', 'budgetLineId', 'applicantUserId', 'status'].every((k) => k in first)
  return `keys=${keysOk} moneyString=${moneyOk} status=${first.status} code=${first.code}`
})
ok('loan contract shape', String(loanShape).includes('keys=true') && String(loanShape).includes('moneyString=true'), String(loanShape))

// 3) funding-config 差旅标准 tab: rows non-empty + upsert-shape fields
await page.goto(`${BASE}/#/funding-config`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1000)
await page.getByRole('button', { name: /差旅标准/ }).click()
await page.waitForTimeout(800)
const travelRows = await page.locator('table.tbl tbody tr').count() // travel tab is the visible table
const travelShape = await page.evaluate(async () => {
  const res = await fetch('/api/v1/travel-standards?size=5')
  const text = await res.text()
  let r = null
  try { r = JSON.parse(text) } catch { return `RAW status=${res.status} body=${text.slice(0, 120)}` }
  const first = r?.data?.list?.[0] || null
  if (!first) return `EMPTY status=${res.status} body=${text.slice(0, 120)}`
  const moneyOk = ['accommodationCap', 'mealsCap', 'transportCap'].every((k) => typeof first[k] === 'string')
  const keysOk = ['name', 'staffCategory', 'cityTier', 'effectiveFrom', 'effectiveTo', 'status', 'remark'].every((k) => k in first)
  return `keys=${keysOk} moneyString=${moneyOk} status=${first.status}`
})
ok('travel tab rows >= 1', travelRows >= 1, `rows=${travelRows}`)
ok('travel contract shape', String(travelShape).includes('keys=true') && String(travelShape).includes('moneyString=true'), String(travelShape))

// 4) expense invoice panel: list request non-empty via mock
await page.goto(`${BASE}/#/expense`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)
const invShape = await page.evaluate(async () => {
  const res = await fetch('/api/v1/invoices?size=5')
  const text = await res.text()
  let r = null
  try { r = JSON.parse(text) } catch { return `RAW status=${res.status} body=${text.slice(0, 120)}` }
  const first = r?.data?.list?.[0] || null
  if (!first) return `EMPTY status=${res.status} body=${text.slice(0, 120)}`
  const moneyOk = ['totalAmount', 'amountExclTax', 'taxAmount', 'ocrConfidence'].every((k) => typeof first[k] === 'string')
  const keysOk = ['invoiceCode', 'sellerName', 'isDuplicated', 'checkResult', 'expenseId'].every((k) => k in first)
  return `keys=${keysOk} moneyString=${moneyOk} status=${first.status}`
})
ok('invoice contract shape', String(invShape).includes('keys=true') && String(invShape).includes('moneyString=true'), String(invShape))
const invPanel = await page.locator('text=发票面板').count()
ok('expense invoice panel rendered', invPanel >= 1, `count=${invPanel}`)

console.log(results.join('\n'))
await browser.close()
process.exit(results.some((r) => r.startsWith('FAIL') || r.startsWith('PAGEERROR')) ? 1 : 0)
