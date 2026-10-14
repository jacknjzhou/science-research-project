import type { Directive, DirectiveBinding } from 'vue'
import { auth } from '@/api/auth'

/**
 * v-perm="'/admin/users POST'" —— 按钮/操作级门控（粒度②）。
 * 值可为字符串或字符串数组（任一命中即放行）。
 * 修饰符 .hide 移除元素；默认禁用（disabled + 半透明 + 拦截点击）。
 * 依赖 auth.caps（登录后 loadMe 填充）；未登录/无能力 → 受限。
 */
function apply(el: HTMLElement, binding: DirectiveBinding<string | string[]>) {
  const want = binding.value
  const list = Array.isArray(want) ? want : [want]
  const allowed = list.some((c) => auth.can(c))
  if (allowed) {
    el.removeAttribute('disabled')
    el.style.opacity = ''
    el.style.pointerEvents = ''
    el.style.display = ''
    return
  }
  if (binding.modifiers.hide) {
    el.style.display = 'none'
  } else {
    el.setAttribute('disabled', 'disabled')
    el.style.opacity = '0.45'
    el.style.pointerEvents = 'none'
  }
}

export const perm: Directive<HTMLElement, string | string[]> = {
  mounted: (el, binding) => apply(el, binding),
  updated: (el, binding) => apply(el, binding),
}
