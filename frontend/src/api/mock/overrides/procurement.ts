/**
 * Curated overrides · 模块 G 采购与合同（ProcurementView 英雄屏）
 * 键规则：
 *  - 命中真实 GET 路由：`GET /procurement/requisitions`、`GET /supplier`（matchRoute 命中）
 *  - G 契约无 GET 合同/订单列表（合同只有 POST /contract，订单在 G 契约缺 GET），
 *    故用"去前缀精确路径"键 `/contract`、`/procurement/orders` 承载英雄拟真数据（未命中路由时由 mock 兜底）。
 * 值：静态 PageResult 形态 {list,total,page,size}，list<T> 直接解包。
 * 字段名严格对齐 09-采购与合同管理-G.openapi.yaml（Requisition/Supplier/Contract 为 snake_case）。
 */

const requisitions = [
  {
    id: 142, code: 'REQ-2026-0142', status: 'BIDDING', category: '设备',
    item_name: '高精度五轴加工中心', spec: '五轴联动 · 定位精度 0.005mm',
    est_amount: '2800000.00', frozen_amount: '2800000.00',
    purchase_way: '公开招标', budget_subject_code: '设备购置 · PRJ-2024-00087',
    project_id: 87, security_level: 'INTERNAL', created_at: '2026-10-08T09:12:00Z',
  },
  {
    id: 138, code: 'REQ-2026-0138', status: 'ORDERED', category: '试剂耗材',
    item_name: 'SEM 扫描电镜耗材包', spec: '样品台 · 溅射仪 · 标样',
    est_amount: '126000.00', frozen_amount: '126000.00',
    purchase_way: '询价', budget_subject_code: '试剂耗材 · 材料所',
    project_id: 42, security_level: 'PUBLIC', created_at: '2026-09-28T14:30:00Z',
  },
  {
    id: 131, code: 'REQ-2026-0131', status: 'WAY_DECIDED', category: '外协',
    item_name: '曲面测量外协服务', spec: '逆向工程 · CMM 全检',
    est_amount: '620000.00', frozen_amount: '620000.00',
    purchase_way: '竞争性谈判', budget_subject_code: '外协 · PRJ-2024-00087',
    project_id: 87, security_level: 'INTERNAL', created_at: '2026-10-02T10:00:00Z',
  },
  {
    id: 127, code: 'REQ-2026-0127', status: 'SUBMITTED', category: '设备',
    item_name: '高性能工控机 ×6', spec: 'i9 · 64G · RTX A4000',
    est_amount: '98000.00', frozen_amount: '98000.00',
    purchase_way: '自行采购', budget_subject_code: '设备 · 信息室',
    project_id: 42, security_level: 'PUBLIC', created_at: '2026-10-11T08:45:00Z',
  },
  {
    id: 119, code: 'REQ-2026-0119', status: 'SUBMITTED', category: '服务',
    item_name: '高温合金试样制备服务', spec: '切割 · 镶嵌 · 抛光',
    est_amount: '45000.00', frozen_amount: '45000.00',
    purchase_way: '自行采购', budget_subject_code: '测试化验 · 材料所',
    project_id: 42, security_level: 'PUBLIC', created_at: '2026-10-12T16:20:00Z',
  },
  {
    id: 151, code: 'REQ-2026-0151', status: 'DRAFT', category: '软件',
    item_name: '空天动力仿真软件授权', spec: 'CFD 求解器 · 3 席位',
    est_amount: '180000.00', frozen_amount: '0.00',
    purchase_way: '单一来源', budget_subject_code: '软件 · 空天室',
    project_id: 87, security_level: 'INTERNAL', created_at: '2026-10-13T09:00:00Z',
  },
]

const suppliers = [
  {
    id: 31, code: 'SUP-2024-0031', name: '华鼎精密装备制造集团', type: '供应商',
    grade: 'A', status: 'IN_LIBRARY', review_status: 'IN_LIBRARY', blacklist: 0,
    expire_date: '2027-06-30', security_level: 'PUBLIC',
  },
  {
    id: 108, code: 'SUP-2023-0108', name: '中科智能系统股份有限公司', type: '供应商',
    grade: 'B', status: 'IN_LIBRARY', review_status: 'IN_LIBRARY', blacklist: 0,
    expire_date: '2026-12-31', security_level: 'PUBLIC',
  },
  {
    id: 72, code: 'SUP-2025-0072', name: '某新材料科技公司', type: '供应商',
    grade: 'A', status: 'IN_LIBRARY', review_status: 'IN_LIBRARY', blacklist: 0,
    expire_date: '2026-10-20', security_level: 'PUBLIC',
  },
  {
    id: 14, code: 'SOSC-2022-0014', name: '恒达外协加工中心', type: '外协单位',
    grade: 'C', status: 'IN_LIBRARY', review_status: 'IN_LIBRARY', blacklist: 0,
    expire_date: '2026-03-15', security_level: 'INTERNAL',
  },
  {
    id: 250, code: 'SUP-2021-0250', name: '某医疗器械厂', type: '供应商',
    grade: 'D', status: 'EXPIRED', review_status: 'REJECTED', blacklist: 1,
    expire_date: '2025-01-10', security_level: 'PUBLIC',
  },
]

// 合同（G 契约无 GET 列表 → 精确路径键承载英雄数据；字段对齐 Contract，risk 为拟真建议项）
const contracts = [
  {
    id: 142, code: 'CON-2026-0142', contract_type: '采购', requisition_id: 142,
    party_a: '启元研究院', party_b: '华鼎精密装备制造集团',
    amount: '2800000.00', currency: 'CNY', status: 'TO_SIGN',
    sign_date: null, end_date: '2027-06-30', risk: 'HIGH', security_level: 'INTERNAL',
  },
  {
    id: 88, code: 'OSC-2026-0088', contract_type: '外协分包', requisition_id: 131,
    party_a: '启元研究院', party_b: '恒达外协加工中心',
    amount: '620000.00', currency: 'CNY', status: 'REVIEW',
    sign_date: null, end_date: '2026-12-31', risk: 'MED', security_level: 'INTERNAL',
  },
  {
    id: 131, code: 'CON-2026-0131', contract_type: '技术服务', requisition_id: null,
    party_a: '启元研究院', party_b: '中科智能系统股份有限公司',
    amount: '180000.00', currency: 'CNY', status: 'ACTIVE',
    sign_date: '2026-06-15', end_date: '2027-06-14', risk: 'LOW', security_level: 'PUBLIC',
  },
  {
    id: 72, code: 'CON-2025-0072', contract_type: '采购', requisition_id: 138,
    party_a: '启元研究院', party_b: '某新材料科技公司',
    amount: '126000.00', currency: 'CNY', status: 'ACTIVE',
    sign_date: '2025-11-02', end_date: '2026-11-01', risk: null, security_level: 'PUBLIC',
  },
  {
    id: 59, code: 'CON-2026-0059', contract_type: '横向委托', requisition_id: null,
    party_a: '启元研究院', party_b: '某汽车模具厂',
    amount: '950000.00', currency: 'CNY', status: 'SETTLING',
    sign_date: '2026-01-20', end_date: '2026-10-31', risk: 'MED', security_level: 'PUBLIC',
  },
]

// 采购订单（G 契约缺 GET 订单列表 → 精确路径键；对齐 DeliveryStatus 枚举）
const orders = [
  {
    id: 138, code: 'ORD-2026-0138', item_name: 'SEM 扫描电镜耗材包',
    supplier_name: '某新材料科技公司', amount: '126000.00',
    status: 'EXECUTING', delivery_status: 'ARRIVED', converted_asset: 0, saving: '18000.00',
  },
  {
    id: 127, code: 'ORD-2026-0127', item_name: '高性能工控机 ×6',
    supplier_name: '中科智能系统股份有限公司', amount: '98000.00',
    status: 'COMPLETED', delivery_status: 'ACCEPTED', converted_asset: 0, saving: '30000.00',
  },
  {
    id: 119, code: 'ORD-2026-0119', item_name: '高温合金试样',
    supplier_name: '某新材料科技公司', amount: '45000.00',
    status: 'CONFIRMED', delivery_status: 'SHIPPED', converted_asset: 0, saving: '0.00',
  },
  {
    id: 210, code: 'ORD-2025-0210', item_name: '高性能计算集群 GPU×8',
    supplier_name: '华鼎精密装备制造集团', amount: '1240000.00',
    status: 'COMPLETED', delivery_status: 'ACCEPTED', converted_asset: 1, saving: '580000.00',
  },
]

export const overrides: Record<string, unknown> = {
  'GET /procurement/requisitions': { list: requisitions, total: requisitions.length, page: 1, size: 50 },
  'GET /supplier': { list: suppliers, total: suppliers.length, page: 1, size: 50 },
  '/contract': { list: contracts, total: contracts.length, page: 1, size: 50 },
  '/procurement/orders': { list: orders, total: orders.length, page: 1, size: 50 },
}
