// 冒烟：页面可见性矩阵在线配置闭环（PRD 2.9）
// 1) admin 在角色页把「资产与耗材」对财务的勾选去掉 → 保存
// 2) finance 登录 → 侧边菜单不应出现「资产与耗材台账」
// 3) admin 恢复勾选 → 保存；finance 重新登录 → 菜单恢复
import { chromium } from 'playwright'

const BASE = 'http://localhost:8080'
const ok = (m) => console.log('✓', m)
const fail = (m) => { console.error('✗', m); process.exit(1) }

async function login(page, u, p) {
  await page.goto(BASE + '/#/dash?needLogin=1')
  await page.fill('input[placeholder="请输入登录账号"]', u)
  await page.fill('input[placeholder="••••••••"]', p)
  await page.click('button.login-btn')
  await page.waitForFunction(() => !document.querySelector('#loginScreen')?.classList.contains('on'), null, { timeout: 8000 })
}
async function logout(page) {
  await page.click('.role-chip')
  await page.waitForTimeout(500)
}
async function menuHas(page, text) {
  const n = await page.locator(`.nav-item:has-text("${text}")`).count()
  return n > 0
}

const browser = await chromium.launch({ channel: 'chrome' })
const page = await browser.newPage()
try {
  // —— admin：矩阵编辑 ——
  await login(page, 'admin', 'Admin@123456')
  await page.goto(BASE + '/#/admin/roles')
  await page.waitForSelector('table.tbl', { timeout: 8000 })
  const row = page.locator('tr:has-text("资产与耗材台账")').first()
  if (!(await row.count())) fail('矩阵中未找到「资产与耗材台账」行')
  // 财务列 = th[title=财务] 在表头中的下标
  const headers = page.locator('table.tbl').nth(1).locator('thead th')
  const colCount = await headers.count()
  let finIdx = -1
  for (let i = 0; i < colCount; i++) {
    if ((await headers.nth(i).getAttribute('title')) === '财务') { finIdx = i; break }
  }
  if (finIdx < 0) fail('未找到「财务」角色列')
  const cell = row.locator('td').nth(finIdx)
  const cb = cell.locator('input[type=checkbox]')
  if (!(await cb.count())) fail('资产行财务列无 checkbox')

  // 1) 取消勾选并保存
  if (await cb.isChecked()) await cb.click()
  await page.click('button:has-text("保存矩阵")')
  await page.waitForFunction(() => document.querySelector('#toast')?.classList.contains('on'), null, { timeout: 5000 })
  ok('admin 取消勾选 资产×财务 并保存')

  // 2) finance 登录 → 菜单应无「资产与耗材台账」
  await logout(page)
  await login(page, 'finance', 'Finance@123456')
  await page.waitForTimeout(800)
  if (await menuHas(page, '资产与耗材台账')) fail('finance 菜单仍显示资产页（应已隐藏）')
  ok('finance 菜单已隐藏「资产与耗材台账」')

  // 3) admin 恢复 → finance 重新登录 → 菜单恢复
  await logout(page)
  await login(page, 'admin', 'Admin@123456')
  await page.goto(BASE + '/#/admin/roles')
  await page.waitForSelector('table.tbl', { timeout: 8000 })
  const row2 = page.locator('tr:has-text("资产与耗材台账")').first()
  const cb2 = row2.locator('td').nth(finIdx).locator('input[type=checkbox]')
  if (!(await cb2.isChecked())) await cb2.click()
  await page.click('button:has-text("保存矩阵")')
  await page.waitForFunction(() => document.querySelector('#toast')?.classList.contains('on'), null, { timeout: 5000 })
  ok('admin 恢复勾选并保存')

  await logout(page)
  await login(page, 'finance', 'Finance@123456')
  await page.waitForTimeout(800)
  if (!(await menuHas(page, '资产与耗材台账'))) fail('finance 菜单未恢复资产页')
  ok('finance 菜单已恢复「资产与耗材台账」')

  // 4) 矩阵授予超越静态表（回归：守卫不得再用静态 meta.roles 硬门禁拦矩阵授权）
  //    当前矩阵配置：archive 含 R-STAFF、performance 不含 R-STAFF。
  //    staff 菜单应显示「科研档案」且点击可达；「科研绩效评价」应隐藏。
  await logout(page)
  await login(page, 'staff', 'Staff@123456')
  await page.waitForTimeout(800)
  if (!(await menuHas(page, '科研档案'))) fail('staff 菜单应显示科研档案（矩阵已授予）')
  if (await menuHas(page, '科研绩效评价')) fail('staff 菜单不应显示科研绩效评价（矩阵未授予）')
  await page.locator('.nav-item:has-text("科研档案")').click()
  await page.waitForTimeout(1500)
  if (page.url().includes('/forbidden')) fail('矩阵授予的页面被守卫拦到 /forbidden')
  // 页面内数据接口也须可达（矩阵授予 ⇒ 读兜底），否则页面空报错
  await page.waitForSelector('.crumb', { timeout: 5000 })
  const crumb = await page.locator('.crumb').innerText()
  if (!crumb.includes('科研档案')) fail(`未落在档案页，crumb=${crumb.replace(/\n/g, ' ')}`)
  ok('staff 点击「科研档案」正常可达（路由 + 页面数据接口均放行）')

  console.log('\nSMOKE PASS · 页面可见性矩阵在线配置闭环')
} finally {
  await browser.close()
}
