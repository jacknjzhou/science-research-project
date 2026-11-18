<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { api, ApiError, type PageResult } from '@/api/client'

// 阶段汇报与验收申请（M2-b C2）：外部机构按本机构项目提交/查看。
// 字段全 snake_case（02-E 契约 EProgressReport / EFinalAccept）。
interface Report {
  id: number
  project_id?: number
  period?: string
  report_type?: string
  progress_percent?: number
  content_rich?: string | null
  submitted_at?: string | null
  created_at?: string | null
}
interface FinalAccept {
  id: number
  project_id?: number
  status?: string
  output_summary?: string | null
  apply_at?: string | null
  accept_at?: string | null
  approval_doc_id?: number | null
}

const toast = (m: string) => (window as any).toast?.(m)

const projectId = ref<number | null>(null)
const rows = ref<Report[]>([])
const total = ref(0)
const loading = ref(false)
const err = ref('')
const fa = ref<FinalAccept | null>(null)
const faErr = ref('')

const form = reactive({ period: '', report_type: 'QUARTERLY', progress_percent: 0, content_rich: '' })
const ready = computed(() => !!projectId.value && form.period.trim().length > 0)

async function load() {
  if (!projectId.value) return
  loading.value = true
  err.value = ''
  faErr.value = ''
  try {
    const r = await api.get<PageResult<Report>>(`/project/${projectId.value}/progress-report`, { page: 1, size: 50 })
    rows.value = r.list || []
    total.value = r.total || 0
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : String((e as any)?.message || e)
  } finally {
    loading.value = false
  }
  try {
    fa.value = await api.get<FinalAccept>(`/project/${projectId.value}/final-accept`)
  } catch {
    fa.value = null // 尚未申请验收（后端 404）
  }
}

async function submitReport() {
  if (!ready.value) return
  try {
    await api.post<Report>(`/project/${projectId.value}/progress-report`, {
      period: form.period.trim(),
      report_type: form.report_type,
      progress_percent: Number(form.progress_percent) || 0,
      content_rich: form.content_rich || null,
    })
    toast('阶段汇报已提交')
    form.period = ''
    form.content_rich = ''
    form.progress_percent = 0
    await load()
  } catch (e: any) {
    toast('提交失败：' + (e?.message || e))
  }
}

async function applyFinalAccept() {
  if (!projectId.value) return
  try {
    fa.value = await api.post<FinalAccept>(`/project/${projectId.value}/final-accept`, {
      output_summary: form.content_rich || null,
    })
    toast('验收申请已提交，等待管理端评审')
  } catch (e: any) {
    toast('提交失败：' + (e?.message || e))
  }
}

function dateShort(v?: string | null): string {
  if (!v) return '—'
  const d = new Date(v)
  return isNaN(d.getTime()) ? '—' : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function useProject() {
  if (projectId.value && projectId.value > 0) load()
}
</script>

<template>
  <section class="view on">
    <div class="page-head">
      <div>
        <div class="page-title">阶段汇报与<em>验收</em></div>
        <div class="page-sub">按本机构项目提交季度汇报 · 项目末期可提交结题验收申请</div>
      </div>
      <div style="display:flex;gap:10px;align-items:center">
        <input v-model.number="projectId" class="fg" style="width:150px" placeholder="项目 ID" />
        <button class="btn" @click="useProject">载入</button>
        <button class="btn ghost" @click="load">刷新</button>
      </div>
    </div>

    <div v-if="!projectId" class="card"><div class="card-b" style="text-align:center;color:var(--ink-mute)">请输入本机构的项目 ID 后载入</div></div>
    <template v-else>
      <div v-if="err" class="card"><div class="card-b" style="text-align:center;color:#c0392b">{{ err }}</div></div>
      <div v-else class="card">
        <div class="card-h"><h5>阶段汇报（{{ total }}）</h5></div>
        <table class="tbl" width="100%" style="border-collapse:collapse">
          <thead><tr style="text-align:left">
            <th>周期</th><th style="width:110px">类型</th><th style="width:90px">进度</th>
            <th>内容</th><th style="width:110px">提交时间</th>
          </tr></thead>
          <tbody>
            <tr v-for="r in rows" :key="r.id">
              <td class="mono" style="font-size:12px">{{ r.period }}</td>
              <td style="font-size:12px">{{ r.report_type }}</td>
              <td class="mono">{{ r.progress_percent }}%</td>
              <td style="font-size:12px;color:var(--ink-mute)">{{ r.content_rich || '—' }}</td>
              <td class="mono" style="font-size:11.5px">{{ dateShort(r.submitted_at || r.created_at) }}</td>
            </tr>
            <tr v-if="!rows.length && !loading"><td colspan="5" style="opacity:.6;padding:16px">暂无汇报</td></tr>
          </tbody>
        </table>

        <div class="hr-rule" style="margin:6px 16px 0"></div>
        <div class="form-grid">
          <div>
            <div class="fld">汇报周期 *</div>
            <input v-model="form.period" class="fg" style="width:100%" placeholder="如 2026Q1" />
          </div>
          <div>
            <div class="fld">类型</div>
            <select v-model="form.report_type" class="fg" style="width:100%">
              <option value="QUARTERLY">季度汇报</option>
              <option value="HALF_YEAR">半年汇报</option>
              <option value="ANNUAL">年度汇报</option>
            </select>
          </div>
          <div>
            <div class="fld">完成进度（%）</div>
            <input v-model.number="form.progress_percent" type="number" min="0" max="100" class="fg" style="width:100%" />
          </div>
          <div>
            <div class="fld">汇报内容</div>
            <textarea v-model="form.content_rich" class="fg" rows="2" style="width:100%"></textarea>
          </div>
        </div>
        <div style="display:flex;gap:10px;padding:0 16px 16px">
          <button class="btn seal" :disabled="!ready" @click="submitReport">提交汇报</button>
          <button class="btn" :disabled="!!fa" @click="applyFinalAccept">提交验收申请</button>
        </div>
      </div>

      <div class="card" style="margin-top:12px">
        <div class="card-h"><h5>结题验收</h5></div>
        <div v-if="faErr" class="card-b" style="color:#c0392b">{{ faErr }}</div>
        <table v-else-if="fa" class="tbl" width="100%" style="border-collapse:collapse">
          <tbody>
            <tr><td style="width:150px;color:var(--ink-mute);font-size:12px">验收单号</td><td class="mono">{{ fa.id }}</td></tr>
            <tr><td style="width:150px;color:var(--ink-mute);font-size:12px">状态</td><td><span class="tag" :class="fa.status === 'APPROVED' ? 'ok' : 'info'">{{ fa.status }}</span></td></tr>
            <tr><td style="width:150px;color:var(--ink-mute);font-size:12px">成果摘要</td><td style="font-size:12.5px">{{ fa.output_summary || '—' }}</td></tr>
            <tr><td style="width:150px;color:var(--ink-mute);font-size:12px">申请时间</td><td class="mono" style="font-size:12px">{{ dateShort(fa.apply_at) }}</td></tr>
            <tr v-if="fa.accept_at"><td style="width:150px;color:var(--ink-mute);font-size:12px">通过时间</td><td class="mono" style="font-size:12px">{{ dateShort(fa.accept_at) }}</td></tr>
            <tr v-if="fa.approval_doc_id"><td style="width:150px;color:var(--ink-mute);font-size:12px">批文编号</td><td class="mono">{{ fa.approval_doc_id }}</td></tr>
          </tbody>
        </table>
        <div v-else class="card-b" style="opacity:.7">尚未提交验收申请；通过后系统会向 PI 发通知并向机构邮箱发结题函。</div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.card-h { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 10px; }
.card-h h5 { margin: 0; font-family: var(--serif); font-size: 14px; }
.form-grid { display: grid; grid-template-columns: 160px 140px 120px minmax(0, 1fr); gap: 12px; padding: 12px 16px 4px; }
.fld { font-size: 12px; color: var(--ink-mute); margin-bottom: 6px; letter-spacing: 1px; }
.mono { font-family: var(--mono); }
</style>
