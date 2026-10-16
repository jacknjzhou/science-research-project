<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { list } from '@/api/client'

// 契约 Guideline（design/01-P）：真实后端字段，展示层语义字段（ico/notes/tags/状态）
// 由下方派生函数计算，不再依赖 mock 时代的 ai_match/ico 注入。
interface Discipline { code: string; label: string }
interface Guideline {
  id: number
  code?: string | null
  title?: string
  project_type?: string
  funding_source?: string | null
  status?: string
  apply_start_at?: string | null
  apply_end_at?: string | null
  total_envelope?: string | null
  content_rich?: string | null
  remark?: string | null
  target_disciplines?: Discipline[] | null
  attachment_ids?: string[] | null
  publish_at?: string | null
}

const router = useRouter()
const toast = (m: string) => (window as any).toast?.(m)

const DAY = 86400000
const now = () => Date.now()

const rows = ref<Guideline[]>([])
const total = ref(0)
const loading = ref(true)
const activeType = ref('全部')
const keyword = ref('')
const active = ref<Guideline | null>(null) // 详情抽屉

// 类型筛选：契约 project_type 为字典 item_code（与 e_project 一致）
const TYPES: { code: string; label: string }[] = [
  { code: '全部', label: '全部' },
  { code: 'NSFC', label: '国家自然科学基金' },
  { code: 'KJBP', label: '重点研发计划' },
  { code: 'ZIGE', label: '院自立项目' },
  { code: 'PROV', label: '省部级' },
  { code: 'HENGXIANG', label: '横向委托' },
]
const TYPE_LABEL: Record<string, string> = Object.fromEntries(TYPES.map((t) => [t.code, t.label]))
const ICO_TEXT: Record<string, string> = { NSFC: '自然', KJBP: '重点', ZIGE: '自立', PROV: '省', HENGXIANG: '横向' }
const ICO_COLOR: Record<string, string> = {
  NSFC: 'var(--seal)', KJBP: 'var(--ink)', ZIGE: 'var(--gold)', PROV: '#41598C', HENGXIANG: 'var(--ai)',
}

const visible = computed(() => {
  let r = rows.value
  if (activeType.value !== '全部') r = r.filter((g) => g.project_type === activeType.value)
  const kw = keyword.value.trim().toLowerCase()
  if (kw) {
    r = r.filter((g) =>
      (g.title || '').toLowerCase().includes(kw) ||
      (g.code || '').toLowerCase().includes(kw) ||
      (g.funding_source || '').toLowerCase().includes(kw) ||
      (g.project_type || '').toLowerCase().includes(kw) ||
      (TYPE_LABEL[g.project_type || ''] || '').toLowerCase().includes(kw))
  }
  return r
})

// 参考资料附件：按扩展名取图标（attachment_ids 为字符串数组，线上为对象存储 id，演示用可读文件名）
function fileIco(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() || ''
  if (ext === 'pdf') return '📕'
  if (ext === 'doc' || ext === 'docx') return '📘'
  if (ext === 'xls' || ext === 'xlsx') return '📗'
  if (ext === 'ppt' || ext === 'pptx') return '📙'
  return '📄'
}

// 状态派生：可申报 / 即将截止(≤3天) / 未开始 / 已截止
function st(g: Guideline): { text: string; cls: string } {
  const end = g.apply_end_at ? new Date(g.apply_end_at).getTime() : 0
  const start = g.apply_start_at ? new Date(g.apply_start_at).getTime() : 0
  const n = now()
  if (g.status === 'CLOSED' || (end && end < n)) return { text: '已截止', cls: 'info' }
  if (start && start > n) return { text: '未开始', cls: 'info' }
  if (end && end - n <= 3 * DAY) return { text: '即将截止', cls: 'warn' }
  return { text: '可申报', cls: 'ok' }
}
function openable(g: Guideline): boolean {
  return st(g).text === '可申报' || st(g).text === '即将截止'
}

function daysLeft(g: Guideline): string {
  if (!openable(g)) return '—'
  const d = Math.round((new Date(g.apply_end_at!).getTime() - now()) / DAY)
  return d > 0 ? String(d) : '—'
}

// 展示备注：发布单位 / 资助强度 / 关键限制
function notes(g: Guideline): string[] {
  const arr: string[] = []
  if (g.funding_source) arr.push('发布单位：' + g.funding_source)
  const m = money(g.total_envelope)
  if (m) arr.push('资助总额：' + m)
  if (g.remark) arr.push(g.remark)
  return arr.slice(0, 3)
}

function money(v?: string | null): string {
  if (!v) return ''
  const n = Number(v)
  if (!Number.isFinite(n) || n <= 0) return ''
  if (n >= 1e8) return (n / 1e8).toFixed(n % 1e8 === 0 ? 0 : 1) + ' 亿'
  if (n >= 1e4) return (n / 1e4).toFixed(n % 1e4 === 0 ? 0 : 1) + ' 万'
  return n + ' 元'
}
function dateShort(v?: string | null): string {
  if (!v) return '—'
  const d = new Date(v)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const icoColor = (g: Guideline) => ICO_COLOR[g.project_type || ''] || 'var(--ink)'
const icoText = (g: Guideline) => ICO_TEXT[g.project_type || ''] || (TYPE_LABEL[g.project_type || ''] || g.project_type || '指南').slice(0, 2)

const openCount = computed(() => rows.value.filter(openable).length)

async function load() {
  loading.value = true
  try {
    const res = await list<Guideline>('/apply/guidelines', { size: 50, status: 'PUBLISHED' })
    // CLOSED 指南不随 PUBLISHED 过滤下发，追加展示（倒计时灰显）
    const closed = await list<Guideline>('/apply/guidelines', { size: 10, status: 'CLOSED' }).catch(() => ({ rows: [] }))
    rows.value = [...res.rows, ...closed.rows]
    total.value = res.total + ((closed as any).total ?? 0)
  } catch (e: any) {
    toast('指南加载失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}
onMounted(load)

// 详情抽屉：点击卡片打开；ESC / 遮罩点击关闭
function openGuide(g: Guideline) {
  active.value = g
}
function closeGuide() {
  active.value = null
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') closeGuide()
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

function goApply() {
  const g = active.value
  closeGuide()
  if (g && !openable(g)) {
    toast('该指南已截止申报，可在"申报计划"关注下一批次')
    return
  }
  toast('已进入申报书撰写（请先在申报计划中选择对应指南）')
  router.push('/editor')
}
</script>

<template>
  <section class="view on" id="v-guide">
    <div class="page-head">
      <div>
        <div class="page-title">申报<em>指南</em></div>
        <div class="page-sub">
          共 {{ total }} 条指南 ·
          <span style="color:var(--ok)">{{ openCount }} 条可申报</span> · 点击卡片查看指南详情
        </div>
      </div>
      <button class="btn ghost" @click="toast('订阅推送设置（演示）')">✉ 订阅推送</button>
    </div>

    <div class="filter-row">
      <span
        class="chip"
        :class="{ on: activeType === t.code }"
        v-for="t in TYPES"
        :key="t.code"
        @click="activeType = t.code"
        >{{ t.code === '全部' ? `全部 (${total})` : t.label }}</span
      >
      <input class="gl-search" v-model="keyword" placeholder="🔍 搜索指南标题 / 编号 / 单位" />
    </div>

    <div v-if="loading" class="card"><div class="card-b" style="text-align:center;color:var(--ink-mute)">正在加载指南…</div></div>

    <div v-else-if="visible.length === 0" class="card">
      <div class="card-b" style="text-align:center;color:var(--ink-mute);padding:36px">该筛选条件下暂无指南，试试切换类型。</div>
    </div>

    <div v-else class="grid" style="gap:12px">
      <div class="card guide-card" v-for="g in visible" :key="g.id" @click="openGuide(g)" :class="{ dim: !openable(g) }">
        <div class="ico" :style="{ background: icoColor(g) }">{{ icoText(g) }}</div>
        <div>
          <h5>{{ g.title }}</h5>
          <div class="meta"><span v-for="(n, i) in notes(g)" :key="i">{{ n }}</span></div>
          <div style="margin-top:8px">
            <span class="tag" :class="st(g).cls">{{ st(g).text }}</span>
            <span class="tag info" v-if="dateShort(g.apply_end_at) !== '—' && openable(g)">截止 {{ dateShort(g.apply_end_at) }}</span>
            <span class="tag seal" v-if="TYPE_LABEL[g.project_type || '']">{{ TYPE_LABEL[g.project_type || ''] }}</span>
          </div>
        </div>
        <div class="count-down" :style="{ opacity: openable(g) ? 1 : 0.45 }">
          <div class="d" :style="openable(g) ? undefined : { color: 'var(--ink-mute)' }">{{ daysLeft(g) }}</div>
          <div class="l">{{ openable(g) ? '天后截止' : '未开放' }}</div>
        </div>
      </div>
    </div>

    <!-- ===== 指南详情抽屉 ===== -->
    <teleport to="body">
      <div v-if="active" class="gl-overlay" @click.self="closeGuide">
        <aside class="gl-drawer">
          <header class="gl-head">
            <div>
              <span class="tag" :class="st(active).cls">{{ st(active).text }}</span>
              <span class="tag seal" style="margin-left:6px">{{ TYPE_LABEL[active.project_type || ''] || active.project_type }}</span>
            </div>
            <button class="gl-close" @click="closeGuide" aria-label="关闭">✕</button>
          </header>
          <h3 class="gl-title">{{ active.title }}</h3>

          <div class="gl-meta">
            <div class="gl-meta-item"><label>指南编号</label><b>{{ active.code || '—' }}</b></div>
            <div class="gl-meta-item"><label>资助来源</label><b>{{ active.funding_source || '—' }}</b></div>
            <div class="gl-meta-item"><label>资助总额</label><b>{{ money(active.total_envelope) || '—' }}</b></div>
            <div class="gl-meta-item">
              <label>申报窗口</label>
              <b>{{ dateShort(active.apply_start_at) }} ~ {{ dateShort(active.apply_end_at) }}</b>
            </div>
            <div class="gl-meta-item">
              <label>目标学科</label>
              <b>{{ (active.target_disciplines || []).map((d) => d.label).join(' · ') || '不限' }}</b>
            </div>
            <div class="gl-meta-item"><label>发布时间</label><b>{{ dateShort(active.publish_at) }}</b></div>
          </div>

          <div class="gl-body">
            <template v-for="(line, i) in (active.content_rich || '（指南正文待发布）').split('\n')" :key="i">
              <h4 v-if="line.startsWith('## ')">{{ line.slice(3) }}</h4>
              <p v-else-if="line.trim()" :style="/^\d+\./.test(line.trim()) ? 'margin-left:1em' : ''">{{ line }}</p>
            </template>
          </div>

          <!-- 参考资料（指南原文 / 模板 / 自查清单等附件） -->
          <div class="gl-refs" v-if="(active.attachment_ids || []).length">
            <h4>📎 参考资料（{{ (active.attachment_ids || []).length }}）</h4>
            <div
              class="gl-ref"
              v-for="f in active.attachment_ids"
              :key="f"
              @click="toast('附件下载为演示功能：' + f)"
            >
              <span class="gl-ref-ico">{{ fileIco(f) }}</span>
              <span class="gl-ref-name">{{ f }}</span>
              <span class="gl-ref-dl">⬇</span>
            </div>
          </div>

          <footer class="gl-foot">
            <span class="gl-atts" v-if="(active.attachment_ids || []).length">共 {{ (active.attachment_ids || []).length }} 份参考附件</span>
            <span v-else></span>
            <div>
              <button class="btn ghost" @click="closeGuide">关闭</button>
              <button class="btn" @click="goApply">去申报 →</button>
            </div>
          </footer>
        </aside>
      </div>
    </teleport>
  </section>
</template>

<style scoped>
.guide-card { cursor: pointer; transition: box-shadow .15s, transform .15s; }
.guide-card:hover { box-shadow: 0 6px 18px rgba(0,0,0,.10); transform: translateY(-1px); }
.guide-card.dim { opacity: .75; }
.guide-card .meta span { white-space: nowrap; }

.gl-overlay { position: fixed; inset: 0; background: rgba(15,23,42,.42); z-index: 90; display: flex; justify-content: flex-end; }
.gl-drawer {
  width: min(560px, 92vw); height: 100%; background: var(--paper, #fff); overflow-y: auto;
  display: flex; flex-direction: column; padding: 20px 24px; box-shadow: -8px 0 28px rgba(0,0,0,.18);
  animation: glIn .18s ease-out;
}
@keyframes glIn { from { transform: translateX(24px); opacity: .4; } to { transform: none; opacity: 1; } }
.gl-head { display: flex; justify-content: space-between; align-items: center; }
.gl-close { border: 0; background: none; font-size: 18px; cursor: pointer; color: var(--ink-mute, #888); padding: 4px 8px; }
.gl-title { margin: 12px 0 4px; font-size: 19px; line-height: 1.45; }
.gl-meta { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 18px; margin: 14px 0 6px; padding: 12px 14px; border: 1px solid rgba(0,0,0,.08); border-radius: 10px; background: rgba(0,0,0,.02); }
.gl-meta-item label { display: block; font-size: 11px; color: var(--ink-mute, #999); margin-bottom: 2px; }
.gl-meta-item b { font-size: 13px; font-weight: 600; }
.gl-body { flex: 1; margin-top: 10px; }
.gl-body h4 { margin: 14px 0 6px; font-size: 14px; color: var(--seal, #8c2f2f); }
.gl-body p { margin: 4px 0; font-size: 13.5px; line-height: 1.7; color: var(--ink, #222); white-space: pre-wrap; }
.gl-foot { display: flex; justify-content: space-between; align-items: center; padding-top: 12px; border-top: 1px solid rgba(0,0,0,.08); }
.gl-atts { font-size: 12px; color: var(--ink-mute, #999); }
.gl-foot .btn { margin-left: 8px; }

.gl-search {
  margin-left: auto; padding: 7px 14px; border: 1px solid var(--line, #ddd); border-radius: 20px;
  background: var(--paper-hi, #fff); font-size: 12.5px; width: 230px; outline: none;
  font-family: var(--sans, inherit); color: var(--ink, #222);
}
.gl-search:focus { border-color: var(--seal, #8c2f2f); }

.gl-refs { margin-top: 14px; padding-top: 12px; border-top: 1px dashed var(--line, #ddd); }
.gl-refs h4 { margin: 0 0 8px; font-size: 13.5px; color: var(--seal, #8c2f2f); }
.gl-ref {
  display: flex; align-items: center; gap: 10px; padding: 9px 12px; margin-bottom: 6px;
  border: 1px solid var(--line, #e5e5e5); border-radius: 8px; cursor: pointer;
  transition: background .12s, border-color .12s; background: var(--paper-hi, #fff);
}
.gl-ref:hover { background: var(--paper-deep, #f4efe4); border-color: var(--seal, #8c2f2f); }
.gl-ref-ico { font-size: 16px; }
.gl-ref-name { flex: 1; font-size: 12.5px; color: var(--ink, #222); }
.gl-ref-dl { font-size: 12px; color: var(--ink-mute, #999); }
</style>
