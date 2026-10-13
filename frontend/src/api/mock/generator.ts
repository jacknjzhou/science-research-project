/**
 * schema → 拟真样例值生成器（契约驱动 mock 的核心）。
 * 规则优先级：override/example/default → enum → type+format → $ref/allOf/oneOf/anyOf → 兜底。
 */
import { fakerZH_CN as faker } from '@faker-js/faker'
import { resolveRef, type SpecDoc } from '../schema'

// 中文人名/机构语义增强：让 id 号段与业务号更贴合科研项目
let seqCounter = 1000
function nextSeq(): number {
  return seqCounter++
}

interface GenCtx {
  doc: any
  depth?: number
}

function genString(schema: any, keyHint: string): string {
  const fmt = schema?.format
  const enumVals = schema?.enum
  if (enumVals && enumVals.length) {
    return String(faker.helpers.arrayElement(enumVals))
  }
  if (schema?.example != null) return String(schema.example)
  if (schema?.pattern && keyHint.toLowerCase().includes('code')) {
    // 保留 pattern，但生成人可读编号
  }
  const k = (keyHint || '').toLowerCase()
  switch (fmt) {
    case 'date':
      return faker.date.recent(30).toISOString().slice(0, 10)
    case 'date-time':
      return faker.date.recent(30).toISOString()
    case 'email':
      return faker.internet.email().toLowerCase()
    case 'uuid':
      return faker.string.uuid()
    case 'uri':
    case 'url':
      return faker.internet.url()
  }
  if (k.includes('phone') || k.includes('mobile')) return faker.phone.number('138####1234')
  if (k.includes('idcard') || k.includes('identity')) return '310***********1234'
  if (k.endsWith('_name') || k === 'name' || k.includes('title')) return pickNameish(keyHint)
  if (k.includes('code')) return pickCodeish(keyHint)
  if (k.includes('summary') || k.includes('desc') || k.includes('note') || k.includes('content') || k.includes('answer') || k.includes('remark'))
    return faker.lorem.sentence(faker.number.int({ min: 8, max: 20 }))
  if (k.includes('url') || k.includes('path') || k.includes('file')) return faker.internet.url()
  if (k.includes('unit')) return faker.helpers.arrayElement(['项', '万元', '篇', '件', '%', '人'])
  if (k.includes('role')) return faker.helpers.arrayElement(['R-STAFF', 'R-MANAGER', 'R-LEADER', 'R-FINANCE', 'R-AUDITOR'])
  if (k.includes('level')) return faker.helpers.arrayElement(['HIGH', 'MED', 'LOW'])
  return faker.lorem.words(faker.number.int({ min: 1, max: 3 }))
}

function pickNameish(keyHint: string): string {
  const k = keyHint.toLowerCase()
  if (k.includes('dept') || k.includes('department') || k.includes('org'))
    return faker.helpers.arrayElement(['先进制造研究中心', '智能机器人实验室', '新材料研究所', '信息科学部', '生物医学工程室', '空天动力研究室'])
  if (k.includes('project') || k.includes('prj') || k.includes('protocol'))
    return faker.helpers.arrayElement([
      '面向高端装备的多轴机床颤振主动抑制方法研究',
      '基于扩散模型的拓扑优化生成式设计',
      '高温合金涡轮叶片服役行为与寿命预测',
      '人形机器人柔顺控制与全身动力学',
      '新型钙钛矿光伏组件稳定性机理',
    ]) + faker.helpers.maybe(() => '（' + faker.number.int({ min: 1, max: 3 }) + '期）' , { probability: 0.3 }) || ''
  if (k.includes('peer') || k.includes('institute'))
    return faker.helpers.arrayElement(['中科院某所', '清华某实验室', '上海交大某中心', '哈工大某研究组', '某省实验室'])
  if (k.includes('partner') || k.includes('company') || k.includes('supplier'))
    return faker.helpers.arrayElement(['华为技术', '比亚迪精密', '某装备制造集团', '中科智能', '某新材料公司', '某医疗器械厂'])
  if (k.includes('user') || k.includes('staff') || k.includes('pi') || k.includes('custodian'))
    return faker.person.fullName()
  return faker.person.fullName()
}

function pickCodeish(keyHint: string): string {
  const y = new Date().getFullYear()
  const k = keyHint.toLowerCase()
  const map: Record<string, string> = {
    expense: 'EXP', budget: 'BUD', project: 'PRJ', prj: 'PRJ',
    report: 'RPT', screen: 'SCR', subscription: 'SUB', metric: 'MET',
    asset: 'AST', disposal: 'DSP', purchase: 'REQ', order: 'ORD',
    contract: 'CON', supplier: 'SUP', disclosure: 'DIS', deal: 'DEAL',
    ethics: 'ETH', flow: 'EXF', legal: 'LE',
  }
  const pre = map[k] || faker.helpers.arrayElement(['BIZ', 'DOC'])
  return `${pre}-${y}-${String(nextSeq()).padStart(5, '0')}`
}

function genNumber(schema: any, keyHint: string): number {
  if (schema?.enum && schema.enum.length) return Number(faker.helpers.arrayElement(schema.enum))
  if (schema?.example != null && !isNaN(Number(schema.example))) return Number(schema.example)
  const k = (keyHint || '').toLowerCase()
  const min = schema?.minimum ?? 0
  const max = schema?.maximum ?? undefined
  if (k === 'id' || k.endsWith('_id')) return nextSeq()
  if (k.includes('amount') || k.includes('value') || k.includes('price') || k.includes('cost') || k.includes('income') || k.includes('budget'))
    return Number(faker.finance.amount({ min: 1000, max: 5_000_000, dec: 2 }))
  if (k.includes('rate') || k.includes('pct') || k.includes('percent') || k.includes('confidence') || k.includes('score'))
    return Number((faker.number.float({ min: 0, max: 1 }) ).toFixed(4))
  if (k.includes('year')) return faker.number.int({ min: 2019, max: 2026 })
  if (k.includes('count') || k.includes('qty') || k.includes('total') || k.includes('num'))
    return faker.number.int({ min: 1, max: 200 })
  if (k.includes('rank')) return faker.number.int({ min: 1, max: 20 })
  return faker.number.int({ min, max: max ?? 9999 })
}

function genBoolean(schema: any): boolean {
  if (schema?.example != null) return Boolean(schema.example)
  return faker.datatype.boolean()
}

export function generate(schema: any, ctx: GenCtx, keyHint = '', depth = 0): unknown {
  if (!schema) return null
  if (depth > 16) return null

  // $ref
  if (schema.$ref) {
    const target = resolveRef(ctx.doc, schema.$ref)
    return generate(target, ctx, keyHint, depth + 1)
  }
  // allOf：合并各子 schema 的 properties
  if (Array.isArray(schema.allOf)) {
    const merged: any = { type: 'object', properties: {} }
    for (const sub of schema.allOf) {
      const r = generate(sub, ctx, keyHint, depth + 1)
      if (r && typeof r === 'object') Object.assign(merged.properties, r)
    }
    return merged.properties
  }
  if (Array.isArray(schema.oneOf) && schema.oneOf.length) {
    return generate(faker.helpers.arrayElement(schema.oneOf), ctx, keyHint, depth + 1)
  }
  if (Array.isArray(schema.anyOf) && schema.anyOf.length) {
    return generate(schema.anyOf[0], ctx, keyHint, depth + 1)
  }

  let type = schema.type
  if (!type && schema.properties) type = 'object'
  if (!type && schema.items) type = 'array'
  if (!type && (schema.enum || schema.example)) {
    return schema.example ?? faker.helpers.arrayElement(schema.enum)
  }

  switch (type) {
    case 'object': {
      // additionalProperties:true 的自由对象
      const props = schema.properties || {}
      const out: Record<string, unknown> = {}
      const keys = Object.keys(props)
      if (keys.length === 0 && schema.additionalProperties && typeof schema.additionalProperties === 'object') {
        // 生成少量动态列（如 rows 的 additionalProperties）
        for (let i = 0; i < 3; i++) {
          out[`col_${i}`] = generate(schema.additionalProperties, ctx, 'value', depth + 1)
        }
        return out
      }
      for (const key of keys) {
        const sub = props[key]
        // nullable：小概率置 null，但 id/code/status/created_at 保留
        const isCore = ['id', 'code', 'status', 'created_at', 'updated_at', 'name', 'list', 'total', 'page', 'size'].includes(key)
        if (sub?.nullable && !isCore && faker.datatype.boolean({ probability: 0.12 })) {
          out[key] = null
          continue
        }
        out[key] = generate(sub, ctx, key, depth + 1)
      }
      return out
    }
    case 'array': {
      const n = schema.minItems
        ? Math.max(schema.minItems, 0)
        : faker.number.int({ min: 3, max: 8 })
      const arr: unknown[] = []
      for (let i = 0; i < n; i++) {
        const item = generate(schema.items, ctx, keyHint, depth + 1)
        // 数组元素若为 object，给稳定自增 id
        if (item && typeof item === 'object' && 'id' in (item as any)) {
          (item as any).id = nextSeq()
        }
        arr.push(item)
      }
      return arr
    }
    case 'string':
      return genString(schema, keyHint)
    case 'integer':
    case 'number':
      return genNumber(schema, keyHint)
    case 'boolean':
      return genBoolean(schema)
    case 'null':
      return null
    default:
      return schema?.example ?? null
  }
}
