<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { api, ApiError, type PageResult } from '@/api/client'

// 指南建议审核（M2-b C2，管理端）：列表 + 采纳（自动生成指南草稿）/ 驳回。
// 字段全 snake_case（01-P 契约 GuideSuggestion）。
interface Suggestion {
  id: number
  code?: string | null
  title?: string
  content_rich?: string | null
  org_id?: number | null
  status?: string
  guideline_id?: number | null
  reject_reason?: string | null
  created_at?: string | null
}

const STATUS_LABEL: Record<string, string> = { PENDING: '待处理', ACCEPTED: '已采纳', REJECTED: '已驳回' }
const STATUS_TONE: Record<string, string> = { PENDING: 'info', ACCEPTED: 'ok', REJECTED: 'warn' }

const toast = (m: string) => (window as any).toast?.(m)

const rows = ref<Suggestion[]>([])
const total = ref(0)
const loading = ref(true)
const err = ref('')
const filter = reactive({ status: 'PENDING' })
const acting = ref(0)

async function load() {
  loading.value = true
  err.value = ''
  try {
    const r = await api.get<PageResult<Suggestion>>('/apply/guide-suggestions', {
      page: 1, size: 50, status: filter.status || undefined,
    })
    rows.value = r.list || []
    total.value = r.total || 0
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : String((e as any)?.message || e)
  } finally {
    loading.value = false
  }
}

const drawer = reactive({ open: false, mode: 'REJECT' as 'REJECT' | 'ACCEPT', target: null as Suggestion | null, reason: '', saving: false })
const ready = computed(() => drawer.mode === 'ACCEPT' || drawer.reason.trim().length > 0)

function openReject(s: Suggestion) {
  drawer.mode = 'REJECT'
  drawer.target = s
  drawer.reason = ''
  drawer.open = true
}

async function accept(s: Suggestion) {
  if (acting.value) return
  acting.value = s.id
  try {
    const r = await api.post<{ guideline_id?: number }>(`/apply/guide-suggestions/${s.id}:accept`, {})
    toast(r?.guideline_id ? `已采纳，生成指南草稿 #${r.guideline_id}` : '已采纳')
    await load()
  } catch (e: any) {
    toast('采纳失败：' + (e?.message || e))
  } finally {
    acting.value = 0
  }
}

async function doReject() {
  const s = drawer.target
  if (!s || !ready.value || drawer.saving) return
  drawer.saving = true
  try {
    await api.post<Suggestion>(`/apply/guide-suggestions/${s.id}:reject`, { reason: drawer.reason.trim() })
    drawer.open = false
    toast('已驳回')
    await load()
  } catch (e: any) {
    toast('驳回失败：' + (e?.message || e))
  } finally {
    drawer.saving = false
  }
}

function dateShort(v?: string | null): string {
  if (!v) return '—'
  const d = new Date(v)
  return isNaN(d.getTime()) ? '—' : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

onMounted(load)
</script>

<template>
  <section class="view on">
    <div class="page-head">
      <div>
        <div class="page-title">指南建议<em>审核</em></div>
        <div class="page-sub">外部机构提交的征集建议 · 采纳即生成指南草稿（DRAFT），需在申报指南页发布</div>
      </div>
      <div style="display:flex;gap:10px;align-items:center">
        <select v-model="filter.status" class="fg" style="width:130px" @change="load">
          <option value="">全部状态</option>
          <option value="PENDING">待处理</option>
          <option value="ACCEPTED">已采纳</option>
          <option value="REJECTED">已驳回</option>
        </select>
        <button class="btn ghost" @click="load">刷新</button>
      </div>
    </div>

    <div v-if="loading" class="card"><div class="card-b" style="text-align:center;color:var(--ink-mute)">正在加载建议…</div></div>
    <div v-else-if="err" class="card"><div class="card-b" style="text-align:center;color:#c0392b">{{ err }}</div></div>
    <div v-else class="card">
      <div class="card-h"><h5>建议列表（{{ total }}）</h5></div>
      <table class="tbl" width="100%" style="border-collapse:collapse">
        <thead><tr style="text-align:left">
          <th>编号</th><th>建议标题</th><th style="width:96px">提出机构</th><th style="width:92px">状态</th>
          <th>理由 / 关联指南</th><th style="width:110px">提交时间</th><th style="width:170px">操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="s in rows" :key="s.id">
            <td class="mono" style="font-size:11.5px">{{ s.code || '—' }}</td>
            <td>{{ s.title }}</td>
            <td class="mono" style="font-size:11.5px">{{ s.org_id ?? '院内' }}</td>
            <td><span class="tag" :class="STATUS_TONE[s.status || ''] || 'info'">{{ STATUS_LABEL[s.status || ''] || s.status }}</span></td>
            <td style="font-size:12px;color:var(--ink-mute)">
              <template v-if="s.guideline_id">指南 #{{ s.guideline_id }}</template>
              <template v-else>{{ s.reject_reason || '—' }}</template>
            </td>
            <td class="mono" style="font-size:11.5px">{{ dateShort(s.created_at) }}</td>
            <td>
              <template v-if="s.status === 'PENDING'">
                <button class="btn sm seal" :disabled="acting === s.id" @click="accept(s)">采纳</button>
                <button class="btn sm ghost" :disabled="acting === s.id" @click="openReject(s)">驳回</button>
              </template>
              <span v-else style="opacity:.55;font-size:11.5px">已处理</span>
            </td>
          </tr>
          <tr v-if="!rows.length"><td colspan="7" style="opacity:.6;padding:16px">暂无待处理建议</td></tr>
        </tbody>
      </table>
    </div>

    <div v-if="drawer.open" style="position:fixed;inset:0;background:rgba(15,23,42,.35);z-index:60" @click.self="drawer.open = false">
      <div style="position:absolute;right:0;top:0;bottom:0;width:420px;background:var(--paper);box-shadow:-12px 0 40px rgba(15,23,42,.18);padding:22px;overflow:auto">
        <div style="display:flex;align-items:center;justify-content:space-between">
          <h4 style="font-family:var(--serif);font-size:16px">驳回建议</h4>
          <button class="btn ghost sm" @click="drawer.open = false">关闭</button>
        </div>
        <div class="hr-rule" style="margin:12px 0"></div>
        <div style="font-size:12.5px;margin-bottom:12px">{{ drawer.target?.title }}</div>
        <div class="fld">驳回理由 *</div>
        <textarea v-model="drawer.reason" class="fg" rows="4" style="width:100%" placeholder="如：与本年征集方向不匹配 / 建议内容过宽泛"></textarea>
        <div style="margin-top:16px;display:flex;gap:10px">
          <button class="btn seal" :disabled="!ready || drawer.saving" @click="doReject">{{ drawer.saving ? '提交中…' : '确认驳回' }}</button>
          <button class="btn ghost" @click="drawer.open = false">取消</button>
        </div>
        <p style="font-size:11.5px;color:var(--ink-mute);line-height:1.8;margin-top:14px">
          驳回理由必填，会展示给提出机构；采纳则自动生成一条指南草稿，之后在「申报指南」页补全并发布。
        </p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.card-h { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 10px; }
.card-h h5 { margin: 0; font-family: var(--serif); font-size: 14px; }
.fld { font-size: 12px; color: var(--ink-mute); margin-top: 12px; letter-spacing: 1px; }
.mono { font-family: var(--mono); }
</style>
