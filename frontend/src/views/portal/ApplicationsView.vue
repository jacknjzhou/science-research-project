<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError, type PageResult } from '@/api/client'
import { auth } from '@/api/auth'

// 我的申报（M2-b C2）：R-PARTNER 专属。后端按登录用户 org_id 收敛到本机构，
// 前端不做过滤。字段全 snake_case（01-P 契约），金额为字符串。
interface Application {
  id: number
  code?: string | null
  title?: string
  project_type?: string
  status?: string
  applicant_org_id?: number | null
  applicant_type?: string
  total_budget?: string | null
  duration_months?: number | null
  updated_at?: string | null
}

const STATUS_LABEL: Record<string, string> = {
  DRAFT: '草稿', SUBMITTED: '已提交', FORMAL_CHECK: '形式审查',
  RECOMMENDED: '待评审', UNDER_REVIEW: '评审中', INTERVIEWING: '答辩中',
  DECIDED: '已决议', PUBLISHED: '立项通过', SIGNED: '已签约',
  EXECUTING: '执行中', REJECTED: '未通过', WITHDRAWN: '已撤回',
}
const STATUS_TONE: Record<string, string> = {
  DRAFT: 'info', SUBMITTED: 'info', PUBLISHED: 'ok', DECIDED: 'ok',
  SIGNED: 'ok', EXECUTING: 'ok', REJECTED: 'warn', WITHDRAWN: 'warn',
}

const router = useRouter()
const toast = (m: string) => (window as any).toast?.(m)

const rows = ref<Application[]>([])
const total = ref(0)
const loading = ref(true)
const err = ref('')
const acting = ref(0)

async function load() {
  loading.value = true
  err.value = ''
  try {
    const r = await api.get<PageResult<Application>>('/apply/applications', { page: 1, size: 50 })
    rows.value = r.list || []
    total.value = r.total || 0
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : String((e as any)?.message || e)
  } finally {
    loading.value = false
  }
}

// —— 新建申报（外部机构：PI 与机构由后端强制为本人/本机构，前端不传）——
const drawer = reactive({ open: false, saving: false })
const form = reactive({ title: '', project_type: '开放课题', duration_months: 12, total_budget: '', abstract: '' })
const ready = computed(() => form.title.trim().length > 0 && !!form.project_type && Number(form.total_budget) > 0)

function openDrawer() {
  form.title = ''
  form.project_type = '开放课题'
  form.duration_months = 12
  form.total_budget = ''
  form.abstract = ''
  drawer.open = true
}

async function create() {
  if (!ready.value || drawer.saving) return
  drawer.saving = true
  try {
    await api.post<Application>('/apply/applications', {
      title: form.title.trim(),
      project_type: form.project_type,
      duration_months: Number(form.duration_months) || 12,
      total_budget: Number(form.total_budget).toFixed(2),
      abstract: form.abstract || null,
    })
    drawer.open = false
    toast('申报已创建（草稿）')
    await load()
  } catch (e: any) {
    toast('创建失败：' + (e?.message || e))
  } finally {
    drawer.saving = false
  }
}

async function submit(a: Application) {
  if (acting.value) return
  acting.value = a.id
  try {
    await api.post<Application>(`/apply/applications/${a.id}/submit`, {})
    toast('申报已提交')
    await load()
  } catch (e: any) {
    toast('提交失败：' + (e?.message || e))
  } finally {
    acting.value = 0
  }
}

/** 立项通过后可生成任务书（PUBLISHED/DECIDED），生成后进入签订页。 */
async function genTaskBook(a: Application) {
  if (acting.value) return
  acting.value = a.id
  try {
    const tb = await api.post<{ id: number }>('/apply/task-books', { application_id: a.id })
    toast('任务书已生成')
    router.push(`/portal/task-book?id=${tb.id}`)
  } catch (e: any) {
    toast('生成失败：' + (e?.message || e))
  } finally {
    acting.value = 0
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
        <div class="page-title">我的<em>申报</em></div>
        <div class="page-sub">本机构开放课题申报 · 立项通过后可生成任务书并电子签章</div>
      </div>
      <div style="display:flex;gap:10px">
        <button class="btn ghost" @click="load">刷新</button>
        <button class="btn seal" @click="openDrawer">新建申报</button>
      </div>
    </div>

    <div v-if="loading" class="card"><div class="card-b" style="text-align:center;color:var(--ink-mute)">正在加载申报…</div></div>
    <div v-else-if="err" class="card"><div class="card-b" style="text-align:center;color:#c0392b">{{ err }}</div></div>
    <div v-else class="card">
      <div class="card-h"><h5>申报列表（{{ total }}）</h5></div>
      <table class="tbl" width="100%" style="border-collapse:collapse">
        <thead><tr style="text-align:left">
          <th>编号</th><th>标题</th><th style="width:96px">类型</th><th style="width:92px">状态</th>
          <th style="width:120px">预算</th><th style="width:110px">更新</th><th style="width:190px">操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="a in rows" :key="a.id">
            <td class="mono" style="font-size:11.5px">{{ a.code || '—' }}</td>
            <td>{{ a.title }}</td>
            <td class="mono" style="font-size:11.5px">{{ a.project_type || '—' }}</td>
            <td><span class="tag" :class="STATUS_TONE[a.status || ''] || 'info'">{{ STATUS_LABEL[a.status || ''] || a.status }}</span></td>
            <td class="mono">￥{{ a.total_budget || '0.00' }}</td>
            <td class="mono" style="font-size:11.5px">{{ dateShort(a.updated_at) }}</td>
            <td>
              <button v-if="a.status === 'DRAFT'" class="btn sm" :disabled="acting === a.id" @click="submit(a)">提交</button>
              <button v-if="a.status === 'PUBLISHED' || a.status === 'DECIDED'" class="btn sm seal" :disabled="acting === a.id" @click="genTaskBook(a)">生成任务书</button>
              <span v-if="!['DRAFT','PUBLISHED','DECIDED'].includes(a.status || '')" style="opacity:.55;font-size:11.5px">—</span>
            </td>
          </tr>
          <tr v-if="!rows.length"><td colspan="7" style="opacity:.6;padding:16px">暂无申报，点击右上角「新建申报」</td></tr>
        </tbody>
      </table>
    </div>

    <div v-if="drawer.open" style="position:fixed;inset:0;background:rgba(15,23,42,.35);z-index:60" @click.self="drawer.open = false">
      <div style="position:absolute;right:0;top:0;bottom:0;width:440px;background:var(--paper);box-shadow:-12px 0 40px rgba(15,23,42,.18);padding:22px;overflow:auto">
        <div style="display:flex;align-items:center;justify-content:space-between">
          <h4 style="font-family:var(--serif);font-size:16px">新建申报</h4>
          <button class="btn ghost sm" @click="drawer.open = false">关闭</button>
        </div>
        <div class="hr-rule" style="margin:12px 0"></div>
        <div class="fld">课题名称 *</div>
        <input v-model="form.title" class="fg" style="width:100%" placeholder="如：面向开放数据的可信治理研究" />
        <div class="fld">项目类型 *</div>
        <select v-model="form.project_type" class="fg" style="width:100%">
          <option value="开放课题">开放课题</option>
          <option value="横向课题">横向课题</option>
          <option value="自立项目">自立项目</option>
        </select>
        <div class="fld">研究周期（月）</div>
        <input v-model="form.duration_months" type="number" min="1" class="fg" style="width:100%" />
        <div class="fld">申请经费（元）*</div>
        <input v-model="form.total_budget" class="fg" style="width:100%" placeholder="如 100000" />
        <div class="fld">摘要</div>
        <textarea v-model="form.abstract" class="fg" rows="3" style="width:100%"></textarea>
        <div style="margin-top:16px;display:flex;gap:10px">
          <button class="btn seal" :disabled="!ready || drawer.saving" @click="create">{{ drawer.saving ? '创建中…' : '创建草稿' }}</button>
          <button class="btn ghost" @click="drawer.open = false">取消</button>
        </div>
        <p style="font-size:11.5px;color:var(--ink-mute);line-height:1.8;margin-top:14px">
          外部机构申报：负责人与申报机构由系统按登录账号锁定为本机构，无需填写。
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
