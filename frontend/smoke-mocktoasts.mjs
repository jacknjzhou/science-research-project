import { chromium } from 'playwright'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

// 冒烟：mock toast 落地（18 处假提示 → 真端点 / 真 UI / 诚实降级）
// BASE_URL 可切换环境：默认 :8080（compose 全栈，mock 关）；mock 构建 preview 用 8090。
const BASE = process.env.BASE_URL || 'http://localhost:8080'
const fails = []
const skips = []
const ok = (m) => console.log('  ✓', m)
const fail = (m) => { fails.push(m); console.log('  ✗', m) }
const skip = (m) => { skips.push(m); console.log('  -', m, '（数据未渲染，跳过）') }

// 1x1 白色 JPEG（OCR 上传用）
const JPG_B64 = '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a'
  + 'HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAA'
  + 'AAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=='
const tmpJpg = path.join(os.tmpdir(), `smoke-ocr-${Date.now()}.jpg`)
fs.writeFileSync(tmpJpg, Buffer.from(JPG_B64, 'base64'))

const browser = await chromium.launch({ channel: 'chrome' })

// —— 登录（独立 context 隔离会话）——
async function login(account, pwd) {
  const ctx = await browser.newContext()
  const page = await ctx.newPage()
  page.on('dialog', (d) => (d.type() === 'confirm' ? d.accept() : d.dismiss()))
  await page.goto(BASE + '/#/dash?needLogin=1')
  await page.fill('input[placeholder="请输入登录账号"]', account)
  await page.fill('input[placeholder="••••••••"]', pwd)
  await page.click('button.login-btn')
  await page.waitForTimeout(2000)
  return { ctx, page }
}

// —— 等待 toast 出现并取文本（2.6s 自灭）——
async function toastText(page, timeout = 3000) {
  try {
    await page.waitForSelector('#toast.on', { timeout })
    await page.waitForTimeout(150)
    return ((await page.textContent('#toast')) || '').trim()
  } catch {
    return null
  }
}

const nav = (page, hash) => page.goto(BASE + hash)

// =====================================================================
console.log('\n[1] 报销填单（staff）· OCR 接 /invoices/ocr + 存草稿接 /expenses')
{
  const { ctx, page } = await login('staff', 'Staff@123456')
  await nav(page, '/#/expense')
  await page.waitForTimeout(2500)

  // ① OCR：点击发票区应触发真实文件选择 + POST /invoices/ocr
  const chooserP = page.waitForEvent('filechooser', { timeout: 5000 }).catch(() => null)
  await page.click('.expense-drop')
  const chooser = await chooserP
  if (chooser) {
    const preCount = await page.locator('.inv-card').count()
    await chooser.setFiles(tmpJpg)
    // toast 2.6s 自灭：等 OCR 响应返回后立即读取
    const resp = await page.waitForResponse((r) => r.url().includes('/invoices/ocr'), { timeout: 10000 }).catch(() => null)
    await page.waitForTimeout(300)
    const isStub = resp ? (await resp.headerValue('x-stub')) === 'true' : false
    const lineCount = await page.locator('.inv-card').count()
    const t = await page.textContent('#toast').catch(() => null)
    if (!resp) fail(`点选发票文件后未发 /invoices/ocr 请求（旧代码不发请求）`)
    else if (isStub && lineCount === preCount && t) ok(`发票区 → 真实 OCR 请求（契约 stub X-Stub），未新增伪造明细行；toast：${t}`)
    else if (!resp.ok() && t) ok(`发票区 → OCR 真实请求（HTTP ${resp.status()}）诚实失败提示：${t}`)
    else if (resp.ok() && !isStub && lineCount >= preCount) ok(`发票区 → OCR 真实识别，回填后明细 ${lineCount} 行；toast：${t}`)
    else fail(`OCR 行为异常：HTTP ${resp.status()} stub=${isStub} 明细行 ${preCount}→${lineCount} toast=${t}（旧代码：伪造演示行）`)
  } else {
    const t = await toastText(page)
    fail(`发票区点击未触发文件选择（旧 simulateOcr 假识别），toast：${t}`)
  }

  // ② 存草稿：有预算 → 真实 POST /expenses 建 DRAFT；无预算 → 诚实校验提示；两种都不得假装「已保存」
  const draftBtn = page.locator('button:has-text("存草稿")')
  if ((await draftBtn.count()) > 0) {
    const isCreateExpense = (r) => r.method() === 'POST' && r.url().includes('/expenses') && !r.url().includes('/expenses/')
    const reqP = page.waitForRequest(isCreateExpense, { timeout: 4000 }).catch(() => null)
    await draftBtn.click()
    // toast 2.6s 自灭：点击后立即读取（校验类 toast 同步出现）
    await page.waitForTimeout(500)
    let t = ((await page.textContent('#toast').catch(() => null)) || '').trim()
    const req = await reqP
    if (!t) { await page.waitForTimeout(1500); t = ((await page.textContent('#toast').catch(() => null)) || '').trim() }
    if (req) {
      if (t && !t.includes('演示') && (t.includes('草稿') || t.includes('失败'))) ok(`存草稿 → 真实 POST /expenses（建 DRAFT），toast：${t}`)
      else fail(`存草稿已发请求但 toast 异常：${t}`)
    } else if (t && (t.includes('请先') || t.includes('请至少') || t.includes('失败') || t.includes('草稿'))) ok(`存草稿 → 真实校验/反馈（无 POST），toast：${t}`)
    else fail(`点「存草稿」无请求且 toast 非诚实提示：${t}（旧代码假装「草稿已保存」）`)
  } else skip('存草稿按钮')

  await ctx.close()
}

// =====================================================================
console.log('\n[2] 资产台账（admin）· 盘点导入接 dataio 底座')
{
  const { ctx, page } = await login('admin', 'Admin@123456')
  await nav(page, '/#/asset')
  await page.waitForTimeout(2500)
  const btn = page.locator('button:has-text("盘点导入")')
  if ((await btn.count()) > 0) {
    await btn.click()
    const modal = await page.waitForSelector('[data-test="inv-wizard"]', { timeout: 3000 }).catch(() => null)
    if (modal) {
      ok('盘点导入 → 打开真实向导（模板下载 + 文件导入）')
      // 向导内：点模板下载 → 应发 /dataio/template 请求
      const tplReq = page.waitForRequest((r) => r.url().includes('/dataio/template'), { timeout: 6000 }).catch(() => null)
      const tplBtn = page.locator('[data-test="inv-tpl"]')
      if ((await tplBtn.count()) > 0) {
        await tplBtn.click()
        const r = await tplReq
        if (r) ok('向导内模板下载 → 触发 /dataio/template 请求')
        else fail('向导内模板下载未触发请求')
      } else fail('向导内缺模板下载控件')
    } else {
      const t = await toastText(page)
      fail(`盘点导入未打开向导（仍为假 toast）：${t}`)
    }
  } else skip('盘点导入按钮')
  await ctx.close()
}

// =====================================================================
console.log('\n[3] 我的项目（staff）· CLOSED 归档项目可正常打开')
{
  const { ctx, page } = await login('staff', 'Staff@123456')
  await nav(page, '/#/projects')
  await page.waitForTimeout(2500)
  const closed = page.locator('.proj-card, .card', { hasText: /CLOSED|已结题|结题/ }).first()
  if ((await closed.count()) > 0) {
    await closed.click()
    await page.waitForTimeout(1500)
    const url = page.url()
    const t = await toastText(page, 1500)
    if (url.includes('/project/')) ok(`CLOSED 项目可进入详情：${url.split('#')[1]}`)
    else fail(`CLOSED 项目仍被假 toast 拦截：${t}`)
  } else skip('种子/演示数据中无 CLOSED 项目')
  await ctx.close()
}

// =====================================================================
console.log('\n[4] 成果认领（staff）· 展开全部做实 + 仲裁诚实降级')
{
  const { ctx, page } = await login('staff', 'Staff@123456')
  await nav(page, '/#/claim')
  await page.waitForTimeout(2500)

  const before = await page.locator('.claim-card').count()
  const expand = page.locator('button:has-text("展开全部")')
  if ((await expand.count()) > 0) {
    await expand.click()
    await page.waitForTimeout(2500)
    const t = await toastText(page, 3000)
    const after = await page.locator('.claim-card').count()
    if (t && t.includes('演示')) fail(`「展开全部」仍为假 toast：${t}`)
    else if (after > before) ok(`「展开全部」真实加载：${before} → ${after} 条`)
    else ok(`「展开全部」已请求全量（池内 ${after} 条，toast：${t}）`)
  } else skip('无低置信余量（total ≤ 已载），「展开全部」未渲染')

  const arb = page.locator('button:has-text("仲裁")')
  if ((await arb.count()) > 0) {
    await arb.first().click()
    const t = await toastText(page)
    if (t && t.includes('尚未开放')) ok(`仲裁诚实降级：${t}`)
    else fail(`仲裁 toast 仍假装成功：${t}`)
  } else skip('无 DOUBTFUL 记录，仲裁按钮未渲染')
  await ctx.close()
}

// =====================================================================
console.log('\n[5] 申报指南（staff）· 订阅推送 / 附件下载诚实降级')
{
  const { ctx, page } = await login('staff', 'Staff@123456')
  await nav(page, '/#/guide')
  await page.waitForTimeout(2500)
  const sub = page.locator('button:has-text("订阅推送")')
  if ((await sub.count()) > 0) {
    await sub.click()
    const t = await toastText(page)
    if (t && t.includes('尚未开放')) ok(`订阅推送诚实降级：${t}`)
    else fail(`订阅推送 toast 仍假装成功：${t}`)
  } else skip('订阅推送按钮未渲染')

  const att = page.locator('.gl-ref').first()
  if ((await att.count()) > 0) {
    await att.click()
    const t = await toastText(page)
    if (t && t.includes('尚未开放')) ok(`附件下载诚实降级：${t}`)
    else fail(`附件下载 toast 仍假装演示：${t}`)
  } else skip('指南无附件，附件下载未渲染')
  await ctx.close()
}

// =====================================================================
console.log('\n[6] 申报书撰写（staff）· 看热点接 AI 真流程 / 条款原文 / 附件预览降级')
{
  const { ctx, page } = await login('staff', 'Staff@123456')
  await nav(page, '/#/editor')
  await page.waitForTimeout(3000)

  const hot = page.locator('button:has-text("看热点")')
  if ((await hot.count()) > 0) {
    const reqP = page.waitForRequest((r) => r.url().includes('/apply/ai/draft'), { timeout: 8000 }).catch(() => null)
    await hot.click()
    const req = await reqP
    if (req) ok('「看热点」→ 真实调用 /apply/ai/draft')
    else fail(`「看热点」未触发任何 AI 请求（旧假 toast：将检索…）`)
  } else skip('AI 面板「看热点」未渲染')

  const clause = page.locator('text=查看条款原文')
  if ((await clause.count()) > 0) {
    await clause.click()
    const t = await toastText(page)
    if (t && t.includes('尚未开放')) ok(`条款原文诚实降级：${t}`)
    else fail(`条款原文 toast 仍假装演示：${t}`)
  } else skip('合规检查卡未渲染')

  const pv = page.locator('.att-item button:has-text("预览")').first()
  if ((await pv.count()) > 0) {
    await pv.click()
    const t = await toastText(page)
    if (t && t.includes('尚未开放')) ok(`附件预览诚实降级：${t}`)
    else fail(`附件预览 toast 仍假装演示：${t}`)
  } else skip('申报书无附件，预览未渲染')
  await ctx.close()
}

// =====================================================================
console.log('\n[7] 转化看板（manager）· 披露详情 / 推介材料 / 修订建议诚实降级')
{
  const { ctx, page } = await login('manager', 'Manager@123456')
  await nav(page, '/#/transfer')
  await page.waitForTimeout(2500)
  const checks = [
    ['button:has-text("详情")', '披露详情'],
    ['button:has-text("生成推介材料")', '生成推介材料'],
    ['text=查看修订建议', '修订建议'],
  ]
  for (const [sel, name] of checks) {
    const loc = page.locator(sel).first()
    if ((await loc.count()) > 0) {
      await loc.click()
      const t = await toastText(page)
      if (t && t.includes('尚未开放')) ok(`${name}诚实降级：${t}`)
      else fail(`${name} toast 仍假装成功：${t}`)
    } else skip(`${name}未渲染`)
  }
  await ctx.close()
}

// =====================================================================
console.log('\n[8] 采购合同（finance）· 修订建议诚实降级')
{
  const { ctx, page } = await login('finance', 'Finance@123456')
  await nav(page, '/#/procurement')
  await page.waitForTimeout(2500)
  const rev = page.locator('text=查看修订')
  if ((await rev.count()) > 0) {
    await rev.click()
    const t = await toastText(page)
    if (t && t.includes('尚未开放')) ok(`修订建议诚实降级：${t}`)
    else fail(`修订建议 toast 仍假装生成：${t}`)
  } else skip('无高风险合同，修订建议未渲染')
  await ctx.close()
}

// =====================================================================
console.log('\n[9] PI 画像（manager）· 导出简历诚实降级')
{
  const { ctx, page } = await login('manager', 'Manager@123456')
  await nav(page, '/#/portrait')
  await page.waitForTimeout(2500)
  const exp = page.locator('button:has-text("导出简历")')
  if ((await exp.count()) > 0) {
    await exp.click()
    const t = await toastText(page)
    if (t && t.includes('尚未开放')) ok(`导出简历诚实降级：${t}`)
    else fail(`导出简历 toast 仍假装演示：${t}`)
  } else skip('导出简历按钮未渲染')
  await ctx.close()
}

// =====================================================================
console.log('\n[10] 评审工作台（manager）· 暂存 / 高亮对比诚实降级')
{
  const { ctx, page } = await login('manager', 'Manager@123456')
  await nav(page, '/#/review')
  await page.waitForTimeout(2500)
  const draft = page.locator('button:has-text("暂存")').first()
  if ((await draft.count()) > 0) {
    await draft.click()
    const t = await toastText(page)
    if (t && t.includes('尚未开放')) ok(`评审暂存诚实降级：${t}`)
    else fail(`评审暂存 toast 仍假装保存：${t}`)
  } else skip('评审任务未加载，暂存未渲染')

  const hl = page.locator('text=查看高亮对比')
  if ((await hl.count()) > 0) {
    await hl.click()
    const t = await toastText(page)
    if (t && t.includes('尚未开放')) ok(`高亮对比诚实降级：${t}`)
    else fail(`高亮对比 toast 仍假装演示：${t}`)
  } else skip('无查重命中，高亮对比未渲染')
  await ctx.close()
}

// =====================================================================
await browser.close()
fs.unlinkSync(tmpJpg)
console.log(`\n汇总：${fails.length} 失败 / ${skips.length} 跳过（数据相关）`)
if (fails.length) { console.log(`SMOKE FAIL · ${fails.length} 项：`); fails.forEach((f) => console.log('  ✗', f)); process.exit(1) }
console.log('SMOKE PASS · mock toast 落地')
