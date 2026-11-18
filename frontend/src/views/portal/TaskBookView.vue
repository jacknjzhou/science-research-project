<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '@/api/client'
import { auth } from '@/api/auth'

// 任务书详情与签署（M2-b C2）：PI 以本人身份签署，管理端/领导签署后即立项建项。
// 字段全 snake_case（01-P 契约 TaskBook）；content_snapshot 在生成时冻结，不可改。
interface SignRecord { role?: string; signerId?: number; signedAt?: string; result?: string }
interface TaskBook {
  id: number
  code?: string | null
  application_id?: number
  status?: string
  content_snapshot?: Record<string, any>
  sign_records?: SignRecord[]
  effective_date?: string | null
  project_id?: number | null
}

const ROLE_LABEL: Record<string, string> = { PI: '项目负责人', MANAGER: '科研管理', LEADER: '院所领导' }
const STATUS_LABEL: Record<string, string> = { DRAFT: '待签署', SIGNED: '已签订', EXECUTING: '执行中' }

const route = useRoute()
const router = useRouter()
const toast = (m: string) => (window as any).toast?.(m)

const tb = ref<TaskBook | null>(null)
const loading = ref(true)
const err = ref('')
const acting = ref(false)

const id = computed(() => Number(route.query.id || 0))
// 终审 M2-b C2/I4：按钮必须按「当前用户身份 + 角色」收窄，服务端仍会再校验一次
const myRoles = computed(() => auth.roles || [])
const myUid = computed(() => Number((auth.user as any)?.id || 0))
const isPartner = computed(() => myRoles.value.includes('R-PARTNER'))
const signedRoles = computed(() => (tb.value?.sign_records || []).map((r) => r.role))
const snapPiId = computed(() => Number((tb.value?.content_snapshot as any)?.pi_user_id || 0))

const canSignPi = computed(() =>
  !!tb.value && tb.value.status === 'DRAFT' && !signedRoles.value.includes('PI') &&
  myUid.value > 0 && myUid.value === snapPiId.value)
const canSignManager = computed(() =>
  !!tb.value && tb.value.status === 'DRAFT' && !isPartner.value &&
  myRoles.value.includes('R-MANAGER') && !signedRoles.value.includes('MANAGER'))
const canSignLeader = computed(() =>
  !!tb.value && tb.value.status === 'DRAFT' && !isPartner.value &&
  myRoles.value.includes('R-LEADER') && !signedRoles.value.includes('LEADER'))

const snapshot = computed(() => {
  const s = tb.value?.content_snapshot || {}
  return [
    { k: '课题名称', v: s.title },
    { k: '项目类型', v: s.project_type },
    { k: '负责人 ID', v: s.pi_user_id },
    { k: '申报机构 ID', v: s.applicant_org_id ?? '院内' },
    { k: '总预算', v: s.total_budget },
    { k: '研究周期（月）', v: s.duration_months },
    { k: '研究目标', v: s.research_target },
    { k: '技术路线', v: s.technical_route },
    { k: '预期成果', v: s.expected_output },
    { k: '冻结时间', v: s.frozen_at },
  ].filter((x) => x.v !== undefined && x.v !== null && x.v !== '')
})

async function load() {
  loading.value = true
  err.value = ''
  try {
    if (!id.value) {
      err.value = '缺少任务书编号，请从「我的申报」进入'
      return
    }
    tb.value = await api.get<TaskBook>(`/apply/task-books/${id.value}`)
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : String((e as any)?.message || e)
  } finally {
    loading.value = false
  }
}

async function sign(role: 'PI' | 'MANAGER' | 'LEADER') {
  if (!tb.value || acting.value) return
  acting.value = true
  try {
    tb.value = await api.post<TaskBook>(`/apply/task-books/${tb.value.id}:sign`, { role })
    toast(tb.value.status === 'SIGNED' ? '任务书已签订，项目已立项' : '签署成功，等待对方签署')
  } catch (e: any) {
    toast('签署失败：' + (e?.message || e))
  } finally {
    acting.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="view on">
    <div class="page-head">
      <div>
        <div class="page-title">任务书<em>签订</em></div>
        <div class="page-sub">PI 与管理端双签后自动立项建项 · 签订后申报内容冻结</div>
      </div>
      <div style="display:flex;gap:10px">
        <button class="btn ghost" @click="router.back()">返回</button>
        <button class="btn ghost" @click="load">刷新</button>
      </div>
    </div>

    <div v-if="loading" class="card"><div class="card-b" style="text-align:center;color:var(--ink-mute)">正在加载任务书…</div></div>
    <div v-else-if="err" class="card"><div class="card-b" style="text-align:center;color:#c0392b">{{ err }}</div></div>
    <template v-else-if="tb">
      <div class="card">
        <div class="card-h">
          <h5>{{ tb.code || '任务书' }}</h5>
          <div style="display:flex;gap:8px;align-items:center">
            <span class="tag" :class="tb.status === 'DRAFT' ? 'info' : 'ok'">{{ STATUS_LABEL[tb.status || ''] || tb.status }}</span>
            <span v-if="tb.project_id" class="mono" style="font-size:11.5px;color:var(--ink-mute)">项目 ID {{ tb.project_id }}</span>
          </div>
        </div>
        <table class="tbl" width="100%" style="border-collapse:collapse">
          <tbody>
            <tr v-for="row in snapshot" :key="row.k">
              <td style="width:150px;color:var(--ink-mute);font-size:12px">{{ row.k }}</td>
              <td style="font-size:12.5px;white-space:pre-wrap">{{ row.v }}</td>
            </tr>
            <tr v-if="tb.effective_date">
              <td style="width:150px;color:var(--ink-mute);font-size:12px">生效日期</td>
              <td class="mono" style="font-size:12.5px">{{ tb.effective_date }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card" style="margin-top:12px">
        <div class="card-h">
          <h5>签署记录</h5>
          <div style="display:flex;gap:8px">
            <button v-if="canSignPi" class="btn seal sm" :disabled="acting" @click="sign('PI')">以 PI 身份签署</button>
            <button v-if="canSignManager" class="btn sm" :disabled="acting" @click="sign('MANAGER')">科研管理签署</button>
            <button v-if="canSignLeader" class="btn sm ghost" :disabled="acting" @click="sign('LEADER')">院所领导签署</button>
            <span v-if="tb.status === 'DRAFT' && !canSignPi && !canSignManager && !canSignLeader"
                  style="font-size:11.5px;color:var(--ink-mute)">当前账号无权签署（PI 须为申报负责人本人；管理端签署需 R-MANAGER/R-LEADER）</span>
          </div>
        </div>
        <table class="tbl" width="100%" style="border-collapse:collapse">
          <thead><tr style="text-align:left"><th>签署方</th><th style="width:120px">签署人</th><th style="width:200px">签署时间</th><th style="width:90px">结果</th></tr></thead>
          <tbody>
            <tr v-for="(r, i) in tb.sign_records || []" :key="i">
              <td>{{ ROLE_LABEL[r.role || ''] || r.role }}</td>
              <td class="mono" style="font-size:12px">{{ r.signerId }}</td>
              <td class="mono" style="font-size:11.5px">{{ r.signedAt }}</td>
              <td><span class="tag ok">{{ r.result || 'OK' }}</span></td>
            </tr>
            <tr v-if="!(tb.sign_records || []).length"><td colspan="4" style="opacity:.6;padding:16px">尚未签署</td></tr>
          </tbody>
        </table>
        <p style="font-size:11.5px;color:var(--ink-mute);line-height:1.8;margin:0 16px 14px">
          PI 由服务端强制取申报负责人本人；PI 与（科研管理或院所领导）双方签署完成后，任务书置「已签订」并自动创建项目。
        </p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.card-h { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 10px; gap: 12px; flex-wrap: wrap; }
.card-h h5 { margin: 0; font-family: var(--serif); font-size: 14px; }
.mono { font-family: var(--mono); }
</style>
