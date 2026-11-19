<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { api, ApiError } from '@/api/client'

// 专家自助申请（M2-c C3）：提交后档案为 CANDIDATE，科研管理岗审核通过即授 R-EXPERT。
const form = reactive({
  name: '', title: '', org_name: '', phone: '', email: '', field_tags: '',
})
const saving = ref(false)
const done = ref(false)
const err = ref('')

const tags = computed(() =>
  form.field_tags.split(/[,，;；\s]+/).map((s) => s.trim()).filter(Boolean),
)
const ready = computed(() => form.name.trim().length > 0 && form.email.includes('@'))

async function submit() {
  if (!ready.value || saving.value) return
  saving.value = true
  err.value = ''
  try {
    await api.post('/portal/expert-apply', {
      name: form.name.trim(),
      title: form.title || null,
      org_name: form.org_name || null,
      phone: form.phone || null,
      email: form.email || null,
      field_tags: tags.value,
    })
    done.value = true
  } catch (e: unknown) {
    err.value = e instanceof ApiError ? e.message : String((e as any)?.message || e)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="view on">
    <div class="page-head">
      <div>
        <div class="page-title">专家<em>申请</em></div>
        <div class="page-sub">申请成为外部评审专家 · 审核通过后可接收评审邀请</div>
      </div>
    </div>

    <div v-if="done" class="card">
      <div class="card-b" style="text-align:center;line-height:2">
        <div style="font-size:15px;font-family:var(--serif)">申请已提交</div>
        <div style="color:var(--ink-mute);font-size:12.5px">
          科研管理岗审核通过后，您的账号将获得评审专家权限，届时可在「专家门户」查看邀请。
        </div>
      </div>
    </div>

    <div v-else class="card">
      <div class="card-h"><h5>申请信息</h5></div>
      <div class="card-b">
        <div class="fld">姓名 *</div>
        <input v-model="form.name" class="fg" style="width:100%" placeholder="真实姓名" />
        <div class="fld">职称 / 职务</div>
        <input v-model="form.title" class="fg" style="width:100%" placeholder="教授 / 研究员 / 高工" />
        <div class="fld">所属单位</div>
        <input v-model="form.org_name" class="fg" style="width:100%" />
        <div class="fld">手机</div>
        <input v-model="form.phone" class="fg" style="width:100%" />
        <div class="fld">邮箱 *（用于接收评审邀请）</div>
        <input v-model="form.email" class="fg" style="width:100%" placeholder="name@example.com" />
        <div class="fld">研究领域（逗号分隔）</div>
        <input v-model="form.field_tags" class="fg" style="width:100%" placeholder="人工智能, 数据治理" />
        <p v-if="tags.length" style="font-size:11.5px;color:var(--ink-mute);margin-top:7px">
          将提交标签：<span v-for="t in tags" :key="t" class="tag info" style="margin-right:4px">{{ t }}</span>
        </p>
        <p v-if="err" style="color:#c0392b;font-size:12.5px;margin-top:10px">{{ err }}</p>
        <div style="margin-top:16px">
          <button class="btn seal" :disabled="!ready || saving" @click="submit">
            {{ saving ? '提交中…' : '提交申请' }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.card-h { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 10px; }
.card-h h5 { margin: 0; font-family: var(--serif); font-size: 14px; }
</style>
