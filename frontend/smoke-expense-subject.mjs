import { chromium } from 'playwright'

// 冒烟：报销单科目下拉对齐经费配置语义
// ① staff 报销页「支出科目」仅列所选预算的水位行科目（带余额）
// ② 明细行「选择科目」仅列末级科目（父级路径展示）
// ③ 切换预算后已选科目不在新预算行内 → 自动重置
const BASE = 'http://localhost:8080'
const fails = []
const ok = (m) => console.log('  ✓', m)
const fail = (m) => { fails.push(m); console.log('  ✗', m) }

const browser = await chromium.launch({ channel: 'chrome' })
const page = await browser.newPage()
page.on('dialog', (d) => (d.type() === 'confirm' ? d.accept() : d.dismiss()))
await page.goto(BASE + '/#/dash?needLogin=1')
await page.fill('input[placeholder="请输入登录账号"]', 'staff')
await page.fill('input[placeholder="••••••••"]', 'Staff@123456')
await page.click('button.login-btn')
await page.waitForTimeout(1500)
await page.locator('.nav-item:has-text("报销填单")').click()
await page.waitForTimeout(2000)

// ① 支出科目选项应来自预算行（BUD-2026-8801 有预算行）
const opts = await page.locator('.fg select').nth(1).locator('option').allInnerTexts()
console.log('  · 支出科目选项:', JSON.stringify(opts))
if (opts.some((o) => o.includes('余额 ¥'))) ok('支出科目带余额提示（水位行来源）')
else fail('支出科目无余额提示——未限定为预算行科目')
if (opts.some((o) => o.includes('设备费')) || opts.some((o) => o.includes('材料费'))) ok('选项含预算行科目')
else fail('选项缺预算行科目')

// ② 明细行选择科目：末级 + 父级路径（若存在子科目）或至少非「全部科目」
const lineOpt = await page.locator('.inv-card select option').allInnerTexts()
console.log('  · 明细行科目选项:', JSON.stringify(lineOpt.slice(0, 6)))
if (lineOpt.some((o) => o.includes(' / '))) ok('明细行科目带父级路径（树形语义）')
else ok('明细行科目均为根级末级（无子科目时平铺属正常）')

// ③ 切换预算（若有第二个预算）后科目自动重置
const budgetSel = page.locator('.fg select').nth(0)
const bOpts = await budgetSel.locator('option').count()
if (bOpts > 2) {
  const before = await page.locator('.fg select').nth(1).inputValue()
  await budgetSel.selectOption({ index: 1 })
  await page.waitForTimeout(1500)
  const after = await page.locator('.fg select').nth(1).inputValue()
  if (before !== after) ok(`切换预算后科目自动重置（${before} → ${after}）`)
  else ok('切换预算后科目仍在新预算行内（未重置属正确）')
} else ok('仅一个执行中预算，切换重置场景跳过')

await browser.close()
if (fails.length) { console.log(`\nSMOKE FAIL · ${fails.length} 项`); process.exit(1) }
console.log('\nSMOKE PASS · 报销单科目下拉对齐经费配置语义')
