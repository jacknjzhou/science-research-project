# Plan · 页面可见性矩阵在线配置（P-U1-dyn）

> 2026-10-16 · 目标：把「页面 ↔ 角色」可见性从三份前端硬编码镜像（router meta.roles / App.vue 菜单 / RolesView PAGES）收敛为**后端一份数据、管理员在线编辑**，同时保留静态 fallback 防锁死。

## 一、现状与问题

| 层 | 现状 | 问题 |
|---|---|---|
| 路由守卫 | `router/index.ts` 每条路由 `meta.roles` 硬编码，`beforeEach` 按 `hasAnyRole` 拦截 | 改配置要改代码重新构建 |
| 侧边菜单 | `App.vue` groups 每项 `roles`，与 router **手工双镜像** | 两处不同步即出现"菜单在、页面 403"式错位 |
| 矩阵展示 | `RolesView.vue` 的 `PAGES` 数组第三份镜像，只读 | 新增自定义角色后全部显示 `·`，无法在线配置 |
| API 授权 | Casbin policy.csv（粒度②） | 不在本次范围（按钮/操作级） |

核心诉求：管理员在「角色与权限」页直接勾选矩阵并保存生效；自定义角色可被授予任意页面。

## 二、方案设计

### 2.1 数据模型（单表，migration 000014）

```sql
CREATE TABLE sys_page_grant (
  id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  page_name VARCHAR(64)  NOT NULL,              -- 路由 name（dash/expense/...）
  role_code VARCHAR(64)  NOT NULL,              -- 角色 code；'*' 表示所有已登录
  tenant_id BIGINT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uk_page_grant ON sys_page_grant(tenant_id, page_name, role_code);
```

语义约定：
- **全量替换**保存（页面×角色 ≈ 15×20 ≤ 300 行，PUT 整体覆盖，无增量语义负担）
- `role_code='*'` 行 = 现在的 `roles: []`（所有已登录可见）
- **不配置 = 不可见**（显式白名单制）；R-ADMIN 恒可见由**前端硬编码兜底**，不入库（防管理员自锁）
- public 路由（`/forbidden`、`/dash?needLogin`）不进矩阵、不走守卫判断

### 2.2 契约（12-U openapi）

- `GET /page-grants`：任意已登录角色（登录即需要，路由守卫消费）→ `{ grants: [{ page_name, role_code }] }`
- `PUT /admin/page-grants`：R-ADMIN，body `{ grants: [{ page_name, role_code }] }`，事务内先删后插 → 返回保存后全量 + 校验（page_name/role_code 白名单：page 取前端上报、role 校验存在于 sys_role）
- Schema：`PageGrant`、`PageGrantSave`

### 2.3 后端（sysadmin 模块，TDD）

1. `db/schema/sys_schema.sql` 摘录 sys_page_grant（编译期解析）
2. `db/query_sys/page_grant.sql`：`ListPageGrants` / `DeleteAllPageGrants` / `InsertPageGrant`（事务在 handler 用 pool Begin 组装）；`ListRoleCodes`（校验角色存在，复用 ListRoles）
3. `handler_page_grant.go`：GET（返回全量行）+ PUT（事务替换 + 角色码校验，未知角色 400）
4. `policy.csv`：全部业务角色补 `GET /api/v1/page-grants/*`（写走 R-ADMIN 通配）
5. 测试：seed 后 GET 返回种子行；PUT 全量替换幂等；R-STAFF 写 403；未知角色码 400；'*' 行语义

### 2.4 前端（单数据源 + fallback）

1. **auth store**（`api/auth.ts`）：`loadMe()` 成功后并行拉 `/page-grants` → `auth.pageGrants: Map<page, Set<role>>`；拉取失败置 `grantsReady=false`（走 fallback）
2. **统一判定函数**（auth.ts 导出）：
   ```ts
   canSeePage(name: string): boolean {
     if (public 路由) return true
     if (roles.includes('R-ADMIN')) return true          // 硬编码兜底，防自锁
     if (!grantsReady) return staticFallback(name)        // 拉 fail → 老 meta.roles 表
     return grants.has('*' 行) || grants 命中任一自身角色
   }
   ```
   `staticFallback` = 现有 router meta.roles 抽成同一模块内的常量表（保留为灾备，标注 fallback-only）
3. **router.beforeEach / App.vue 菜单**：改调 `canSeePage`（路由 meta.roles 保留但仅作 fallback 数据源）
4. **RolesView 矩阵编辑器**：
   - 页面清单：`router.options.routes` 过滤 public（自动同步新路由，zh 取 meta.zh）
   - 角色列：`/admin/roles` 目录（含自定义角色）
   - 单元格 checkbox（R-ADMIN 可编辑；R-ADMIN 列恒 ✓ 且禁用）
   - 「所有已登录」以 `*` 角色列呈现
   - 保存 → PUT → 本地 `auth.pageGrants` 立即更新 + toast「已保存，其他会话重新登录后生效」
   - PAGES 硬编码数组删除

### 2.5 种子（migration 000014 内）

把当前 router meta.roles + 菜单 roles 的并集灌入 `sys_page_grant`（与现状完全一致，部署后零行为变化），含 dash 的 `*` 行。

## 三、Phase 划分

| Phase | 内容 | 交付 |
|---|---|---|
| 0 | 12-U 契约：GET /page-grants + PUT /admin/page-grants + schema | 契约可校验 |
| 1 | migration 000014（建表+种子）+ sys_schema 摘录 + page_grant.sql + handler + policy + 测试 | 后端 -p 1 回归绿 |
| 2 | auth.ts 集成（pageGrants + canSeePage + fallback）+ router/App.vue 切换消费 + RolesView 矩阵编辑器（checkbox 网格 + 保存） | vue-tsc/build 绿 |
| 3 | Docker 重建 + headless 冒烟（admin 勾选新角色可见某页 → staff 登录菜单出现；取消勾选 → 消失）+ commit | 可演示闭环 |

## 四、验收（PRD 2.9）

1. **功能**：矩阵勾选保存后，staff 侧菜单与路由访问实时（下次导航）生效；'*' 行页面全员可见
2. **权限**：仅 R-ADMIN 可写；其它角色 GET 只读；未知角色码/页面码被 400 拒绝
3. **容灾**：后端 grants 不可用时全站仍按静态 fallback 可达（不锁死）；R-ADMIN 永不把自己关门外
4. **审计**：PUT 记 sys_audit_log（沿用现有 Log 模式）

## 五、风险与边界

| 风险 | 对策 |
|---|---|
| grants 接口故障 → 全站页面不可达 | auth.pageGrants 拉取失败走 staticFallback（老 meta.roles 常量表） |
| 管理员取消自己的 R-ADMIN 页面权限自锁 | R-ADMIN 恒可见为前端硬编码，不入库不参与编辑 |
| 三份镜像残留漂移 | meta.roles/App.vue roles 注释标 fallback-only；RolesView PAGES 删除；后续清理任务列入 plan 尾 |
| 多租户 | 所有查询带 tenant_id（与现有模式一致）；M0 单租户不受影响 |
| 矩阵保存并发 | 全量替换 + 页面级粒度小，冲突面可忽略；后续可加 version 乐观锁 |
| Casbin 策略（粒度②）仍离线 | 明确不在本期；页面可见后按钮级 403 由后端兜底，文案提示 |

## 六、工作量估算

- 后端：migration 1 + schema 摘录 + page_grant.sql + handler_page_grant + 测试 ≈ 5 文件
- 前端：auth.ts（grants + canSeePage）+ router 守卫 + App.vue 菜单 + RolesView 编辑器 ≈ 4 文件
- 契约：12-U 增 2 端点 + 2 schema
