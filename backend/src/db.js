/**
 * PostgreSQL 连接层（A 路线：真连库后端）。
 * - 仅当 DB_MODE=pg 且给出连接串（DATABASE_URL 或 PGHOST）时启用；否则后端仍是进程内 mock，零回归。
 * - Pool 惰性创建；测试可用 setPool(fake) 注入假连接，验证生成的 SQL 与行映射而不需真库。
 * - 标识符（表名/列名）一律来自 information_schema 白名单，值一律参数化 —— 杜绝注入。
 */
import pg from 'pg'

const { Pool } = pg

let _pool = null

export function dbMode() {
  return String(process.env.DB_MODE || '').trim().toLowerCase()
}

export function dbEnabled() {
  return dbMode() === 'pg' && !!(process.env.DATABASE_URL || process.env.PGHOST)
}

export function pool() {
  if (!_pool) {
    const cfg = {
      connectionString: process.env.DATABASE_URL || undefined,
      max: Number(process.env.PG_POOL_MAX || 10),
      idleTimeoutMillis: 30000,
      connectionTimeoutMillis: 5000,
    }
    // DATABASE_URL 缺省时回退到 PG* 标准环境变量（host/port/user/password/database）
    if (!cfg.connectionString) {
      if (process.env.PGHOST) cfg.host = process.env.PGHOST
      if (process.env.PGPORT) cfg.port = Number(process.env.PGPORT)
      if (process.env.PGUSER) cfg.user = process.env.PGUSER
      if (process.env.PGPASSWORD) cfg.password = process.env.PGPASSWORD
      if (process.env.PGDATABASE) cfg.database = process.env.PGDATABASE
    }
    if (String(process.env.PGSSLMODE || '') === 'disable') cfg.ssl = false
    _pool = new Pool(cfg)
    _pool.on('error', (e) => console.error('[db] pool error:', e.message))
  }
  return _pool
}

/** 测试注入：传入带 query() 的假对象替代真实 Pool */
export function setPool(p) {
  _pool = p
}

export async function q(sql, params) {
  const res = await pool().query(sql, params)
  return res.rows
}

export async function q1(sql, params) {
  const rows = await q(sql, params)
  return rows[0] || null
}

export async function ping() {
  const r = await q1('SELECT 1 AS ok')
  return r && r.ok === 1
}

export async function closePool() {
  if (_pool && typeof _pool.end === 'function') await _pool.end()
  _pool = null
}
