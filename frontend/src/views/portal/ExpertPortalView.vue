<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api, ApiError } from '@/api/client'

// 专家门户（M2-c C3）：信用档案 / 我的评审邀请 / 受邀学术活动。
interface Credit {
  expert_id: number; name: string; review_count: number
  invited_count: number; accepted_count: number; declined_count: number
  expired_count: number; accept_rate: string; on_time_rate: string
  abstain_count: number; avg_score: string | null; last_review_at: string | null
}
interface ReviewRow {
  id: number; task_id: number; title: string | null; biz_type: string | null
  task_status: string | null; response: string; invited_at: string | null
  responded_at: string | null
}
interface ActivityRow {
  id: number; title: string; activity_type: string; status: string
  start_at: string | null; venue: string | null; role: string
}

const RESP: Record<string, string> = {
  PENDING: '待响应', ACCEPT: '已接受', DECLINE: '已拒绝', EXPIRED: '已过期',
}
const credit = ref<Credit | null>(null)
const reviews = ref<ReviewRow[]>([])
const activities = ref<ActivityRow[]>([])
const loading = ref(true)
const err = ref('')

async function load() {
  loading.value = true
  err.value = ''
  try {
    const [c, r, a] = await Promise.all([
      api.get<Credit>('/portal/expert/credit'),
      api.get<{ list: ReviewRow[] }>('/portal/expert/reviews'),
      api.get<{ list: ActivityRow[] }>('/portal/expert/activities'),
    ])
    credit.value = c
    reviews.value = r.list || []
    activities.value = a.list || []
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : String((e as any)?.message || e)
  } finally {
    loading.value = false
  }
}

function dateShort(v?: string | null): string {
  if (!v) return '—'
  const d = new Date(v)
  return isNaN(d.getTime())
    ? '—'
    : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

onMounted(load)
</script>

<template>
  <section class="view on">
    <div class="page-head">
      <div>
        <div class="page-title">专家<em>门户</em></div>
        <div class="page-sub">信用档案 · 评审邀请 · 学术活动邀请</div>
      </div>
      <button class="btn ghost" @click="load">刷新</button>
    </div>

    <div v-if="loading" class="card"><div class="card-b" style="text-align:center;color:var(--ink-mute)">正在加载…</div></div>
    <div v-else-if="err" class="card"><div class="card-b" style="text-align:center;color:#c0392b">{{ err }}</div></div>
    <template v-else>
      <div class="card" v-if="credit">
        <div class="card-h"><h5>{{ credit.name }} · 信用档案</h5></div>
        <div class="card-b" style="display:flex;gap:26px;flex-wrap:wrap">
          <div><div class="mono" style="font-size:20px">{{ credit.accept_rate }}</div><div class="lbl">接受率</div></div>
          <div><div class="mono" style="font-size:20px">{{ credit.on_time_rate }}</div><div class="lbl">72h 按时率</div></div>
          <div><div class="mono" style="font-size:20px">{{ credit.invited_count }}</div><div class="lbl">邀请数</div></div>
          <div><div class="mono" style="font-size:20px">{{ credit.accepted_count }}</div><div class="lbl">已接受</div></div>
          <div><div class="mono" style="font-size:20px">{{ credit.avg_score || '—' }}</div><div class="lbl">平均评分</div></div>
          <div><div class="mono" style="font-size:20px">{{ credit.abstain_count }}</div><div class="lbl">弃权次数</div></div>
          <div><div class="mono" style="font-size:20px">{{ dateShort(credit.last_review_at) }}</div><div class="lbl">最近评审</div></div>
        </div>
      </div>

      <div class="card" style="margin-top:14px">
        <div class="card-h"><h5>我的评审邀请（{{ reviews.length }}）</h5></div>
        <table class="tbl" width="100%" style="border-collapse:collapse">
          <thead><tr style="text-align:left">
            <th>评审任务</th><th>业务类型</th><th style="width:96px">响应</th>
            <th style="width:110px">邀请时间</th>
          </tr></thead>
          <tbody>
            <tr v-for="r in reviews" :key="r.id">
              <td>{{ r.title || `任务 #${r.task_id}` }}</td>
              <td class="mono" style="font-size:11.5px">{{ r.biz_type || '—' }}</td>
              <td><span class="tag" :class="r.response === 'ACCEPT' ? 'ok' : r.response === 'DECLINE' ? 'warn' : 'info'">{{ RESP[r.response] || r.response }}</span></td>
              <td class="mono" style="font-size:11.5px">{{ dateShort(r.invited_at) }}</td>
            </tr>
            <tr v-if="!reviews.length"><td colspan="4" style="opacity:.6;padding:16px">暂无评审邀请</td></tr>
          </tbody>
        </table>
      </div>

      <div class="card" style="margin-top:14px">
        <div class="card-h"><h5>学术活动邀请（{{ activities.length }}）</h5></div>
        <table class="tbl" width="100%" style="border-collapse:collapse">
          <thead><tr style="text-align:left">
            <th>活动</th><th style="width:110px">类型</th><th style="width:110px">角色</th>
            <th style="width:110px">开始</th><th>地点</th>
          </tr></thead>
          <tbody>
            <tr v-for="a in activities" :key="a.id">
              <td>{{ a.title }}</td>
              <td class="mono" style="font-size:11.5px">{{ a.activity_type }}</td>
              <td><span class="tag info">{{ a.role }}</span></td>
              <td class="mono" style="font-size:11.5px">{{ dateShort(a.start_at) }}</td>
              <td style="font-size:12px;color:var(--ink-mute)">{{ a.venue || '—' }}</td>
            </tr>
            <tr v-if="!activities.length"><td colspan="5" style="opacity:.6;padding:16px">暂无学术活动邀请</td></tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.card-h { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 10px; }
.card-h h5 { margin: 0; font-family: var(--serif); font-size: 14px; }
.lbl { font-size: 11.5px; color: var(--ink-mute); margin-top: 4px; }
</style>
