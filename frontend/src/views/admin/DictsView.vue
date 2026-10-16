<script setup lang="ts">
import { reactive, ref, computed, onMounted } from 'vue'
import { api, list, ApiError } from '@/api/client'
import { auth } from '@/api/auth'

// 数据字典维护（PRD 2.8）：R-ADMIN 专属。左字典目录 + 右条目明细。
interface Dict {
  id: number
  code: string
  name: string
  remark?: string | null
  tenant_id?: number
  created_at?: string
  updated_at?: string
  items?: DictItem[]
}
interface DictItem {
  id: number
  dict_id: number
  item_code: string
  item_label: string
  parent_id?: number | null
  ext?: Record<string, any> | null
  i18n?: Record<string, any> | null
  sort_no: number
  effective_from?: string | null
  effective_to?: string | null
  active: boolean
  tenant_id?: number
}

const toast = (m: string) => (window as any).toast?.(m)
const canWrite = computed(() => auth.can('/admin/dicts POST'))

// —— 左：字典目录 ——
const dicts = ref<Dict[]>([])
const dictTotal = ref(0)
const dictPage = ref(1)
const dictSize = 50
const dictKeyword = ref('')
const dictLoading = ref(false)
const dictErr = ref('')
const activeId = ref(0)

async function reloadDicts() {
  dictLoading.value = true
  dictErr.value = ''
  try {
    const params: Record<string, any> = { page: dictPage.value, size: dictSize }
    if (dictKeyword.value.trim()) params.keyword = dictKeyword.value.trim()
    const r = await list<Dict>('/admin/dicts', params)
    dicts.value = r.rows
    dictTotal.value = r.total
    if (!r.rows.find((d) => d.id === activeId.value)) {
      activeId.value = r.rows[0]?.id ?? 0
      if (activeId.value) await reloadItems()
      else items.value = []
    }
  } catch (e: any) {
    dictErr.value = (e as ApiError)?.message || '加载失败'
  } finally {
    dictLoading.value = false
  }
}

function selectDict(d: Dict) {
  activeId.value = d.id
  reloadItems()
}

// —— 右：条目明细 ——
const items = ref<DictItem[]>([])
const itemsLoading = ref(false)
const itemsErr = ref('')
const activeDict = computed(() => dicts.value.find((d) => d.id === activeId.value) ?? null)

async function reloadItems() {
  if (!activeId.value) return
  itemsLoading.value = true
  itemsErr.value = ''
  try {
    const d = await api.get<Dict>(`/admin/dicts/${activeId.value}`)
    items.value = d?.items ?? []
  } catch (e: any) {
    itemsErr.value = (e as ApiError)?.message || '条目加载失败'
  } finally {
    itemsLoading.value = false
  }
}

// —— 字典抽屉 ——
const dictDrawer = reactive({ open: false, editing: false })
const dictForm = reactive({ id: 0, code: '', name: '', remark: '' })
function openDictCreate() {
  Object.assign(dictForm, { id: 0, code: '', name: '', remark: '' })
  dictDrawer.editing = false
  dictDrawer.open = true
}
function openDictEdit(d: Dict) {
  Object.assign(dictForm, { id: d.id, code: d.code, name: d.name, remark: d.remark ?? '' })
  dictDrawer.editing = true
  dictDrawer.open = true
}
const savingDict = ref(false)
async function saveDict() {
  savingDict.value = true
  dictErr.value = ''
  try {
    await api.post<Dict>('/admin/dicts', {
      code: dictForm.code.trim(), name: dictForm.name.trim(),
      remark: dictForm.remark.trim() || null,
    })
    toast(dictDrawer.editing ? '字典已更新' : '字典已创建')
    dictDrawer.open = false
    activeId.value = 0
    await reloadDicts()
  } catch (e: any) {
    dictErr.value = (e as ApiError)?.message || '保存失败'
  } finally {
    savingDict.value = false
  }
}

async function removeDict(d: Dict) {
  if (!confirm(`确认软删字典「${d.name}（${d.code}）」？条目保留但业务页不再展示。`)) return
  try {
    await api.del(`/admin/dicts/${d.id}`)
    toast('已软删')
    activeId.value = 0
    await reloadDicts()
  } catch (e: any) {
    dictErr.value = (e as ApiError)?.message || '删除失败'
  }
}

// —— 条目抽屉 ——
const itemDrawer = reactive({ open: false, editing: false })
const itemForm = reactive({
  id: 0, item_code: '', item_label: '', sort_no: 0, active: true,
  effective_from: '', effective_to: '', extText: '',
})
function openItemCreate() {
  Object.assign(itemForm, {
    id: 0, item_code: '', item_label: '', sort_no: items.value.length + 1, active: true,
    effective_from: '', effective_to: '', extText: '',
  })
  itemDrawer.editing = false
  itemDrawer.open = true
}
function openItemEdit(it: DictItem) {
  Object.assign(itemForm, {
    id: it.id, item_code: it.item_code, item_label: it.item_label, sort_no: it.sort_no, active: it.active,
    effective_from: it.effective_from ?? '', effective_to: it.effective_to ?? '',
    extText: it.ext ? JSON.stringify(it.ext, null, 2) : '',
  })
  itemDrawer.editing = true
  itemDrawer.open = true
}
const savingItem = ref(false)
async function saveItem() {
  if (!activeId.value) return
  let ext: any = null
  if (itemForm.extText.trim()) {
    try {
      ext = JSON.parse(itemForm.extText)
    } catch {
      itemsErr.value = 'ext_json 不是合法 JSON'
      return
    }
  }
  savingItem.value = true
  itemsErr.value = ''
  try {
    const body = {
      item_code: itemForm.item_code.trim(), item_label: itemForm.item_label.trim(),
      sort_no: itemForm.sort_no, active: itemForm.active,
      effective_from: itemForm.effective_from || null,
      effective_to: itemForm.effective_to || null,
      ext, i18n: null,
    }
    if (itemDrawer.editing && itemForm.id) {
      await api.put(`/admin/dicts/${activeId.value}/items/${itemForm.id}`, body)
    } else {
      await api.post(`/admin/dicts/${activeId.value}/items`, body)
    }
    toast('条目已保存')
    itemDrawer.open = false
    await reloadItems()
  } catch (e: any) {
    itemsErr.value = (e as ApiError)?.message || '保存失败'
  } finally {
    savingItem.value = false
  }
}

async function toggleActive(it: DictItem) {
  try {
    await api.put(`/admin/dicts/${activeId.value}/items/${it.id}`, {
      item_code: it.item_code, item_label: it.item_label, sort_no: it.sort_no,
      active: !it.active, effective_from: it.effective_from ?? null,
      effective_to: it.effective_to ?? null, ext: it.ext ?? null, i18n: it.i18n ?? null,
    })
    await reloadItems()
  } catch (e: any) {
    itemsErr.value = (e as ApiError)?.message || '操作失败'
  }
}

async function moveItem(it: DictItem, dir: -1 | 1) {
  const idx = items.value.findIndex((x) => x.id === it.id)
  const neighbor = items.value[idx + dir]
  if (!neighbor) return
  try {
    // sort_no 互换（upsert 语义：同码同生效期即更新）
    await api.put(`/admin/dicts/${activeId.value}/items/${it.id}`, {
      item_code: it.item_code, item_label: it.item_label, sort_no: neighbor.sort_no,
      active: it.active, effective_from: it.effective_from ?? null,
      effective_to: it.effective_to ?? null, ext: it.ext ?? null, i18n: it.i18n ?? null,
    })
    await api.put(`/admin/dicts/${activeId.value}/items/${neighbor.id}`, {
      item_code: neighbor.item_code, item_label: neighbor.item_label, sort_no: it.sort_no,
      active: neighbor.active, effective_from: neighbor.effective_from ?? null,
      effective_to: neighbor.effective_to ?? null, ext: neighbor.ext ?? null, i18n: neighbor.i18n ?? null,
    })
    await reloadItems()
  } catch (e: any) {
    itemsErr.value = (e as ApiError)?.message || '排序失败'
  }
}

async function removeItem(it: DictItem) {
  if (!confirm(`确认删除条目「${it.item_label}（${it.item_code}）」？`)) return
  try {
    await api.del(`/admin/dicts/${activeId.value}/items/${it.id}`)
    toast('已删除')
    await reloadItems()
  } catch (e: any) {
    itemsErr.value = (e as ApiError)?.message || '删除失败'
  }
}

// 生效期展示：两端皆空显示 —；单端空显示 …
function effText(it: DictItem): string {
  const f = it.effective_from || ''
  const t = it.effective_to || ''
  if (!f && !t) return '—'
  return `${f || '…'} ~ ${t || '…'}`
}
const extText = (it: DictItem) => (it.ext ? JSON.stringify(it.ext) : '')

onMounted(reloadDicts)
</script>

<template>
  <div class="card" style="padding:18px">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;flex-wrap:wrap">
      <h3 style="margin:0">数据字典维护</h3>
      <span class="tag info">PRD 2.8 · 禁止硬编码</span>
      <input v-model="dictKeyword" placeholder="按编码/名称检索" @keyup.enter="dictPage=1;reloadDicts()"
             style="width:240px;margin-left:8px" />
      <button class="btn" @click="reloadDicts">刷新</button>
      <button class="btn seal" v-if="canWrite" @click="openDictCreate">＋ 新建字典</button>
    </div>
    <div v-if="dictErr" style="color:#c0392b;margin-bottom:8px">{{ dictErr }}</div>

    <div style="display:grid;grid-template-columns:320px minmax(0, 1fr);gap:16px;align-items:start">
      <!-- 左：字典目录（table-layout:fixed + min-width:0，杜绝溢出与右侧重叠） -->
      <div class="dict-pane">
        <table class="tbl fixed" width="100%" style="border-collapse:collapse">
          <thead><tr style="text-align:left"><th class="c-code">编码</th><th class="c-name">名称</th><th class="c-ops"></th></tr></thead>
          <tbody>
            <tr v-for="d in dicts" :key="d.id" @click="selectDict(d)"
                :style="{ cursor: 'pointer', background: d.id === activeId ? 'var(--paper-deep)' : '' }">
              <td class="mono c-code" :title="d.code">{{ d.code }}</td>
              <td class="c-name" :title="d.name">{{ d.name }}</td>
              <td class="ops">
                <button class="btn sm mini" v-if="canWrite" @click.stop="openDictEdit(d)">编辑</button>
                <button class="btn sm mini danger" v-if="canWrite" @click.stop="removeDict(d)">删</button>
              </td>
            </tr>
            <tr v-if="!dicts.length"><td colspan="3" style="opacity:.6;padding:16px">{{ dictLoading ? '加载中…' : '暂无字典' }}</td></tr>
          </tbody>
        </table>
      </div>

      <!-- 右：条目明细 -->
      <div class="item-pane">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <b v-if="activeDict">{{ activeDict.name }} <span class="mono" style="font-size:11px;color:var(--ink-mute)">{{ activeDict.code }}</span></b>
          <span style="flex:1"></span>
          <button class="btn sm" :disabled="!activeId || !canWrite" @click="openItemCreate">＋ 新增条目</button>
        </div>
        <div v-if="itemsErr" style="color:#c0392b;margin-bottom:8px">{{ itemsErr }}</div>
        <table class="tbl" width="100%" style="border-collapse:collapse">
          <thead>
            <tr style="text-align:left">
              <th style="width:52px">排序</th><th>编码</th><th>标签</th><th>生效期</th><th>状态</th><th>ext</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(it, idx) in items" :key="it.id" :style="{ opacity: it.active ? 1 : 0.45 }">
              <td class="sort-cell">
                <button class="btn sm mini" :disabled="idx===0" :title="idx===0 ? '已在顶部' : '上移'" @click="moveItem(it, -1)">↑</button>
                <button class="btn sm mini" :disabled="idx===items.length-1" :title="idx===items.length-1 ? '已在底部' : '下移'" @click="moveItem(it, 1)">↓</button>
                <span class="mono sort-no">{{ it.sort_no }}</span>
              </td>
              <td class="mono">{{ it.item_code }}</td>
              <td>{{ it.item_label }}</td>
              <td class="mono eff">{{ effText(it) }}</td>
              <td><span class="tag" :class="it.active ? 'ok' : 'info'">{{ it.active ? '启用' : '停用' }}</span></td>
              <td class="mono ext" :title="extText(it) || ''">{{ extText(it) || '—' }}</td>
              <td class="ops">
                <button class="btn sm mini" v-if="canWrite" @click="openItemEdit(it)">编辑</button>
                <button class="btn sm mini ghost" v-if="canWrite" @click="toggleActive(it)">{{ it.active ? '停用' : '启用' }}</button>
                <button class="btn sm mini danger" v-if="canWrite" @click="removeItem(it)">删</button>
              </td>
            </tr>
            <tr v-if="!items.length"><td colspan="7" style="opacity:.6;padding:16px">{{ itemsLoading ? '加载中…' : activeId ? '暂无条目' : '← 选择左侧字典' }}</td></tr>
          </tbody>
        </table>
      </div>
    </div>
    <!-- 字典抽屉 -->
    <div v-if="dictDrawer.open" style="position:fixed;inset:0;background:rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;z-index:60">
      <div style="background:#fff;width:min(460px,92vw);max-height:88vh;overflow:auto;padding:20px;border-radius:10px">
        <h3 style="margin-top:0">{{ dictDrawer.editing ? '编辑字典' : '新建字典' }}</h3>
        <div class="fld"><label>编码 *（如 project_type）</label><input v-model="dictForm.code" :disabled="dictDrawer.editing" /></div>
        <div class="fld"><label>名称 *</label><input v-model="dictForm.name" /></div>
        <div class="fld"><label>备注</label><input v-model="dictForm.remark" /></div>
        <p style="font-size:12px;color:var(--ink-mute)">编码租户内唯一；软删后同编码可重建。编辑态按编码 upsert 更新。</p>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
          <button class="btn" @click="dictDrawer.open=false">取消</button>
          <button class="btn seal" :disabled="savingDict" @click="saveDict">{{ savingDict ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>

    <!-- 条目抽屉 -->
    <div v-if="itemDrawer.open" style="position:fixed;inset:0;background:rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;z-index:60">
      <div style="background:#fff;width:min(520px,92vw);max-height:88vh;overflow:auto;padding:20px;border-radius:10px">
        <h3 style="margin-top:0">{{ itemDrawer.editing ? '编辑条目' : '新增条目' }}</h3>
        <div class="fld"><label>条目编码 *（如 NSFC）</label><input v-model="itemForm.item_code" /></div>
        <div class="fld"><label>条目标签 *</label><input v-model="itemForm.item_label" /></div>
        <div class="fld"><label>排序值</label><input v-model.number="itemForm.sort_no" type="number" /></div>
        <div class="fld"><label>生效起（留空不限制）</label><input v-model="itemForm.effective_from" type="date" /></div>
        <div class="fld"><label>生效止（留空不限制）</label><input v-model="itemForm.effective_to" type="date" /></div>
        <div class="fld"><label>扩展属性 ext_json（可选，JSON）</label>
          <textarea v-model="itemForm.extText" rows="4" placeholder='{"icon":"自","color":"#2C6E49"}'></textarea></div>
        <div class="fld"><label style="display:flex;align-items:center;gap:6px"><input type="checkbox" v-model="itemForm.active" /> 启用</label></div>
        <p style="font-size:12px;color:var(--ink-mute)">同编码 + 同生效起视为同一条目（upsert）；不同生效起可并存历史版本。</p>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
          <button class="btn" @click="itemDrawer.open=false">取消</button>
          <button class="btn seal" :disabled="savingItem" @click="saveItem">{{ savingItem ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fld { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; }
.fld label { font-size: 12px; color: var(--ink-mute); }
.fld input, .fld textarea { border: 1px solid var(--line-hard); border-radius: 4px; padding: 7px 10px; font: inherit; font-size: 13px; }
.fld textarea { font-family: var(--mono, monospace); font-size: 12px; }

/* 表格行内按钮组：压缩为迷你尺寸、强制单行，避免撑破行高/换行错位 */
.tbl .btn.sm.mini { padding: 2px 8px; font-size: 11px; line-height: 1.5; border-radius: 3px; }
.tbl .btn.sm.mini.ghost { background: transparent; color: var(--ink); border-color: var(--line-hard); }
.tbl .btn.sm.mini.danger { background: var(--bad, #a33); border-color: var(--bad, #a33); }
.sort-cell { white-space: nowrap; }
.sort-cell .btn { margin-right: 3px; }
.sort-no { display: inline-block; min-width: 16px; text-align: center; font-size: 10px; color: var(--ink-mute); }
.eff { font-size: 11px; white-space: nowrap; color: var(--ink-mute); }
.ext { font-size: 10px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink-mute); }
.ops { white-space: nowrap; }
.ops .btn + .btn { margin-left: 4px; }

/* 两栏隔离：min-width:0 防网格子项溢出重叠 */
.dict-pane, .item-pane { min-width: 0; }
.dict-pane { overflow-x: auto; }

/* 左目录表固定布局：列宽锁死，内容截断省略（title 悬浮看全文），永不撑破容器 */
table.fixed { table-layout: fixed; }
table.fixed td, table.fixed th { padding: 7px 8px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
table.fixed .c-code { width: 40%; }
table.fixed .c-name { width: 32%; }
table.fixed .c-ops { width: 28%; }

.tbl td, .tbl th { vertical-align: middle; }
.tbl th { padding: 8px 10px; white-space: nowrap; }
</style>
