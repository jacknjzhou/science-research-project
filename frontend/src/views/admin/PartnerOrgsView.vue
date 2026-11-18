<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { api, list, ApiError } from '@/api/client'

// 外部机构资质审核台（M2-a C1）：R-MANAGER 专属。
// 列表 GET /partner-orgs（status/keyword 过滤 + 分页），动作 POST /partner-orgs/{id}/audit。
// 字段对齐契约 12-U PartnerOrg / PartnerOrgAuditRequest（全 snake_case）。
interface PartnerOrg {
  id: number
  code?: string | null
  name?: string
  short_name?: string | null
  credit_code?: string
  org_type?: string
  contact_name?: string | null
  contact_phone?: string | null
  contact_email?: string | null
  status?: string
  audit_user_id?: number | null
  audited_at?: string | null
  reject_reason?: string | null
  created_at?: string
}

const ORG_TYPE_LABEL: Record<string, string> = {
  COLLAB: '协作单位', SUPPLIER: '供应商', UNIVERSITY: '高校', INSTITUTE: '科研院所',
}
const STATUS_TAG: Record<string, { text: string; cls: string }> = {
  PENDING: { text: '待审核', cls: 'warn' },
  APPROVED: { text: '已通过', cls: 'ok' },
  REJECTED: { text: '已驳回', cls: 'info' },
  SUSPENDED: { text: '已暂停', cls: 'info' },
}

const toast = (m: string) => (window as any).toast?.(m)

const rows = ref<PartnerOrg[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const status = ref('PENDING')
const keyword = ref('')
const loading = ref(false)
const err = ref('')
const acting = ref(0)

const pendingCount = computed(() => rows.value.filter((r) => r.status === 'PENDING').length)

async function reload() {
  loading.value = true
  err.value = ''
  try {
    const params: Record<string, any> = { page: page.value, size: size.value }
    if (status.value) params.status = status.value
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    const r = await list<PartnerOrg>('/partner-orgs', params)
    rows.value = r.rows
    total.value = r.total
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : String((e as any)?.message || e)
  } finally {
    loading.value = false
  }
}

function filterBy(s: string) {
  status.value = s
  page.value = 1
  reload()
}

// —— 驳回理由 ——
const rejectDrawer = reactive({ open: false, saving: false, reason: '', target: null as PartnerOrg | null })
function openReject(o: PartnerOrg) {
  rejectDrawer.target = o
  rejectDrawer.reason = ''
  rejectDrawer.open = true
}
async function submitReject() {
  const o = rejectDrawer.target
  const reason = rejectDrawer.reason.trim()
  if (!o || !reason) {
    toast('请填写驳回理由')
    return
  }
  if (rejectDrawer.saving) return
  rejectDrawer.saving = true
  try {
    const r = await api.post<PartnerOrg>(`/partner-orgs/${o.id}/audit`, { action: 'REJECT', reason })
    applyResult(r)
    rejectDrawer.open = false
    toast(`已驳回 ${o.name}`)
  } catch (e: any) {
    toast('驳回失败：' + (e?.message || e))
  } finally {
    rejectDrawer.saving = false
  }
}

async function approve(o: PartnerOrg) {
  if (acting.value) return
  acting.value = o.id
  try {
    const r = await api.post<PartnerOrg>(`/partner-orgs/${o.id}/audit`, { action: 'APPROVE' })
    applyResult(r)
    toast(`${o.name} 审核通过，外部账号已激活并邮件通知`)
  } catch (e: any) {
    toast('审核失败：' + (e?.message || e))
  } finally {
    acting.value = 0
  }
}

// 就地刷新单行（后端幂等，重复通过不会重复授权）
function applyResult(r: PartnerOrg | null | undefined) {
  if (!r) return
  const i = rows.value.findIndex((x) => x.id === r.id)
  if (i >= 0) rows.value[i] = r
}

function dateShort(v?: string | null): string {
  if (!v) return '—'
  const d = new Date(v)
  return isNaN(d.getTime()) ? '—' : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

onMounted(reload)
</script>

<template>
  <section class="view on" id="v-partner-orgs">
    <div class="page-head">
      <div>
        <div class="page-title">机构<em>资质审核</em></div>
        <div class="page-sub">
          共 {{ total }} 家外部机构 · 本页待审
          <span style="color:var(--warn,#b7791f)">{{ pendingCount }}</span> 家 · 通过即激活账号并授予 R-PARTNER
        </div>
      </div>
      <div style="display:flex;gap:8px">
        <input v-model="keyword" class="fg" placeholder="🔍 机构名称 / 信用代码" style="width:220px"
               @keyup.enter="page = 1; reload()" />
        <button class="btn" @click="reload">刷新</button>
      </div>
    </div>

    <div class="filter-row">
      <span class="chip" :class="{ on: status === 'PENDING' }" @click="filterBy('PENDING')">待审核</span>
      <span class="chip" :class="{ on: status === 'APPROVED' }" @click="filterBy('APPROVED')">已通过</span>
      <span class="chip" :class="{ on: status === 'REJECTED' }" @click="filterBy('REJECTED')">已驳回</span>
      <span class="chip" :class="{ on: status === '' }" @click="filterBy('')">全部</span>
    </div>

    <div v-if="err" class="card"><div class="card-b" style="color:#c0392b">{{ err }}</div></div>

    <div class="card" style="padding:6px 16px 14px">
      <table class="tbl" width="100%" style="border-collapse:collapse">
        <thead>
          <tr style="text-align:left">
            <th style="width:130px">机构编号</th>
            <th>机构名称</th>
            <th style="width:96px">类型</th>
            <th style="width:190px">统一社会信用代码</th>
            <th style="width:150px">联系人</th>
            <th style="width:88px">状态</th>
            <th style="width:110px">提交时间</th>
            <th style="width:130px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="o in rows" :key="o.id">
            <td class="mono" style="font-size:11.5px">{{ o.code || '—' }}</td>
            <td>
              <div style="font-size:13px">{{ o.name }}</div>
              <div v-if="o.reject_reason" style="font-size:11px;color:#a12b2b;margin-top:2px">驳回理由：{{ o.reject_reason }}</div>
            </td>
            <td class="mono" style="font-size:11.5px">{{ ORG_TYPE_LABEL[o.org_type || ''] || o.org_type || '—' }}</td>
            <td class="mono" style="font-size:11.5px">{{ o.credit_code || '—' }}</td>
            <td>
              <div style="font-size:12px">{{ o.contact_name || '—' }}</div>
              <div class="mono" style="font-size:11px;color:var(--ink-mute)">{{ o.contact_phone || o.contact_email || '—' }}</div>
            </td>
            <td>
              <span class="tag" :class="STATUS_TAG[o.status || '']?.cls || 'info'">{{ STATUS_TAG[o.status || '']?.text || o.status }}</span>
            </td>
            <td class="mono" style="font-size:11.5px">{{ dateShort(o.created_at) }}</td>
            <td>
              <template v-if="o.status === 'PENDING'">
                <button class="btn sm" :disabled="acting === o.id" @click="approve(o)">通过</button>
                <button class="btn sm ghost" :disabled="acting === o.id" @click="openReject(o)">驳回</button>
              </template>
              <span v-else-if="o.status === 'APPROVED'" class="mono" style="font-size:11px;color:var(--ink-mute)">
                {{ dateShort(o.audited_at) }} 通过
              </span>
              <span v-else class="mono" style="font-size:11px;color:var(--ink-mute)">—</span>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="8" style="opacity:.6;padding:18px;text-align:center">{{ loading ? '加载中…' : '暂无机构申请' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 驳回抽屉 -->
    <div v-if="rejectDrawer.open" style="position:fixed;inset:0;background:rgba(15,23,42,.35);z-index:60" @click.self="rejectDrawer.open = false">
      <div style="position:absolute;right:0;top:0;bottom:0;width:400px;background:var(--paper);box-shadow:-12px 0 40px rgba(15,23,42,.18);padding:22px;overflow:auto">
        <div style="display:flex;align-items:center;justify-content:space-between">
          <h4 style="font-family:var(--serif);font-size:16px">驳回机构申请</h4>
          <button class="btn ghost sm" @click="rejectDrawer.open = false">关闭</button>
        </div>
        <div class="hr-rule" style="margin:12px 0"></div>
        <div style="font-size:12.5px;color:var(--ink-mute)">{{ rejectDrawer.target?.name }}</div>
        <div class="fld">驳回理由（将邮件通知联系人）</div>
        <textarea v-model="rejectDrawer.reason" class="fg" rows="4" style="width:100%"
                  placeholder="如：资质证明缺失、信用代码与营业执照不一致…"></textarea>
        <div style="margin-top:16px;display:flex;gap:10px">
          <button class="btn seal" :disabled="rejectDrawer.saving" @click="submitReject">{{ rejectDrawer.saving ? '提交中…' : '确认驳回' }}</button>
          <button class="btn ghost" @click="rejectDrawer.open = false">取消</button>
        </div>
        <p style="font-size:11.5px;color:var(--ink-mute);line-height:1.8;margin-top:14px">
          驳回后该机构账号保持锁定，机构可补齐材料后重新提交注册。
        </p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.fld { font-size: 12px; color: var(--ink-mute); margin-top: 12px; letter-spacing: 1px; }
.mono { font-family: var(--mono); }
</style>
