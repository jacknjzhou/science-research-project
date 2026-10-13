import { buildApp } from '../src/server.js'
const app = await buildApp()
const hit = async (m, u, payload, headers) => {
  const r = await app.inject({ method: m, url: u, payload, headers })
  let b
  try { b = JSON.parse(r.body) } catch { b = { parseError: r.body.slice(0, 120) } }
  return { s: r.statusCode, b }
}
let r
r = await hit('GET', '/healthz'); console.log('healthz', r.s, JSON.stringify(r.b))
r = await hit('GET', '/api/v1/project/mine'); console.log('project/mine', r.s, 'code=' + r.b.code, 'listLen=' + (r.b.data?.list?.length ?? r.b.data?.length ?? 'n/a'))
r = await hit('GET', '/api/v1/project/90001'); console.log('project/90001 keys:', Object.keys(r.b.data || {}).slice(0, 10).join(','))
r = await hit('GET', '/api/v1/apply/guidelines?page=2&size=5'); console.log('guidelines', r.s, 'page=' + r.b.data?.page, 'size=' + r.b.data?.size, 'total=' + r.b.data?.total, 'listLen=' + (r.b.data?.list?.length))
r = await hit('GET', '/api/v1/nope/xyz'); console.log('unmatched', r.s, 'code=' + r.b.code, r.b.message)
r = await hit('POST', '/api/v1/apply/applications', { title: '测试申报', project_type: '自然' }, { 'idempotency-key': 'k-1' })
const aid = r.b.data.id
console.log('create app id', aid, 'status', r.b.data.status, 'title', r.b.data.title)
r = await hit('POST', `/api/v1/apply/applications/${aid}/submit`, {})
console.log('submit ->', r.b.data.status)
r = await hit('GET', `/api/v1/apply/applications/${aid}`)
console.log('read-back status', r.b.data.status)
// idempotency: same key returns cached (same id)
r = await hit('POST', '/api/v1/apply/applications', { title: '测试申报', project_type: '自然' }, { 'idempotency-key': 'k-1' })
console.log('idempotent replay id (expect == ' + aid + '):', r.b.data.id)
