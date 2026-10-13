/**
 * 契约加载器：从 ../design 读取 11 份 OpenAPI 3.0.3 yaml，解析成"路由索引"。
 * 与前端 frontend/src/api/schema/index.ts 同构——契约是唯一真源。
 * 这里用 fs 读取（Node 侧），前端用 import.meta.glob（浏览器侧）。
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import yaml from 'js-yaml'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
// 设计契约目录：backend/src -> backend -> repo root -> design
export const DESIGN_DIR = path.resolve(__dirname, '..', '..', 'design')
export const API_PREFIX = '/api/v1'

const MODULE_CODES = {
  '01': 'P', '02': 'E', '03': 'F', '04': 'R', '05': 'T', '06': 'C',
  '07': 'S', '08': 'D', '09': 'G', '10': 'A', '11': 'X',
}

/** 解析 #/components/... 形式的本地 $ref */
export function resolveRef(doc, ref) {
  if (!ref || typeof ref !== 'string' || !ref.startsWith('#/')) return null
  const parts = ref.slice(2).split('/')
  let cur = doc
  for (const seg of parts) {
    cur = cur?.[seg]
    if (cur == null) return null
  }
  return cur
}

/** OpenAPI 模板路径 -> Fastify 路径：/project/{id} -> /project/:id */
export function toFastifyPath(p) {
  return p.replace(/\{[^}/]+\}/g, (m) => ':' + m.slice(1, -1))
}

export const specs = []            // { module, file, doc }
export const routeIndex = new Map() // "METHOD /template/path" -> op

const HTTP_METHODS = ['get', 'post', 'put', 'delete', 'patch']

function loadOne(file) {
  const text = fs.readFileSync(path.join(DESIGN_DIR, file), 'utf8')
  const doc = yaml.load(text)
  const m = file.match(/^(\d{2})-/)
  const module = m && MODULE_CODES[m[1]] ? MODULE_CODES[m[1]] : '?'
  specs.push({ module, file, doc })
  const paths = doc.paths || {}
  for (const p of Object.keys(paths)) {
    for (const method of HTTP_METHODS) {
      const op = paths[p]?.[method]
      if (!op) continue
      const resp = op.responses?.['200'] ?? op.responses?.['201'] ?? null
      let responseSchema = null
      if (resp) {
        const resolved = resp.$ref ? resolveRef(doc, resp.$ref) : resp
        responseSchema = resolved?.content?.['application/json']?.schema || null
      }
      routeIndex.set(`${method.toUpperCase()} ${p}`, {
        method, path: p, module, file,
        operationId: op.operationId,
        summary: op.summary,
        tag: Array.isArray(op.tags) ? op.tags[0] : undefined,
        responseSchema,
        doc,
        raw: op,
      })
    }
  }
}

export function loadAll() {
  const files = fs.readdirSync(DESIGN_DIR).filter((f) => f.endsWith('.openapi.yaml')).sort()
  for (const f of files) loadOne(f)
  return { specs, routeIndex, files }
}

/** 从 200 schema 抽出 ApiResponse.data 子 schema（解析 $ref + allOf 结构） */
export function extractDataSchema(op) {
  const doc = op?.doc
  const deref = (s) => (s && typeof s.$ref === 'string' && doc) ? resolveRef(doc, s.$ref) : s
  const rs = deref(op?.responseSchema)
  if (!rs) return op?.responseSchema ?? null
  // data 子 schema 是否"有结构"：区别于 ApiResponse 的泛型 data（{type:object} 无任何约束）
  const isStructured = (d) => !!(d && typeof d === 'object' &&
    (d.$ref || d.allOf || d.oneOf || d.anyOf || d.items || (d.properties && Object.keys(d.properties).length)))
  if (Array.isArray(rs.allOf)) {
    // 遍历 allOf 各成员，优先取内联覆写的结构化 data，跳过 ApiResponse 的泛型 data；
    // 若无覆写则退回泛型（仅校验包裹），再否则 null。
    let generic = null
    for (const sub of rs.allOf) {
      const d = deref(sub)?.properties?.data
      if (!d) continue
      if (isStructured(d)) return d
      if (!generic) generic = d
    }
    // allOf 仅 $ref 到 ApiResponse（无内联 data 覆写）→ 取 ApiResponse.data 泛型
    return generic
  }
  if (rs.properties?.data) return rs.properties.data
  return rs
}

/** OpenAPI 模板路径 -> 锚定正则：{var} 支持整段或段内内嵌（如 /tasks/{id}:score 冒号自定义动作） */
const _tplReCache = new Map()
function templateRegex(tpl) {
  if (_tplReCache.has(tpl)) return _tplReCache.get(tpl)
  let re = ''
  for (const part of tpl.split(/(\{[^/}]+\})/)) {
    if (/^\{[^/}]+\}$/.test(part)) re += '([^/]+?)'
    else re += part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  }
  const rx = new RegExp('^' + re + '$')
  _tplReCache.set(tpl, rx)
  return rx
}

/** 模板"具体度"= 去掉 {var} 后的字面量字符数；越大越优先（避免 /{id} 抢走 /{id}:score） */
const _tplLitCache = new Map()
function literalLen(tpl) {
  if (_tplLitCache.has(tpl)) return _tplLitCache.get(tpl)
  const n = tpl.replace(/\{[^/}]+\}/g, '').length
  _tplLitCache.set(tpl, n)
  return n
}

/** 匹配请求路径 -> op（供写流程与调试用） */
export function matchRoute(method, urlPath) {
  let p = urlPath.split('?')[0]
  if (p.startsWith(API_PREFIX)) p = p.slice(API_PREFIX.length)
  if (!p.startsWith('/')) p = '/' + p
  const mu = method.toUpperCase()
  const exact = routeIndex.get(`${mu} ${p}`)
  if (exact) return exact
  let best = null
  let bestLit = -1
  for (const op of routeIndex.values()) {
    if (op.method.toUpperCase() !== mu) continue
    if (!templateRegex(op.path).test(p)) continue
    const lit = literalLen(op.path)
    if (lit > bestLit) { bestLit = lit; best = op }
  }
  return best
}
