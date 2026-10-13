/**
 * 汇总各视图的 curated override：自动加载 overrides/ 下除本文件外的所有 *.ts，
 * 合并它们导出的 `overrides` 映射。新增屏只需放一个 overrides/<view>.ts，零冲突。
 */
export type OverrideMap = Record<string, unknown>

const globbed = import.meta.glob('./*.ts', {
  eager: true,
}) as Record<string, { overrides?: OverrideMap }>

export const overrides: OverrideMap = {}
for (const [file, mod] of Object.entries(globbed)) {
  if (file === './index.ts') continue
  const map = (mod as any)?.overrides
  if (map && typeof map === 'object') Object.assign(overrides, map)
}
