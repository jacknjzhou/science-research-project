import { writeFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const dir = fileURLToPath(new URL('../src/views/', import.meta.url))

const stubs = [
  'BigscreenView', 'GuideView', 'EditorView', 'ReviewView', 'ProjectsView',
  'ProjectView', 'ExpenseView', 'ClaimView', 'TransferView', 'ProcurementView',
  'AssetView', 'PortraitView',
]

for (const name of stubs) {
  const file = dir + name + '.vue'
  if (existsSync(file)) { console.log('skip (exists):', name); continue }
  const label = name.replace('View', '')
  const content = `<template>
  <section class="view on">
    <div class="page-head"><div><div class="page-title">${label}<em> · 待实现</em></div>
      <div class="page-sub">契约驱动脚手架占位屏（stub），将由实现阶段替换为完整数据驱动视图。</div>
    </div></div>
    <div class="card"><div class="card-b" style="padding:36px;text-align:center;color:var(--ink-mute)">
      TODO: ${label} — 消费 \`@/api/client\` 的 <code>api.get/list</code> 命中 0X 模块 OpenAPI 契约路径渲染。
    </div></div>
  </section>
</template>
`
  writeFileSync(file, content, 'utf8')
  console.log('wrote stub:', name)
}
