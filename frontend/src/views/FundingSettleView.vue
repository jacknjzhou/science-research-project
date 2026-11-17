<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api } from '@/api/client'
import { auth } from '@/api/auth'
import { toNum } from '@/utils/money'

// —— 项目决算 / 结题（M1-b F-17）：契约 Settlement camelCase、Money string（design/03 :2632）——
// 创建落地即 AUDITING；approve(action APPROVE|REJECT)：APPROVE 必选 treatment(结转|收回|留用)；APPROVED/REJECTED 终态。
interface Settlement {
  id: number
  code: string
  projectId: number
  closingDate: string
  incomeTotal: string
  expenseTotal: string
  remaining: string
  treatment: string | null
  auditReportUrl: string | null
  status: 'DRAFT' | 'SUBMITTED' | 'AUDITING' | 'APPROVED' | 'REJECTED'
}
interface MyProject { id: number; name?: string; code?: string; title?: string; [k: string]: unknown }

const toast = (m: string) => (window as any).toast?.(m)
const num = (v?: string | number | null) => toNum(v)
const money = (v?: string | number | null) => num(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const SETTLE_STATUS_META: Record<string, { tag: string; cls: string }> = {
  DRAFT: { tag: '草稿', cls: 'warn' }, SUBMITTED: { tag: '已提交', cls: 'info' },
  AUDITING: { tag: '审计中', cls: 'info' }, APPROVED: { tag: '已核准', cls: 'ok' },
  REJECTED: { tag: '已驳回', cls: 'bad' },
}
const stMeta = (s?: string | null) => SETTLE_STATUS_META[s || ''] || { tag: s || '—', cls: 'muted' }

const canApprove = computed(() => auth.can('/settlements POST') || auth.can('/settlements/* POST'))
const canCreate = computed(() => auth.can('/settlements POST'))

const loading = ref(false)
const submitting = ref(false)
const deciding = ref(false)
const projects = ref<MyProject[]>([])

// 单项目决算视图：GET /settlements/{projectId}（后端未注册列表端点，按项目查询）
const projectId = ref<number | null>(null)
const closingDate = ref(new Date().toISOString().slice(0, 10))
const settle = ref<Settlement | null>(null)
const notFound = ref(false)

// 审批：action + treatment（APPROVE 必选）+ comment
const decideAction = ref<'APPROVE' | 'REJECT'>('APPROVE')
const treatment = ref<'结转' | '收回' | '留用'>('结转')
const comment = ref('')

const projName = (id?: number | null) => {
  const p = projects.value.find(x => x.id === id)
  return p ? (p.name || p.title || p.code || `项目 #${id}`) : `项目 #${id}`
}

const cardNo = computed(() => settle.value?.code || (settle.value ? '#' + settle.value.id : ''))

async function reloadCtx() {
  const ps = await (await import('@/api/client')).list<MyProject>('/project/mine').catch(() => ({ rows: [] as MyProject[], total: 0 }))
  projects.value = (ps.rows ?? []) as MyProject[]
  if (!projectId.value && projects.value.length) projectId.value = projects.value[0].id
}

async function load() {
  if (!projectId.value) { settle.value = null; notFound.value = false; return }
  loading.value = true
  try {
    settle.value = await api.get<Settlement>(`/settlements/${projectId.value}`)
    notFound.value = false
  } catch (e: any) {
    if (e?.code === 40404 || e?.code === 404 || String(e?.message || '').includes('不存在')) {
      settle.value = null; notFound.value = true
    } else {
      settle.value = null; notFound.value = true
      toast('查询决算失败：' + (e?.message || e))
    }
  } finally {
    loading.value = false
  }
}

async function createSettle() {
  if (submitting.value) return
  const pid = projectId.value
  if (!pid) { toast('请先选择项目'); return }
  if (!closingDate.value) { toast('请选择决算基准日（closingDate）'); return }
  submitting.value = true
  try {
    settle.value = await api.post<Settlement>('/settlements', { projectId: pid, closingDate: closingDate.value })
    notFound.value = false
    toast(`决算单 ${settle.value?.code || ''} 已生成，进入审计（AUDITING）`)
  } catch (e: any) {
    toast('生成决算失败：' + (e?.message || e))
  } finally {
    submitting.value = false
  }
}

async function decide() {
  if (deciding.value || !settle.value) return
  if (settle.value.status !== 'AUDITING') { toast('仅 AUDITING 状态可审批'); return }
  if (decideAction.value === 'APPROVE' && !treatment.value) { toast('核准必须选择结转处理方式（treatment）'); return }
  deciding.value = true
  try {
    await api.post<unknown>(`/settlements/${settle.value.id}/approve`, {
      action: decideAction.value,
      ...(decideAction.value === 'APPROVE' ? { treatment: treatment.value } : {}),
      ...(comment.value.trim() ? { comment: comment.value.trim() } : {}),
    })
    toast(decideAction.value === 'APPROVE' ? `已核准，结转方式：${treatment.value}` : '已驳回')
    await load()
  } catch (e: any) {
    toast('审批失败：' + (e?.message || e))
  } finally {
    deciding.value = false
  }
}

onMounted(() => { void reloadCtx() })
</script>

<template>
  <section class="view on" id="v-funding-settle">
    <div class="page-head">
      <div>
        <div class="page-title">项目决算<em>结题结算</em></div>
        <div class="page-sub">收入 / 支出 / 结余 汇总 · 审批后 APPROVED 终态 · 核准须选择结转方式（结转/收回/留用）</div>
      </div>
    </div>

    <!-- 项目选择 + 新建 -->
    <div class="card">
      <div class="card-b" style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
        <div>
          <div class="fld" style="margin-top:0">项目</div>
          <select v-model.number="projectId" class="fg" style="width:280px" @change="load">
            <option :value="null" disabled>请选择项目</option>
            <option v-for="p in projects" :key="p.id" :value="p.id">{{ projName(p.id) }}</option>
          </select>
        </div>
        <template v-if="!settle">
          <div>
            <div class="fld" style="margin-top:0">决算基准日</div>
            <input v-model="closingDate" type="date" class="fg" style="width:170px" />
          </div>
          <button v-if="canCreate" class="btn seal" :disabled="submitting || !projectId" @click="createSettle">
            {{ submitting ? '生成中…' : '⚖ 生成决算单' }}
          </button>
        </template>
        <button v-else class="btn ghost" @click="load">刷新</button>
        <span v-if="loading" style="font-size:12px;color:var(--ink-mute)">加载中…</span>
      </div>
    </div>

    <template v-if="settle">
      <!-- 决算卡片 -->
      <div class="card">
        <div class="card-h">
          <h4>决算单 <span class="mono">{{ cardNo }}</span>
            <span class="tag" :class="stMeta(settle.status).cls" style="margin-left:8px">{{ stMeta(settle.status).tag }}</span>
          </h4>
          <span style="font-size:12px;color:var(--ink-mute)">项目：{{ projName(settle.projectId) }} · 基准日 {{ settle.closingDate || '—' }}</span>
        </div>
        <div class="card-b">
          <div class="sum-row">
            <div class="sum-card">
              <div class="sum-lbl">收入合计 incomeTotal</div>
              <div class="sum-val">¥ {{ money(settle.incomeTotal) }}</div>
            </div>
            <div class="sum-card">
              <div class="sum-lbl">支出合计 expenseTotal</div>
              <div class="sum-val">¥ {{ money(settle.expenseTotal) }}</div>
            </div>
            <div class="sum-card hi">
              <div class="sum-lbl">结余 remaining</div>
              <div class="sum-val" :style="{ color: num(settle.remaining) < 0 ? 'var(--bad)' : 'var(--seal)' }">¥ {{ money(settle.remaining) }}</div>
            </div>
          </div>
          <div style="margin-top:10px;font-size:12px;color:var(--ink-mute)">
            结转方式：<b>{{ settle.treatment || '—' }}</b>
            <template v-if="settle.auditReportUrl"> · 审计报告：<a :href="settle.auditReportUrl" target="_blank" rel="noopener" class="mono">查看</a></template>
          </div>
        </div>
      </div>

      <!-- 审批操作（仅 AUDITING） -->
      <div v-if="settle.status === 'AUDITING' && canApprove" class="card">
        <div class="card-h"><h4>审批</h4></div>
        <div class="card-b" style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
          <div>
            <div class="fld" style="margin-top:0">动作</div>
            <select v-model="decideAction" class="fg" style="width:130px">
              <option value="APPROVE">核准 APPROVE</option>
              <option value="REJECT">驳回 REJECT</option>
            </select>
          </div>
          <div v-if="decideAction === 'APPROVE'">
            <div class="fld" style="margin-top:0">结转处理 treatment（必选）</div>
            <select v-model="treatment" class="fg" style="width:130px">
              <option value="结转">结转</option>
              <option value="收回">收回</option>
              <option value="留用">留用</option>
            </select>
          </div>
          <div style="flex:1;min-width:200px">
            <div class="fld" style="margin-top:0">意见（可选）</div>
            <input v-model="comment" class="fg" placeholder="审批意见" />
          </div>
          <button class="btn seal" :disabled="deciding" @click="decide">{{ deciding ? '提交中…' : '提交审批' }}</button>
        </div>
      </div>
      <p v-else-if="settle.status === 'AUDITING'" style="font-size:11.5px;color:var(--ink-mute);margin-top:8px">
        审批权限：R-LEADER / R-FINANCE（POST /settlements/{id}/approve）。
      </p>
    </template>

    <div v-else-if="!loading && projectId" class="card">
      <div class="card-b" style="color:var(--ink-mute);font-size:13px">
        该项目尚无决算单（GET /settlements/{{ projectId }} → 404）。
        <template v-if="canCreate">填写决算基准日后点击「生成决算单」——落地即进入 AUDITING。</template>
        <template v-else>决算单由财务（R-FINANCE）生成。</template>
      </div>
    </div>

    <p style="font-size:11.5px;color:var(--ink-mute);line-height:1.8;margin-top:10px">
      决算幂等：同项目重复生成返回既有决算单；APPROVED 后再生成将 409（40901）。
      REJECTED 后可重新生成。结余 = 收入合计 − 支出合计。
    </p>
  </section>
</template>

<style scoped>
.fld { font-size: 12px; color: var(--ink-mute); margin-top: 12px; letter-spacing: 1px; }
.mono { font-family: var(--mono); }
.sum-row { display: flex; gap: 12px; flex-wrap: wrap; }
.sum-card { flex: 1; min-width: 180px; border: 1px solid var(--line, #e5e9f2); border-radius: 10px; padding: 12px 14px; background: #fafbfd; }
.sum-card.hi { background: #f4f8ff; }
.sum-lbl { font-size: 11px; color: var(--ink-mute); letter-spacing: 1px; }
.sum-val { font-size: 20px; font-weight: 800; margin-top: 6px; font-family: var(--mono); font-variant-numeric: tabular-nums; }
.tag.muted { background: #eef1f6; color: #6b7280; }
.btn:disabled { opacity: .6; cursor: not-allowed; }
</style>
