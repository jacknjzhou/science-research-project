import { loadAll, routeIndex, extractDataSchema, specs } from '../src/schema.js'
import { generate } from '../src/generator.js'
loadAll()
const op = [...routeIndex.values()].find(o=>o.method==='get'&&o.path==='/project/{id}/risk-warnings')
const doc = specs.find(s=>s.module===op.module)?.doc
const ds = extractDataSchema(op)
console.log('DATA SCHEMA:', JSON.stringify(ds, null, 1).slice(0, 800))
const data = generate(ds, {doc})
console.log('GENERATED:', JSON.stringify(data, null, 1).slice(0, 600))
