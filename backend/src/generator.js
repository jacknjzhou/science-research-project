/**
 * schema -> 拟真样例值生成器（契约驱动 mock 的核心，Node 版）。
 * 与前端 frontend/src/api/mock/generator.ts 同逻辑：
 * 优先级 $ref/allOf/oneOf/anyOf -> type+format -> enum/example -> keyHint 启发式 -> 兜底。
 * 产出严格贴合契约 schema 的数据（含各模块自身的命名风格：P 用 snake_case，E 用 camelCase）。
 */
import { fakerZH_CN as faker } from '@faker-js/faker'
import { resolveRef } from './schema.js'

let seqCounter = 1000
function nextSeq() { return seqCounter++ }

function pickNameish(keyHint) {
  const k = (keyHint || '').toLowerCase()
  if (k.includes('dept') || k.includes('department') || k.includes('org'))
    return faker.helpers.arrayElement(['先进制造研究中心', '智能机器人实验室', '新材料研究所', '信息科学部', '生物医学工程室', '空天动力研究室'])
  if (k.includes('project') || k.includes('prj') || k.includes('protocol'))
    return faker.helpers.arrayElement([
      '面向高端装备的多轴机床颤振主动抑制方法研究',
      '基于扩散模型的拓扑优化生成式设计',
      '高温合金涡轮叶片服役行为与寿命预测',
      '人形机器人柔顺控制与全身动力学',
      '新型钙钛矿光伏组件稳定性机理',
    ])
  if (k.includes('peer') || k.includes('institute'))
    return faker.helpers.arrayElement(['中科院某所', '清华某实验室', '上海交大某中心', '哈工大某研究组', '某省实验室'])
  if (k.includes('partner') || k.includes('company') || k.includes('supplier'))
    return faker.helpers.arrayElement(['华为技术', '比亚迪精密', '某装备制造集团', '中科智能', '某新材料公司', '某医疗器械厂'])
  return faker.person.fullName()
}

function pickCodeish(keyHint) {
  const y = new Date().getFullYear()
  const k = (keyHint || '').toLowerCase()
  const map = {
    expense: 'EXP', budget: 'BUD', project: 'PRJ', prj: 'PRJ',
    report: 'RPT', screen: 'SCR', subscription: 'SUB', metric: 'MET',
    asset: 'AST', disposal: 'DSP', purchase: 'REQ', order: 'ORD',
    contract: 'CON', supplier: 'SUP', disclosure: 'DIS', deal: 'DEAL',
    ethics: 'ETH', flow: 'EXF', legal: 'LE', output: 'OUT', paper: 'PUB',
    patent: 'PAT', invoice: 'INV', change: 'CHG', task: 'TSK',
  }
  const pre = map[k] || faker.helpers.arrayElement(['BIZ', 'DOC'])
  return `${pre}-${y}-${String(nextSeq()).padStart(5, '0')}`
}

// 从 enum 中取一个具体值；可空枚举（如 next_level:[ADS,DWS,DWD,BIZ,null]）先剔除 null 候选，
// 避免 String(null)="null" 被契约 enum 判为非法值（间歇性 verify 失败根因）。全为 null 时才返回 null。
function pickEnum(schema, coerce) {
  const vals = schema.enum.filter((v) => v !== null && v !== undefined)
  if (!vals.length) return null
  return coerce(faker.helpers.arrayElement(vals))
}

function genString(schema, keyHint) {
  if (schema?.enum && schema.enum.length) return pickEnum(schema, String)
  if (schema?.example != null) return String(schema.example)
  const fmt = schema?.format
  const k = (keyHint || '').toLowerCase()
  switch (fmt) {
    case 'date': return faker.date.recent({ days: 30 }).toISOString().slice(0, 10)
    case 'date-time': return faker.date.recent({ days: 30 }).toISOString()
    case 'email': return faker.internet.email().toLowerCase()
    case 'uuid': return faker.string.uuid()
    case 'uri': case 'url': return faker.internet.url()
  }
  if (k.includes('phone') || k.includes('mobile')) return '138' + String(faker.number.int({ min: 10000000, max: 99999999 }))
  if (k.includes('idcard') || k.includes('identity')) return '310***********1234'
  // 比率：契约以 string 承载 0~1 小数（如 budgetExecRate），须早于金额判定，避免含 budget 的比率被当金额
  if (k.includes('rate') || k.includes('ratio') || k.includes('pct') || k.includes('percent'))
    return faker.number.float({ min: 0, max: 1 }).toFixed(4)
  // 金额：契约以 string 承载 NUMERIC(18,2) 精度，产出两位小数的数字字符串（非 lorem）
  const desc = String(schema?.description || '')
  if (k.includes('budget') || k.includes('amount') || k.includes('envelope') || k.includes('received') ||
      k.includes('spent') || k.includes('cost') || k.includes('price') || k.includes('money') || k.includes('fee') ||
      /NUMERIC|金额/.test(desc))
    return faker.finance.amount({ min: 1000, max: 5000000, dec: 2 })
  if (k.endsWith('_name') || k === 'name' || k.includes('title')) return pickNameish(keyHint)
  if (k.includes('code')) return pickCodeish(keyHint)
  if (k.includes('summary') || k.includes('desc') || k.includes('note') || k.includes('content') || k.includes('answer') || k.includes('remark') || k.includes('reason') || k.includes('suggestion'))
    return faker.lorem.sentence({ min: 8, max: 20 })
  if (k.includes('url') || k.includes('path') || k.includes('file')) return faker.internet.url()
  if (k.includes('unit')) return faker.helpers.arrayElement(['项', '万元', '篇', '件', '%', '人'])
  if (k.includes('role')) return faker.helpers.arrayElement(['R-STAFF', 'R-MANAGER', 'R-LEADER', 'R-FINANCE', 'R-AUDITOR'])
  if (k.includes('level') || k.includes('risk')) return faker.helpers.arrayElement(['HIGH', 'MED', 'LOW'])
  if (k.includes('status') || k.includes('state')) return ''
  return faker.lorem.words(faker.number.int({ min: 1, max: 3 }))
}

function genNumber(schema, keyHint) {
  if (schema?.enum && schema.enum.length) return pickEnum(schema, Number)
  if (schema?.example != null && !isNaN(Number(schema.example))) return Number(schema.example)
  const k = (keyHint || '').toLowerCase()
  const min = schema?.minimum ?? undefined
  const max = schema?.maximum ?? undefined
  let v
  if (k === 'id' || k.endsWith('_id') || k.endsWith('id')) v = nextSeq()
  else if (k.includes('amount') || k.includes('value') || k.includes('price') || k.includes('cost') || k.includes('income') || k.includes('budget') || k.includes('envelope'))
    v = Number(faker.finance.amount({ min: 1000, max: 5000000, dec: 2 }))
  else if (k.includes('rate') || k.includes('pct') || k.includes('percent') || k.includes('confidence'))
    v = Number(faker.number.float({ min: 0, max: 1 }).toFixed(4))
  else if (k.includes('score')) v = faker.number.int({ min: 40, max: 100 })
  else if (k.includes('year')) v = faker.number.int({ min: 2019, max: 2026 })
  else if (k.includes('count') || k.includes('qty') || k.includes('total') || k.includes('num') || k.includes('weight'))
    v = faker.number.int({ min: 1, max: 200 })
  else if (k.includes('rank')) v = faker.number.int({ min: 1, max: 20 })
  else v = faker.number.int({ min: min ?? 0, max: max ?? 9999 })
  if (schema?.type === 'integer') v = Math.round(v)
  if (min != null && v < min) v = min
  if (max != null && v > max) v = max
  return v
}

function genBoolean(schema) {
  if (schema?.example != null) return Boolean(schema.example)
  return faker.datatype.boolean()
}

export function generate(schema, ctx, keyHint = '', depth = 0) {
  if (!schema) return null
  ctx = ctx || { doc: null }
  if (depth > 16) return null

  if (schema.$ref) {
    return generate(resolveRef(ctx.doc, schema.$ref), ctx, keyHint, depth + 1)
  }
  if (Array.isArray(schema.allOf)) {
    const merged = {}
    for (const sub of schema.allOf) {
      const r = generate(sub, ctx, keyHint, depth + 1)
      if (r && typeof r === 'object' && !Array.isArray(r)) Object.assign(merged, r)
    }
    return merged
  }
  if (Array.isArray(schema.oneOf) && schema.oneOf.length) return generate(faker.helpers.arrayElement(schema.oneOf), ctx, keyHint, depth + 1)
  if (Array.isArray(schema.anyOf) && schema.anyOf.length) return generate(schema.anyOf[0], ctx, keyHint, depth + 1)

  let type = schema.type
  if (!type && schema.properties) type = 'object'
  if (!type && schema.items) type = 'array'
  if (!type && (schema.enum || schema.example != null)) {
    return schema.example != null ? schema.example : faker.helpers.arrayElement(schema.enum)
  }

  switch (type) {
    case 'object': {
      const props = schema.properties || {}
      const out = {}
      const keys = Object.keys(props)
      if (keys.length === 0 && schema.additionalProperties && typeof schema.additionalProperties === 'object') {
        for (let i = 0; i < 3; i++) out[`col_${i}`] = generate(schema.additionalProperties, ctx, 'value', depth + 1)
        return out
      }
      for (const key of keys) {
        const sub = props[key]
        const isCore = ['id', 'code', 'status', 'created_at', 'updated_at', 'name', 'list', 'total', 'page', 'size'].includes(key)
        if (sub?.nullable && !isCore && faker.datatype.boolean({ probability: 0.12 })) { out[key] = null; continue }
        out[key] = generate(sub, ctx, key, depth + 1)
      }
      return out
    }
    case 'array': {
      const n = schema.minItems ? Math.max(schema.minItems, 0) : faker.number.int({ min: 3, max: 8 })
      const arr = []
      for (let i = 0; i < n; i++) {
        const item = generate(schema.items, ctx, keyHint, depth + 1)
        if (item && typeof item === 'object' && !Array.isArray(item) && 'id' in item) item.id = nextSeq()
        arr.push(item)
      }
      return arr
    }
    case 'string': return genString(schema, keyHint)
    case 'integer': case 'number': return genNumber(schema, keyHint)
    case 'boolean': return genBoolean(schema)
    case 'null': return null
    default: return schema?.example ?? null
  }
}
