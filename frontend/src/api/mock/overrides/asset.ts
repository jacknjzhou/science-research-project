/**
 * Curated overrides · 模块 A 资产与耗材（AssetView 英雄屏）
 * 键规则：
 *  - `GET /asset/ledger`：A 契约真实 GET 路由（queryAssetLedger），matchRoute 命中。
 *  - `/consumable`：A 契约无 GET 耗材库存列表（仅 /consumable/{sku}/stock-in|stock-out），
 *    以"去前缀精确路径"键承载英雄拟真数据（未命中路由时 mock 兜底），字段对齐 ConsumableStatus 枚举。
 * 注意：Asset schema 为 camelCase（区别于 G 的 snake_case），此处严格照 schema 字段名。
 */

// 资产台账（Asset，camelCase）
const assets = [
  {
    id: 88, code: 'AST-2023-0088', name: '扫描电子显微镜 SEM-7',
    brand: 'Zeiss', model: 'Sigma 300', serialNo: 'SEM7-2023-0088',
    assetType: 'FIXED', categoryCode: '电子设备',
    value: 1860000, netValue: 987000, deprAccum: 873000,
    deprMethod: 'STRAIGHT_LINE', deprYears: 10,
    status: 'IN_USE', location: '材料所 · A203', custodianId: 4501, deptId: 20,
    shareFlag: true, openFlag: true, usageRate: 0.68,
    sourceType: 'PURCHASE', inDate: '2023-05-20', securityLevel: 'PUBLIC',
  },
  {
    id: 142, code: 'AST-2026-0142', name: '五轴加工中心（在途）',
    brand: 'DMG', model: 'DMU 80', serialNo: '',
    assetType: 'FIXED', categoryCode: '机械设备',
    value: 2800000, netValue: 2800000, deprAccum: 0,
    deprMethod: 'NONE', deprYears: 10,
    status: 'PENDING_RECEIPT', location: '制造所 · 待验收', custodianId: null, deptId: 10,
    shareFlag: false, openFlag: false, usageRate: 0,
    sourceType: 'PURCHASE', inDate: '', securityLevel: 'INTERNAL',
  },
  {
    id: 210, code: 'AST-2024-0210', name: '高性能计算集群 GPU×8',
    brand: 'Inspur', model: 'NF5688M6', serialNo: 'HPC-2024-0210',
    assetType: 'FIXED', categoryCode: '电子设备',
    value: 1240000, netValue: 839000, deprAccum: 401000,
    deprMethod: 'STRAIGHT_LINE', deprYears: 8,
    status: 'IN_USE', location: '信息室 · 机房', custodianId: 4510, deptId: 30,
    shareFlag: true, openFlag: true, usageRate: 0.82,
    sourceType: 'PURCHASE', inDate: '2024-03-12', securityLevel: 'PUBLIC',
  },
  {
    id: 31, code: 'AST-2019-0031', name: '三坐标测量机',
    brand: 'Hexagon', model: 'GLOBAL S', serialNo: 'CMM-2019-0031',
    assetType: 'FIXED', categoryCode: '仪器设备',
    value: 680000, netValue: 68000, deprAccum: 612000,
    deprMethod: 'STRAIGHT_LINE', deprYears: 10,
    status: 'PENDING_DISPOSE', location: '制造所 · B101', custodianId: 4490, deptId: 10,
    shareFlag: false, openFlag: false, usageRate: 0.1,
    sourceType: 'PURCHASE', inDate: '2019-07-01', securityLevel: 'PUBLIC',
  },
  {
    id: 175, code: 'AST-2022-0175', name: '激光共聚焦显微镜',
    brand: 'Leica', model: 'STORM', serialNo: 'LSM-2022-0175',
    assetType: 'FIXED', categoryCode: '电子设备',
    value: 1520000, netValue: 912000, deprAccum: 608000,
    deprMethod: 'STRAIGHT_LINE', deprYears: 10,
    status: 'IN_USE', location: '生物室 · C305', custodianId: 4522, deptId: 40,
    shareFlag: true, openFlag: false, usageRate: 0.55,
    sourceType: 'PURCHASE', inDate: '2022-09-15', securityLevel: 'INTERNAL',
  },
  {
    id: 61, code: 'AST-2025-0061', name: '真空烧结炉',
    brand: 'Koyo', model: 'VH-50', serialNo: 'SINT-2025-0061',
    assetType: 'FIXED', categoryCode: '热处理设备',
    value: 460000, netValue: 405000, deprAccum: 55000,
    deprMethod: 'STRAIGHT_LINE', deprYears: 10,
    status: 'IDLE', location: '材料所 · A110', custodianId: 4501, deptId: 20,
    shareFlag: false, openFlag: false, usageRate: 0.05,
    sourceType: 'PURCHASE', inDate: '2025-04-02', securityLevel: 'PUBLIC',
  },
]

// 耗材/试剂库存（ConsumableStatus 枚举：IN_STOCK/LOW_STOCK/NEAR_EXPIRY/EXPIRED/STAGNANT）
const consumables = [
  {
    sku: 'REAG-ETOH-001', name: '无水乙醇（分析纯）', category: 'REAGENT',
    qty: 3, unit: 'L', safe_stock: 10, status: 'LOW_STOCK',
    is_hazard: true, consumed_30d: 12, expire_date: '2027-03-01', location: '危化品柜 · A118',
  },
  {
    sku: 'CONS-ABR-P1200', name: '金相砂纸 P1200', category: 'CONSUMABLE',
    qty: 40, unit: '张', safe_stock: 100, status: 'LOW_STOCK',
    is_hazard: false, consumed_30d: 60, expire_date: '', location: '耗材库 · B102',
  },
  {
    sku: 'GAS-AR-HIGH', name: '氩气（高纯）', category: 'CONSUMABLE',
    qty: 2, unit: '瓶', safe_stock: 3, status: 'IN_STOCK',
    is_hazard: false, consumed_30d: 1, expire_date: '2028-01-01', location: '气瓶区 · C201',
  },
  {
    sku: 'REAG-HCL-36', name: '盐酸 36%（AR）', category: 'REAGENT',
    qty: 5, unit: '瓶', safe_stock: 4, status: 'NEAR_EXPIRY',
    is_hazard: true, consumed_30d: 2, expire_date: '2026-11-05', location: '危化品柜 · A118',
  },
  {
    sku: 'REAG-AGNO3', name: '硝酸银（AR）', category: 'REAGENT',
    qty: 1, unit: '瓶', safe_stock: 2, status: 'EXPIRED',
    is_hazard: true, consumed_30d: 0, expire_date: '2026-09-20', location: '危化品柜 · A118',
  },
  {
    sku: 'CONS-TIP-200', name: '移液枪头 200μL', category: 'CONSUMABLE',
    qty: 800, unit: '支', safe_stock: 500, status: 'STAGNANT',
    is_hazard: false, consumed_30d: 30, expire_date: '2029-06-01', location: '耗材库 · B102',
  },
]

export const overrides: Record<string, unknown> = {
  'GET /asset/ledger': { list: assets, total: assets.length, page: 1, size: 50 },
  '/consumable': { list: consumables, total: consumables.length, page: 1, size: 50 },
}
