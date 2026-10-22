<script setup lang="ts">
import { ref, computed, reactive, onMounted } from 'vue'
import { api, list } from '@/api/client'

interface DocSection { no: string; h: string; text: string }
interface ReviewDocView {
  code?: string; apply_code?: string; title?: string
  sections?: DocSection[]; attachments?: string
  dup?: { similarity?: string; text?: string }
}
interface ReviewTask {
  id: number; application_id?: number; status?: string; deadline_at?: string
  comment_text?: string; score_detail?: unknown[]; load?: string
  dims?: string[]; doc?: ReviewDocView
}
interface ScoreItem { dim: string; score: string; max_score: string }
interface AiReview { overall?: string; strengths?: string; weaknesses?: string; suggestions?: string; adopted?: boolean }

const toast = (m: string) => (window as any).toast?.(m)
const DEFAULT_DIMS = ['创新性', '科学问题', '研究方案', '研究基础']
const DOTS = [1, 2, 3, 4, 5]

const loading = ref(true)
const aiBusy = ref(false)
const task = ref<ReviewTask | null>(null)
const dims = ref<string[]>([...DEFAULT_DIMS])
const scores = reactive<Record<string, number>>({})
const comment = ref('')

const total = computed(() => {
  const vals = dims.value.map((d) => scores[d]).filter((n) => n > 0)
  if (!vals.length) return '—'
  return (vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(1)
})

function fmtDeadline(iso?: string) {
  if (!iso) return '—'
  const d = new Date(iso)
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

async function load() {
  loading.value = true
  try {
    const { rows } = await list<ReviewTask>('/apply/review/mytasks', { status: 'SCORING', size: 20 })
    const t = rows[0] || null
    if (t) {
      task.value = t
      dims.value = t.dims && t.dims.length ? t.dims : [...DEFAULT_DIMS]
      dims.value.forEach((d) => (scores[d] = 0))
      comment.value = t.comment_text || ''
    }
  } catch (e: any) {
    toast('评审任务加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
onMounted(load)

function buildScoreDetail(): ScoreItem[] {
  return dims.value.map((d) => ({ dim: d, score: String(scores[d] || 0), max_score: '5' }))
}

async function genComment() {
  if (!task.value) return
  aiBusy.value = true
  try {
    const r = await api.post<AiReview>('/apply/ai/review-draft', {
      task_id: task.value.id,
      score_detail: buildScoreDetail(),
    })
    const parts = [
      r?.overall,
      r?.strengths && `【创新性/方案】${r.strengths}`,
      r?.weaknesses && `【不足】${r.weaknesses}`,
      r?.suggestions && `【建议】${r.suggestions}`,
    ].filter(Boolean).join('\n')
    comment.value = parts || 'AI 暂未生成意见，请先完成评分。'
    toast('AI 已起草评审意见，请编辑后提交')
  } catch (e: any) {
    toast('AI 起草失败：' + (e?.message || e))
  } finally {
    aiBusy.value = false
  }
}

async function submitScore() {
  if (!task.value) return
  try {
    await api.post(`/apply/review/tasks/${task.value.id}:score`, {
      score_detail: buildScoreDetail(),
      comment_text: comment.value,
    })
    toast('意见已提交 · 感谢评审')
  } catch (e: any) {
    toast('提交失败：' + (e?.message || e))
  }
}
</script>

<template>
  <section class="view on" id="v-review">
    <div class="page-head">
      <div>
        <div class="page-title">评审<span style="color:var(--seal)">工作台</span></div>
        <div class="page-sub">
          通讯评审 · 匿名模式 · 你的负荷 {{ task?.load || '—' }} · 评审截止 {{ fmtDeadline(task?.deadline_at) }}
        </div>
      </div>
      <span class="stamp">评审中</span>
    </div>

    <div v-if="loading" class="card"><div class="card-b" style="text-align:center;color:var(--ink-mute)">正在载入评审任务…</div></div>

    <div v-else-if="!task" class="card">
      <div class="card-b" style="text-align:center;color:var(--ink-mute);padding:40px">当前没有待评审任务。</div>
    </div>

    <div v-else class="review-grid">
      <!-- 左：匿名申请书正文 -->
      <div class="card review-doc">
        <div style="text-align:center;margin-bottom:14px">
          <div style="font-family:var(--serif);font-size:18px;font-weight:900">{{ task.doc?.title || '（匿名）待评审申请书' }}</div>
          <div style="font-size:11px;color:var(--ink-mute);margin-top:6px" class="mono">
            申请书编号 {{ task.doc?.code || 'MS-—' }} · 受理代码 {{ task.doc?.apply_code || '—' }} · 申请人信息 <span class="redact">隐藏</span>
          </div>
        </div>
        <div class="divider-double"></div>
        <template v-for="(s, i) in task.doc?.sections || []" :key="i">
          <h6 style="font-family:var(--serif);margin:14px 0 6px">{{ s.no }} {{ s.h }}</h6>
          <p style="font-size:12.5px;line-height:1.9;color:var(--ink-soft)">{{ s.text }}</p>
        </template>
        <div v-if="task.doc?.attachments" style="margin-top:12px;padding:12px;background:var(--paper-deep);border-radius:5px;font-size:12px">
          📎 附件：{{ task.doc?.attachments }}
        </div>
        <div class="compliance-card bad" style="margin-top:14px" v-if="task.doc?.dup">
          ◈ <b>AI 查重提示：</b>{{ task.doc?.dup?.text }}
          <b style="cursor:pointer;color:var(--bad)" @click="toast('查重高亮对比尚未开放')">查看高亮对比 →</b>
          　<em style="color:var(--ink-mute)">（仅供参考，不作为唯一依据）</em>
        </div>
      </div>

      <!-- 右：评分卡 + 评审意见 -->
      <div style="display:flex;flex-direction:column;gap:16px">
        <div class="card">
          <div class="card-h"><h4>评分卡 · 面上标准</h4><span class="tag ai">点击打分</span></div>
          <div class="card-b" style="padding-top:4px">
            <div class="score-row" v-for="(d, i) in dims" :key="d" :style="i === dims.length - 1 ? 'border-bottom:0' : undefined">
              <span class="nm">{{ d }}</span>
              <div class="score-dots">
                <span
                  class="sdot"
                  :class="{ on: (scores[d] || 0) >= n }"
                  v-for="n in DOTS"
                  :key="n"
                  @click="scores[d] = n"
                >{{ n }}</span>
              </div>
              <span class="mono" style="font-size:11px;color:var(--ink-mute)">/5</span>
            </div>
            <div style="display:flex;justify-content:space-between;padding:10px 2px 0">
              <span style="font-size:12px">综合</span>
              <b style="font-family:var(--serif);font-size:20px">{{ total }}</b>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-h"><h4>评审意见</h4><button class="btn sm ai" :disabled="aiBusy" @click="genComment">✦ AI 起草</button></div>
          <div class="card-b">
            <textarea v-model="comment" class="ed-text" rows="6" style="min-height:130px;background:#fff" placeholder="撰写意见，或点击 AI 根据评分要点起草…"></textarea>
            <div style="display:flex;gap:8px;margin-top:12px">
              <button class="btn seal" style="flex:1;justify-content:center" @click="submitScore">提交评审</button>
              <button class="btn ghost" @click="toast('草稿暂存尚未开放（点击「提交评审」正式保存）')">暂存</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.btn:disabled { opacity: 0.55; cursor: not-allowed; }
</style>
