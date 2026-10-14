<script setup lang="ts">
import { computed } from 'vue'
import { auth } from '@/api/auth'
const who = computed(() => auth.user?.real_name || auth.user?.username || '访客')
const roles = computed(() => auth.roles.join(' · ') || '无')
</script>
<template>
  <div class="card" style="padding:48px;text-align:center">
    <h2 style="margin:0 0 8px">403 · 无访问权限</h2>
    <p style="opacity:.7;margin:0">当前身份「{{ who }}」（{{ roles }}）没有访问此页面的角色。</p>
    <p style="opacity:.5;margin-top:16px">请返回可访问的工作台，或联系管理员分配角色。</p>
  </div>
</template>
