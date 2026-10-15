<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, list, API_PREFIX } from '@/api/client'
import { auth } from '@/api/auth'

// —— 数据模型严格对齐契约 16-O.openapi.yaml / 后端 mapper（snake_case；本域无金额字段，时间一律 ISO 串）——
interface Archive {
  id: number; code: string | null; title: string; archive_type: string
  source_module: string | null; source_id: number | null; source_code: string | null
  owner_dept_id: number | null; retention_years: number; status: string
  security_level: string; submitter_id: number | null; submit_at: string | null
  archivist_id: number | null; filed_at: string | null; created_at: string; updated_at: string
  [k: string]: any
}
interface ArchiveItem {
  id: number; archive_id: number; category_code: string; category_name: string | null
  required: boolean; doc_id: number | null; status: string; sort_no: number; [k: string]: any
}
interface ArchiveCheck {
  id: number; archive_id: number; check_type: string; result: string
  detail: Record<string, any>; checked_at: string | null; checker_id: number | null; [k: string]: any
}
interface CheckReport { list: ArchiveCheck[]; passed: boolean; [k: string]: any }
interface Document {
  id: number; code: string | null; tenant_id: number; status: string; name: string
  doc_type: string | null; size_bytes: number | null; bucket: string | null; object_key: string | null
  checksum_sha256: string | null; source_module: string | null; source_id: number | null
  security_level: string; uploaded_at: string | null; created_at: string; [k: string]: any
}
interface DocHit extends Document { snippet?: string; rank?: number }
interface Borrow {
  id: number; code: string | null; archive_id: number; archive_title: string | null
  borrower_user_id: number; purpose: string | null; borrow_type: string; status: string
  approved_by: number | null; approved_at: string | null; due_at: string | null
  returned_at: string | null; created_at: string; [k: string]: any
}

const toast = (m: string) => (window as any).toast?.(m)
const fmtTime = (d?: string | null) => (d ? d.replace('T', ' ').slice(0, 16) + 'Z' : '—')

type TabKey = 'ledger' | 'check' | 'search' | 'borrow'
const TABS: { key: TabKey; label: string }[] = [
  { key: 'ledger', label: '案卷台账' },
  { key: 'check', label: '四性检测' },
  { key: 'search', label: '全文检索' },
  { key: 'borrow', label: '借阅' },
]
const tab = ref<TabKey>('ledger')

// 角色门控（O 规格：入库/销毁/审批仅 R-ADMIN；建卷/提交/检测/借阅发起 R-MANAGER+）
const canAdmin = computed(() => auth.hasAnyRole(['R-ADMIN']))
const canManage = computed(() => auth.hasAnyRole(['R-MANAGER', 'R-LEADER', 'R-ADMIN']))

// —— 字典 ——
const ARCH_STATUS: Record<string, { cls: string; txt: string }> = {
  PENDING_SUBMIT: { cls: 'info', txt: '待提交' }, SUBMITTED: { cls: 'warn', txt: '已提交' },
  CHECKING: { cls: 'info', txt: '检测中' }, PASSED: { cls: 'ok', txt: '检测通过' },
  REJECTED: { cls: 'bad', txt: '已驳回' }, ARCHIVED: { cls: 'ok', txt: '已入库' },
  DESTROYED: { cls: 'bad', txt: '已销毁' },
}
const ARCH_TYPE_TXT: Record<string, string> = {
  PROJECT: '项目档案', OUTPUT: '成果档案', EXPENSE: '经费档案',
  CONTRACT: '合同档案', ACTIVITY: '活动档案', OTHER: '其他档案',
}
const SEC_TXT: Record<string, string> = { PUBLIC: '公开', INTERNAL: '内部', SECRET: '秘密', TOP_SECRET: '机密' }
const ITEM_STATUS: Record<string, { cls: string; txt: string }> = {
  MISSING: { cls: 'bad', txt: '缺失' }, FILLED: { cls: 'ok', txt: '已挂载' }, CHECKED: { cls: 'info', txt: '已核验' },
}
const CHECK_TYPE_TXT: Record<string, { txt: string; hint: string }> = {
  AUTHENTICITY: { txt: '真实性', hint: '电子件 checksum 一致' },
  INTEGRITY: { txt: '完整性', hint: 'required 门类齐备' },
  USABILITY: { txt: '可用性', hint: '格式可读、可长期打开' },
  SECURITY: { txt: '安全性', hint: '密级与访问权限合规' },
}
const CHECK_RESULT: Record<string, { cls: string; txt: string }> = {
  PASS: { cls: 'ok', txt: '通过' }, WARN: { cls: 'warn', txt: '警示' }, FAIL: { cls: 'bad', txt: '不通过' },
}
const DOC_STATUS: Record<string, { cls: string; txt: string }> = {
  UPLOADING: { cls: 'warn', txt: '上传中' }, STORED: { cls: 'ok', txt: '已入库' }, MISSING: { cls: 'bad', txt: '缺失' },
}
const BORROW_TYPE: Record<string, string> = { READ: '查阅', COPY: '复制' }
const BORROW_STATUS: Record<string, { cls: string; txt: string }> = {
  SUBMITTED: { cls: 'warn', txt: '待审批' }, APPROVED: { cls: 'ok', txt: '已批准' },
  REJECTED: { cls: 'bad', txt: '已驳回' }, RETURNED: { cls: 'info', txt: '已归还' }, EXPIRED: { cls: 'bad', txt: '已逾期' },
}

const busy = ref(false)
async function runAction(name: string, fn: () => Promise<any>, okMsg: string, after?: () => Promise<void> | void) {
  if (busy.value) return
  busy.value = true
  try {
    await fn()
    toast(okMsg)
    if (after) await after()
  } catch (e: any) {
    toast(`${name}失败：` + (e?.message || e))
  } finally {
    busy.value = false
  }
}

// ============ ① 案卷台账 ============
const archives = ref<Archive[]>([])
const arcTotal = ref(0)
const arcLoading = ref(false)
const arcPage = ref(1)
const arcSize = ref(20)
const arcStatus = ref('')
const arcType = ref('')
const arcKw = ref('')
const arcPageCount = computed(() => Math.max(1, Math.ceil(arcTotal.value / arcSize.value)))

async function loadArchives() {
  arcLoading.value = true
  try {
    const { rows, total } = await list<Archive>('/archives', {
      page: arcPage.value, size: arcSize.value,
      status: arcStatus.value || undefined, archive_type: arcType.value || undefined, kw: arcKw.value || undefined,
    })
    archives.value = rows ?? []
    arcTotal.value = total ?? archives.value.length
  } catch (e: any) {
    toast('案卷加载失败：' + (e?.message || e))
  } finally {
    arcLoading.value = false
  }
}
function arcReload() { arcPage.value = 1; loadArchives() }
function arcSetStatus(v: string) { arcStatus.value = v; arcReload() }
function arcSetType(v: string) { arcType.value = v; arcReload() }
function arcGo(delta: number) {
  const n = arcPage.value + delta
  if (n < 1 || n > arcPageCount.value) return
  arcPage.value = n; loadArchives()
}

// 选中案卷 → 门类清单
const selectedId = ref<number | null>(null)
const items = ref<ArchiveItem[]>([])
const itemsLoading = ref(false)
const selectedArchive = computed<Archive | null>(
  () => archives.value.find((a) => a.id === selectedId.value) ?? null,
)

async function loadItems(id: number) {
  itemsLoading.value = true
  try {
    // 契约 GET /archives/{id}/items 的 data = { list }（非 PageResult）
    const data = await api.get<{ list: ArchiveItem[] }>(`/archives/${id}/items`)
    items.value = data?.list ?? []
  } catch (e: any) {
    toast('门类清单加载失败：' + (e?.message || e))
    items.value = []
  } finally {
    itemsLoading.value = false
  }
}
function selectArchive(a: Archive) {
  selectedId.value = a.id
  loadItems(a.id)
}

// 新建案卷（R-MANAGER+）
const createModal = ref(false)
const nf = ref({ title: '', archive_type: 'PROJECT', retention_years: 10, security_level: 'INTERNAL' })
function openCreate() { if (canManage.value) createModal.value = true }
function submitCreate() {
  if (!nf.value.title.trim()) { toast('请填写案卷题名'); return }
  runAction('新建案卷', () => api.post<Archive>('/archives', {
    title: nf.value.title.trim(), archive_type: nf.value.archive_type,
    retention_years: Number(nf.value.retention_years) || 10, security_level: nf.value.security_level,
  }), '案卷已创建 → PENDING_SUBMIT ✓', async () => {
    createModal.value = false
    nf.value = { title: '', archive_type: 'PROJECT', retention_years: 10, security_level: 'INTERNAL' }
    await loadArchives()
  })
}

// 上传电子件（multipart → /documents；mock 下不触 MinIO）
const fileInput = ref<HTMLInputElement | null>(null)
function pickFile() { if (canManage.value) fileInput.value?.click() }
async function onFileChange(ev: Event) {
  const input = ev.target as HTMLInputElement
  const f = input.files?.[0]
  if (!f) return
  busy.value = true
  try {
    const form = new FormData()
    form.append('file', f)
    form.append('name', f.name)
    form.append('security_level', 'INTERNAL')
    const res = await fetch(API_PREFIX + '/documents', {
      method: 'POST',
      body: form,
      headers: auth.token ? { Authorization: 'Bearer ' + auth.token } : {},
    })
    const env = await res.json()
    if (env?.code !== 0) throw new Error(env?.message || `HTTP ${res.status}`)
    toast('已上传：' + (env?.data?.name || f.name) + ' ✓')
  } catch (e: any) {
    toast('上传失败：' + (e?.message || e))
  } finally {
    busy.value = false
    input.value = ''
  }
}

// 状态机动作
function doSubmit(a: Archive) {
  runAction('提交', () => api.post(`/archives/${a.id}/submit`), `案卷 ${a.code || a.id} 已提交 → SUBMITTED ✓`, loadArchives)
}
function doIngest(a: Archive) {
  runAction('摄取来源', () => api.post<ArchiveItem>(`/archives/${a.id}/ingest`, { category_code: 'ING-DOC', category_name: '来源摄取件' }), '已从来源摄取生成门类条目 ✓', () => { if (selectedId.value === a.id) loadItems(a.id) })
}
function doFile(a: Archive) {
  if (!canAdmin.value) return
  runAction('入库', () => api.post(`/archives/${a.id}/file`), `案卷 ${a.code || a.id} 已入库 → ARCHIVED ✓`, loadArchives)
}
function doDestroy(a: Archive) {
  if (!canAdmin.value) return
  if (!window.confirm(`确认销毁案卷「${a.title}」？此操作留痕且不可撤销。`)) return
  runAction('销毁', () => api.post(`/archives/${a.id}/destroy`, { reason: '保管期限届满，依规销毁' }), `案卷 ${a.code || a.id} 已销毁 → DESTROYED ✓`, loadArchives)
}

// 状态机门禁（对齐契约流转 token）
function gateOf(s: string) {
  return {
    submit: s === 'PENDING_SUBMIT' || s === 'REJECTED',
    check: s === 'SUBMITTED',
    file: s === 'PASSED',
    destroy: s === 'ARCHIVED',
  }
}
function gotoCheck(a: Archive) {
  selectedId.value = a.id
  tab.value = 'check'
  runCheck()
}

// ============ ② 四性检测 ============
const checkReport = ref<CheckReport | null>(null)
const checkLoading = ref(false)
async function runCheck() {
  if (selectedId.value == null) { toast('请先在「案卷台账」中选择一个案卷'); return }
  checkLoading.value = true
  checkReport.value = null
  try {
    checkReport.value = await api.post<CheckReport>(`/archives/${selectedId.value}/check`)
    await loadArchives()
  } catch (e: any) {
    toast('四性检测失败：' + (e?.message || e))
  } finally {
    checkLoading.value = false
  }
}

// ============ ③ 全文检索 ============
const hits = ref<DocHit[]>([])
const hitTotal = ref(0)
const searching = ref(false)
const searchKw = ref('')
const searched = ref(false)
async function doSearch() {
  const q = searchKw.value.trim()
  if (!q) { toast('请输入检索关键词'); return }
  searching.value = true
  searched.value = true
  try {
    const { rows, total } = await list<DocHit>('/documents/search', { q, page: 1, size: 20 })
    hits.value = rows ?? []
    hitTotal.value = total ?? hits.value.length
  } catch (e: any) {
    toast('检索失败：' + (e?.message || e))
  } finally {
    searching.value = false
  }
}
function segs(text: string, kw: string): { t: string; hit: boolean }[] {
  const out: { t: string; hit: boolean }[] = []
  if (!text) return out
  const k = kw.trim().toLowerCase()
  if (!k) { out.push({ t: text, hit: false }); return out }
  const lower = text.toLowerCase()
  let i = 0
  while (i < text.length) {
    const j = lower.indexOf(k, i)
    if (j < 0) { out.push({ t: text.slice(i), hit: false }); break }
    if (j > i) out.push({ t: text.slice(i, j), hit: false })
    out.push({ t: text.slice(j, j + k.length), hit: true })
    i = j + k.length
  }
  return out
}
const fmtBytes = (n?: number | null) => (n == null ? '—' : n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : (n / 1048576).toFixed(1) + ' MB')
async function doDownload(d: Document) {
  try {
    const r = await api.get<{ url: string; expires_at: string }>(`/documents/${d.id}/download`)
    if (r?.url) { window.open(r.url, '_blank'); toast('已打开下载链接（有效期至 ' + fmtTime(r.expires_at) + '）') }
    else toast('未获取到下载链接')
  } catch (e: any) {
    toast('下载失败：' + (e?.message || e))
  }
}

// ============ ④ 借阅 ============
const borrows = ref<Borrow[]>([])
const borrowLoading = ref(false)
const bStatus = ref('')
async function loadBorrows() {
  borrowLoading.value = true
  try {
    const { rows, total } = await list<Borrow>('/borrows', { page: 1, size: 50, status: bStatus.value || undefined })
    borrows.value = rows ?? []
    if (!archives.value.length) await loadArchives()
    void total
  } catch (e: any) {
    toast('借阅加载失败：' + (e?.message || e))
  } finally {
    borrowLoading.value = false
  }
}
function bSetStatus(v: string) { bStatus.value = v; loadBorrows() }
// 后端 archive_title 恒为 null（无 join）→ 从已加载台账按 archive_id 反查标题
function titleOf(b: Borrow): string {
  if (b.archive_title) return b.archive_title
  const a = archives.value.find((x) => x.id === b.archive_id)
  return a ? a.title : `案卷 #${b.archive_id}`
}
const borrowModal = ref(false)
const bf = ref({ archive_id: 0, purpose: '', borrow_type: 'READ', due_at: '' })
function openBorrow() {
  if (!canManage.value) return
  if (!archives.value.length) loadArchives()
  bf.value = { archive_id: archives.value[0]?.id ?? 0, purpose: '', borrow_type: 'READ', due_at: '' }
  borrowModal.value = true
}
function submitBorrow() {
  if (!bf.value.archive_id) { toast('请选择借阅案卷'); return }
  const body: Record<string, any> = { archive_id: Number(bf.value.archive_id), purpose: bf.value.purpose.trim(), borrow_type: bf.value.borrow_type }
  if (bf.value.due_at) body.due_at = bf.value.due_at + 'T08:00:00Z'
  runAction('借阅申请', () => api.post<Borrow>('/borrows', body), '借阅申请已发起 → SUBMITTED ✓', async () => {
    borrowModal.value = false
    await loadBorrows()
  })
}
function doApprove(b: Borrow) {
  if (!canAdmin.value) return
  runAction('批准', () => api.post(`/borrows/${b.id}/approve`), '借阅已批准 → APPROVED ✓', loadBorrows)
}
function doReject(b: Borrow) {
  if (!canAdmin.value) return
  runAction('驳回', () => api.post(`/borrows/${b.id}/reject`), '借阅已驳回 → REJECTED ✓', loadBorrows)
}
function doReturn(b: Borrow) {
  runAction('归还', () => api.post(`/borrows/${b.id}/return`), '借阅已归还 → RETURNED ✓', loadBorrows)
}

function switchTab(k: TabKey) {
  tab.value = k
  if (k === 'borrow' && !borrows.value.length) loadBorrows()
  if (k === 'ledger' && selectedId.value == null && archives.value.length) selectArchive(archives.value[0])
}

onMounted(async () => {
  await loadArchives()
  if (archives.value.length) selectArchive(archives.value[0])
})
</script>

<template>
  <section class="view on" id="v-archive">
    <div class="page-head">
      <div>
        <div class="page-title">科研<em>档案</em></div>
        <div class="page-sub">
          案卷台账 {{ arcTotal }} 卷 · 电子件检索 · 四性检测（真实/完整/可用/安全）· 借阅审批 · 状态机 提交→检测→入库→销毁
        </div>
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <span class="tag info">角色：{{ auth.roles.join(' / ') || '访客' }}</span>
        <span v-if="!canManage && !canAdmin" class="tag warn">当前角色仅可查看</span>
        <span v-else-if="canManage && !canAdmin" class="tag info">入库/销毁/审批需管理员</span>
      </div>
    </div>

    <div class="tabs">
      <div class="tab" :class="{ on: tab === t.key }" v-for="t in TABS" :key="t.key" @click="switchTab(t.key)">{{ t.label }}</div>
    </div>

    <!-- ① 案卷台账 -->
    <div class="pane" v-show="tab === 'ledger'">
      <div class="filter-row">
        <input class="sel" style="min-width:200px" v-model="arcKw" placeholder="搜索题名 / 编号 / 来源号" @keyup.enter="arcReload" />
        <select class="sel" v-model="arcType" @change="arcSetType(arcType)">
          <option value="">全部门类</option>
          <option v-for="(v, k) in ARCH_TYPE_TXT" :key="k" :value="k">{{ v }}</option>
        </select>
        <span class="chip" :class="{ on: arcStatus === '' }" @click="arcSetStatus('')">全部</span>
        <span class="chip" v-for="(v, k) in ARCH_STATUS" :key="k" :class="{ on: arcStatus === k }" @click="arcSetStatus(k)">{{ v.txt }}</span>
        <button class="btn ghost sm" @click="arcReload">查询</button>
        <span style="flex:1"></span>
        <button class="btn sm ghost" :disabled="busy || !canManage" @click="pickFile">上传电子件</button>
        <input ref="fileInput" type="file" style="display:none" @change="onFileChange" />
        <button class="btn sm seal" :disabled="busy || !canManage" @click="openCreate">+ 新建案卷</button>
      </div>

      <div v-if="arcLoading" class="card"><div class="card-b" style="color:var(--ink-mute)">案卷加载中…</div></div>
      <div v-else-if="!archives.length" class="card"><div class="card-b" style="padding:32px;text-align:center;color:var(--ink-mute)">暂无案卷记录</div></div>

      <template v-else>
        <div class="card" style="padding:0">
          <table class="tbl">
            <thead>
              <tr>
                <th>编号</th><th>题名</th><th>门类</th><th>来源</th><th>保管</th><th>密级</th>
                <th>提交人</th><th>档案员</th><th>状态</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="a in archives" :key="a.id" :class="{ 'row-on': selectedId === a.id }" @click="selectArchive(a)">
                <td class="mono">{{ a.code || '—' }}</td>
                <td><b>{{ a.title }}</b></td>
                <td><span class="tag seal">{{ ARCH_TYPE_TXT[a.archive_type] || a.archive_type }}</span></td>
                <td style="font-size:12px;color:var(--ink-mute)">
                  <div>{{ a.source_module || '—' }}<span v-if="a.source_id"> · #{{ a.source_id }}</span></div>
                  <div class="mono">{{ a.source_code || '—' }}</div>
                </td>
                <td class="mono">{{ a.retention_years }}年</td>
                <td><span class="tag">{{ SEC_TXT[a.security_level] || a.security_level }}</span></td>
                <td class="mono">{{ a.submitter_id ?? '—' }}</td>
                <td class="mono">{{ a.archivist_id ?? '—' }}</td>
                <td><span class="tag" :class="(ARCH_STATUS[a.status]||{}).cls">{{ (ARCH_STATUS[a.status]||{}).txt || a.status }}</span></td>
                <td>
                  <div class="ops">
                    <button class="btn xs ghost" :disabled="busy || !canManage || !gateOf(a.status).submit" @click.stop="doSubmit(a)">提交</button>
                    <button class="btn xs ghost" :disabled="busy || !canManage || !gateOf(a.status).check" @click.stop="gotoCheck(a)">检测</button>
                    <button class="btn xs ghost" :disabled="busy || !canManage" @click.stop="doIngest(a)">摄取</button>
                    <button class="btn xs seal" :disabled="busy || !canAdmin || !gateOf(a.status).file" @click.stop="doFile(a)" title="仅管理员">入库</button>
                    <button class="btn xs ghost" :disabled="busy || !canAdmin || !gateOf(a.status).destroy" @click.stop="doDestroy(a)" title="仅管理员">销毁</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="pager">
          <button class="btn ghost sm" :disabled="arcPage <= 1" @click="arcGo(-1)">← 上一页</button>
          <span class="mono pg-info">第 {{ arcPage }} / {{ arcPageCount }} 页 · 共 {{ arcTotal }} 卷</span>
          <button class="btn ghost sm" :disabled="arcPage >= arcPageCount" @click="arcGo(1)">下一页 →</button>
        </div>

        <!-- 选中案卷 · 门类清单 -->
        <div class="card" style="margin-top:16px;padding:0" v-if="selectedArchive">
          <div class="card-h">
            <h4>门类清单 · {{ selectedArchive.title }}</h4>
            <span class="tag info">{{ items.length }} 项 · 缺失 {{ items.filter(i => i.status === 'MISSING').length }}</span>
          </div>
          <div v-if="itemsLoading" class="card-b" style="color:var(--ink-mute)">清单加载中…</div>
          <table v-else class="tbl">
            <thead><tr><th>序</th><th>门类编码</th><th>门类名称</th><th>必归</th><th>挂载电子件</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="it in items" :key="it.id">
                <td class="mono">{{ it.sort_no }}</td>
                <td class="mono">{{ it.category_code }}</td>
                <td>{{ it.category_name || '—' }}</td>
                <td><span class="tag" :class="it.required ? 'warn' : ''">{{ it.required ? '必归' : '可选' }}</span></td>
                <td class="mono">{{ it.doc_id == null ? '—' : ('#' + it.doc_id) }}</td>
                <td><span class="tag" :class="(ITEM_STATUS[it.status]||{}).cls">{{ (ITEM_STATUS[it.status]||{}).txt || it.status }}</span></td>
              </tr>
              <tr v-if="!items.length"><td colspan="6" style="text-align:center;color:var(--ink-mute);padding:20px">该案卷暂无门类条目</td></tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>

    <!-- ② 四性检测 -->
    <div class="pane" v-show="tab === 'check'">
      <div class="filter-row">
        <select class="sel" style="min-width:260px" v-model.number="selectedId">
          <option :value="null" disabled>— 选择案卷 —</option>
          <option v-for="a in archives" :key="a.id" :value="a.id">{{ a.code || ('#' + a.id) }} · {{ a.title }}</option>
        </select>
        <button class="btn sm seal" :disabled="busy || checkLoading || !canManage" @click="runCheck">执行四性检测</button>
        <span style="font-size:11px;color:var(--ink-mute)">真实性(checksum) · 完整性(required 齐备) · 可用性(格式可读) · 安全性(密级权限)</span>
      </div>

      <div v-if="!selectedId" class="card"><div class="card-b" style="padding:32px;text-align:center;color:var(--ink-mute)">请先在上方选择一个案卷。</div></div>
      <div v-else-if="checkLoading" class="card"><div class="card-b" style="color:var(--ink-mute)">四性检测执行中…</div></div>
      <div v-else-if="!checkReport" class="card"><div class="card-b" style="padding:32px;text-align:center;color:var(--ink-mute)">点击「执行四性检测」生成本案卷的四性报告。</div></div>

      <template v-else>
        <div class="card" style="margin-bottom:16px">
          <div class="card-b" style="display:flex;align-items:center;gap:16px">
            <span class="tag" :class="checkReport.passed ? 'ok' : 'bad'" style="font-size:14px;padding:6px 14px">
              {{ checkReport.passed ? '✓ 四性全通过 → PASSED' : '✕ 存在不通过 → REJECTED' }}
            </span>
            <div style="flex:1;font-size:12px;color:var(--ink-mute)" v-if="selectedArchive">
              {{ selectedArchive.code || '—' }} · {{ selectedArchive.title }} · 当前状态
              <span class="tag" :class="(ARCH_STATUS[selectedArchive.status]||{}).cls">{{ (ARCH_STATUS[selectedArchive.status]||{}).txt || selectedArchive.status }}</span>
            </div>
            <button class="btn sm seal" :disabled="busy || !canAdmin || selectedArchive?.status !== 'PASSED'" @click="selectedArchive && doFile(selectedArchive)" title="仅管理员">确认入库</button>
          </div>
        </div>

        <div class="grid g2">
          <div class="card ck-card" v-for="c in checkReport.list" :key="c.id">
            <div class="card-h">
              <h4>{{ (CHECK_TYPE_TXT[c.check_type]||{}).txt || c.check_type }}性</h4>
              <span class="tag" :class="(CHECK_RESULT[c.result]||{}).cls">{{ (CHECK_RESULT[c.result]||{}).txt || c.result }}</span>
            </div>
            <div class="card-b">
              <div style="font-size:11px;color:var(--ink-mute);margin-bottom:8px">{{ (CHECK_TYPE_TXT[c.check_type]||{}).hint || c.check_type }}</div>
              <div class="kv" v-for="(val, key) in c.detail" :key="String(key)">
                <span class="k mono">{{ key }}</span>
                <span class="v mono">{{ Array.isArray(val) ? (val.length ? val.join(', ') : '（空）') : String(val) }}</span>
              </div>
              <div class="ck-foot">
                <span class="mono">检测人 #{{ c.checker_id ?? '—' }}</span>
                <span class="mono">{{ fmtTime(c.checked_at) }}</span>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- ③ 全文检索 -->
    <div class="pane" v-show="tab === 'search'">
      <div class="filter-row">
        <input class="sel" style="min-width:320px" v-model="searchKw" placeholder="输入关键词，如「结题 / 分割 / 经费」" @keyup.enter="doSearch" />
        <button class="btn sm" :disabled="searching" @click="doSearch">{{ searching ? '检索中…' : '检索' }}</button>
        <span v-if="searched" class="tag info">命中 {{ hitTotal }} 条</span>
      </div>

      <div v-if="searching" class="card"><div class="card-b" style="color:var(--ink-mute)">检索中…</div></div>
      <div v-else-if="!searched" class="card"><div class="card-b" style="padding:32px;text-align:center;color:var(--ink-mute)">输入关键词进行全文检索（正文不外泄，仅回片段与相关度）。</div></div>
      <div v-else-if="!hits.length" class="card"><div class="card-b" style="padding:32px;text-align:center;color:var(--ink-mute)">未检索到匹配电子件</div></div>

      <template v-else>
        <div class="card hit-card" v-for="h in hits" :key="h.id">
          <div class="card-b">
            <div style="display:flex;align-items:center;gap:10px">
              <div style="flex:1">
                <div class="hit-name">{{ h.name }}<span class="tag seal" style="margin-left:6px">{{ h.doc_type || '文件' }}</span></div>
                <div class="mono hit-meta">
                  {{ h.code || '—' }} · {{ h.bucket || '—' }}/{{ h.object_key || '—' }} · {{ fmtBytes(h.size_bytes) }} · {{ SEC_TXT[h.security_level] || h.security_level }}
                </div>
              </div>
              <span class="tag" :class="(DOC_STATUS[h.status]||{}).cls">{{ (DOC_STATUS[h.status]||{}).txt || h.status }}</span>
              <button class="btn sm ghost" :disabled="busy" @click="doDownload(h)">下载</button>
            </div>
            <div class="divider-double" style="margin:10px 0"></div>
            <div v-if="h.snippet" class="snippet">
              <template v-for="(sg, i) in segs(h.snippet, searchKw)" :key="i"><span :class="{ mark: sg.hit }">{{ sg.t }}</span></template>
            </div>
            <div v-else style="font-size:12px;color:var(--ink-mute)">（无片段）</div>
            <div class="hit-foot">
              <span class="mono">sha256 {{ (h.checksum_sha256 || '').slice(0, 12) }}…</span>
              <span class="mono" v-if="h.rank != null">相关度 {{ h.rank }}</span>
              <span class="mono">来源 {{ h.source_module || '—' }}{{ h.source_id ? (' #' + h.source_id) : '' }} · 上传 {{ fmtTime(h.uploaded_at) }}</span>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- ④ 借阅 -->
    <div class="pane" v-show="tab === 'borrow'">
      <div class="filter-row">
        <span class="chip" :class="{ on: bStatus === '' }" @click="bSetStatus('')">全部</span>
        <span class="chip" v-for="(v, k) in BORROW_STATUS" :key="k" :class="{ on: bStatus === k }" @click="bSetStatus(k)">{{ v.txt }}</span>
        <button class="btn ghost sm" @click="loadBorrows">刷新</button>
        <span style="flex:1"></span>
        <button class="btn sm seal" :disabled="busy || !canManage" @click="openBorrow">+ 发起借阅</button>
      </div>

      <div v-if="borrowLoading" class="card"><div class="card-b" style="color:var(--ink-mute)">借阅加载中…</div></div>
      <div v-else-if="!borrows.length" class="card"><div class="card-b" style="padding:32px;text-align:center;color:var(--ink-mute)">暂无借阅申请</div></div>

      <div v-else class="card" style="padding:0">
        <table class="tbl">
          <thead>
            <tr><th>编号</th><th>案卷</th><th>借阅人</th><th>用途</th><th>方式</th><th>期限</th><th>状态</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="b in borrows" :key="b.id">
              <td class="mono">{{ b.code || ('#' + b.id) }}</td>
              <td>{{ titleOf(b) }}<div class="mono" style="font-size:11px;color:var(--ink-mute)">案卷 #{{ b.archive_id }}</div></td>
              <td class="mono">#{{ b.borrower_user_id }}</td>
              <td style="font-size:12px;color:var(--ink-soft)">{{ b.purpose || '—' }}</td>
              <td><span class="tag info">{{ BORROW_TYPE[b.borrow_type] || b.borrow_type }}</span></td>
              <td class="mono" style="font-size:11px">{{ fmtTime(b.due_at) }}</td>
              <td><span class="tag" :class="(BORROW_STATUS[b.status]||{}).cls">{{ (BORROW_STATUS[b.status]||{}).txt || b.status }}</span></td>
              <td>
                <div class="ops">
                  <button class="btn xs seal" :disabled="busy || !canAdmin || b.status !== 'SUBMITTED'" @click="doApprove(b)" title="仅管理员">批准</button>
                  <button class="btn xs ghost" :disabled="busy || !canAdmin || b.status !== 'SUBMITTED'" @click="doReject(b)" title="仅管理员">驳回</button>
                  <button class="btn xs ghost" :disabled="busy || b.status !== 'APPROVED'" @click="doReturn(b)">归还</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 新建案卷浮层 -->
    <div v-if="createModal" class="mask" @click.self="createModal = false">
      <div class="card" style="width:360px">
        <div class="card-h"><h4>新建案卷</h4></div>
        <div class="card-b" style="display:flex;flex-direction:column;gap:12px">
          <label style="font-size:12px">题名 *</label>
          <input class="sel" v-model="nf.title" placeholder="案卷题名" />
          <label style="font-size:12px">门类</label>
          <select class="sel" v-model="nf.archive_type">
            <option v-for="(v, k) in ARCH_TYPE_TXT" :key="k" :value="k">{{ v }}</option>
          </select>
          <div style="display:flex;gap:12px">
            <div style="flex:1"><label style="font-size:12px">保管年限</label><input class="sel" type="number" min="1" v-model.number="nf.retention_years" /></div>
            <div style="flex:1"><label style="font-size:12px">密级</label><select class="sel" v-model="nf.security_level"><option v-for="(v, k) in SEC_TXT" :key="k" :value="k">{{ v }}</option></select></div>
          </div>
          <div style="display:flex;gap:8px;justify-content:flex-end">
            <button class="btn sm ghost" @click="createModal = false">取消</button>
            <button class="btn sm seal" :disabled="busy" @click="submitCreate">创建</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 借阅申请浮层 -->
    <div v-if="borrowModal" class="mask" @click.self="borrowModal = false">
      <div class="card" style="width:360px">
        <div class="card-h"><h4>发起借阅</h4></div>
        <div class="card-b" style="display:flex;flex-direction:column;gap:12px">
          <label style="font-size:12px">借阅案卷 *</label>
          <select class="sel" v-model.number="bf.archive_id">
            <option :value="0" disabled>— 选择案卷 —</option>
            <option v-for="a in archives" :key="a.id" :value="a.id">{{ a.code || ('#' + a.id) }} · {{ a.title }}</option>
          </select>
          <label style="font-size:12px">用途</label>
          <input class="sel" v-model="bf.purpose" placeholder="借阅用途" />
          <div style="display:flex;gap:12px">
            <div style="flex:1"><label style="font-size:12px">方式</label><select class="sel" v-model="bf.borrow_type"><option v-for="(v, k) in BORROW_TYPE" :key="k" :value="k">{{ v }}</option></select></div>
            <div style="flex:1"><label style="font-size:12px">应还日期</label><input class="sel" type="date" v-model="bf.due_at" /></div>
          </div>
          <div style="display:flex;gap:8px;justify-content:flex-end">
            <button class="btn sm ghost" @click="borrowModal = false">取消</button>
            <button class="btn sm seal" :disabled="busy" @click="submitBorrow">提交申请</button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.sel { font-size:12px; padding:5px 10px; border:1px solid var(--line-hard,#d8d2c4); border-radius:6px; background:#fff; outline:none; }
.sel:focus { border-color:var(--ink); }
.sel:disabled { opacity:.5; cursor:not-allowed; }
.pager { display:flex;align-items:center;gap:14px;justify-content:center;margin-top:18px; }
.pg-info { font-size:12px;color:var(--ink-mute); }
.pager .btn:disabled { opacity:.4;cursor:not-allowed; }
.btn[disabled] { opacity:.5;cursor:not-allowed;transform:none; }
.btn.xs { font-size:11px;padding:2px 8px; }
.ops { display:flex;flex-wrap:wrap;gap:4px; }
.row-on { background:var(--seal-soft,#fbf6ee); }
.rv-title { font-family:var(--serif);font-weight:700;font-size:15px;line-height:1.4; }
.mask { position:fixed;inset:0;background:rgba(20,20,20,.4);display:grid;place-items:center;z-index:60; }
.ck-card { height:100%; }
.kv { display:flex;justify-content:space-between;gap:10px;font-size:12px;padding:3px 0;border-bottom:1px dashed var(--line-hard,#eee6d8); }
.kv .k { color:var(--ink-mute); }
.kv .v { color:var(--ink-soft); word-break:break-all; text-align:right; }
.ck-foot { display:flex;justify-content:space-between;margin-top:8px;font-size:11px;color:var(--ink-mute); }
.hit-card { cursor:default; }
.hit-name { font-family:var(--serif);font-weight:700;font-size:14px; }
.hit-meta { font-size:11px;color:var(--ink-mute);margin-top:4px;word-break:break-all; }
.hit-foot { display:flex;flex-wrap:wrap;gap:14px;margin-top:8px;font-size:11px;color:var(--ink-mute); }
.snippet { font-size:13px;line-height:1.7;color:var(--ink-soft); }
.snippet .mark { background:#fff2b8;color:var(--ink);padding:0 2px;border-radius:2px;font-weight:700; }
</style>
