/**
 * 契约一致性自验：对每条 GET 路由，注入请求取回 ApiResponse，
 * 再用该路由 200 schema 的 data 子 schema（解引用 + OpenAPI→JSON Schema 归一）做 ajv 校验。
 * 这是"契约驱动"的硬证明：响应体结构必须能被契约本身描述。
 */
import Ajv from 'ajv'
import addFormats from 'ajv-formats'
import { loadAll, routeIndex, extractDataSchema, API_PREFIX, specs } from '../src/schema.js'
import { buildApp } from '../src/server.js'

loadAll()

const KEEP_FORMATS = new Set(['date', 'date-time', 'email', 'uri', 'url', 'ipv4', 'ipv6'])
const DROP_KEYS = ['example', 'discriminator', 'externalDocs', 'xml', 'readOnly', 'writeOnly', 'deprecated']

function resolveLocal(doc, ref) {
  if (!ref.startsWith('#/')) return {}
  let cur = doc
  for (const seg of ref.slice(2).split('/')) cur = cur?.[seg]
  return cur || {}
}
function normalize(node, doc, stack = []) {
  if (!node || typeof node !== 'object') return node
  if (Array.isArray(node)) return node.map((n) => normalize(n, doc, stack))
  if (node.$ref) {
    if (stack.includes(node.$ref)) return {} // 循环引用：放开（accept anything）
    return normalize(resolveLocal(doc, node.$ref), doc, [...stack, node.$ref])
  }
  const out = {}
  let nullable = false
  for (const [k, v] of Object.entries(node)) {
    if (DROP_KEYS.includes(k)) continue
    if (k === 'format') { if (KEEP_FORMATS.has(v)) out.format = v; continue }
    if (k === 'nullable') { nullable = Boolean(v); continue }
    if ((k === 'exclusiveMinimum' || k === 'exclusiveMaximum') && typeof v === 'boolean') continue
    out[k] = normalize(v, doc, stack)
  }
  if (nullable && out.type && !String(out.type).includes('null')) out.type = [out.type, 'null']
  if (nullable && Array.isArray(out.enum) && !out.enum.includes(null)) out.enum = [...out.enum, null]
  return out
}

const ajv = new Ajv({ strict: false, allErrors: true })
addFormats(ajv)

const app = await buildApp()
const getOps = [...routeIndex.values()].filter((o) => o.method === 'get')

let pass = 0
const fails = []
for (const op of getOps) {
  const url = API_PREFIX + op.path.replace(/\{\w+\}/g, '1')
  let env
  try {
    const res = await app.inject({ method: 'GET', url })
    env = JSON.parse(res.body)
  } catch (e) {
    fails.push({ key: `GET ${op.path}`, err: '请求异常: ' + e.message })
    continue
  }
  if (env.code !== 0) { fails.push({ key: `GET ${op.path}`, err: 'code!=0: ' + env.code + ' ' + env.message }); continue }
  const dataSchema = extractDataSchema(op)
  if (!dataSchema) { pass++; continue } // 无 data 结构定义，视为通过（仅校验包裹）
  const doc = specs.find((s) => s.module === op.module)?.doc
  let compiled
  try {
    compiled = ajv.compile(normalize(dataSchema, doc))
  } catch (e) {
    fails.push({ key: `GET ${op.path}`, err: 'schema 编译失败: ' + e.message })
    continue
  }
  const ok = compiled(env.data)
  if (ok) pass++
  else fails.push({ key: `GET ${op.path}`, err: ajv.errorsText(compiled.errors, { maxErrors: 3 }).slice(0, 200) })
}

console.log(`\n=== 契约一致性自验 ===`)
console.log(`GET 路由: ${getOps.length}  通过: ${pass}  失败: ${fails.length}`)
if (fails.length) {
  console.log(`\n失败明细（前 40 条）:`)
  for (const f of fails.slice(0, 40)) console.log(`  ✗ ${f.key}\n     ${f.err}`)
  process.exitCode = 1
} else {
  console.log(`\n✅ 全部 GET 响应体均符合各自契约 schema。`)
}
