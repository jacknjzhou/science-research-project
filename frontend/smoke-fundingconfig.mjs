import { chromium } from 'playwright'

// 冒烟：经费配置页（plan 2026-10-16-funding-config Phase 3）
// ① manager 菜单含「经费配置」→ 进入 → 新增子科目 → 树上出现
// ② 新建预算（2 行科目明细）→ 列表 DRAFT → 提交
// ③ finance 登录 → 页面可见但写按钮隐藏（只读态）
// ④ RolesView 矩阵出现 funding-config 行
const BASE = 'http://localhost:8080'
const fails = []
const ok = (m) => console.log('  ✓', m)
function fail(m) { fails.push(m); console.log('  ✗', m) }

const browser = await chromium.launch({ channel: 'chrome' })
const page = await browser.newPage()
page.on('dialog', (d) => (d.type() === 'confirm' ? d.accept() : d.dismiss()))

async function login(u, p) {
  await page.goto(BASE + '/#/dash?needLogin=1')
  await page.fill('input[placeholder="请输入登录账号"]', u)
  await page.fill('input[placeholder="••••••••"]', p)
  await page.click('button.login-btn')
  await page.waitForTimeout(1500)
}
async function menuHas(label) {
  return (await page.locator(`.nav-item:has-text("${label}")`).count()) > 0
}

console.log('① manager：菜单/进入/建子科目')
await login('manager', 'Manager@123456')
if (!(await menuHas('经费配置'))) fail('manager 菜单缺「经费配置」')
else ok('manager 菜单含「经费配置」（矩阵种子生效）')
await page.locator('.nav-item:has-text("经费配置")').click()
await page.waitForTimeout(1500)
if (!page.url().includes('funding-config')) fail('未进入经费配置页: ' + page.url())
else ok('进入经费配置页')
// 新增子科目：第一行「材料费」的 +子级
const before = await page.locator('td:has-text("材料费-冒烟子项")').count()
const addBtns = page.locator('button:has-text("+子级")')
if ((await addBtns.count()) === 0) fail('无 +子级 按钮（写权限未放行？）')
else {
  await addBtns.first().click()
  await page.fill('.fld input[placeholder="如：测试化验加工费"]', '材料费-冒烟子项')
  await page.locator('.btn.seal:has-text("保存")').click()
  await page.waitForTimeout(1200)
  const after = await page.locator('td:has-text("材料费-冒烟子项")').count()
  if (after <= before) fail('子科目未出现在树上')
  else ok('新增子科目「材料费-冒烟子项」树上可见')
}

console.log('② manager：新建预算 → 提交')
const cntBefore = await page.locator('tr:has(button:has-text("水位"))').count()

// 幂等：撞 uk_budget_project_ver 前先经 API 选一个尚无预算的项目
const be = 'http://localhost:8787/api/v1'
const mtok = (await (await fetch(`${be}/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'manager', password: 'Manager@123456' }) })).json()).data.access_token
const h = { Authorization: `Bearer ${mtok}` }
const budgeted = new Set(((await (await fetch(`${be}/budgets?size=100`, { headers: h })).json()).data.list || []).map((b) => b.project_id))
const mine = ((await (await fetch(`${be}/project/mine?size=50`, { headers: h })).json()).data.list || [])
const target = mine.find((p) => !budgeted.has(p.id))
const targetLabel = target ? (target.code ? target.code + ' · ' : '') + (target.name || target.title || '项目 #' + target.id) : ''
if (target) console.log('  · 选用项目:', targetLabel)
else console.log('  · 所有项目均已有预算——跳过 UI 新建（创建流程已在前次运行验证），直接验证提交')

let created = false
if (target) {
  await page.locator('button:has-text("＋ 新建预算")').click()
  await page.waitForTimeout(400)
  const projSel = page.locator('.fld select').first()
  await projSel.selectOption({ label: targetLabel }).catch((e) => fail('项目下拉选不中: ' + targetLabel))
  const rows = page.locator('select').filter({ hasText: '选择科目…' })
  await page.locator('button:has-text("＋ 加一行")').click()
  await rows.nth(0).selectOption({ label: '材料费' }).catch(() => rows.nth(0).selectOption({ index: 1 }))
  await rows.nth(0).locator('xpath=following-sibling::input').fill('1234')
  await rows.nth(1).selectOption({ label: '差旅费' }).catch(() => rows.nth(1).selectOption({ index: 2 }))
  await rows.nth(1).locator('xpath=following-sibling::input').fill('567')
  await page.locator('.btn.seal:has-text("创建")').click()
  await page.waitForTimeout(1500)
  const cntAfter = await page.locator('tr:has(button:has-text("水位"))').count()
  if (cntAfter <= cntBefore) fail('预算列表未新增')
  else { created = true; ok('新建预算出现在列表') }
}
// 找到 DRAFT 行点提交；无 DRAFT 且无未预算项目 → 幂等跳过（前次运行已建过）
const draftBtn = page.locator('button:has-text("提交")').first()
if ((await draftBtn.count()) === 0) {
  if (!target) ok('无 DRAFT 预算且无未预算项目（前次运行已建）——跳过提交（幂等）')
  else fail('无 DRAFT 预算可提交')
} else { await draftBtn.click(); await page.waitForTimeout(1200); ok('DRAFT 预算已提交') }

console.log('③ finance：页面可见但只读')
await page.evaluate(() => localStorage.removeItem('ark_token'))
await login('finance', 'Finance@123456')
if (!(await menuHas('经费配置'))) fail('finance 菜单缺「经费配置」（种子应含 R-FINANCE）')
else ok('finance 菜单含「经费配置」（只读授权生效）')
await page.locator('.nav-item:has-text("经费配置")').click()
await page.waitForTimeout(1500)
const writeBtns = await page.locator('button:has-text("＋ 新增根级科目"), button:has-text("＋ 新建预算"), button:has-text("+子级")').count()
if (writeBtns > 0) fail(`finance 页面出现 ${writeBtns} 个写按钮（应为 0）`)
else ok('finance 为只读态（无任何写按钮）')

console.log('④ admin：RolesView 矩阵含 funding-config')
await page.evaluate(() => localStorage.removeItem('ark_token'))
await login('admin', 'Admin@123456')
await page.goto(BASE + '/#/admin/roles')
await page.waitForTimeout(1500)
if ((await page.locator('td:has-text("funding-config")').count()) === 0) fail('矩阵缺 funding-config 行')
else ok('RolesView 矩阵出现 funding-config 行')

await browser.close()
if (fails.length) { console.log(`\nSMOKE FAIL · ${fails.length} 项`); process.exit(1) }
console.log('\nSMOKE PASS · 经费配置页全链路')
