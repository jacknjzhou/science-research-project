// 冒烟：mock 模式登录可用（curated auth override）
// 背景：契约生成器为 /auth/me 编造随机角色、为 /page-grants 编造随机矩阵 →
// 随机角色命中不了矩阵 → 守卫弹 /forbidden → mock 模式实际不可用。
// 修复后预期：登录落在 /dash；页面可见性与真实后端 seed 矩阵一致（staff 进不去 admin，finance 经费配置只读）。
import { chromium } from 'playwright'

const BASE = process.env.BASE_URL || 'http://localhost:8090'

const passed = []
const failed = []
function ok(m) { passed.push(m); console.log(`  ✓ ${m}`) }
function fail(m) { failed.push(m); console.log(`  ✗ ${m}`) }

async function login(page, username) {
  await page.goto(`${BASE}/#/dash?needLogin=1`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(600)
  await page.fill('input[placeholder="请输入登录账号"]', username)
  await page.fill('input[placeholder="••••••••"]', 'Mock@123456')
  await page.click('button.login-btn')
  await page.waitForTimeout(2500)
  return page.url()
}

const browser = await chromium.launch({ channel: 'chrome' })
try {
  // ① staff 登录：应落 /dash（不再弹 /forbidden）
  let page = await browser.newPage()
  let url = await login(page, 'staff')
  if (url.includes('/forbidden')) fail(`staff 登录后被弹 /forbidden（url=${url}）——随机角色矩阵未 curated`)
  else if (url.includes('/dash')) ok(`staff 登录落 /dash（不再 403）`)
  else fail(`staff 登录后落 ${url}（期望 /dash）`)

  // ② staff 页面矩阵：可进 /expense，进不去 /admin/users
  await page.goto(`${BASE}/#/expense`)
  await page.waitForTimeout(1500)
  if (page.url().includes('/forbidden')) fail(`staff → /expense 被弹 /forbidden（矩阵应有 staff）`)
  else ok('staff → /expense 可达')
  await page.goto(`${BASE}/#/admin/users`)
  await page.waitForTimeout(1200)
  if (page.url().includes('/forbidden')) ok('staff → /admin/users 正确 403（矩阵无 staff）')
  else fail(`staff → /admin/users 未 403（url=${page.url()}）——矩阵未生效`)
  await page.close()

  // ③ finance 登录：经费配置可达但只读（caps 铁律：无 /subjects POST）
  page = await browser.newPage()
  url = await login(page, 'finance')
  if (url.includes('/forbidden')) fail(`finance 登录后被弹 /forbidden（url=${url}）`)
  else ok(`finance 登录成功`)
  await page.goto(`${BASE}/#/funding-config`)
  await page.waitForTimeout(1500)
  if (page.url().includes('/forbidden')) fail(`finance → /funding-config 被弹 /forbidden（矩阵应有 finance）`)
  else {
    ok('finance → /funding-config 可达')
    const hasWriteBtn = await page.locator('button:has-text("新增")').count()
    const enabledWrite = await page.locator('button:has-text("新增"):not([disabled])').count()
    if (hasWriteBtn > 0 && enabledWrite > 0) fail(`finance 有可用写按钮 ${enabledWrite} 个（caps 铁律应为只读）`)
    else ok(`finance 写按钮按 caps 门控（${hasWriteBtn} 个按钮，0 可用）`)
  }
  await page.close()

  // ④ admin 登录：全域可达（含 admin-users）
  page = await browser.newPage()
  url = await login(page, 'admin')
  if (url.includes('/forbidden')) fail(`admin 登录后被弹 /forbidden（url=${url}）`)
  else ok(`admin 登录成功`)
  await page.goto(`${BASE}/#/admin/users`)
  await page.waitForTimeout(1200)
  if (page.url().includes('/forbidden')) fail(`admin → /admin/users 被弹 /forbidden（R-ADMIN 应全通）`)
  else ok('admin → /admin/users 可达（R-ADMIN 全通）')
  await page.close()
} finally {
  await browser.close()
}

console.log(`\n汇总：${failed.length} 失败 / ${passed.length} 通过`)
if (failed.length) {
  console.log('SMOKE FAIL · mock 登录 curated：')
  failed.forEach((m) => console.log(`  ✗ ${m}`))
  process.exit(1)
}
console.log('SMOKE PASS · mock 登录 curated')
