/**
 * 契约驱动参考后端。
 * 路由不按契约逐条注册（246 条含 :verb 自定义动作，路径形态杂），而是每个 HTTP 方法挂一个通配
 * 分发器，运行时用 matchRoute 把请求解析回契约里的操作，再据其 200 schema 现场生成响应。
 * —— 契约即路由，即响应，即真源。
 */
import Fastify from 'fastify'
import cors from '@fastify/cors'
import { loadAll, routeIndex, matchRoute, extractDataSchema, toFastifyPath, API_PREFIX, resolveRef, specs } from './schema.js'
import { generate } from './generator.js'
import { flows, READ_BACK } from './flows.js'
import { table, idempotent, stats } from './store.js'
import { dbEnabled, ping } from './db.js'
import { buildRegistry, getBinding } from './registry.js'
import { listRows, readRow, createRow, upsertRecord } from './adapters.js'

loadAll()

const DOCS = new Map() // module -> doc
for (const s of specs) DOCS.set(s.module, s.doc)

function traceId() { return 'srv-' + Math.random().toString(36).slice(2, 12) }
function envelope(code, message, data) {
  return { code, message, data, traceId: traceId(), timestamp: Date.now() }
}

// —— 路径参数解析（缓存编译）——
const pathCache = new Map()
function compilePath(tpl) {
  if (pathCache.has(tpl)) return pathCache.get(tpl)
  const names = []
  let re = ''
  for (const part of tpl.split(/(\{\w+\})/)) {
    const m = part.match(/^\{(\w+)\}$/)
    if (m) { names.push(m[1]); re += '([^/]+?)' }
    else re += part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  }
  const compiled = { regex: new RegExp('^' + re + '$'), names }
  pathCache.set(tpl, compiled)
  return compiled
}
function extractParams(tpl, reqPath) {
  let p = reqPath.split('?')[0]
  if (p.startsWith(API_PREFIX)) p = p.slice(API_PREFIX.length)
  if (!p.startsWith('/')) p = '/' + p
  const { regex, names } = compilePath(tpl)
  const m = p.match(regex)
  if (!m) return null
  const out = {}
  names.forEach((n, i) => { out[n] = m[i + 1] })
  return out
}

function docFor(module) { return DOCS.get(module) || specs[0]?.doc }

function fillPage(data, query) {
  if (data && typeof data === 'object' && !Array.isArray(data) && 'list' in data) {
    const page = Number(query?.page || 1)
    const size = Number(query?.size || 20)
    data.page = page
    data.size = size
    if (data.total == null) data.total = Array.isArray(data.list) ? data.list.length : 0
  }
  return data
}

function genericResponse(op, req) {
  const dataSchema = extractDataSchema(op)
  const doc = docFor(op.module)
  let data = generate(dataSchema, { doc, depth: 0 })
  // GET-by-id 命中已写实体：把实体字段叠加到 schema 形状之上（既合契约又反映状态）
  const templateKey = `${op.method.toUpperCase()} ${op.path}`
  if (op.method === 'get' && READ_BACK[templateKey]) {
    const rb = READ_BACK[templateKey]
    const params = extractParams(op.path, req.url) || {}
    const rec = table(rb.table).get(Number(params[rb.idParam]))
    if (rec && data && typeof data === 'object') Object.assign(data, rec)
  }
  if (op.method === 'get') fillPage(data, req.query)
  return envelope(0, 'ok', data)
}

async function dispatch(req, reply) {
  const method = req.method.toUpperCase()
  const op = matchRoute(method, req.url)
  if (!op) {
    reply.code(404)
    return envelope(40401, `契约未定义该路由: ${method} ${req.url.split('?')[0]}`, null)
  }
  const templateKey = `${method} ${op.path}`

  // —— PostgreSQL 快路径（DB_MODE=pg 且该 op 绑定到业务表）——
  if (dbEnabled()) {
    const b = getBinding(templateKey)
    if (b && b.kind !== 'passthrough' && b.kind !== 'action') {
      try {
        if (method === 'GET' && b.kind === 'list') {
          return envelope(0, 'ok', await listRows(b, req.query))
        }
        if (method === 'GET' && b.kind === 'read') {
          const params = extractParams(op.path, req.url) || {}
          const row = await readRow(b, params)
          if (!row) { reply.code(404); return envelope(40401, '记录不存在', null) }
          return envelope(0, 'ok', row)
        }
        if (method === 'POST' && b.kind === 'create') {
          const idemKey = req.headers['idempotency-key']
          const out = await idempotent(idemKey, async () => ({ body: await createRow(b, req.body) }))
          if (out.body) return envelope(0, 'ok', out.body)
        }
      } catch (e) {
        console.warn(`[db] pg 路径失败，回退参考实现: ${templateKey} — ${e.message}`)
      }
    }
  }

  // 写流程状态机
  if (method !== 'GET' && flows[templateKey]) {
    const params = extractParams(op.path, req.url) || {}
    const idemKey = req.headers['idempotency-key']
    const result = idempotent(idemKey, () => flows[templateKey](req, params))
    const { status = 200, code = 0, message = 'ok', data } = result
    reply.code(status)
    if (code !== 0) return envelope(code, message, null)
    // 叠加契约 200 schema 形状，保证响应体结构合规
    const schemaData = generate(extractDataSchema(op), { doc: docFor(op.module), depth: 0 })
    const merged = (schemaData && typeof schemaData === 'object' && !Array.isArray(schemaData))
      ? { ...schemaData, ...(data && typeof data === 'object' ? data : {}) }
      : (data ?? schemaData)
    // pg 模式：把状态机真正改动的字段（仅 data，避免用生成填充覆盖真实列）回写业务表
    if (dbEnabled() && data && typeof data === 'object' && data.id != null) {
      const b = getBinding(templateKey)
      if (b && b.table) {
        try { await upsertRecord(b, Number(data.id), data) }
        catch (e) { console.warn(`[db] 动作回写失败: ${templateKey} — ${e.message}`) }
      }
    }
    return envelope(0, message, merged)
  }

  // 其它写操作：通用幂等 + 生成响应
  if (method !== 'GET') {
    const idemKey = req.headers['idempotency-key']
    const cached = idempotent(idemKey, () => ({ body: genericResponse(op, req) }))
    return cached.body
  }

  // GET：生成 / 读回
  return genericResponse(op, req)
}

export async function buildApp() {
  const app = Fastify({ logger: false, bodyLimit: 4 * 1024 * 1024 })
  await app.register(cors, { origin: true })

  // —— PostgreSQL 初始化：连通则建登记表；失败自动降级回参考实现（零回归）——
  let dbStatus = { enabled: false, connected: false, coverage: null, error: null }
  if (dbEnabled()) {
    try {
      await ping()
      const cov = await buildRegistry()
      const bound = cov.tally.list + cov.tally.read + cov.tally.create + cov.tally.action
      dbStatus = { enabled: true, connected: true, coverage: cov, error: null }
      const msg = `[db] pg 已连接；路由绑定 ${bound}/${cov.total}（list=${cov.tally.list} read=${cov.tally.read} create=${cov.tally.create} action=${cov.tally.action} passthrough=${cov.tally.passthrough}）`
      app.log.info(msg)
      console.log(msg)
    } catch (e) {
      dbStatus = { enabled: true, connected: false, coverage: null, error: e.message }
      const msg = `[db] pg 连接/内省失败 → 降级为进程内参考实现：${e.message}`
      app.log.warn(msg)
      console.error(msg)
      process.env.DB_MODE = '' // 关闭 pg 快路径，dispatch 回退 generate/flows
    }
  }

  app.get('/healthz', async () => ({ ok: true, modules: specs.length, operations: routeIndex.size, db: { mode: process.env.DB_MODE || 'memory', enabled: dbStatus.enabled, connected: dbStatus.connected }, ts: Date.now() }))
  app.get(API_PREFIX + '/_db', async () => {
    if (!dbStatus.enabled) return envelope(0, 'ok', { mode: 'memory', note: 'DB_MODE≠pg，运行于参考内存实现' })
    if (!dbStatus.connected) return envelope(0, 'ok', { mode: 'pg', connected: false, error: dbStatus.error })
    const cov = dbStatus.coverage
    return envelope(0, 'ok', {
      mode: 'pg',
      connected: true,
      total: cov.total,
      tally: cov.tally,
      boundCount: cov.bound.length,
      skipCount: cov.skip.length,
      bound: cov.bound,
      skip: cov.skip,
    })
  })
  app.get('/api/v1/_stats', async () => envelope(0, 'ok', { operations: routeIndex.size, collections: stats() }))
  app.get(API_PREFIX + '/_openapi', async () => {
    const modules = specs.map((s) => ({ module: s.module, file: s.file, title: s.doc?.info?.title, version: s.doc?.info?.version, paths: Object.keys(s.doc?.paths || {}).length }))
    return envelope(0, 'ok', { modules, totalOperations: routeIndex.size })
  })

  for (const method of ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']) {
    app.route({ method, url: API_PREFIX + '/*', handler: dispatch })
  }
  await app.ready()
  return app
}

const isMain = process.argv[1] && process.argv[1].endsWith('server.js')
if (isMain) {
  const PORT = Number(process.env.PORT || 8787)
  const HOST = process.env.HOST || '127.0.0.1'
  buildApp().then((app) => {
    app.listen({ port: PORT, host: HOST }).then(() => {
      app.log.info(`契约驱动后端已启动: http://${HOST}:${PORT}${API_PREFIX}  (modules=${specs.length}, ops=${routeIndex.size})`)
      console.log(`[backend] listening http://${HOST}:${PORT}${API_PREFIX}  ops=${routeIndex.size}`)
    }).catch((e) => { console.error(e); process.exit(1) })
  })
}
