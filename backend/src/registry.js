/**
 * 生成式路由→表 登记表：不手写 249 控制器，而是从 OpenAPI 契约自动推导每个 op 落到哪张业务表、属于何种 CRUD。
 * 规则：
 *  - 表名 = `${模块代号小写}_${snake(实体名)}`（p_application / g_contract / r_output / a_asset…），再对 information_schema 真实表集校验，命中才绑定。
 *  - 大小写：A/D 模块契约用 camelCase，其余 snake_case。
 *  - kind：GET→list(有分页 list)/read(路径含 {var})；POST 无 {var} 无冒号→create；POST/PUT/PATCH/DELETE 含 {var} 或 :verb→action；否则 passthrough。
 *  - 无法解析实体 / 表不存在 / 分析聚合类（dash、forecast、metrics、trace、governance、drill 等）→ passthrough（继续走 generate/flows，不回归）。
 */
import { routeIndex, extractDataSchema } from './schema.js'
import { toSnake, loadTables, hasTable } from './mapping.js'

const CAMEL_MODULES = new Set(['A', 'D'])
const PASSTHROUGH_HINT = /(\/dash\/|\/forecast|\/benchmark|\/metrics|\/drill|\/trace|\/consolidate|\/governance|\/health-score|\/risk-warnings|\/archive-checklist|\/annual-report|\/ai-|:score|\/ai|analyze|\/calculate|\/run\b|\/generate|\/depreciation|collab-graph|portrait|talent-plans)/i

function lastSeg(ref) {
  const i = ref.lastIndexOf('/')
  return i >= 0 ? ref.slice(i + 1) : ref
}

/** 从（可能含 $ref/allOf 的）data schema 里找出实体名与是否分页 */
function findEntity(node, doc, depth = 0) {
  if (!node || typeof node !== 'object' || depth > 6) return null
  const deref = (ref) => {
    if (typeof ref !== 'string' || !ref.startsWith('#/')) return null
    let cur = doc
    for (const seg of ref.slice(2).split('/')) { cur = cur?.[seg]; if (cur == null) return null }
    return cur
  }
  // 直接命中 list.items.$ref（typed 列表覆写）
  const li = node.properties?.list?.items
  if (li && typeof li.$ref === 'string') return { entity: lastSeg(li.$ref), many: true }
  if (li && li.properties && li.$ref) return { entity: lastSeg(li.$ref), many: true }

  if (Array.isArray(node.allOf)) {
    let single = null
    for (const sub of node.allOf) {
      const r = findEntity(sub?.$ref ? deref(sub.$ref) : sub, doc, depth + 1) || findEntity(sub, doc, depth + 1)
      if (!r) continue
      if (r.many) return r
      single = single || r
    }
    if (single) return single
  }
  if (typeof node.$ref === 'string') {
    const name = lastSeg(node.$ref)
    if (name === 'PageResult') {
      const r = findEntity(deref(node.$ref), doc, depth + 1)
      return r ? { entity: r.entity, many: true } : null
    }
    // 裸数组：items.$ref
    return { entity: name, many: false }
  }
  if (node.type === 'array' && node.items) {
    const name = typeof node.items.$ref === 'string' ? lastSeg(node.items.$ref) : null
    return name ? { entity: name, many: true } : null
  }
  return null
}

/** 取路径里的 {var}（若有）作为主键参数名 */
function pathVar(p) {
  const m = p.match(/\{(\w+)\}/)
  return m ? m[1] : null
}

// 极少数实体名 snake 后与 DDL 表基名不一致（历史命名），显式登记别名，避免误判"表不存在"回落。
const ENTITY_TABLE_ALIAS = {
  EntPartner: 'enterpartner', // DDL: t_enterpartner
}

/** 契约实体名 → 业务表名：`${模块代号小写}_${snake(实体)}`（p_application / a_asset / d_report…）*/
export function deriveTable(op, entity) {
  const mod = String(op.module).toLowerCase()
  let name = String(entity)
  // 部分模块(E)实体带模块首字母以避免跨模块重名(EProject/ETask)，直接拼会得到 e_e_project 这类双重前缀；
  // 仅当去掉首字母后余串仍以大写字母开头(PascalCase 前缀)才剥离，避免误伤 Envelope(模块E 下)这类真名。
  if (name.length > 1 && name[0].toLowerCase() === mod && /^[A-Z]/.test(name.slice(1))) {
    name = name.slice(1)
  }
  const base = ENTITY_TABLE_ALIAS[String(entity)] || toSnake(name)
  return `${mod}_${base}`
}

function classify(op, has = hasTable) {
  const method = op.method.toUpperCase()
  if (PASSTHROUGH_HINT.test(op.path)) return { kind: 'passthrough', reason: '分析/AI/自定义动作' }

  const ent = findEntity(extractDataSchema(op), op.doc)
  if (!ent || !ent.entity) return { kind: 'passthrough', reason: '契约未描述实体（泛型 Ok / 计算列）' }

  const table = deriveTable(op, ent.entity)
  if (!has(table)) return { kind: 'passthrough', reason: `表 ${table} 不存在/未迁移` }

  const casing = CAMEL_MODULES.has(String(op.module).toUpperCase()) ? 'camel' : 'snake'

  if (method === 'GET') {
    if (ent.many) return { kind: 'list', table, casing, entity: ent.entity }
    const v = pathVar(op.path)
    if (v) return { kind: 'read', table, casing, entity: ent.entity, idParam: v }
    // 无 id 的 GET 但返回单实体：极少，退化为 list
    return { kind: 'list', table, casing, entity: ent.entity }
  }
  if (method === 'POST') {
    const v = pathVar(op.path)
    if (v || op.path.includes(':')) return { kind: 'action', table, casing, entity: ent.entity, idParam: v }
    return { kind: 'create', table, casing, entity: ent.entity }
  }
  // PUT/PATCH/DELETE
  return { kind: 'action', table, casing, entity: ent.entity, idParam: pathVar(op.path) }
}

/** 纯函数：给定“表是否存在”谓词即可分类，供离线覆盖率报告复用（不依赖已连库）*/
export function classifyOp(op, has = () => false) {
  return classify(op, has)
}

const registry = new Map()   // templateKey -> binding
let built = false

export async function buildRegistry() {
  await loadTables()
  registry.clear()
  for (const [key, op] of routeIndex) registry.set(key, classify(op))
  built = true
  return coverage()
}

export function ensureBuilt() {
  return built
}

export function getBinding(templateKey) {
  return registry.get(templateKey) || null
}

export function coverage() {
  const tally = { list: 0, read: 0, create: 0, action: 0, passthrough: 0 }
  const bound = []
  const skip = []
  for (const [key, b] of registry) {
    tally[b.kind] = (tally[b.kind] || 0) + 1
    if (b.kind === 'passthrough') skip.push({ key, reason: b.reason })
    else bound.push({ key, table: b.table, kind: b.kind })
  }
  return { total: registry.size, tally, bound, skip }
}
