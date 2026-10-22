/**
 * 轻量类型化 API client：走 /api/v1，统一解包 ApiResponse，POST/PUT 自动带 Idempotency-Key。
 * dev 下 fetch 被 mock/index 拦截；接真后端时删掉 installMock 调用即可，接口同构。
 */
export const API_PREFIX = '/api/v1'

// —— 认证 provider（由 auth.init() 注册；避免 auth↔client 循环 import）——
let tokenProvider: () => string = () => ''
let onUnauthorized: () => void = () => {}
export function setAuthProvider(getToken: () => string, handle401: () => void): void {
  tokenProvider = getToken
  onUnauthorized = handle401
}

export interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
  traceId: string
  timestamp: number
}

export interface PageResult<T> {
  list: T[]
  total: number
  page: number
  size: number
}

export class ApiError extends Error {
  code: number
  traceId?: string
  constructor(code: number, message: string, traceId?: string) {
    super(message)
    this.code = code
    this.traceId = traceId
  }
}

function uuid(): string {
  // Node16/浏览器 crypto.randomUUID 兜底
  const c = (globalThis as any).crypto
  if (c?.randomUUID) return c.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0
    const v = ch === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

export interface RequestOptions {
  params?: Record<string, string | number | boolean | undefined | null>
  body?: unknown
  idempotency?: boolean
  headers?: Record<string, string>
}

function buildUrl(path: string, params?: RequestOptions['params']): string {
  let url = API_PREFIX + path
  if (params) {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === '') continue
      qs.append(k, String(v))
    }
    const s = qs.toString()
    if (s) url += (url.includes('?') ? '&' : '?') + s
  }
  return url
}

async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(opts.headers || {}),
  }
  const t = tokenProvider()
  if (t) headers['Authorization'] = 'Bearer ' + t
  if (opts.idempotency && (method === 'POST' || method === 'PUT' || method === 'DELETE')) {
    headers['Idempotency-Key'] = uuid()
  }
  const init: RequestInit = { method, headers }
  if (opts.body !== undefined) init.body = JSON.stringify(opts.body)

  const res = await fetch(buildUrl(path, opts.params), init)
  if (res.status === 401) {
    onUnauthorized()
    throw new ApiError(40101, '未认证或令牌过期')
  }
  if (!res.ok) {
    throw new ApiError(res.status, `HTTP ${res.status} ${res.statusText}`)
  }
  const env = (await res.json()) as ApiEnvelope<T>
  if (env.code !== 0) {
    throw new ApiError(env.code, env.message, env.traceId)
  }
  // 契约 stub 兜底层（X-Stub: true）返回的是合规占位数据：延时提示，
  // 避免调用方把自己的成功 toast 盖掉后才看到（成功 toast 2.6s 自灭）。
  if (res.headers.get('X-Stub')) {
    setTimeout(() => (window as any).toast?.('演示数据：该端点后端的真实实现尚未落地'), 900)
  }
  return env.data
}

/**
 * 二进制下载（dataio 模板 / 文档流）：不解析 JSON，直接取 Blob。
 * 文件名从 Content-Disposition 解析，缺省用 fallback。
 */
async function blob(path: string, params?: RequestOptions['params'], fallbackName = 'download.bin') {
  const headers: Record<string, string> = {}
  const t = tokenProvider()
  if (t) headers['Authorization'] = 'Bearer ' + t
  const res = await fetch(buildUrl(path, params), { headers })
  if (res.status === 401) {
    onUnauthorized()
    throw new ApiError(40101, '未认证或令牌过期')
  }
  if (!res.ok) {
    // xlsx 流不会带信封，错误时尝试解析 JSON 拿业务码
    const text = await res.text()
    try {
      const env = JSON.parse(text) as ApiEnvelope<unknown>
      throw new ApiError(env.code, env.message, env.traceId)
    } catch (e: any) {
      if (e instanceof ApiError) throw e
      throw new ApiError(res.status, `HTTP ${res.status}`)
    }
  }
  let name = fallbackName
  const cd = res.headers.get('Content-Disposition') || ''
  const m = cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i)
  if (m) name = m[1]
  return { blob: await res.blob(), filename: name }
}

/** multipart 表单上传（dataio import）：body 直接传 FormData，不 JSON 序列化。 */
function postForm<T>(path: string, formData: FormData, params?: RequestOptions['params']) {
  const headers: Record<string, string> = {}
  const t = tokenProvider()
  if (t) headers['Authorization'] = 'Bearer ' + t
  headers['Idempotency-Key'] = uuid()
  return requestRaw<T>('POST', path, { headers, body: formData as unknown as BodyInit, params })
}

/** 同 request() 的信封/错误处理，但 body 不做 JSON 序列化（FormData 透传）。 */
async function requestRaw<T>(method: string, path: string, opts: RequestOptions & { body?: unknown }) {
  const init: RequestInit = { method, headers: { ...(opts.headers || {}) } as Record<string, string> }
  if (opts.body !== undefined) init.body = opts.body as BodyInit
  const res = await fetch(buildUrl(path, opts.params), init)
  if (res.status === 401) {
    onUnauthorized()
    throw new ApiError(40101, '未认证或令牌过期')
  }
  if (!res.ok) {
    throw new ApiError(res.status, `HTTP ${res.status} ${res.statusText}`)
  }
  const env = (await res.json()) as ApiEnvelope<T>
  if (env.code !== 0) {
    throw new ApiError(env.code, env.message, env.traceId)
  }
  return env.data
}

export const api = {
  get: <T>(path: string, params?: RequestOptions['params']) => request<T>('GET', path, { params }),
  post: <T>(path: string, body?: unknown, params?: RequestOptions['params']) =>
    request<T>('POST', path, { body, params, idempotency: true }),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, { body, idempotency: true }),
  del: <T>(path: string, params?: RequestOptions['params']) =>
    request<T>('DELETE', path, { params, idempotency: true }),
  blob: (path: string, params?: RequestOptions['params'], fallbackName?: string) =>
    blob(path, params, fallbackName),
  form: <T>(path: string, formData: FormData, params?: RequestOptions['params']) =>
    postForm<T>(path, formData, params),
}

export interface BlobDownload {
  blob: Blob
  filename: string
}

// 便捷：拉一页列表，返回 {rows,total}
export async function list<T>(path: string, params?: Record<string, any>) {
  const data = await api.get<PageResult<T>>(path, params)
  return { rows: data?.list ?? [], total: data?.total ?? 0 }
}
