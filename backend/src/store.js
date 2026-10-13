/**
 * 内存态存储：演示写流程（状态机）与幂等去重。
 * 生产应替换为 PostgreSQL/MyBatis（见 TECH_ARCHITECTURE.md），此处保持接口同构。
 */
const collections = new Map() // name -> Map(id -> record)

export function table(name) {
  if (!collections.has(name)) collections.set(name, new Map())
  return collections.get(name)
}

let idSeq = 90000
export function nextId() { return ++idSeq }

// 幂等键缓存：Idempotency-Key -> 已生成的响应体（同键重试返回同一结果）
const idemCache = new Map()
export function idempotent(key, produce) {
  if (!key) return produce()
  if (idemCache.has(key)) return { cached: true, ...idemCache.get(key) }
  const out = produce()
  idemCache.set(key, out)
  return { cached: false, ...out }
}

export function stats() {
  const s = {}
  for (const [name, m] of collections) s[name] = m.size
  s.__idempotencyKeys = idemCache.size
  return s
}
