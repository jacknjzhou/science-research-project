<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { api, ApiError, type PageResult } from '@/api/client'

// 专家申请审核台（M2-c C3）：通过即授 R-EXPERT，驳回需填理由。
interface Application {
  id: number; code?: string | null; status: string; name: string
  title?: string | null; org_name?: string | null; phone?: string | null
  email?: string | null; field_tags?: string[]; created_at?: string | null
  audited_at?: string | null; reject_reason?: string | null
}
const STATUS_LABEL: Record<string, string> = {
  CANDIDATE: '待审核', ACTIVE: '已通过', SUSPENDED: '已驳回', BLACKLIST: '黑名单',
}

const rows = ref<Application[]>([])
const total = ref(0)
const loading = ref(true)
const err = ref('')
const statusFilter = ref('CANDIDATE')

async function load() {
  loading.value = true
  err.value = ''
  try {
    const r = await api.get<PageResult<Application>>('/expert-applications', {
      page: 1, size: 50, status: statusFilter.value || 'CANDIDATE',
    })
    rows.value = r.list || []
    total.value = r.total || 0
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : String((e as any)?.message || e)
  } finally {
    loading.value = false
  }
}

const drawer = reactive({ open: false, saving: false, mode: 'APPROVE' as 'APPROVE' | 'REJECT', target: null as Application | null })
const reason = ref('')

function openAudit(a: Application, mode: 'APPROVE' | 'REJECT') {
  drawer.target = a
  drawer.mode = mode
  reason.value = ''
  drawer.open = true
}

async function submit() {
  if (!drawer.target || drawer.saving) return
  if (drawer.mode === 'REJECT' && !reason.value.trim()) return
  drawer.saving = true
  try {
    await api.post(`/expert-applications/${drawer.target.id}/audit`, {
      action: drawer.mode,
      reason: drawer.mode === 'REJECT' ? reason.value.trim() : null,
    })
    drawer.open = false
    ;(window as any).toast?.(drawer.mode === 'APPROVE' ? '已通过并授权 R-EXPERT' : '已驳回')
    await load()
  } catch (e: any) {
    ;(window as any).toast?.('操作失败：' + (e?.message || e))
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
        <div class="page-title">专家申请<em>审核</em></div>
        <div class="page-sub">外部专家资质审核 · 通过后自动授予评审专家权限并邮件通知</div>
      </div>
      <div style="display:flex;gap:10px">
        <select v-model="statusFilter" class="fg" style="width:130px" @change="load">
          <option value="CANDIDATE">待审核</option>
          <option value="ACTIVE">已通过</option>
          <option value="SUSPENDED">已驳回</option>
          <option value="ALL">全部</option>
        </select>
        <button class="btn ghost" @click="load">刷新</button>
      </div>
    </div>

    <div v-if="loading" class="card"><div class="card-b" style="text-align:center;color:var(--ink-mute)">正在加载…</div></div>
    <div v-else-if="err" class="card"><div class="card-b" style="text-align:center;color:#c0392b">{{ err }}</div></div>
    <div v-else class="card">
      <div class="card-h"><h5>申请（{{ total }}）</h5></div>
      <table class="tbl" width="100%" style="border-collapse:collapse">
        <thead><tr style="text-align:left">
          <th>编号</th><th style="width:96px">姓名</th><th>单位 / 职称</th>
          <th>研究领域</th><th style="width:150px">联系方式</th>
          <th style="width:88px">状态</th><th style="width:140px">操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="a in rows" :key="a.id">
            <td class="mono" style="font-size:11.5px">{{ a.code || `#${a.id}` }}</td>
            <td>{{ a.name }}</td>
            <td style="font-size:12px">{{ a.org_name || '—' }}<span v-if="a.title" style="color:var(--ink-mute)"> · {{ a.title }}</span></td>
            <td style="font-size:12px">
              <span v-for="t in (a.field_tags || []).slice(0, 3)" :key="t" class="tag info" style="margin-right:4px">{{ t }}</span>
              <span v-if="!(a.field_tags || []).length" style="color:var(--ink-mute)">—</span>
            </td>
            <td style="font-size:11.5px" class="mono">{{ a.email || a.phone || '—' }}</td>
            <td><span class="tag" :class="a.status === 'CANDIDATE' ? 'info' : a.status === 'ACTIVE' ? 'ok' : 'warn'">{{ STATUS_LABEL[a.status] || a.status }}</span></td>
            <td>
              <template v-if="a.status === 'CANDIDATE'">
                <button class="btn seal sm" @click="openAudit(a, 'APPROVE')">通过</button>
                <button class="btn ghost sm" style="margin-left:6px" @click="openAudit(a, 'REJECT')">驳回</button>
              </template>
              <span v-else style="font-size:11.5px;color:var(--ink-mute)">{{ dateShort(a.audited_at) }}</span>
            </td>
          </tr>
          <tr v-if="!rows.length"><td colspan="7" style="opacity:.6;padding:16px">暂无待审申请</td></tr>
        </tbody>
      </table>
    </div>

    <div v-if="drawer.open" style="position:fixed;inset:0;background:rgba(15,23,42,.35);z-index:60" @click.self="drawer.open = false">
      <div style="position:absolute;right:0;top:0;bottom:0;width:420px;background:var(--paper);box-shadow:-12px 0 40px rgba(15,23,42,.18);padding:22px;overflow:auto">
        <div style="display:flex;align-items:center;justify-content:space-between">
          <h4 style="font-family:var(--serif);font-size:16px">{{ drawer.mode === 'APPROVE' ? '通过专家申请' : '驳回专家申请' }}</h4>
          <button class="btn ghost sm" @click="drawer.open = false">关闭</button>
        </div>
        <div class="hr-rule" style="margin:12px 0"></div>
        <p style="font-size:12px;color:var(--ink-mute);line-height:1.9">
          申请人：{{ drawer.target?.name }}<br />
          单位：{{ drawer.target?.org_name || '—' }}<br />
          邮箱：{{ drawer.target?.email || '—' }}
        </p>
        <template v-if="drawer.mode === 'REJECT'">
          <div class="fld">驳回理由 *</div>
          <textarea v-model="reason" class="fg" rows="4" style="width:100%" placeholder="将随通知邮件发送给申请人"></textarea>
        </template>
        <p v-else style="font-size:12px;color:var(--ink-mute);line-height:1.9">
          通过后系统将：① 档案置为 ACTIVE；② 授予 R-EXPERT 角色；③ 站内信 + 邮件通知本人。
        </p>
        <div style="margin-top:16px;display:flex;gap:10px">
          <button class="btn seal" :disabled="drawer.saving || (drawer.mode === 'REJECT' && !reason.trim())" @click="submit">
            {{ drawer.saving ? '提交中…' : '确认' }}
          </button>
          <button class="btn ghost" @click="drawer.open = false">取消</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.card-h { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 10px; }
.card-h h5 { margin: 0; font-family: var(--serif); font-size: 14px; }
</style>
