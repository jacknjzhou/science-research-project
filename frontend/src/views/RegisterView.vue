<script setup lang="ts">
import { reactive, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '@/api/client'

// 外部机构自助注册（M2-a C1）：公开页，无需登录。
// 字段对齐契约 12-U `PartnerOrgRegisterRequest`（required 9 键，全 snake_case）。
interface RegisterForm {
  name: string
  credit_code: string
  org_type: string
  contact_name: string
  contact_phone: string
  contact_email: string
  username: string
  password: string
  short_name: string
}

const ORG_TYPES = [
  { code: 'COLLAB', label: '协作单位' },
  { code: 'SUPPLIER', label: '供应商' },
  { code: 'UNIVERSITY', label: '高校' },
  { code: 'INSTITUTE', label: '科研院所' },
]

const router = useRouter()
const form = reactive<RegisterForm>({
  name: '', credit_code: '', org_type: 'COLLAB',
  contact_name: '', contact_phone: '', contact_email: '',
  username: '', password: '', short_name: '',
})
const submitting = ref(false)
const done = ref(false)
const err = ref('')

// 前端仅做「必填 + 明显格式」提示，真校验在后端（401/40001、409/40901）
const creditOk = computed(() => form.credit_code.trim().length === 18)
const pwdHint = computed(() => {
  const p = form.password
  if (!p) return ''
  if (p.length < 8) return '至少 8 位'
  if (/^\d+$/.test(p)) return '不能是纯数字'
  if (!/[A-Za-z]/.test(p)) return '需含字母'
  return ''
})
const ready = computed(() =>
  !!form.name.trim() && creditOk.value && !!form.contact_name.trim() &&
  !!form.username.trim() && !pwdHint.value && !!form.password,
)

async function submit() {
  if (submitting.value || !ready.value) return
  submitting.value = true
  err.value = ''
  try {
    await api.post('/portal/register', { ...form })
    done.value = true
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : String((e as any)?.message || e)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="reg-wrap">
    <div class="card reg-card">
      <div class="reg-head">
        <div class="seal-mark">合</div>
        <div>
          <h3 class="reg-title">外部机构注册</h3>
          <p class="reg-sub">协作单位 / 供应商 / 高校院所自助开户 —— 提交后由科研管理岗审核资质，通过即可登录门户。</p>
        </div>
      </div>

      <div v-if="done" class="reg-done">
        <div class="big">✓ 已提交，等待资质审核</div>
        <p>我们将对贵单位资质进行审核，通过后会向 {{ form.contact_email || '预留邮箱' }} 发送开通通知。
           审核通过前账号处于锁定状态，无法登录。</p>
        <button class="btn seal" @click="router.push('/dash')">返回登录页</button>
      </div>

      <template v-else>
        <div v-if="err" class="reg-err">{{ err }}</div>

        <div class="reg-grid">
          <div class="cell span2">
            <label>机构全称 <i>*</i></label>
            <input v-model="form.name" class="fg" placeholder="如：示例大学科学技术研究院" />
          </div>
          <div class="cell">
            <label>统一社会信用代码 <i>*</i></label>
            <input v-model="form.credit_code" class="fg mono" maxlength="18" placeholder="18 位" />
            <span v-if="form.credit_code && !creditOk" class="hint">须为 18 位</span>
          </div>
          <div class="cell">
            <label>机构简称</label>
            <input v-model="form.short_name" class="fg" placeholder="选填" />
          </div>
          <div class="cell">
            <label>机构类型 <i>*</i></label>
            <select v-model="form.org_type" class="fg">
              <option v-for="t in ORG_TYPES" :key="t.code" :value="t.code">{{ t.label }}</option>
            </select>
          </div>
          <div class="cell">
            <label>联系人 <i>*</i></label>
            <input v-model="form.contact_name" class="fg" placeholder="经办人姓名" />
          </div>
          <div class="cell">
            <label>联系电话</label>
            <input v-model="form.contact_phone" class="fg" placeholder="选填" />
          </div>
          <div class="cell">
            <label>联系邮箱</label>
            <input v-model="form.contact_email" class="fg" placeholder="审核结果将发至该邮箱" />
          </div>
          <div class="cell">
            <label>登录用户名 <i>*</i></label>
            <input v-model="form.username" class="fg mono" placeholder="≥3 位，登录用" />
          </div>
          <div class="cell">
            <label>登录口令 <i>*</i></label>
            <input v-model="form.password" type="password" class="fg" placeholder="≥8 位，含字母且非纯数字" />
            <span v-if="pwdHint" class="hint">{{ pwdHint }}</span>
          </div>
        </div>

        <div class="reg-actions">
          <button class="btn seal" :disabled="!ready || submitting" @click="submit">
            {{ submitting ? '提交中…' : '提交注册申请' }}
          </button>
          <button class="btn ghost" @click="router.push('/dash')">已有账号，返回登录</button>
        </div>
        <p class="reg-note">
          注册即代表同意《数据使用与保密约定》：贵单位仅可查看本单位相关数据与公开发布的申报指南。
        </p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.reg-wrap {
  min-height: 100vh; display: flex; align-items: center; justify-content: center;
  padding: 40px 16px; background: var(--paper-deep, #f4f1ea);
}
.reg-card { width: 100%; max-width: 760px; padding: 28px 30px 24px; }
.reg-head { display: flex; gap: 14px; align-items: flex-start; margin-bottom: 18px; }
.seal-mark {
  width: 40px; height: 40px; flex: 0 0 40px; border-radius: 6px; background: var(--seal, #9c2b2b);
  color: #fff; display: flex; align-items: center; justify-content: center;
  font-family: var(--serif, serif); font-size: 20px;
}
.reg-title { font-family: var(--serif, serif); font-size: 20px; margin: 0 0 6px; }
.reg-sub { font-size: 12.5px; color: var(--ink-mute, #6b7280); margin: 0; line-height: 1.7; }
.reg-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 16px; }
.cell { display: flex; flex-direction: column; gap: 6px; }
.cell.span2 { grid-column: span 2; }
.cell label { font-size: 12px; color: var(--ink-mute, #6b7280); letter-spacing: 1px; }
.cell label i { color: var(--seal, #9c2b2b); font-style: normal; }
.hint { font-size: 11.5px; color: #c0392b; }
.reg-actions { display: flex; gap: 10px; margin-top: 20px; }
.reg-note { font-size: 11.5px; color: var(--ink-mute, #6b7280); line-height: 1.8; margin-top: 14px; }
.reg-err { background: #fdecec; color: #a12b2b; border-radius: 6px; padding: 10px 12px; font-size: 12.5px; margin-bottom: 14px; }
.reg-done { text-align: center; padding: 18px 8px 8px; }
.reg-done .big { font-family: var(--serif, serif); font-size: 18px; color: var(--ok, #2f7a4f); margin-bottom: 10px; }
.reg-done p { font-size: 12.5px; color: var(--ink-mute, #6b7280); line-height: 1.9; margin-bottom: 16px; }
.mono { font-family: var(--mono, monospace); }
</style>
