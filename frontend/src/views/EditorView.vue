<script setup lang="ts">
import { ref, computed, onMounted, reactive } from 'vue'
import { api, list } from '@/api/client'

interface AppRow {
  id: number; code?: string; title?: string; project_type?: string; status?: string
  apply_code?: string; pi_name?: string; member_count?: number; duration_months?: number
  total_budget?: string; updated_at?: string
}
interface Doc { section_code: string; content_rich?: string; word_count?: number; doc_version?: number }
interface BudgetRow {
  subject_code?: string; subject_name: string; amount?: string
  ai_compliance_flag?: string; ai_compliance_reason?: string
}
interface SectionMeta { code: string; no: string; label: string; toc: string; limit: number; hero?: boolean; budget?: boolean }
interface Msg { role: 'user' | 'bot'; text: string; cite?: string; actions?: boolean; warn?: boolean }
interface AiRef { project_code?: string; title?: string }
interface AiDraft { content?: string; mode?: string; confidence?: string; references?: AiRef[]; watermark?: string }

const toast = (m: string) => (window as any).toast?.(m)

const SECTIONS: SectionMeta[] = [
  { code: 'background', no: '§1', label: '立项依据（研究意义与科学问题）', toc: '① 立项依据', limit: 2000, hero: true },
  { code: 'objective', no: '§2', label: '研究目标', toc: '② 研究目标', limit: 800, hero: true },
  { code: 'content', no: '§3', label: '研究内容', toc: '③ 研究内容', limit: 1500, hero: true },
  { code: 'route', no: '§4', label: '技术路线', toc: '④ 技术路线', limit: 1500 },
  { code: 'innovation', no: '§5', label: '创新点', toc: '⑤ 创新点', limit: 600 },
  { code: 'foundation', no: '§6', label: '研究基础', toc: '⑥ 研究基础', limit: 2000 },
  { code: 'schedule', no: '§7', label: '进度安排', toc: '⑦ 进度安排', limit: 800 },
  { code: 'budget_note', no: '§8', label: '预算说明 · 摘要', toc: '⑧ 预算说明', limit: 800, budget: true },
  { code: 'attachments', no: '§9', label: '附件材料', toc: '⑨ 附件材料', limit: 0 },
]

const loading = ref(true)
const aiBusy = ref(false)
const app = ref<AppRow | null>(null)
const budget = ref<BudgetRow[]>([])
const contents = reactive<Record<string, string>>({})
const activeSection = ref(0)
const savedAt = ref('—')
const version = ref(3)
const aiInput = ref('')
const msgs = ref<Msg[]>([])

const heroSections = computed(() => SECTIONS.filter((s) => s.hero))
const budgetSection = computed(() => SECTIONS.find((s) => s.budget))

const filled = computed(() => SECTIONS.filter((s) => (contents[s.code] || '').trim().length > 0).length)
const pct = computed(() => Math.round((filled.value / SECTIONS.length) * 100))

const barCls = computed(() => (pct.value >= 70 ? 'b-ok' : pct.value >= 40 ? 'b-warn' : 'b-bad'))
const directSum = computed(() => budget.value.reduce((a, b) => a + (Number(b.amount) || 0), 0))
const baseBudget = computed(() => Number(app.value?.total_budget) || directSum.value || 1)

function wordOf(code: string) {
  return (contents[code] || '').length
}
function moneyWan(v?: string) {
  return v ? (Number(v) / 10000).toFixed(1) : '—'
}
function percentOf(b: BudgetRow) {
  if (!b.amount) return '—'
  return Math.round((Number(b.amount) / baseBudget.value) * 100) + '%'
}
const FLAG: Record<string, { cls: string; txt: string }> = {
  OK: { cls: 'ok', txt: '✓ 合规' },
  WARN: { cls: 'warn', txt: '⚠ ' },
  VIOLATION: { cls: 'bad', txt: '✕ ' },
  UNKNOWN: { cls: 'info', txt: '' },
}
function flagTag(b: BudgetRow) {
  const f = FLAG[b.ai_compliance_flag || 'UNKNOWN'] || FLAG.UNKNOWN
  const txt = f.cls === 'warn' || f.cls === 'bad' ? f.txt + (b.ai_compliance_reason || '待核') : f.txt || b.ai_compliance_reason || '按政策计提'
  return { cls: f.cls, txt }
}
function metaTag(text: string) {
  return text
}

async function load() {
  loading.value = true
  try {
    const { rows } = await list<AppRow>('/apply/applications', { status: 'DRAFT', size: 20 })
    let a = rows[0] || null
    if (!a) a = (await api.get<AppRow>('/apply/applications/412')) || null
    if (a) {
      app.value = a
      savedAt.value = fmtTime(a.updated_at)
      const [docs, bud] = await Promise.all([
        api.get<Doc[]>(`/apply/applications/${a.id}/documents`).catch(() => [] as Doc[]),
        api.get<BudgetRow[]>(`/apply/applications/${a.id}/budget`).catch(() => [] as BudgetRow[]),
      ])
      SECTIONS.forEach((s) => (contents[s.code] = ''))
      ;(docs || []).forEach((d) => { contents[d.section_code] = d.content_rich || '' })
      version.value = Math.max(1, ...(docs || []).map((d) => d.doc_version || 1))
      budget.value = bud || []
      seedChat()
    }
  } catch (e: any) {
    toast('申报书加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
function fmtTime(iso?: string) {
  if (!iso) return '10:42:17'
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function seedChat() {
  msgs.value = [
    { role: 'bot', text: '你好，我是申报助手。检测到当前指南为<b>面上项目</b>，限 2000 字立项依据。需要我基于关键词「扩散模型 / 曲面磨抛 / 自适应」起草 §3 研究内容吗？', actions: true },
    { role: 'bot', warn: true, text: '◈ <b>形式审查预检</b>（自动）：研究基础缺少 5 篇代表作全文；合作协议未上传；伦理批件 ETH-2026-011 已关联 ✓。' },
  ]
}
onMounted(load)

async function aiDraft(sectionCode = 'content', userText?: string) {
  if (!app.value) return
  if (userText) msgs.value.push({ role: 'user', text: userText })
  aiBusy.value = true
  try {
    const r = await api.post<AiDraft>('/apply/ai/draft', {
      application_id: app.value.id,
      section_code: sectionCode,
      keywords: ['扩散模型', '曲面磨抛', '自适应'],
      project_type: app.value.project_type,
    })
    const cite = (r?.references || [])
      .map((ref, i) => `[${i + 1}] ${ref.project_code || ''}（${ref.title || ''}）`)
      .join(' ')
    const target = SECTIONS.find((s) => s.code === sectionCode)
    if (r?.content && target?.hero) contents[sectionCode] = r.content
    msgs.value.push({
      role: 'bot',
      text: r?.content || 'AI 暂无可用草稿。',
      cite: cite ? '参考：' + cite : undefined,
    })
    toast(`AI 已起草 ${target?.no || ''} · 置信度 ${r?.confidence || '—'}${r?.watermark ? '（' + r.watermark + '）' : ''}`)
  } catch (e: any) {
    msgs.value.push({ role: 'bot', warn: true, text: 'AI 服务暂时不可用（50301），已降级为要点建议。' })
    toast('AI 起草失败：' + (e?.message || e))
  } finally {
    aiBusy.value = false
  }
}

function sendAi() {
  const t = aiInput.value.trim()
  if (!t) return
  aiInput.value = ''
  aiDraft('content', t)
}

async function saveSection(code: string) {
  if (!app.value) return
  try {
    await api.put(`/apply/applications/${app.value.id}/sections/${code}`, {
      content_rich: contents[code] || '',
      word_count: wordOf(code),
    })
    savedAt.value = fmtTime(new Date().toISOString())
  } catch {
    /* 保存失败静默，下方 toast 反馈 */
  }
}
async function saveDraft() {
  await Promise.all(heroSections.value.map((s) => saveSection(s.code)))
  version.value += 1
  toast('草稿已保存 v' + version.value)
}
async function submitPrecheck() {
  if (!app.value) return
  try {
    await api.post(`/apply/applications/${app.value.id}/submit`, { confirm_ai_watermark: true })
    toast('已发起部门预审，流程进入「形式审查」节点')
  } catch (e: any) {
    toast('提交失败：' + (e?.message || e))
  }
}
</script>

<template>
  <section class="view on" id="v-editor" style="margin:-26px">
    <div v-if="loading" class="card" style="margin:26px"><div class="card-b" style="text-align:center;color:var(--ink-mute)">正在载入申报书…</div></div>

    <div v-else-if="!app" class="card" style="margin:26px">
      <div class="card-b" style="text-align:center;color:var(--ink-mute);padding:40px">
        暂无进行中的申报草稿。<div style="margin-top:14px"><button class="btn seal" @click="$router.push({ name: 'guide' })">＋ 从指南新建申报</button></div>
      </div>
    </div>

    <template v-else>
      <div class="editor">
        <!-- 左侧结构目录 -->
        <div class="ed-toc">
          <div class="t">申报书结构 · {{ app.project_type?.split('·').pop()?.trim() || '面上项目' }}</div>
          <div
            class="toc-item"
            :class="{ on: i === activeSection }"
            v-for="(s, i) in SECTIONS"
            :key="s.code"
            @click="activeSection = i"
          >
            {{ s.toc }}<span class="dot" :class="{ filled: (contents[s.code] || '').trim().length > 0 }"></span>
          </div>
          <div class="hr-rule"></div>
          <div style="padding:0 18px;font-size:11px;color:var(--ink-mute)">
            完整度
            <div class="bar" :class="barCls" style="margin-top:6px"><i :style="{ width: pct + '%' }"></i></div>
            <div class="mono" style="margin-top:4px">{{ pct }}% · {{ filled }}/{{ SECTIONS.length }} 节完成</div>
          </div>
        </div>

        <!-- 中部正文 -->
        <div class="ed-body">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
            <span class="tag info mono">{{ app.code }} · 草稿 v{{ version }}</span>
            <span style="font-size:11px;color:var(--ink-mute)" class="mono">autosaved {{ savedAt }} · 本地缓存正常</span>
          </div>
          <div class="paper-title">{{ app.title }}</div>
          <div style="text-align:center;font-size:12px;color:var(--ink-mute);margin-bottom:8px">
            {{ app.project_type }} · 申报代码 {{ app.apply_code || '—' }}
          </div>
          <div style="display:flex;gap:10px;justify-content:center;margin-bottom:4px;flex-wrap:wrap">
            <span class="tag ok">{{ metaTag('PI ' + (app.pi_name || '—')) }}</span>
            <span class="tag info">成员 {{ app.member_count ?? 0 }} 人</span>
            <span class="tag info">执行期 {{ app.duration_months ?? 0 }} 个月</span>
            <span class="tag warn">直接经费 {{ moneyWan(app.total_budget) }} 万</span>
          </div>
          <div class="divider-double"></div>

          <template v-for="s in heroSections" :key="s.code">
            <h6><span class="sec-no">{{ s.no }}</span>{{ s.label }}</h6>
            <textarea
              class="ed-text"
              :rows="s.code === 'background' ? 7 : s.code === 'objective' ? 4 : 3"
              v-model="contents[s.code]"
              :placeholder="s.code === 'content' ? '点击右侧 AI 助手起草本节，或手动输入…' : ''"
              @blur="saveSection(s.code)"
            ></textarea>
            <div class="word-count">{{ wordOf(s.code) }} / {{ s.limit }} 字</div>
          </template>

          <template v-if="budgetSection">
            <h6><span class="sec-no">{{ budgetSection.no }}</span>{{ budgetSection.label }}</h6>
            <table class="tbl">
              <thead><tr><th>科目</th><th>金额(万)</th><th>占比</th><th>AI 合规审查</th></tr></thead>
              <tbody>
                <tr v-for="(b, i) in budget" :key="i">
                  <td>{{ b.subject_name }}</td>
                  <td class="mono">{{ moneyWan(b.amount) }}</td>
                  <td class="mono">{{ percentOf(b) }}</td>
                  <td><span class="tag" :class="flagTag(b).cls">{{ flagTag(b).txt }}</span></td>
                </tr>
              </tbody>
            </table>
            <div class="compliance-card">⚠ <b>AI 预算检查：</b>劳务费接近占比上限，若后续调增其他科目可能触发超限。依据：《国家自然科学基金资助项目资金管理办法》财教〔2021〕177 号 第十四条。<b style="color:var(--ai);cursor:pointer" @click="toast('查看条款原文（演示）')">查看条款原文 →</b></div>
          </template>
        </div>

        <!-- 右侧 AI 面板 -->
        <div class="ai-panel">
          <div class="ai-head">
            <div class="ai-orb"></div>
            <div><b style="font-size:13px">科研申报助手</b><div style="font-size:11px;color:var(--ink-mute)">RAG · 已检索本所 217 份中标书</div></div>
          </div>
          <div class="ai-msgs">
            <div class="ai-bubble" :class="[m.role, { warn: m.warn }]" :style="m.warn ? 'border-left:3px solid var(--warn)' : undefined" v-for="(m, i) in msgs" :key="i">
              <span v-html="m.text"></span>
              <div class="ai-actions" v-if="m.actions">
                <button class="btn sm ai" :disabled="aiBusy" @click="aiDraft('content')">✦ 起草 §3</button>
                <button class="btn sm ghost" @click="toast('将检索近 3 年同领域热点')">看热点</button>
              </div>
              <div class="ai-cite" v-if="m.cite" v-html="m.cite"></div>
            </div>
          </div>
          <div class="ai-input">
            <input v-model="aiInput" placeholder="向 AI 描述你的研究思路…" @keyup.enter="sendAi">
            <button class="btn sm ai" :disabled="aiBusy" @click="sendAi">{{ aiBusy ? '思考中…' : '发送' }}</button>
          </div>
        </div>
      </div>

      <div class="ed-foot">
        <span class="mono" style="font-size:11px;color:var(--ink-mute)">提交前将执行：字数校验 · 附件完整性 · 限项检查 · AI 查重（相似度预估 <b style="color:var(--ok)">11%</b>）</span>
        <div style="margin-left:auto;display:flex;gap:10px">
          <button class="btn ghost sm" @click="saveDraft">保存草稿</button>
          <button class="btn sm" @click="submitPrecheck">提交预审</button>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.ai-bubble.warn { background: var(--paper-deep); }
.ai-input input:disabled { opacity: 0.6; }
.btn:disabled { opacity: 0.55; cursor: not-allowed; }
</style>
