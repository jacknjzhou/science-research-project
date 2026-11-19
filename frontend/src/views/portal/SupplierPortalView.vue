<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { api, ApiError } from '@/api/client'

// 供应商门户（M2-c C4）：被邀请的询价与在线应价；合同执行进度（对外脱敏）。
interface Inquiry {
  id: number; code: string | null; method: string; status: string
  title: string | null; category: string | null; open_at: string | null
  quoted: boolean; my_amount: string | null
}
interface Contract {
  id: number; code: string | null; name: string; amount: string
  signed_at: string | null; end_date: string | null; status: string
  pay_phase_count: number; paid_amount: string; paid_ratio: string
}

const inquiries = ref<Inquiry[]>([])
const contracts = ref<Contract[]>([])
const loading = ref(true)
const err = ref('')

const drawer = reactive({ open: false, saving: false, target: null as Inquiry | null })
const form = reactive({ totalAmount: '', remark: '' })
const ready = computed(() => {
  const v = Number(form.totalAmount)
  return form.totalAmount.trim().length > 0 && !isNaN(v) && v > 0
})

async function load() {
  loading.value = true
  err.value = ''
  try {
    const [q, c] = await Promise.all([
      api.get<{ list: Inquiry[] }>('/portal/supplier/inquiries'),
      api.get<{ list: Contract[] }>('/portal/supplier/contracts'),
    ])
    inquiries.value = q.list || []
    contracts.value = c.list || []
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : String((e as any)?.message || e)
  } finally {
    loading.value = false
  }
}

function openQuote(i: Inquiry) {
  drawer.target = i
  form.totalAmount = i.my_amount || ''
  form.remark = ''
  drawer.open = true
}

async function quote() {
  if (!ready.value || drawer.saving || !drawer.target) return
  drawer.saving = true
  try {
    await api.post(`/portal/supplier/inquiries/${drawer.target.id}:quote`, {
      totalAmount: Number(form.totalAmount).toFixed(2),
      remark: form.remark || null,
    })
    drawer.open = false
    ;(window as any).toast?.('报价已提交')
    await load()
  } catch (e: any) {
    ;(window as any).toast?.('报价失败：' + (e?.message || e))
  } finally {
    drawer.saving = false
  }
}

function money(v?: string | null): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  return isNaN(n) ? String(v) : n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
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
        <div class="page-title">供应商<em>门户</em></div>
        <div class="page-sub">受邀询价在线应价 · 合同执行进度（对外脱敏口径）</div>
      </div>
      <button class="btn ghost" @click="load">刷新</button>
    </div>

    <div v-if="loading" class="card"><div class="card-b" style="text-align:center;color:var(--ink-mute)">正在加载…</div></div>
    <div v-else-if="err" class="card"><div class="card-b" style="text-align:center;color:#c0392b">{{ err }}</div></div>
    <template v-else>
      <div class="card">
        <div class="card-h"><h5>询价邀请（{{ inquiries.length }}）</h5></div>
        <table class="tbl" width="100%" style="border-collapse:collapse">
          <thead><tr style="text-align:left">
            <th>询价单</th><th>采购品目</th><th style="width:88px">方式</th>
            <th style="width:88px">状态</th><th style="width:120px">我的报价</th>
            <th style="width:104px">操作</th>
          </tr></thead>
          <tbody>
            <tr v-for="i in inquiries" :key="i.id">
              <td class="mono" style="font-size:11.5px">{{ i.code || `#${i.id}` }}</td>
              <td>{{ i.title || '—' }}</td>
              <td style="font-size:12px;color:var(--ink-mute)">{{ i.method }}</td>
              <td><span class="tag" :class="i.status === 'PUBLICIZING' ? 'info' : 'ok'">{{ i.status === 'PUBLICIZING' ? '应价中' : '已定标' }}</span></td>
              <td class="mono" style="font-size:12px">{{ i.quoted ? money(i.my_amount) : '未报价' }}</td>
              <td>
                <button v-if="i.status === 'PUBLICIZING'" class="btn ghost sm" @click="openQuote(i)">
                  {{ i.quoted ? '修改报价' : '在线应价' }}
                </button>
                <span v-else style="font-size:11.5px;color:var(--ink-mute)">已关闭</span>
              </td>
            </tr>
            <tr v-if="!inquiries.length"><td colspan="6" style="opacity:.6;padding:16px">暂无询价邀请</td></tr>
          </tbody>
        </table>
      </div>

      <div class="card" style="margin-top:14px">
        <div class="card-h"><h5>合同执行进度（{{ contracts.length }}）</h5></div>
        <table class="tbl" width="100%" style="border-collapse:collapse">
          <thead><tr style="text-align:left">
            <th>合同</th><th>名称</th><th style="width:110px">金额</th>
            <th style="width:110px">已付</th><th style="width:78px">进度</th>
            <th style="width:78px">付款期</th><th style="width:100px">状态</th>
          </tr></thead>
          <tbody>
            <tr v-for="c in contracts" :key="c.id">
              <td class="mono" style="font-size:11.5px">{{ c.code || `#${c.id}` }}</td>
              <td>{{ c.name }}</td>
              <td class="mono" style="font-size:12px">{{ money(c.amount) }}</td>
              <td class="mono" style="font-size:12px">{{ money(c.paid_amount) }}</td>
              <td class="mono" style="font-size:12px">{{ (Number(c.paid_ratio) * 100).toFixed(0) }}%</td>
              <td class="mono" style="font-size:12px">{{ c.pay_phase_count }}</td>
              <td><span class="tag info">{{ c.status }}</span></td>
            </tr>
            <tr v-if="!contracts.length"><td colspan="7" style="opacity:.6;padding:16px">暂无合同</td></tr>
          </tbody>
        </table>
      </div>
    </template>

    <div v-if="drawer.open" style="position:fixed;inset:0;background:rgba(15,23,42,.35);z-index:60" @click.self="drawer.open = false">
      <div style="position:absolute;right:0;top:0;bottom:0;width:420px;background:var(--paper);box-shadow:-12px 0 40px rgba(15,23,42,.18);padding:22px;overflow:auto">
        <div style="display:flex;align-items:center;justify-content:space-between">
          <h4 style="font-family:var(--serif);font-size:16px">在线应价</h4>
          <button class="btn ghost sm" @click="drawer.open = false">关闭</button>
        </div>
        <div class="hr-rule" style="margin:12px 0"></div>
        <p style="font-size:12px;color:var(--ink-mute);line-height:1.9">
          询价单：<span class="mono">{{ drawer.target?.code || drawer.target?.id }}</span><br />
          采购品目：{{ drawer.target?.title || '—' }}
        </p>
        <div class="fld">报价总额（元）*</div>
        <input v-model="form.totalAmount" class="fg" style="width:100%" placeholder="如 98000.00" />
        <div class="fld">备注（含税/交货期等）</div>
        <textarea v-model="form.remark" class="fg" rows="3" style="width:100%"></textarea>
        <div style="margin-top:16px;display:flex;gap:10px">
          <button class="btn seal" :disabled="!ready || drawer.saving" @click="quote">
            {{ drawer.saving ? '提交中…' : '提交报价' }}
          </button>
          <button class="btn ghost" @click="drawer.open = false">取消</button>
        </div>
        <p style="font-size:11.5px;color:var(--ink-mute);line-height:1.8;margin-top:14px">
          定标前可重复修改，系统只保留贵单位最新一次报价；定标后不可再报。
        </p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.card-h { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 10px; }
.card-h h5 { margin: 0; font-family: var(--serif); font-size: 14px; }
</style>
