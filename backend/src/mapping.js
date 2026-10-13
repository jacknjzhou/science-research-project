/**
 * 列内省 + 命名映射：把 information_schema 的真实列集合作为唯一白名单，
 * 在 API JSON（P/E/F/R/T/C/S 用 snake_case，A/D 用 camelCase）与 DB 列（全 snake_case）之间双向换算。
 * 所有拼接进 SQL 的标识符都先经此白名单校验；值全部走 $n 参数。
 */
import { q } from './db.js'

export function toSnake(s) {
  return String(s).replace(/([a-z0-9])([A-Z])/g, '$1_$2').replace(/([A-Z]+)([A-Z][a-z])/g, '$1_$2').toLowerCase()
}
export function toCamel(s) {
  return String(s).replace(/_+([a-z0-9])/g, (_, c) => c.toUpperCase())
}

const SCHEMAS = "('public','dwh')"
let _tables = null            // Set<string>
const _cols = new Map()       // table -> Map<column, dataType>
const _insertable = new Map() // table -> string[]（可写列，排除 GENERATED ALWAYS 标识列）

export async function loadTables() {
  if (_tables) return _tables
  const rows = await q(
    `SELECT table_schema, table_name FROM information_schema.tables
       WHERE table_schema IN ${SCHEMAS} AND table_type IN ('BASE TABLE','VIEW')`)
  _tables = new Set(rows.map((r) => r.table_name))
  return _tables
}

export function hasTable(name) {
  return _tables ? _tables.has(name) : false
}

/** table -> Map(column -> data_type) */
export async function columnsInfo(table) {
  if (_cols.has(table)) return _cols.get(table)
  const rows = await q(
    `SELECT column_name, data_type, is_generated, identity_generation
       FROM information_schema.columns
      WHERE table_schema IN ${SCHEMAS} AND table_name = $1
      ORDER BY ordinal_position`, [table])
  const m = new Map()
  for (const r of rows) m.set(r.column_name, r)
  _cols.set(table, m)
  return m
}

/** 可 INSERT/UPDATE 的列：排除 generated always 标识列（id 由库自管），排除只算生成列 */
export async function insertableColumns(table) {
  if (_insertable.has(table)) return _insertable.get(table)
  const info = await columnsInfo(table)
  const cols = []
  for (const [name, meta] of info) {
    if (String(meta.identity_generation || '').toLowerCase() === 'always') continue
    if (String(meta.is_generated || '').toLowerCase() === 'always') continue
    cols.push(name)
  }
  _insertable.set(table, cols)
  return cols
}

function isJsonType(t) {
  return t === 'json' || t === 'jsonb'
}

function jsonColsOf(info) {
  const s = new Set()
  for (const [name, meta] of info) if (isJsonType(meta.data_type)) s.add(name)
  return s
}

/**
 * API 对象 -> { cols:string[], vals:any[] }：key 归一到 snake，仅保留真实列；
 * JSONB 列把对象/数组 stringify；未知键忽略。
 */
export async function apiToRow(table, apiObj) {
  const info = await columnsInfo(table)
  const writable = new Set(await insertableColumns(table))
  const jsonCols = jsonColsOf(info)
  const cols = []
  const vals = []
  for (const [k, v] of Object.entries(apiObj || {})) {
    const col = toSnake(k)
    if (!writable.has(col)) continue
    if (v === undefined) continue
    if (jsonCols.has(col)) {
      cols.push(col)
      vals.push(typeof v === 'string' ? v : JSON.stringify(v))
    } else {
      cols.push(col)
      vals.push(v)
    }
  }
  return { cols, vals, info }
}

/** 生成参数化 INSERT ... RETURNING * */
export function buildInsert(table, { cols, vals }) {
  if (!cols.length) {
    // 无可写列：插入默认行，靠列默认值/自增
    return { sql: `INSERT INTO ${table} DEFAULT VALUES RETURNING *`, params: [] }
  }
  const idents = cols.map((c) => `"${c}"`).join(', ')
  const holders = vals.map((_, i) => `$${i + 1}`).join(', ')
  return { sql: `INSERT INTO ${table} (${idents}) VALUES (${holders}) RETURNING *`, params: vals }
}

/** DB 行 -> API 对象：按 casing 输出 snake 或 camel；Date→ISO；NUMERIC 保持字符串（贴合契约）*/
export function rowToApi(table, row, casing = 'snake') {
  if (!row) return null
  const out = {}
  for (const [col, val] of Object.entries(row)) {
    let v = val
    if (v instanceof Date) v = v.toISOString()
    const key = casing === 'camel' ? toCamel(col) : col
    out[key] = v
  }
  return out
}

/** 把若干行按 casing 转 API */
export function rowsToApi(table, rows, casing = 'snake') {
  return (rows || []).map((r) => rowToApi(table, r, casing))
}
