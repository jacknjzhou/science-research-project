// 冒烟：管理员全量视角——admin 的「项目」列表应显示全部项目，staff 仅显示自己为 PI 的项目
import { chromium } from 'playwright'
const BASE = 'http://localhost:8080'
const fails = []
const ok = (m) => console.log('  ✓', m)
const fail = (m) => { fails.push(m); console.log('  ✗', m) }

const browser = await chromium.launch({ channel: 'chrome' })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await ctx.newPage()

async function login(u, p) {
  await page.goto(BASE + '/#/dash?needLogin=1')
  await page.waitForTimeout(600)
  await page.fill('input[placeholder="请输入登录账号"]', u)
  await page.fill('input[placeholder="••••••••"]', p)
  await page.click('button.login-btn')
  await page.waitForTimeout(1500)
}
async function goProjects() {
  await page.goto(BASE + '/#/projects')
  await page.waitForTimeout(1500)
}

async function apiTotal() {
  return await page.evaluate(async () => {
    const t = localStorage.getItem('ark_token') || ''
    const r = await fetch('/api/v1/project/mine?page=1&size=50', { headers: { Authorization: 'Bearer ' + t } })
    return (await r.json())?.data?.total
  })
}

console.log('① staff：我的项目 = PI 视角')
await login('staff', 'Staff@123456')
await goProjects()
const staffTitle = (await page.locator('.page-title').innerText().catch(() => '')).replace(/\s/g, '')
console.log(`  staff 页面标题: "${staffTitle}"`)
const staffApi = await apiTotal()
console.log(`  staff API total = ${staffApi}`)

await logout()
console.log('② admin：全部项目 = 全库')
await login('admin', 'Admin@123456')
await goProjects()
const adminTitle = (await page.locator('.page-title').innerText().catch(() => '')).replace(/\s/g, '')
console.log(`  admin 页面标题: "${adminTitle}", 含「全部」: ${adminTitle.includes('全部')}`)
if (!adminTitle.includes('全部')) fail('admin 标题未切换为「全部项目」')
else ok('admin 标题为「全部项目」')

const adminApi = await apiTotal()
console.log(`  admin API total = ${adminApi}`)
if (!(adminApi > staffApi)) fail(`admin total(${adminApi}) 应大于 staff total(${staffApi})`)
else ok(`admin 全量视角生效（${adminApi} > ${staffApi}）`)

// 列表/甘特视图在 admin 全量数据下仍工作
await page.locator('.chip:has-text("列表")').click()
await page.waitForTimeout(800)
const rows = await page.locator('table tbody tr').count()
if (rows < adminApi) fail(`列表视图行数 ${rows} < total ${adminApi}`)
else ok(`列表视图 ${rows} 行与全量一致`)
await page.locator('.chip:has-text("甘特")').click()
await page.waitForTimeout(800)
const bars = await page.locator('.gantt-bar, .g-row').count()
console.log(`  甘特条元素约 ${bars}`)

async function logout() {
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear() })
}

console.log(fails.length ? `\nSMOKE FAIL · ${fails.length} 项` : '\nSMOKE PASS · 管理员全量视角闭环')
await browser.close()
process.exit(fails.length ? 1 : 0)
