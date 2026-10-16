# Plan：经费配置页（支出科目树管理 + 预算编制与审批）

> 2026-10-16 · 需求来源：用户在报销填单页发现「预算（执行中）」「支出科目」两个下拉无管理入口。
> 调研结论：**后端契约与实现已全部就绪，纯前端页面 + 种子数据任务，后端零代码改动（除种子迁移）**。

## 0. 现状盘点（调研证据）

| 项 | 后端 | 契约 | policy.csv | 前端 |
|---|---|---|---|---|
| 科目树管理（T15） | ✅ `funding/subject_admin.go` 全套 CRUD（树查询/增/改/删，删除守卫 40901 子级 / 40902 预算引用） | ✅ `03-F.openapi.yaml` `/subjects`、`/subjects/tree`、`/subjects/{id}` | ✅ R-MANAGER 全量写；R-STAFF/R-FINANCE/R-LEADER 只读；R-ADMIN 通配 | ❌ 无消费页 |
| 预算编制/审批（F-02/03/04） | ✅ `funding/budget.go`：POST /budgets（头+多行同事务，DRAFT）→ submit → approve/adjust | ✅ `/budgets`、`/budgets/{id}/submit|approve|adjust|lines` | ✅ R-MANAGER 全量（`/budgets/*` POST 覆盖 submit/approve/adjust）；R-LEADER approve；R-STAFF/R-FINANCE 只读 | ❌ 无消费页 |
| 页面可见性矩阵 | ✅ `sys_page_grant`（migration 000014，白名单制） | — | — | RolesView 矩阵编辑器自动列 router 路由 |

**关键语义**：矩阵是白名单制——`canSeePage` 对「无种子行的页面 = 不可见（R-ADMIN 除外）」。新页面必须随 migration 灌种子行，否则上线即只有管理员可见。

**种子数据基线**：`f_subject` 9 条（设备费/材料费/…，全部 level=1 is_leaf）；`f_budget` 2 条 EXECUTING（BUD-2026-8801 → project 9001、BUD-DASH-1 → project 9701，legal_entity_id=1）。

## 1. 交付物

### 1.1 migration 000015（`000015_funding_config_page.up.sql` / `.down.sql`）

向 `sys_page_grant` 灌新页种子（up；down 删之）：

| page_name | role_code |
|---|---|
| `funding-config` | R-MANAGER |
| `funding-config` | R-FINANCE |

（R-ADMIN 前端硬编码恒可见，无需种；R-AUDITOR 全局只读角色不授页，需要时管理员矩阵勾选即可。）

⚠️ 本地库 migration 需手动 psql 应用 + `schema_migrations` 推进到 15（同 000014 惯例）。

### 1.2 前端新页 `views/FundingConfigView.vue`（单文件，无构建依赖惯例）

路由 `/funding-config`（name: `funding-config`，meta.zh=经费配置，meta.roles=`['R-MANAGER','R-FINANCE']` 作 fallback）。挂「经费 · 成果」菜单组，图标 `⚗`。

**布局：上下两节（同 DictsView 双栏教训，避免 grid 溢出）**

**节一：支出科目树（T15 消费端）**
- 树形展示 `GET /subjects/tree`（缩进层级 + category 标签 DIRECT/INDIRECT/PERFORMANCE + is_leaf 徽标 + ratio_limit）
- 新增子级：行内「+子级」按钮，抽屉表单（name 必填、code、category 必填、is_leaf、ratio_limit、sort_no）；parent 自动带出
- 编辑：`PUT /subjects/:id`（name/ratio_limit/sort_no/remark——后端仅支持这四个字段的局部更新）
- 删除：`DELETE /subjects/:id`，40901/40902 后端守卫文案透出（「存在下级科目」「已被预算引用」）
- 写操作按钮用 `auth.can('/subjects POST')` 门控（R-MANAGER 可见；FINANCE 只读态自动隐藏写按钮）

**节二：预算列表与编制（F-02/03/04 消费端）**
- 列表 `GET /budgets`（状态筛选 DRAFT/SUBMITTED/EXECUTING/…；显示 code/项目/mode/批复总额/状态/版本）
- 水位详情：行展开或抽屉 `GET /budgets/:id/lines`（科目名 × planned/used/remaining，沿用报销页水位条样式）
- 新建预算抽屉：项目（`GET /project/mine` 下拉）+ legal_entity_id（默认 1）+ mode（预算制/包干制）+ 多行明细（科目下拉仅 is_leaf=true + 金额 input），前端合计实时展示；提交 `POST /budgets`（lines: [{subject_id, amount}]）
- 动作链：提交（submit，DRAFT→SUBMITTED）、批复（approve，仅 `auth.can('/budgets/ APPROVE')`… 实际用 `auth.can('/budgets/1/approve POST')` 形态探测——R-MANAGER 通配与 R-LEADER 显式条均命中）、调整（adjust）
- 空态/403 兜底：沿用 ExpenseView 的 `.catch(() => fallback)` 模式

### 1.3 路由与菜单

- `router/index.ts`：+1 条路由（meta.roles 同矩阵种子，仅作 grants 故障时的 fallback）
- `App.vue`：「经费 · 成果」组 +1 菜单项 `{ v: 'funding-config', ic: '⚗', label: '经费配置', roles: ['R-MANAGER','R-FINANCE'] }`

### 1.4 契约

`03-F.openapi.yaml` 已含全部端点（T15 时补过），**零改动**。12-U 无涉。

## 2. 不做什么（范围边界）

- ❌ Casbin 粒度②在线编辑（老欠账，另案）
- ❌ 预算追加（T14 append）/外拨/结转页面化（后端有 API，本期不做 UI，避免范围膨胀）
- ❌ 预警配置（warn-configs）UI（T15 另一半，后端已有，可下期）
- ❌ R-FINANCE 写权限放开（维持现状只读；管理员如需可在 Casbin 策略加行，属权限决策不在本期）

## 3. 实施步骤

| Phase | 内容 | 验收 |
|---|---|---|
| P1 | migration 000015 up/down + 手动应用 + 版本推进 15 | psql 查到 2 行 funding-config 种子 |
| P2 | FundingConfigView.vue + router + App.vue | vue-tsc 零错 + `npm run build` 绿 |
| P3 | Docker 重建 frontend；Playwright 冒烟：①manager 登录菜单含「经费配置」→ 进入页 → 新增子科目「测试化验加工费-子项」→ 树上出现；②新建预算（选项目+2 行科目）→ 列表出现 DRAFT → 提交；③finance 登录 → 页面可见但写按钮隐藏（只读态）；④RolesView 矩阵出现 funding-config 行 | 冒烟全 PASS |
| P4 | commit（develop，不推送）+ memory 记录 | git log 一条 feat 提交 |

## 4. 风险与预案

| 风险 | 预案 |
|---|---|
| 矩阵种子遗漏导致新页仅 R-ADMIN 可见 | P1 先行且纳入冒烟断言（manager 可见） |
| `GET /project/mine` 对 R-MANAGER 返回的只是自己项目 | 编制预算本就是主管动作，可接受；全量项目列表端点不存在，不新增后端 |
| 科目树层级深导致样式溢出 | 树缩进上限 + 容器 `min-width:0`（DictsView 教训） |
| budget approve 按钮对 R-LEADER 的可见性 | leader 无 funding-config 页面授权（矩阵未种），本期批复入口仅在 manager 视角；leader 需要时管理员矩阵勾选即可，页面内按钮走 `auth.can` 自动放行 |
| 创建科目 category 枚举约束（DIRECT/INDIRECT/PERFORMANCE） | 表单用 select 三选一，杜绝自由文本 |

## 5. 工作量估算

约 1 个新视图文件（~400 行）+ 2 行路由/菜单 + 1 个 migration。后端零改动。
