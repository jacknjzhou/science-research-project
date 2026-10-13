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

/** 从 200 schema 抽出 ApiResponse.data 子 schema（allOf 结构） */
export function extractDataSchema(op) {
  const rs = op?.responseSchema
  if (!rs) return null
  if (Array.isArray(rs.allOf)) {
    for (const sub of rs.allOf) {
      if (sub?.properties?.data) return sub.properties.data
    }
    // allOf 里可能是 $ref 到 ApiResponse + 内联 {properties:{data}}
    return null
  }
  if (rs.properties?.data) return rs.properties.data
  return rs
}

/** 匹配请求路径 -> op（供写流程与调试用） */
export function matchRoute(method, urlPath) {
  let p = urlPath.split('?')[0]
  if (p.startsWith(API_PREFIX)) p = p.slice(API_PREFIX.length)
  if (!p.startsWith('/')) p = '/' + p
  const mu = method.toUpperCase()
  const exact = routeIndex.get(`${mu} ${p}`)
  if (exact) return exact
  const reqSegs = p.split('/').filter(Boolean)
  for (const op of routeIndex.values()) {
    if (op.method.toUpperCase() !== mu) continue
    const tplSegs = op.path.split('/').filter(Boolean)
    if (tplSegs.length !== reqSegs.length) continue
    let ok = true
    for (let i = 0; i < tplSegs.length; i++) {
      const t = tplSegs[i]
      if (t.startsWith('{') && t.endsWith('}')) continue
      if (t !== reqSegs[i]) { ok = false; break }
    }
    if (ok) return op
  }
  return null
}
