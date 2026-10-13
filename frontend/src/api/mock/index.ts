/**
 * 契约 mock 服务：拦截 window.fetch，按命中的 OpenAPI 路由现场生成响应。
 * 统一响应包裹 {code,message,data,traceId,timestamp}；list 走 PageResult；支持 curated override。
 */
import { specs, matchRoute, API_PREFIX, type OpenApiOperation } from '../schema'
import { generate } from './generator'
import { overrides } from './overrides'

let installed = false

function docForModule(module: string): any {
  return specs.find((s) => s.module === module)?.doc || specs[0]?.doc
}

function envelope(data: unknown): string {
  return JSON.stringify({
    code: 0,
    message: 'ok',
    data,
    traceId: 'mock-' + Math.random().toString(36).slice(2, 12),
    timestamp: Date.now(),
  })
}

/** 从 200 schema 抽出 ApiResponse 里 data 子 schema（allOf 结构） */
function extractDataSchema(op: OpenApiOperation): any {
  const rs = op.responseSchema
  if (!rs) return null
  if (rs.allOf) {
    for (const sub of rs.allOf) {
      if (sub?.properties?.data) return sub.properties.data
    }
    return null
  }
  if (rs.properties?.data) return rs.properties.data
  return rs
}

type OverrideValue = unknown | ((url: string) => unknown)

function resolveOverride(v: OverrideValue, url: string): unknown {
  return typeof v === 'function' ? (v as (u: string) => unknown)(url) : v
}

function buildResponse(op: OpenApiOperation | null, url: string): { status: number; body: string } {
  const key = `${op?.method.toUpperCase()} ${op?.path}`
  // 1) curated override 优先（支持静态值或按 url 计算的函数）
  if (op && overrides[key] !== undefined) {
    return { status: 200, body: envelope(resolveOverride(overrides[key], url)) }
  }
  // 也允许按"去前缀请求路径"命中 override（模板未匹配时）
  let reqPath = url
  try { reqPath = new URL(url, 'http://x.local').pathname } catch { /* ignore */ }
  const cleanPath = reqPath.startsWith(API_PREFIX) ? reqPath.slice(API_PREFIX.length) : reqPath
  const ov = overrides[cleanPath]
  if (ov !== undefined) return { status: 200, body: envelope(resolveOverride(ov, url)) }

  if (!op) {
    // 未匹配到契约：返回空结构，不阻断（视图侧兜底渲染）
    return { status: 200, body: envelope({ list: [], total: 0, page: 1, size: 20 }) }
  }

  const dataSchema = extractDataSchema(op)
  const doc = docForModule(op.module)
  let data = generate(dataSchema, { doc })

  // 2) 分页参数落地：若生成的是 PageResult，回填 page/size/total
  if (data && typeof data === 'object' && 'list' in (data as any)) {
    const u = new URL(url, 'http://x.local')
    const page = Number(u.searchParams.get('page') || 1)
    const size = Number(u.searchParams.get('size') || 20)
    const d = data as any
    d.page = page
    d.size = size
    if (d.total == null) d.total = d.list?.length ?? 0
  }

  return { status: 200, body: envelope(data) }
}

export function installMock() {
  if (installed) return
  installed = true
  const nativeFetch = window.fetch.bind(window)

  window.fetch = async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : (input as Request).url
    const method = ((init.method || (input as any)?.method || 'GET') as string).toUpperCase()

    // 只拦截本系统的 /api/v1 请求
    const isApi = url.includes(API_PREFIX) || url.startsWith('/api/')
    if (!isApi) return nativeFetch(input as any, init)

    // 幂等键（演示：仅校验存在性）
    const idem = (init.headers as any)?.['Idempotency-Key']

    const op = matchRoute(method, url)
    const { status, body } = buildResponse(op, url)

    // 轻微延迟模拟网络，AI 接口更慢
    const isAi = op?.path?.includes('nl-query') || op?.path?.includes('policy-qa') || op?.tag === 'ai'
    const delay = isAi ? 450 : 120
    await new Promise((r) => setTimeout(r, delay))

    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.debug(`[mock] ${method} ${url} → ${op ? op.operationId || op.path : 'UNMATCHED'}${idem ? ' (idempotent)' : ''}`)
    }

    return new Response(body, {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  }
}
