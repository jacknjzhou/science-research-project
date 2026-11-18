<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '@/api/client'

// 外部机构门户（M2-a C1）：R-PARTNER 专属。数据全部来自
// GET /portal/home（机构卡 + 公告 + 已发布指南 + 待办）与 GET/PUT /portal/org。
// 字段对齐契约 12-U，全程 snake_case；本机构范围由后端按登录用户 org_id 收敛，前端不做过滤。
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
  address?: string | null
  status?: string
  audited_at?: string | null
  reject_reason?: string | null
}
interface Notice { id: number; typ?: string; title?: string; content?: string | null; created_at?: string }
interface Guideline {
  id: number
  title?: string
  project_type?: string
  apply_start_at?: string | null
  apply_end_at?: string | null
  publish_at?: string | null
}
interface PortalHome {
  org: PartnerOrg
  announcements: Notice[]
  guidelines: Guideline[]
  todos: { unread_notifications: number }
}

const ORG_TYPE_LABEL: Record<string, string> = {
  COLLAB: '协作单位', SUPPLIER: '供应商', UNIVERSITY: '高校', INSTITUTE: '科研院所',
}
const STATUS_LABEL: Record<string, string> = {
  PENDING: '待审核', APPROVED: '已通过', REJECTED: '已驳回', SUSPENDED: '已暂停',
}

const router = useRouter()
const toast = (m: string) => (window as any).toast?.(m)

const home = ref<PortalHome | null>(null)
const loading = ref(true)
const err = ref('')

async function load() {
  loading.value = true
  err.value = ''
  try {
    home.value = await api.get<PortalHome>('/portal/home')
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : String((e as any)?.message || e)
  } finally {
    loading.value = false
  }
}

// —— 机构资料抽屉：仅四个联系字段可编辑（镜像后端白名单）——
const drawer = reactive({ open: false, saving: false })
const form = reactive({ contact_name: '', contact_phone: '', contact_email: '', address: '' })
function openDrawer() {
  const o = home.value?.org
  if (!o) return
  form.contact_name = o.contact_name || ''
  form.contact_phone = o.contact_phone || ''
  form.contact_email = o.contact_email || ''
  form.address = o.address || ''
  drawer.open = true
}
async function saveOrg() {
  if (drawer.saving) return
  drawer.saving = true
  try {
    const r = await api.put<PartnerOrg>('/portal/org', { ...form })
    if (home.value) home.value.org = r
    drawer.open = false
    toast('机构资料已更新')
  } catch (e: any) {
    toast('保存失败：' + (e?.message || e))
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
  <section class="view on" id="v-portal">
    <div class="page-head">
      <div>
        <div class="page-title">机构<em>门户</em></div>
        <div class="page-sub">外部协作单位工作台 · 指南推送与待办集中在首页</div>
      </div>
      <button class="btn ghost" @click="load">刷新</button>
    </div>

    <div v-if="loading" class="card"><div class="card-b" style="text-align:center;color:var(--ink-mute)">正在加载门户数据…</div></div>
    <div v-else-if="err" class="card"><div class="card-b" style="text-align:center;color:#c0392b">{{ err }}</div></div>

    <template v-else-if="home">
      <!-- 机构卡 -->
      <div class="card org-card">
        <div class="org-main">
          <div class="org-avatar">{{ (home.org.name || '机').slice(0, 1) }}</div>
          <div style="min-width:0">
            <h4 style="margin:0 0 6px;font-family:var(--serif);font-size:17px">{{ home.org.name }}</h4>
            <div class="org-meta">
              <span class="tag oak">{{ ORG_TYPE_LABEL[home.org.org_type || ''] || home.org.org_type || '—' }}</span>
              <span class="tag" :class="home.org.status === 'APPROVED' ? 'ok' : 'info'">{{ STATUS_LABEL[home.org.status || ''] || home.org.status }}</span>
              <span class="mono" style="font-size:11.5px;color:var(--ink-mute)">{{ home.org.code || '—' }}</span>
              <span class="mono" style="font-size:11.5px;color:var(--ink-mute)">信用代码 {{ home.org.credit_code || '—' }}</span>
            </div>
          </div>
        </div>
        <div class="org-side">
          <div class="org-contact">
            <div><label>联系人</label><b>{{ home.org.contact_name || '—' }}</b></div>
            <div><label>电话</label><b>{{ home.org.contact_phone || '—' }}</b></div>
            <div><label>邮箱</label><b>{{ home.org.contact_email || '—' }}</b></div>
          </div>
          <button class="btn sm" @click="openDrawer">维护联系方式</button>
        </div>
      </div>

      <!-- 待办数字 -->
      <div class="todo-row">
        <div class="todo-card">
          <div class="n">{{ home.todos.unread_notifications }}</div>
          <div class="l">未读通知</div>
        </div>
        <div class="todo-card" @click="router.push('/guide')">
          <div class="n">{{ home.guidelines.length }}</div>
          <div class="l">可申报指南</div>
        </div>
        <div class="todo-card">
          <div class="n">{{ home.announcements.length }}</div>
          <div class="l">公告</div>
        </div>
      </div>

      <div class="cols">
        <!-- 指南推送 -->
        <div class="card">
          <div class="card-h">
            <h5>申报指南推送</h5>
            <button class="btn sm ghost" @click="router.push('/guide')">查看全部</button>
          </div>
          <table class="tbl" width="100%" style="border-collapse:collapse">
            <thead><tr style="text-align:left"><th>指南标题</th><th style="width:96px">类型</th><th style="width:200px">申报期</th></tr></thead>
            <tbody>
              <tr v-for="g in home.guidelines" :key="g.id" style="cursor:pointer" @click="router.push('/guide')">
                <td>{{ g.title }}</td>
                <td class="mono" style="font-size:11.5px">{{ g.project_type || '—' }}</td>
                <td class="mono" style="font-size:11.5px">{{ dateShort(g.apply_start_at) }} ~ {{ dateShort(g.apply_end_at) }}</td>
              </tr>
              <tr v-if="!home.guidelines.length"><td colspan="3" style="opacity:.6;padding:16px">暂无已发布指南</td></tr>
            </tbody>
          </table>
        </div>

        <!-- 公告 -->
        <div class="card">
          <div class="card-h"><h5>机构公告</h5></div>
          <div class="notice-list">
            <div v-for="n in home.announcements" :key="n.id" class="notice">
              <div class="nt">{{ n.title }}</div>
              <div class="nb">{{ n.content || '—' }}</div>
              <div class="nd mono">{{ dateShort(n.created_at) }}</div>
            </div>
            <div v-if="!home.announcements.length" style="opacity:.6;padding:16px">暂无公告</div>
          </div>
        </div>
      </div>
    </template>

    <!-- 机构资料抽屉 -->
    <div v-if="drawer.open" style="position:fixed;inset:0;background:rgba(15,23,42,.35);z-index:60" @click.self="drawer.open = false">
      <div style="position:absolute;right:0;top:0;bottom:0;width:400px;background:var(--paper);box-shadow:-12px 0 40px rgba(15,23,42,.18);padding:22px;overflow:auto">
        <div style="display:flex;align-items:center;justify-content:space-between">
          <h4 style="font-family:var(--serif);font-size:16px">机构资料</h4>
          <button class="btn ghost sm" @click="drawer.open = false">关闭</button>
        </div>
        <div class="hr-rule" style="margin:12px 0"></div>
        <div class="fld">联系人</div>
        <input v-model="form.contact_name" class="fg" style="width:100%" />
        <div class="fld">联系电话</div>
        <input v-model="form.contact_phone" class="fg" style="width:100%" />
        <div class="fld">联系邮箱</div>
        <input v-model="form.contact_email" class="fg" style="width:100%" />
        <div class="fld">通讯地址</div>
        <textarea v-model="form.address" class="fg" rows="2" style="width:100%"></textarea>
        <div style="margin-top:16px;display:flex;gap:10px">
          <button class="btn seal" :disabled="drawer.saving" @click="saveOrg">{{ drawer.saving ? '保存中…' : '保存' }}</button>
          <button class="btn ghost" @click="drawer.open = false">取消</button>
        </div>
        <p style="font-size:11.5px;color:var(--ink-mute);line-height:1.8;margin-top:14px">
          机构名称、信用代码与审核状态由科研管理岗维护，如需变更请提交资质材料。
        </p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.org-card { display: flex; gap: 18px; justify-content: space-between; align-items: flex-start; padding: 18px; flex-wrap: wrap; }
.org-main { display: flex; gap: 14px; align-items: flex-start; min-width: 0; }
.org-avatar {
  width: 44px; height: 44px; flex: 0 0 44px; border-radius: 8px; background: var(--ink, #1f2937); color: #fff;
  display: flex; align-items: center; justify-content: center; font-family: var(--serif, serif); font-size: 20px;
}
.org-meta { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.org-side { display: flex; gap: 14px; align-items: flex-end; flex-wrap: wrap; }
.org-contact { display: flex; gap: 18px; }
.org-contact label { display: block; font-size: 11px; color: var(--ink-mute); letter-spacing: 1px; }
.org-contact b { font-size: 12.5px; font-weight: 500; }
.todo-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 12px; }
.todo-card {
  background: var(--paper); border: 1px solid var(--rule, #e6e2d8); border-radius: 8px; padding: 16px;
  cursor: pointer; text-align: center;
}
.todo-card .n { font-family: var(--serif, serif); font-size: 26px; line-height: 1.1; }
.todo-card .l { font-size: 11.5px; color: var(--ink-mute); letter-spacing: 1px; margin-top: 4px; }
.cols { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr); gap: 12px; margin-top: 12px; }
.card-h { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 10px; }
.card-h h5 { margin: 0; font-family: var(--serif); font-size: 14px; }
.notice-list { padding: 0 16px 14px; }
.notice { padding: 10px 0; border-top: 1px dashed var(--rule, #e6e2d8); }
.notice:first-child { border-top: 0; }
.notice .nt { font-size: 12.5px; font-weight: 600; }
.notice .nb { font-size: 12px; color: var(--ink-mute); line-height: 1.7; margin-top: 3px; }
.notice .nd { font-size: 11px; color: var(--ink-mute); margin-top: 4px; }
.fld { font-size: 12px; color: var(--ink-mute); margin-top: 12px; letter-spacing: 1px; }
.mono { font-family: var(--mono); }
</style>
