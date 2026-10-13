/**
 * 假连接（fake pool）单测：无需真实 Postgres，验证 list/read/create 生成的 SQL
 * 与 information_schema 白名单过滤、参数化、row→api（snake/camel、Date→ISO、NUMERIC 保串、JSONB stringify）映射。
 *   运行：npm run dbtest   （或 node scripts/db.adapter.test.mjs）
 * 说明：db.js 的 q() 调用 pool().query(sql,params) 并取 .rows；这里注入假 pool 拦截并录制每条 SQL。
 */
process.env.DB_MODE = 'pg'
process.env.DATABASE_URL = 'postgres://fake/fake' // 仅为满足 dbEnabled；实际查询走注入的假 pool

import assert from 'node:assert'
import { setPool } from '../src/db.js'
import { loadTables, columnsInfo, apiToRow, rowToApi } from '../src/mapping.js'
import { listRows, readRow, createRow } from '../src/adapters.js'

const COLUMNS = [
  { column_name: 'id', data_type: 'bigint', is_generated: 'NEVER', identity_generation: 'ALWAYS' },
  { column_name: 'code', data_type: 'character varying', is_generated: 'NEVER', identity_generation: null },
  { column_name: 'title', data_type: 'character varying', is_generated: 'NEVER', identity_generation: null },
  { column_name: 'budget_amount', data_type: 'numeric', is_generated: 'NEVER', identity_generation: null },
  { column_name: 'tags', data_type: 'jsonb', is_generated: 'NEVER', identity_generation: null },
  { column_name: 'status', data_type: 'character varying', is_generated: 'NEVER', identity_generation: null },
  { column_name: 'legal_entity_id', data_type: 'bigint', is_generated: 'NEVER', identity_generation: null },
  { column_name: 'deleted', data_type: 'smallint', is_generated: 'NEVER', identity_generation: null },
  { column_name: 'created_at', data_type: 'timestamp with time zone', is_generated: 'NEVER', identity_generation: null },
]

function sampleRow() {
  return {
    id: 42n,
    code: 'APP-0042',
    title: '面向科研院所的项目',
    budget_amount: '1000.00', // NUMERIC 驱动本就返回字符串
    tags: ['a', 'b'],
    status: 'DRAFT',
    legal_entity_id: 7n,
    deleted: 0,
    created_at: new Date('2026-01-02T03:04:05.000Z'),
  }
}

function makeFakePool() {
  const calls = []
  return {
    calls,
    async query(sql, params) {
      calls.push({ sql: sql.replace(/\s+/g, ' ').trim(), params })
      if (/FROM information_schema\.tables/.test(sql)) {
        return { rows: [{ table_schema: 'public', table_name: 'p_application' }] }
      }
      if (/FROM information_schema\.columns/.test(sql)) {
        return { rows: COLUMNS }
      }
      if (/SELECT count\(\*\)::bigint/.test(sql)) {
        return { rows: [{ n: '3' }] }
      }
      if (/^INSERT INTO/.test(sql.replace(/\s+/g, ' ').trim())) {
        // 回显：把插入参数映射回一条行（仅测试断言用）
        return { rows: [sampleRow()] }
      }
      if (/^UPDATE/.test(sql.replace(/\s+/g, ' ').trim())) {
        return { rows: [{ id: 42n }] }
      }
      if (/^SELECT \* FROM/.test(sql.replace(/\s+/g, ' ').trim())) {
        return { rows: [sampleRow()] }
      }
      return { rows: [] }
    },
    async end() {},
  }
}

const pool = makeFakePool()
setPool(pool)

const results = []
function check(name, fn) {
  return Promise.resolve()
    .then(fn)
    .then(() => results.push({ name, ok: true }))
    .catch((e) => results.push({ name, ok: false, err: e.message }))
}

const binding = { kind: 'list', table: 'p_application', casing: 'snake', entity: 'Application', idParam: 'id' }

async function main() {
  // 预热内省缓存（loadTables + columnsInfo）
  await loadTables()
  await columnsInfo('p_application')

  await check('apiToRow 过滤不可写列(id GENERATED ALWAYS)与未知键、JSONB stringify', async () => {
    const { cols, vals } = await apiToRow('p_application', {
      id: 999, // 应被剔除（identity always）
      code: 'APP-1',
      title: 'T',
      budget_amount: '5.00',
      tags: { k: 1 },
      status: 'DRAFT',
      bogus_field: 'x', // 未知列应被忽略
    })
    assert.ok(!cols.includes('id'), 'id 不可写入')
    assert.ok(!cols.includes('bogus_field'), '未知键应忽略')
    assert.ok(cols.includes('code') && cols.includes('tags'))
    const tagIdx = cols.indexOf('tags')
    assert.equal(vals[tagIdx], JSON.stringify({ k: 1 }), 'JSONB 应 stringify')
  })

  await check('listRows：软删除 + 白名单等值过滤 + 分页 LIMIT/OFFSET', async () => {
    const before = pool.calls.length
    const out = await listRows(binding, { page: 2, size: 10, status: 'DRAFT', notAColumn: 'zzz' })
    const countCall = pool.calls.slice(before).find((c) => /count\(\*\)/.test(c.sql))
    const selCall = pool.calls.slice(before).find((c) => /^SELECT \* FROM/.test(c.sql))
    assert.ok(countCall, '应发 count 查询')
    assert.ok(/deleted = 0/.test(countCall.sql), 'WHERE 应含 deleted = 0')
    assert.ok(/"status" = \$1/.test(countCall.sql), 'status 应作为白名单等值过滤')
    assert.ok(!/not_a_column/.test(countCall.sql), '非白名单列不得进 WHERE')
    assert.deepEqual(countCall.params, ['DRAFT'])
    assert.ok(/LIMIT \$2 OFFSET \$3/.test(selCall.sql), '分页占位紧随过滤参数')
    assert.deepEqual(selCall.params, ['DRAFT', 10, 10], 'page=2,size=10 → offset=10')
    assert.equal(out.total, 3, 'total 来自 count')
    assert.equal(out.page, 2)
    assert.equal(out.size, 10)
    assert.ok(Array.isArray(out.list) && out.list.length === 1)
  })

  await check('readRow：主键参数化 + 软删除 + Date→ISO + NUMERIC 保字符串', async () => {
    const before = pool.calls.length
    const row = await readRow(binding, { id: '42' })
    const call = pool.calls[before]
    assert.ok(/^SELECT \* FROM p_application WHERE "id" = \$1 AND deleted = 0 LIMIT 1$/.test(call.sql), `SQL 不符：${call.sql}`)
    assert.deepEqual(call.params, [42], 'id 应转 Number')
    assert.equal(row.created_at, '2026-01-02T03:04:05.000Z', 'Date 应转 ISO')
    assert.equal(row.budget_amount, '1000.00', 'NUMERIC 应保持字符串')
    assert.ok('code' in row && 'status' in row, 'snake 键直出')
  })

  await check('createRow：INSERT 只含可写真实列 + RETURNING * + 行回映射', async () => {
    const before = pool.calls.length
    const out = await createRow(binding, { code: 'APP-2', title: 'X', tags: ['m'], status: 'DRAFT' })
    const call = pool.calls.slice(before).find((c) => /^INSERT INTO/.test(c.sql))
    assert.ok(call, '应发 INSERT')
    assert.ok(!/"id"/.test(call.sql), 'id 不应出现在 INSERT 列')
    assert.ok(/"code", "title", "tags", "status"/.test(call.sql), `列集合不符：${call.sql}`)
    assert.ok(/RETURNING \*$/.test(call.sql))
    const tagIdx = ['code', 'title', 'tags', 'status'].indexOf('tags')
    assert.equal(call.params[tagIdx], JSON.stringify(['m']), 'tags→JSON 串')
    assert.equal(out.code, 'APP-0042')
  })

  await check('rowToApi camel 模式：snake 列名转 camel 键', () => {
    const camel = rowToApi('p_application', { legal_entity_id: 7, budget_amount: '1.00', created_at: new Date('2026-05-05T00:00:00.000Z') }, 'camel')
    assert.ok('legalEntityId' in camel, '应转 camelCase 键')
    assert.ok('budgetAmount' in camel)
    assert.equal(camel.created_at === undefined, true, '不应残留 snake 键')
    assert.equal(camel.created_at, undefined)
    assert.equal(camel.legalEntityId, 7)
  })

  const pass = results.filter((r) => r.ok).length
  const fail = results.length - pass
  for (const r of results) console.log(`${r.ok ? '✓' : '✗'} ${r.name}${r.ok ? '' : `\n    ${r.err}`}`)
  console.log(`\n[dbtest] ${pass}/${results.length} passed, ${fail} failed`)
  if (fail) process.exit(1)
}

main().catch((e) => { console.error(e); process.exit(1) })
