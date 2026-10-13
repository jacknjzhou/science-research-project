/**
 * 离线覆盖率审计：无需连库，直接用 design/*.sql 里出现的表名当作 information_schema 的等价集合，
 * 跑一遍 registry 的生成式分类，报告 249 条路由里有多少能真正绑定到业务表、哪些落为 passthrough 及原因。
 * 用途：在 docker 起库前，先预判 DB_MODE=pg 会接管哪些路由、哪些仍走参考实现，并暴露"表名漂移"（契约实体名→表名与 DDL 不一致）。
 *   运行：npm run coverage   （或 node scripts/coverage-report.mjs）
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadAll, routeIndex } from '../src/schema.js'
import { classifyOp } from '../src/registry.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const DESIGN_DIR = path.resolve(__dirname, '..', '..', 'design')

// Postgres 对未加引号的标识符做大小写折叠 → 一律小写存储。故把 DDL 表名按小写入库集合比对。
function ddlTableSet() {
  const set = new Set()
  for (const f of fs.readdirSync(DESIGN_DIR)) {
    if (!f.endsWith('.sql')) continue
    const txt = fs.readFileSync(path.join(DESIGN_DIR, f), 'utf8')
    const re = /CREATE\s+(?:FOREIGN\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_."]+)/gi
    let m
    while ((m = re.exec(txt))) {
      let name = m[1].replace(/"/g, '').toLowerCase()
      if (name.includes('.')) name = name.split('.').pop() // schema.table → table
      set.add(name)
    }
  }
  return set
}

loadAll()
const tables = ddlTableSet()
const has = (t) => tables.has(t)

const tally = { list: 0, read: 0, create: 0, action: 0, passthrough: 0 }
const bound = []
const passthrough = []
for (const [key, op] of routeIndex) {
  const b = classifyOp(op, has)
  tally[b.kind] = (tally[b.kind] || 0) + 1
  if (b.kind === 'passthrough') passthrough.push({ key, reason: b.reason })
  else bound.push({ key, table: b.table, kind: b.kind })
}

const total = routeIndex.size
const boundCount = tally.list + tally.read + tally.create + tally.action

console.log(`\n=== 契约→表 生成式绑定覆盖审计（离线，对照 design/*.sql 的 ${tables.size} 张表）===`)
console.log(`路由总数 ${total}  已绑定 ${boundCount}（list=${tally.list} read=${tally.read} create=${tally.create} action=${tally.action}）  passthrough=${tally.passthrough}`)

// 按原因归类 passthrough
const byReason = new Map()
for (const p of passthrough) byReason.set(p.reason, (byReason.get(p.reason) || 0) + 1)
const sorted = [...byReason.entries()].sort((a, b) => b[1] - a[1])
console.log(`\n— passthrough 原因分布 —`)
for (const [r, n] of sorted) console.log(`  ${String(n).padStart(3)}  ${r}`)

// 表名漂移：因"表 X 不存在"落空的，正是契约实体名与 DDL 命名不一致，可据此补 typed 或改名
const drift = passthrough.filter((p) => /^表 .+ 不存在/.test(p.reason))
if (drift.length) {
  console.log(`\n— ⚠ 表名漂移（补契约 typed 响应 或 对齐 DDL 命名 后可纳入库路径）—`)
  for (const d of drift) console.log(`  ✗ ${d.key}  →  ${d.reason}`)
}

// 泛型 Ok 的 GET 列表/详情：这些是"本可落库但契约未描述实体"的候选，补 typed schema 即可接管
const generic = passthrough.filter((p) => /泛型 Ok|计算列/.test(p.reason) && /^GET /.test(p.key))
if (generic.length) {
  console.log(`\n— 泛型 Ok 的 GET（${generic.length} 条，分析/聚合类应保持 passthrough；确属业务表列表的再补 typed）—`)
  for (const g of generic) console.log(`  · ${g.key}`)
}

console.log(`\n— 已绑定样例（前 20）—`)
for (const b of bound.slice(0, 20)) console.log(`  ✓ ${b.kind.padEnd(6)} ${b.key}  →  ${b.table}`)
