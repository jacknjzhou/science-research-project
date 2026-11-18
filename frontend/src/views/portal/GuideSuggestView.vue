<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { api, ApiError, type PageResult } from '@/api/client'

// 指南建议（M2-b C2）：外部机构向主办方建议征集方向，管理端采纳后自动生成指南草稿。
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

const STATUS_LABEL: Record<string, string> = {
  PENDING: '待处理', ACCEPTED: '已采纳', REJECTED: '已驳回',
}
const STATUS_TONE: Record<string, string> = { PENDING: 'info', ACCEPTED: 'ok', REJECTED: 'warn' }

const rows = ref<Suggestion[]>([])
const total = ref(0)
const loading = ref(true)
const err = ref('')

async function load() {
  loading.value = true
  err.value = ''
  try {
    const r = await api.get<PageResult<Suggestion>>('/apply/guide-suggestions', { page: 1, size: 50 })
    rows.value = r.list || []
    total.value = r.total || 0
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : String((e as any)?.message || e)
  } finally {
    loading.value = false
  }
}

const drawer = reactive({ open: false, saving: false })
const form = reactive({ title: '', content_rich: '' })
const ready = computed(() => form.title.trim().length > 0)

function openDrawer() {
  form.title = ''
  form.content_rich = ''
  drawer.open = true
}

async function create() {
  if (!ready.value || drawer.saving) return
  drawer.saving = true
  try {
    await api.post<Suggestion>('/apply/guide-suggestions', {
      title: form.title.trim(),
      content_rich: form.content_rich || null,
    })
    drawer.open = false
    ;(window as any).toast?.('建议已提交，等待主办方处理')
    await load()
  } catch (e: any) {
    ;(window as any).toast?.('提交失败：' + (e?.message || e))
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
        <div class="page-title">指南<em>建议</em></div>
        <div class="page-sub">向主办方建议开放课题征集方向 · 采纳后自动生成指南草稿</div>
      </div>
      <div style="display:flex;gap:10px">
        <button class="btn ghost" @click="load">刷新</button>
        <button class="btn seal" @click="openDrawer">提交建议</button>
      </div>
    </div>

    <div v-if="loading" class="card"><div class="card-b" style="text-align:center;color:var(--ink-mute)">正在加载建议…</div></div>
    <div v-else-if="err" class="card"><div class="card-b" style="text-align:center;color:#c0392b">{{ err }}</div></div>
    <div v-else class="card">
      <div class="card-h"><h5>我的建议（{{ total }}）</h5></div>
      <table class="tbl" width="100%" style="border-collapse:collapse">
        <thead><tr style="text-align:left">
          <th>编号</th><th>建议标题</th><th style="width:92px">状态</th>
          <th>驳回理由</th><th style="width:110px">提交时间</th>
        </tr></thead>
        <tbody>
          <tr v-for="s in rows" :key="s.id">
            <td class="mono" style="font-size:11.5px">{{ s.code || '—' }}</td>
            <td>{{ s.title }}</td>
            <td><span class="tag" :class="STATUS_TONE[s.status || ''] || 'info'">{{ STATUS_LABEL[s.status || ''] || s.status }}</span></td>
            <td style="font-size:12px;color:var(--ink-mute)">{{ s.reject_reason || '—' }}</td>
            <td class="mono" style="font-size:11.5px">{{ dateShort(s.created_at) }}</td>
          </tr>
          <tr v-if="!rows.length"><td colspan="5" style="opacity:.6;padding:16px">暂无建议，点击右上角「提交建议」</td></tr>
        </tbody>
      </table>
    </div>

    <div v-if="drawer.open" style="position:fixed;inset:0;background:rgba(15,23,42,.35);z-index:60" @click.self="drawer.open = false">
      <div style="position:absolute;right:0;top:0;bottom:0;width:440px;background:var(--paper);box-shadow:-12px 0 40px rgba(15,23,42,.18);padding:22px;overflow:auto">
        <div style="display:flex;align-items:center;justify-content:space-between">
          <h4 style="font-family:var(--serif);font-size:16px">提交指南建议</h4>
          <button class="btn ghost sm" @click="drawer.open = false">关闭</button>
        </div>
        <div class="hr-rule" style="margin:12px 0"></div>
        <div class="fld">建议标题 *</div>
        <input v-model="form.title" class="fg" style="width:100%" placeholder="如：面向产业场景的大模型评测方法" />
        <div class="fld">建议内容</div>
        <textarea v-model="form.content_rich" class="fg" rows="6" style="width:100%" placeholder="研究方向、必要性、预期成果等"></textarea>
        <div style="margin-top:16px;display:flex;gap:10px">
          <button class="btn seal" :disabled="!ready || drawer.saving" @click="create">{{ drawer.saving ? '提交中…' : '提交' }}</button>
          <button class="btn ghost" @click="drawer.open = false">取消</button>
        </div>
        <p style="font-size:11.5px;color:var(--ink-mute);line-height:1.8;margin-top:14px">
          建议提交后由科研管理岗审核；采纳时系统会按建议自动生成一条指南草稿，待发布后即可申报。
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
