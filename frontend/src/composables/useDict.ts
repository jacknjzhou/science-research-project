/**
 * useDict · 数据字典消费端 composable（PRD 2.8：业务下拉统一走 sys_dict）。
 * - GET /dicts/{code}（全员只读，后端已过滤停用/未生效条目）
 * - 模块级 Promise 缓存：同码一次拉取全局复用
 * - fallback：字典缺失/后端异常时回退调用方传入的硬编码数组，保证 UI 不空下拉
 */
import { ref } from 'vue'
import { api } from '@/api/client'

export interface DictItemView {
  code: string
  label: string
  ext?: Record<string, any> | null
}
export interface DictItemRaw {
  id: number
  item_code: string
  item_label: string
  ext?: Record<string, any> | null
  [k: string]: any
}

const cache = new Map<string, Promise<DictItemView[]>>()

function fetchDict(code: string, fallback: DictItemView[]): Promise<DictItemView[]> {
  return api
    .get<{ items?: DictItemRaw[] }>(`/dicts/${encodeURIComponent(code)}`)
    .then((d) => {
      const list = (d?.items ?? []).map((i) => ({ code: i.item_code, label: i.item_label, ext: i.ext ?? null }))
      return list.length ? list : fallback
    })
    .catch(() => fallback) // 404/网络异常 → 硬编码兜底
}

export function useDict(code: string, fallback: DictItemView[] = []) {
  const items = ref<DictItemView[]>(fallback)
  const loaded = ref(false)
  let p = cache.get(code)
  if (!p) {
    p = fetchDict(code, fallback)
    cache.set(code, p)
  }
  p.then((list) => {
    items.value = list
    loaded.value = true
  })
  // labelOf：item_code → 中文标签；未命中回退原 code
  const labelOf = (c?: string | null) => {
    if (!c) return ''
    return items.value.find((i) => i.code === c)?.label ?? c
  }
  return { items, loaded, labelOf }
}

/** toRecord 条目数组 → Record<code,label>（替换原硬编码 *_TEXT 映射） */
export function toRecord(items: DictItemView[]): Record<string, string> {
  return Object.fromEntries(items.map((i) => [i.code, i.label]))
}
