/**
 * 契约注册表：把 11 份 OpenAPI 3.0.3 yaml 以 ?raw 载入、js-yaml 解析，
 * 归并成一个"路由索引"，供 mock 生成器与类型工具消费。
 * 契约是唯一真源：mock 数据由这些 schema 现场生成（或命中 curated override）。
 */
import yaml from 'js-yaml'

export interface OpenApiOperation {
  method: 'get' | 'post' | 'put' | 'delete' | 'patch'
  path: string                 // 原始模板路径，如 /dash/metrics/{code}
  operationId?: string
  summary?: string
  tag?: string
  module: string               // 模块代号 P/E/F/...
  responseSchema: any          // 200 的 application/json schema（含 allOf/ApiResponse 包裹）
}

export interface SpecDoc {
  module: string
  doc: any
}

const MODULE_CODES: Record<string, string> = {
  '01': 'P', '02': 'E', '03': 'F', '04': 'R', '05': 'T', '06': 'C',
  '07': 'S', '08': 'D', '09': 'G', '10': 'A', '11': 'X',
}

// Vite glob：把 schema 目录下所有 yaml 以原始文本导入
const globbed = import.meta.glob('./*.yaml', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

export const specs: SpecDoc[] = []
export const routeIndex = new Map<string, OpenApiOperation>()

function moduleCodeFromFile(file: string): string {
  const m = file.match(/(\d{2})-/)
  return m && MODULE_CODES[m[1]] ? MODULE_CODES[m[1]] : '?'
}

export const API_PREFIX = '/api/v1'

for (const [file, text] of Object.entries(globbed)) {
  const module = moduleCodeFromFile(file)
  const doc = yaml.load(text) as any
  specs.push({ module, doc })
  const paths = doc.paths || {}
  for (const p of Object.keys(paths)) {
    for (const method of ['get', 'post', 'put', 'delete', 'patch']) {
      const op = paths[p][method]
      if (!op) continue
      const resp = op.responses?.['200']
      let responseSchema: any = null
      if (resp) {
        // 支持本地 responses 或 $ref 到 components.responses
        const resolved = resp.$ref ? resolveRef(doc, resp.$ref) : resp
        responseSchema = resolved?.content?.['application/json']?.schema || null
      }
      const entry: OpenApiOperation = {
        method: method as any,
        path: p,
        operationId: op.operationId,
        summary: op.summary,
        tag: Array.isArray(op.tags) ? op.tags[0] : undefined,
        module,
        responseSchema,
      }
      routeIndex.set(`${method.toUpperCase()} ${p}`, entry)
    }
  }
}

export function resolveRef(doc: any, ref: string): any {
  // ref like '#/components/schemas/Metric'
  if (!ref || !ref.startsWith('#/')) return null
  const parts = ref.slice(2).split('/')
  let cur = doc
  for (const seg of parts) {
    cur = cur?.[seg]
    if (cur == null) return null
  }
  return cur
}

/**
 * 归一化请求 URL → 匹配模板路由。
 * 去掉 /api/v1 前缀、query、以及 host；对 {var} 段做通配匹配。
 */
export function matchRoute(method: string, url: string): OpenApiOperation | null {
  let path = url
  try {
    const u = new URL(url, 'http://x.local')
    path = u.pathname
  } catch {
    /* keep raw */
  }
  if (path.startsWith(API_PREFIX)) path = path.slice(API_PREFIX.length)
  if (!path.startsWith('/')) path = '/' + path
  const methodUp = method.toUpperCase()
  const exact = routeIndex.get(`${methodUp} ${path}`)
  if (exact) return exact
  // 模板匹配：把 path 拆段，与每个模板比
  const reqSegs = path.split('/').filter(Boolean)
  for (const op of routeIndex.values()) {
    if (op.method.toUpperCase() !== methodUp) continue
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

export function totalOperations(): number {
  return routeIndex.size
}
