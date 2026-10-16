import { chromium } from 'playwright'

// 冒烟：我的项目「列表」「甘特」视图切换生效
const BASE = 'http://localhost:8080'
const fails = []
const ok = (m) => console.log('  ✓', m)
const fail = (m) => { fails.push(m); console.log('  ✗', m) }

const browser = await chromium.launch({ channel: 'chrome' })
const page = await browser.newPage()
await page.goto(BASE + '/#/dash?needLogin=1')
await page.fill('input[placeholder="请输入登录账号"]', 'staff')
await page.fill('input[placeholder="••••••••"]', 'Staff@123456')
await page.click('button.login-btn')
await page.waitForTimeout(1500)
await page.locator('.nav-item:has-text("我的项目")').click()
await page.waitForTimeout(1800)

// 初始卡片视图
if ((await page.locator('.proj-card').count()) > 0) ok('卡片视图正常（默认）')
else fail('卡片视图未渲染')

// 点击「列表」
await page.locator('.chip:has-text("列表")').click()
await page.waitForTimeout(800)
const tblRows = await page.locator('.tbl tbody tr').count()
if (tblRows > 0) ok(`列表视图生效（${tblRows} 行）`)
else fail('列表视图无数据行')
if ((await page.locator('.chip.on:has-text("列表")').count()) === 1) ok('列表 chip 高亮')
else fail('列表 chip 未高亮')

// 点击「甘特」
await page.locator('.chip:has-text("甘特")').click()
await page.waitForTimeout(800)
const gBars = await page.locator('.g-bar').count()
const gToday = await page.locator('.g-today').count()
if (gBars > 0) ok(`甘特视图生效（${gBars} 条时间带）`)
else fail('甘特视图无时间带')
if (gToday === 1) ok('今日线已标注')
else fail('今日线缺失')
const barText = await page.locator('.g-bar span').first().innerText().catch(() => '')
if (barText) ok(`甘特带标注：${barText}`)

// 回「卡片」
await page.locator('.chip:has-text("卡片")').click()
await page.waitForTimeout(600)
if ((await page.locator('.proj-card').count()) > 0) ok('切回卡片视图正常')
else fail('切回卡片视图失败')

await browser.close()
if (fails.length) { console.log(`\nSMOKE FAIL · ${fails.length} 项`); process.exit(1) }
console.log('\nSMOKE PASS · 我的项目三视图切换')
