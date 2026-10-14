<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api, list } from '@/api/client'
import { auth } from '@/api/auth'
import { toWan } from '@/utils/money'

type ActType = 'CONFERENCE' | 'LECTURE' | 'SEMINAR' | 'TRAINING' | 'OTHER'
type Level = 'INTERNATIONAL' | 'NATIONAL' | 'PROVINCIAL' | 'CAMPUS'
type HostMode = 'HOST' | 'ATTEND' | 'SPONSOR'
type Status =
  | 'DRAFT' | 'SUBMITTED' | 'DEPT_REVIEW' | 'APPROVED'
  | 'HELD' | 'ARCHIVED' | 'REJECTED' | 'RETURNED' | 'CANCELLED'

interface Activity {
  id: number
  code?: string | null
  status: Status
  activity_type: ActType
  level: Level
  host_mode: HostMode
  title: string
  theme?: string | null
  start_at?: string | null
  end_at?: string | null
  venue?: string | null
  host_unit?: string | null
  organizer_dept_id?: number | null
  est_attendees?: number | null
  budget_amount?: string | null
}
interface Participant { id: number; user_id?: number | null; guest_name?: string | null; role?: 'SPEAKER' | 'CHAIR' | 'MEMBER' | 'ATTENDEE' | null; report_title?: string | null }
interface Review { id: number; review_level?: number; reviewer_id?: number; action?: 'APPROVE' | 'REJECT' | 'RETURN'; opinion?: string | null; acted_at?: string }
interface ActivityDetail extends Activity { participants?: Participant[]; reviews?: Review[] }

const toast = (m: string) => (window as any).toast?.(m)

// —— 展示映射（中文标签 + 徽章色，色用设计系统既有 tag 变体）——
const TYPE_LABEL: Record<ActType, string> = { CONFERENCE: '学术会议', LECTURE: '讲座报告', SEMINAR: '研讨班', TRAINING: '培训', OTHER: '其他' }
const LEVEL_LABEL: Record<Level, string> = { INTERNATIONAL: '国际', NATIONAL: '国家', PROVINCIAL: '省级', CAMPUS: '校内' }
const MODE_LABEL: Record<HostMode, string> = { HOST: '主办', ATTEND: '参加', SPONSOR: '承办' }
const STATUS_LABEL: Record<Status, string> = { DRAFT: '草稿', SUBMITTED: '已提交', DEPT_REVIEW: '部门评审', APPROVED: '已批准', HELD: '已举办', ARCHIVED: '已归档', REJECTED: '已驳回', RETURNED: '已退回', CANCELLED: '已取消' }
function statusCls(s: Status): string {
  if (s === 'APPROVED' || s === 'ARCHIVED') return 'ok'
  if (s === 'REJECTED' || s === 'CANCELLED') return 'warn'
  if (s === 'SUBMITTED' || s === 'DEPT_REVIEW' || s === 'HELD') return 'info'
  return ''
}
const fmtDate = (iso?: string | null) => (iso ? iso.slice(0, 10) : '—')

// —— 列表 + 筛选 ——
const items = ref<Activity[]>([])
const total = ref(0)
const loading = ref(true)
const busy = ref(false)
const fType = ref<'' | ActType>('')
const fLevel = ref<'' | Level>('')
const fStatus = ref<'' | Status>('')

async function load() {
  loading.value = true
  try {
    const { rows, total: t } = await list<Activity>('/activities', {
      activity_type: fType.value || undefined,
      level: fLevel.value || undefined,
      status: fStatus.value || undefined,
      size: 100,
    })
    items.value = rows ?? []
    total.value = t ?? items.value.length
  } catch (e: any) {
    toast('加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
onMounted(load)

// —— 统计条（按类型分组）——
const stats = ref<{ key: string; count: number }[]>([])
async function loadStats() {
  try {
    const d = await api.get<{ buckets?: { key: string; count: number }[] }>('/activities/stats', { group_by: 'activity_type' })
    stats.value = d?.buckets ?? []
  } catch { /* 统计失败不阻断主列表 */ }
}
onMounted(loadStats)

// —— 详情抽屉 ——
const detail = ref<ActivityDetail | null>(null)
const drawer = ref(false)
async function openDetail(a: Activity) {
  drawer.value = true
  detail.value = null
  try {
    detail.value = await api.get<ActivityDetail>(`/activities/${a.id}`)
  } catch (e: any) {
    toast('详情加载失败：' + (e?.message || e))
    drawer.value = false
  }
}
function closeDrawer() { drawer.value = false; detail.value = null }

// —— 动作（迁移）：按状态 + 角色显示按钮 ——
// 门控口径：域级读用 auth.can('/activities GET')；带 :id 的动作按角色（与路由 meta.roles 同源）。
const canManage = computed(() => auth.hasAnyRole(['R-MANAGER', 'R-LEADER']))
const canStaffAct = computed(() => auth.hasAnyRole(['R-STAFF', 'R-MANAGER']))

async function transition(a: Activity, verb: 'submit' | 'approve' | 'hold' | 'archive' | 'cancel', body?: unknown) {
  if (busy.value) return
  busy.value = true
  try {
    await api.post(`/activities/${a.id}/${verb}`, body ?? {})
    toast(`${TYPE_LABEL[a.activity_type]}「${a.title}」已${VERB_CN[verb]} ✓`)
    await load()
    if (drawer.value && detail.value?.id === a.id) await openDetail(a)
  } catch (e: any) {
    toast('操作失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}
const VERB_CN: Record<string, string> = { submit: '提交', approve: '审批通过', hold: '标记举办', archive: '归档', cancel: '取消' }

async function doApprove(a: Activity, action: 'APPROVE' | 'REJECT' | 'RETURN') {
  await transition(a, 'approve', { review_level: 1, action, opinion: action === 'APPROVE' ? '同意' : '需补充材料' })
}

async function removeActivity(a: Activity) {
  if (busy.value) return
  busy.value = true
  try {
    await api.del(`/activities/${a.id}`)
    toast('已删除草稿')
    await load()
  } catch (e: any) {
    toast('删除失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}

// —— 参与人维护（抽屉内）——
const npUserId = ref('')
const npRole = ref<'SPEAKER' | 'CHAIR' | 'MEMBER' | 'ATTENDEE'>('MEMBER')
async function addParticipant() {
  if (!detail.value || !npUserId.value) return toast('请填写参与人用户 ID')
  busy.value = true
  try {
    await api.post(`/activities/${detail.value.id}/participants`, { user_id: Number(npUserId.value), role: npRole.value })
    npUserId.value = ''
    await openDetail(detail.value)
    toast('已添加参与人 ✓')
  } catch (e: any) {
    toast('添加失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}
async function removeParticipant(pid: number) {
  if (!detail.value) return
  busy.value = true
  try {
    await api.del(`/activities/${detail.value.id}/participants/${pid}`)
    await openDetail(detail.value)
    toast('已移除参与人')
  } catch (e: any) {
    toast('移除失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}

// 某条记录当前可执行的动作（状态机 × 角色）
function actionsFor(a: Activity): { key: string; label: string; cls: string; run: () => void; show: boolean }[] {
  const st = a.status
  return [
    { key: 'edit', label: '详情', cls: 'ghost', run: () => openDetail(a), show: true },
    { key: 'submit', label: '提交', cls: 'seal', run: () => transition(a, 'submit'), show: st === 'DRAFT' && canStaffAct.value },
    { key: 'approve', label: '批准', cls: 'seal', run: () => doApprove(a, 'APPROVE'), show: (st === 'SUBMITTED' || st === 'DEPT_REVIEW') && canManage.value },
    { key: 'return', label: '退回', cls: 'ghost', run: () => doApprove(a, 'RETURN'), show: (st === 'SUBMITTED' || st === 'DEPT_REVIEW') && canManage.value },
    { key: 'hold', label: '标记已举办', cls: 'ghost', run: () => transition(a, 'hold', { sign_in_count: a.est_attendees ?? 0 }), show: st === 'APPROVED' && canManage.value },
    { key: 'archive', label: '归档', cls: 'ghost', run: () => transition(a, 'archive', { minutes_rich: '（归档纪要）' }), show: st === 'HELD' && canManage.value },
    { key: 'cancel', label: '取消', cls: 'ghost', run: () => transition(a, 'cancel', { cancel_reason: '活动取消' }), show: st !== 'ARCHIVED' && st !== 'CANCELLED' && canManage.value },
    { key: 'del', label: '删除', cls: 'ghost', run: () => removeActivity(a), show: st === 'DRAFT' && canStaffAct.value },
  ].filter((x) => x.show)
}
</script>

<template>
  <section class="view on" id="v-activity">
    <div class="page-head">
      <div>
        <div class="page-title">学术<em>活动</em></div>
        <div class="page-sub">
          会议 / 讲座 / 研讨 / 培训全流程登记 → 审批 → 举办 → 归档 ·
          共 <b style="color:var(--seal)">{{ total }}</b> 条
          <span v-for="s in stats" :key="s.key" class="tag info" style="margin-left:8px">{{ TYPE_LABEL[s.key as ActType] || s.key }} {{ s.count }}</span>
        </div>
      </div>
    </div>

    <div class="filter-row">
      <select class="sel" v-model="fType" @change="load">
        <option value="">全部类型</option>
        <option value="CONFERENCE">学术会议</option><option value="LECTURE">讲座报告</option>
        <option value="SEMINAR">研讨班</option><option value="TRAINING">培训</option><option value="OTHER">其他</option>
      </select>
      <select class="sel" v-model="fLevel" @change="load">
        <option value="">全部级别</option>
        <option value="INTERNATIONAL">国际</option><option value="NATIONAL">国家</option>
        <option value="PROVINCIAL">省级</option><option value="CAMPUS">校内</option>
      </select>
      <select class="sel" v-model="fStatus" @change="load">
        <option value="">全部状态</option>
        <option v-for="(lbl, k) in STATUS_LABEL" :key="k" :value="k">{{ lbl }}</option>
      </select>
      <button class="btn sm ghost" @click="load">↻ 刷新</button>
    </div>

    <div class="grid" style="gap:12px">
      <div v-if="loading" class="card"><div class="card-b" style="padding:28px;text-align:center;color:var(--ink-mute)">正在加载学术活动…</div></div>
      <div v-else-if="!items.length" class="card"><div class="card-b" style="padding:28px;text-align:center;color:var(--ink-mute)">当前筛选下暂无活动。</div></div>

      <div class="act-card" v-for="a in items" :key="a.id">
        <div style="flex:1">
          <div style="font-family:var(--serif);font-weight:700;font-size:14px">{{ a.title }}</div>
          <div style="font-size:12px;color:var(--ink-mute);margin-top:5px">
            <span class="tag info">{{ TYPE_LABEL[a.activity_type] }}</span>
            <span class="tag">{{ LEVEL_LABEL[a.level] }}</span>
            <span class="tag">{{ MODE_LABEL[a.host_mode] }}</span>
            <span class="tag" :class="statusCls(a.status)">{{ STATUS_LABEL[a.status] }}</span>
          </div>
          <div style="font-size:12px;color:var(--ink-mute);margin-top:6px">
            📅 {{ fmtDate(a.start_at) }} · 📍 {{ a.venue || '—' }} · 👥 {{ a.est_attendees ?? '—' }} 人
            <template v-if="a.budget_amount"> · 预算 {{ toWan(a.budget_amount) }} 万</template>
          </div>
        </div>
        <div class="claim-actions">
          <button v-for="act in actionsFor(a)" :key="act.key" class="btn sm" :class="act.cls" :disabled="busy" @click="act.run">{{ act.label }}</button>
        </div>
      </div>
    </div>

    <!-- 详情抽屉 -->
    <div class="drawer-mask" v-if="drawer" @click="closeDrawer"></div>
    <aside class="drawer" v-if="drawer">
      <div class="drawer-head">
        <b>{{ detail?.title || '加载中…' }}</b>
        <button class="btn sm ghost" @click="closeDrawer">✕</button>
      </div>
      <div class="drawer-b" v-if="detail">
        <div class="kv"><span>编号</span><b>{{ detail.code || detail.id }}</b></div>
        <div class="kv"><span>类型/级别</span><b>{{ TYPE_LABEL[detail.activity_type] }} · {{ LEVEL_LABEL[detail.level] }}</b></div>
        <div class="kv"><span>起止</span><b>{{ fmtDate(detail.start_at) }} ~ {{ fmtDate(detail.end_at) }}</b></div>
        <div class="kv"><span>场地</span><b>{{ detail.venue || '—' }}</b></div>
        <div class="kv"><span>主办方</span><b>{{ detail.host_unit || '—' }}</b></div>
        <div class="kv"><span>状态</span><b><span class="tag" :class="statusCls(detail.status)">{{ STATUS_LABEL[detail.status] }}</span></b></div>

        <div class="sec-title">参与人（{{ detail.participants?.length ?? 0 }}）</div>
        <div class="plist">
          <div class="pitem" v-for="p in detail.participants" :key="p.id">
            <span>{{ p.guest_name || ('用户#' + p.user_id) }}<em v-if="p.role"> · {{ p.role }}</em></span>
            <button class="btn xs ghost" :disabled="busy" @click="removeParticipant(p.id)">移除</button>
          </div>
        </div>
        <div class="padd">
          <input class="sel" style="flex:1" v-model="npUserId" placeholder="参与人用户 ID" />
          <select class="sel" style="width:110px" v-model="npRole"><option value="SPEAKER">主讲</option><option value="CHAIR">主持</option><option value="MEMBER">成员</option><option value="ATTENDEE">参加</option></select>
          <button class="btn sm seal" :disabled="busy" @click="addParticipant">＋添加</button>
        </div>

        <div class="sec-title">审批轨迹（{{ detail.reviews?.length ?? 0 }}）</div>
        <div class="rlist">
          <div class="ritem" v-for="r in detail.reviews" :key="r.id">
            <b>L{{ r.review_level ?? 1 }} {{ r.action }}</b>
            <span>{{ r.reviewer_id ? '审查人#' + r.reviewer_id : '—' }}{{ r.opinion ? '：' + r.opinion : '' }}</span>
          </div>
          <div v-if="!detail.reviews?.length" style="color:var(--ink-mute);font-size:12px">暂无审批记录</div>
        </div>
      </div>
    </aside>
  </section>
</template>

<style scoped>
.act-card { display:flex; gap:12px; align-items:flex-start; background:var(--card,#fff); border:1px solid var(--line,#e5e0d5); border-radius:10px; padding:14px 16px; }
.claim-actions { display:flex; flex-wrap:wrap; gap:6px; justify-content:flex-end; max-width:280px; }
.btn.xs { font-size:11px; padding:2px 8px; }
.sel { font-size:12px; padding:5px 8px; border:1px solid var(--line,#d8d2c4); border-radius:6px; background:#fff; }
.filter-row { display:flex; gap:10px; align-items:center; margin:8px 0 14px; flex-wrap:wrap; }
.drawer-mask { position:fixed; inset:0; background:rgba(0,0,0,.32); z-index:40; }
.drawer { position:fixed; top:0; right:0; bottom:0; width:420px; max-width:92vw; background:#fff; z-index:41; box-shadow:-8px 0 28px rgba(0,0,0,.16); display:flex; flex-direction:column; }
.drawer-head { display:flex; justify-content:space-between; align-items:center; padding:14px 16px; border-bottom:1px solid var(--line,#eee); }
.drawer-b { padding:14px 16px; overflow:auto; }
.kv { display:flex; justify-content:space-between; font-size:12.5px; padding:5px 0; border-bottom:1px dashed var(--line,#f0ece0); }
.kv span { color:var(--ink-mute); }
.sec-title { font-family:var(--serif); font-weight:700; margin:14px 0 6px; font-size:13px; }
.pitem,.ritem { display:flex; justify-content:space-between; align-items:center; font-size:12px; padding:4px 0; }
.pitem em { color:var(--ink-mute); font-style:normal; }
.padd { display:flex; gap:6px; margin-top:8px; }
.ritem { flex-direction:column; align-items:flex-start; }
.ritem b { color:var(--seal,#b5462f); }
.ritem span { color:var(--ink-mute); }
</style>
