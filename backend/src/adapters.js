/**
 * pg 读写适配器：把已绑定到业务表的 CRUD 操作翻译成参数化 SQL。
 * 所有表名/列名来自 registry 绑定 + information_schema 白名单；值一律 $n 参数。
 * server 在 DB_MODE=pg 且操作命中绑定时调用；异常由 server 兜底回退 generate/flows。
 */
import { q, q1 } from './db.js'
import {
  toSnake, columnsInfo, apiToRow, buildInsert, rowToApi, rowsToApi,
} from './mapping.js'

async function colSet(table) {
  const info = await columnsInfo(table)
  return new Set(info.keys())
}

function pageArgs(query) {
  const page = Math.max(1, Number(query?.page || 1) || 1)
  const size = Math.min(200, Math.max(1, Number(query?.size || 20) || 20))
  return { page, size, offset: (page - 1) * size }
}

/** 读取排序列：优先 id DESC，退 created_at DESC，再退首个列 */
function pickOrder(cols) {
  if (cols.has('id')) return '"id" DESC'
  if (cols.has('created_at')) return '"created_at" DESC'
  const first = [...cols][0]
  return first ? `"${first}" ASC` : '1'
}

/**
 * 由 query 参数与列白名单组装 WHERE（软删除 + 精确等值过滤）。
 * 返回 { where:string[], params:any[] }，占位从 startIdx 起。
 */
async function buildWhere(table, query, startIdx = 1) {
  const cols = await colSet(table)
  const where = []
  const params = []
  if (cols.has('deleted')) where.push('deleted = 0')
  let i = startIdx
  for (const [k, raw] of Object.entries(query || {})) {
    if (raw === undefined || raw === null || raw === '') continue
    if (k === 'page' || k === 'size') continue
    const col = toSnake(k)
    if (!cols.has(col)) continue
    where.push(`"${col}" = $${i}`)
    params.push(raw)
    i++
  }
  return { where, params, next: i }
}

/** 列表分页 */
export async function listRows(binding, query) {
  const { table, casing } = binding
  const cols = await colSet(table)
  const { page, size, offset } = pageArgs(query)
  const w = await buildWhere(table, query, 1)
  const whereSql = w.where.length ? ' WHERE ' + w.where.join(' AND ') : ''

  const countRow = await q1(`SELECT count(*)::bigint AS n FROM ${table}${whereSql}`, w.params)
  const total = Number(countRow?.n ?? 0)

  const rows = await q(
    `SELECT * FROM ${table}${whereSql} ORDER BY ${pickOrder(cols)} LIMIT $${w.next} OFFSET $${w.next + 1}`,
    [...w.params, size, offset])
  return { list: rowsToApi(table, rows, casing), total, page, size }
}

/** 按主键读单条；找不到返回 null（server 转 40401） */
export async function readRow(binding, params) {
  const { table, casing, idParam } = binding
  const cols = await colSet(table)
  const candidates = [idParam ? toSnake(idParam) : null, 'id', toSnake(idParam || '')].filter(Boolean)
  const idCol = candidates.find((c) => cols.has(c)) || (cols.has('id') ? 'id' : null)
  if (!idCol) return null
  const raw = params?.[idParam]
  if (raw === undefined || raw === null) return null
  const val = idCol === 'id' ? Number(raw) : raw
  const softDel = cols.has('deleted') ? ' AND deleted = 0' : ''
  const row = await q1(`SELECT * FROM ${table} WHERE "${idCol}" = $1${softDel} LIMIT 1`, [val])
  return row ? rowToApi(table, row, casing) : null
}

/** 创建：body→列映射，参数化 INSERT RETURNING * */
export async function createRow(binding, body) {
  const { table, casing } = binding
  const mapped = await apiToRow(table, body || {})
  const { sql, params } = buildInsert(table, mapped)
  const row = await q1(sql, params)
  return row ? rowToApi(table, row, casing) : null
}

/** 状态机动作后回写：把 flow 产出的记录 upsert 到其绑定表（尽力而为；缺列自动忽略） */
export async function upsertRecord(binding, id, rec) {
  const { table } = binding
  const cols = await colSet(table)
  if (!cols.has('id') || id == null) return null
  const mapped = await apiToRow(table, rec || {})
  const setCols = mapped.cols.filter((c) => c !== 'id')
  if (!setCols.length) {
    // 无有效列可写：确保存在一行占位
    const exists = await q1(`SELECT id FROM ${table} WHERE id = $1`, [Number(id)])
    return exists ? 'noop' : null
  }
  // 先试 UPDATE，未命中再 INSERT（带 id 覆盖自增：用 OVERRIDING SYSTEM VALUE）
  const setSql = setCols.map((c, i) => `"${c}" = $${i + 1}`).join(', ')
  const whereId = ` WHERE id = $${setCols.length + 1}`
  const updRes = await q(`UPDATE ${table} SET ${setSql}${whereId} RETURNING id`,
    [...setCols.map((_, i) => mapped.vals[mapped.cols.indexOf(setCols[i])]), Number(id)])
  if (updRes.length) return 'updated'
  const allCols = ['id', ...setCols]
  const allVals = [Number(id), ...setCols.map((c) => mapped.vals[mapped.cols.indexOf(c)])]
  const holders = allVals.map((_, i) => `$${i + 1}`).join(', ')
  try {
    await q(
      `INSERT INTO ${table} (${allCols.map((c) => `"${c}"`).join(', ')}) VALUES (${holders}) ` +
      `OVERRIDING SYSTEM VALUE RETURNING id`, allVals)
    return 'inserted'
  } catch {
    return null
  }
}
