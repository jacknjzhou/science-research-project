# 科研管理系统 · 用户管理与权限（模块 U）全栈实现计划

**目标：** 在已完成的 Go+Gin M0 奠基 + P 竖切之上，补齐「用户管理 + 角色 + 各页面访问权限」的完整垂直能力——后端 `sysadmin`（模块 U）提供用户 CRUD、角色目录、用户↔角色授权、`/auth/me` 能力查询与 bcrypt 真实登录；契约新增 `12-用户与权限-U.openapi.yaml`；前端落地登录态、路由守卫、按角色过滤的侧栏菜单，以及用户管理与角色权限两个管理页。端到端跑通「design 契约 → Go 服务 → PostgreSQL → Vue 前端」，Go 服务仍是 compose 里唯一的 `backend`。

**架构：** 契约驱动、模块化单体（单 codebase、按域分包）。三种权限粒度各有明确归属，互不混淆：**① 路由/菜单级**——前端 `router/index.ts` 每条路由 `meta.roles: string[]` + `beforeEach` 守卫 + 侧栏 `groups[].items[].roles` 过滤（静态配置，决定"哪些页面可见/可达"）；**② 按钮/操作级**——后端 `GET /auth/me` 依 Casbin `policy.csv` 派生当前用户的能力集合 `caps[]`，前端 `auth.can(cap)` 决定"某个操作按钮是否可用"；**③ 数据可见性（ABAC）**——仓储层强制注入 `auth.DomainFrom(c).TenantID`（并预留 `security_level` 谓词），跨租户行天然不可见。后端 API 传输层鉴权仍由现有 `middleware.Auth`（JWT 解析 + Casbin `Enforce(role,path,method)`）统一拦截。策略源沿用静态 `policy.csv`（烘进镜像），本轮**不**引入 `casbin_rule` 表、**不**引入 `sys_menu/sys_permission` 表。登录本轮从内置 `ark/ark` 升级为 bcrypt 真实校验（`sys_user.password_hash`），但保留 `Pool==nil` 时的 dev 回退以保证无库单测零回归。

**技术栈：** Go 1.22（本机以 `GOTOOLCHAIN=go1.23.4` 跑 sqlc）、Gin v1.10、sqlc v1.27（pgx/v5，第二生成块）、oapi-codegen（仅 models，沿用）、jackc/pgx/v5、golang-migrate v4、golang-jwt/v5、Casbin v2.135、`golang.org/x/crypto/bcrypt`、go-playground/validator、zap、stretchr/testify；PostgreSQL 15；Vue 3.4 + vue-router 4（**无 pinia**，用 `reactive` 组合式 store）+ Vite 4.5 + TS 5.3；Docker Compose。

---

## 0. 范围分解地图（本计划只写全「用户与权限垂直」，其余登记为后续独立计划）

本需求按 writing-plans「每计划产出可独立测试的软件」原则，与既有 `2026-10-13-go-m0-foundation-p-slice.md`（M0）解耦。M0 已交付：Go 底座、`httpx` 包络、traceId/Recover、config、pgx 池、golang-migrate 生成迁移、JWT 签发/校验、Casbin enforcer + `middleware.Auth`、幂等中间件、`oapi` passthrough、P 模块 list/read/create、compose 一键起服。本计划在其上补齐用户/角色/权限垂直。

| 计划 | 覆盖 | 产出可测试物 | 状态 |
|---|---|---|---|
| **P-U0（本文）** | 用户/角色/权限垂直 | `sys_user.password_hash` + 角色/用户种子迁移 + U 契约 + bcrypt 登录 + `/auth/me` 能力 + sysadmin 用户 CRUD/角色授权/ABAC + Casbin 路由策略扩展 + 前端登录态/守卫/菜单过滤/用户与角色管理页 | 本文写全 |
| P-M1-core | 核心业务 | E/F/R/G/A/C 域真实逻辑、事务、状态机、单号服务、审计落库 | 后续计划 |
| P-U1-dyn | 权限动态化 | `casbin_rule` 表持久化策略 + 策略管理 UI + 角色自定义增删、菜单表 `sys_menu`、自助改密/找回 | 后续计划 |
| P-U2-org | 组织与三员 | `sys_org` 部门树、数据域按部门/法人细分、三员（`sys_admin_duty`）强制分立校验 | 后续计划 |

> 决策依据（用户确认）：范围=**全栈完整多页**；登录=**本轮加 bcrypt 真实登录**；策略源=**继续 policy.csv**（不入库、不建菜单/权限表）；粒度=**路由/菜单级 + 按钮/操作级 + 数据可见性 ABAC（三者全要）**。

## 1. 文件结构映射（分解决策在此锁定）

在既有 `backend-go/` 与 `frontend/` 上增量。每个文件单一职责，按域分组。标注〔改〕=修改既有文件，〔新〕=新建，〔生〕=codegen 产物（纳入版本库）。

```
design/
  00-common.sql                                   〔改〕sys_user 增列 password_hash VARCHAR(100)（放在 status 之后、tenant_id 之前）
  12-用户与权限-U.openapi.yaml                     〔新〕模块 U 契约：/auth/login、/auth/me、/admin/users(CRUD)、/admin/users/{id}、/admin/roles、/admin/users/{id}/roles、/admin/users/{userId}/roles/{roleId}

backend-go/
  migrations/
    000001_init.up.sql / .down.sql                〔生〕由 gen.go 重生成（含 password_hash 新列）
    000002_seed_auth.up.sql                       〔新·手写〕8 角色 + 4 演示用户（含真实 bcrypt）+ user_role 绑定；不被 regen 覆盖
    000002_seed_auth.down.sql                     〔新·手写〕按 FK 逆序 DELETE
    gen.go                                         〔改〕GenerateUp 无需改（自动含 design 新列）；补一条 doc 注释说明 000002 为手写种子、不参与 regen
    gen_test.go                                    〔改〕增守卫：断言生成的 up.sql 含 "password_hash"，且不含 ClickHouse 残留
  db/
    schema/sys_schema.sql                          〔新〕sqlc 第二块裁剪 schema：sys_user(+password_hash)/sys_role/sys_user_role 三表
    query_sys/sys_user.sql                         〔新〕GetUserByUsername/ListUsers/CountUsers/GetUser/CreateUser/UpdateUser/SoftDeleteUser/UpdateUserPassword
    query_sys/sys_role.sql                         〔新〕ListRoles/ListRoleCodesByUser/ListRoleIDsByUser
    query_sys/sys_user_role.sql                    〔新〕AssignRole/RevokeRole/ListUserRoles
  sqlc.yaml                                        〔改〕追加第二个 postgresql 生成块（schema=db/schema/sys_schema.sql, queries=db/query_sys, package=sysstore, out=internal/modules/sysadmin/store）
  internal/modules/sysadmin/store/                 〔生〕sqlc 输出：SysUser/SysRole/SysUserRole 模型 + Queries
  internal/modules/sysadmin/
    routes.go                                      〔新〕func Register(r gin.IRoutes, h *Handler)：U 全部路由（相对 /admin、/auth 前缀，挂受保护组）
    handler.go                                     〔新〕Handler{q *sysstore.Queries, enf *casbin.Enforcer}；NewHandler(pool, enf)；ListUsers/GetUser/CreateUser/UpdateUser/DeleteUser/ListRoles/AssignRole/RevokeRole/GetMe
    mapper.go                                      〔新〕ToAPIUser/ToAPIRole（绝不外泄 password_hash）
    caps.go                                        〔新〕BuildCaps(enf, roles []string) []string：遍历 GetPolicy() 命中角色的 p 规则 → "obj act"
    handler_test.go                                〔新〕httptest 端到端（ARK_TEST_DATABASE_URL 门控）
    contract_test.go                               〔新〕纯契约合规：合成 data 对 design 12 schema（无 DB）+ 真响应校验（有 DB）
  internal/platform/auth/
    login.go                                       〔改〕HandleLogin → NewLoginHandler(secret, ttl, pool)：pool!=nil 走 bcrypt DB，pool==nil 保留 ark/ark dev 回退
    login_test.go                                  〔新〕dev 路径签发断言（无 DB）+ bcrypt 校验断言
    caps_test.go                                   〔新〕BuildCaps 单测（真 policy.csv）
  internal/router.go                               〔改〕登录路由改用 auth.NewLoginHandler(...,d.Pool)；受保护组内 if d.Pool!=nil 注册 sysadmin.Register
  internal/modules/p/store/*                       （不动，P 竖切保持）

frontend/
  src/api/schema/12-用户与权限-U.openapi.yaml       〔新〕从 design/ 同名 cp（mock ?raw 读前端副本，两套必须一致）
  src/api/schema/index.ts                          〔改〕MODULE_CODES 增 '12':'U'
  src/api/auth.ts                                  〔新〕reactive 单例 store：state{token,user,roles,caps} + login()/logout()/loadMe()/hasAnyRole()/can()；localStorage 持久化（try/catch）
  src/api/client.ts                                〔改〕Authorization 从 auth.state.token 取真实 Bearer；401→logout+跳登录
  src/directives/perm.ts                           〔新〕v-perm 指令：依 auth.can() 禁用/隐藏元素
  src/router/index.ts                              〔改〕各路由补 meta.roles；新增 /admin/users、/admin/roles、/forbidden；导出 beforeEach 守卫（未登录→/login 语义即浮层，越权→/forbidden）
  src/views/LoginGate.ts                           〔新〕可选薄封装：登录提交→auth.login→loadMe（若不改 App.vue 内联则用此）
  src/App.vue                                      〔改〕登录浮层接真实 auth.login；侧栏 groups.items 增 roles，computed 过滤后渲染；role-chip 显示真实用户名/角色 + 退出
  src/views/admin/UsersView.vue                    〔新〕用户管理页：列表/分页/筛选 + 新建/编辑抽屉 + 停用 + 角色分配
  src/views/admin/RolesView.vue                    〔新〕角色权限页：8 基础角色 + 每角色 caps 只读矩阵（源自 /auth/me caps + 角色目录）
```

**运行期契约来源**：沿用 M0——Go 运行时从磁盘 `DESIGN_DIR` 读 `design/*.openapi.yaml`；`000002_seed_auth` 手工迁移纳入版本库、`golang-migrate` 按版本号顺序自动应用（000001→000002）。前端 mock 读的是 `frontend/src/api/schema/` 副本，故新契约必须 cp 同步（任务 3）。

**命名一致性铁律**（贯穿全计划，防漂移；与 M0 铁律并列）：
- 新 Go 包一律 `package sysadmin`，仓储包 `package sysstore`（import path `github.com/eplugger/ark/internal/modules/sysadmin/store`）。两包并存、互不冲突。
- sqlc 模型：`sys_user`→`sysstore.SysUser`、`sys_role`→`sysstore.SysRole`、`sys_user_role`→`sysstore.SysUserRole`。
- U 路由相对前缀只写 `/admin`、`/auth`；`/api/v1` 由 `router.Build` 的 `api := e.Group("/api/v1")` 提供。契约 `servers.url=/api/v1`，模板路径不带 `/api/v1`（如 `/admin/users`）。
- 契约实体对外形状（snake_case，与 DDL 列名一致，但**剔除 password_hash**）：`User{id,username,real_name,email,phone,staff_no,employment_status,security_level,status,tenant_id,legal_entity_id,roles[],created_at,updated_at}`；`UserRequest{username,real_name,password,security_level?,roles[],...}`；`Role{id,code,name,is_builtin,tenant_id}`；`MeResponse{user:User, roles:string[], caps:string[]}`。
- `password_hash VARCHAR(100)`（bcrypt `$2a$10$` 定长 60，留裕度）。可空（NULL 表示无口令账号，dev 回退/外联身份用），bcrypt 比较时 NULL 一律拒登。
- 前端 store 单例导出 `auth`（`reactive` 对象）+ 方法 `auth.login/logout/loadMe/hasAnyRole/can/isReady`。能力字符串 = `BuildCaps` 从 Casbin 策略取出的 obj+act **原样**（含 `/api/v1` 前缀、`R-ADMIN` 等可能为 `/*` 通配），例：`"/api/v1/admin/users POST"`、`"/api/v1/* GET"`。前端 `auth.can(want)` 采**容错匹配**（任务 15）：`want` 可写简写 `"/admin/users POST"`，内部补 `/api/v1` 前缀、并把授予项 `/*` 后缀按「前缀命中」判定，故简写与通配/精确授予都能匹配。
- Casbin 角色码沿用 8 基础角色：`R-STAFF/R-MANAGER/R-LEADER/R-FINANCE/R-AUDITOR/R-EXPERT/R-ETHICS/R-ADMIN`。演示口令：`admin/Admin@123456`、`manager/Manager@123456`、`staff/Staff@123456`、`finance/Finance@123456`（均为本计划实测生成的真实 bcrypt 哈希，写死进 `000002` 种子）。
- ABAC：所有 sysadmin 查询第一参数恒为 `auth.DomainFrom(c).TenantID`；`security_level` 谓词本轮只在写入时落列，读取过滤在 P-U2 展开（本计划提供 hook 注释，不空实现）。

**本机工具链手册（执行期铁约束，来自 M0 实测）**：
- 跑 sqlc 必须 `GOTOOLCHAIN=go1.23.4`（sqlc v1.27 的 wazero pg_query 解析器在 auto/1.26 下 panic）；本机 `go1.21.6 windows/amd64` 可编译 1.22 目标。
- **切勿 `go mod tidy`**（会把 `rogpeppe/go-internal` 强拉到需 go1.25）。新增依赖用定向 `go get`（本计划唯一新增运行期依赖 `golang.org/x/crypto` **已在** go.mod，无需新增）。
- sqlc 不解析 ~394KB 全量迁移——第二块同样指向裁剪 schema `db/schema/sys_schema.sql`。
- Bash 工具走 git-bash：给子进程传环境变量须 `VAR=x cmd` 前缀（例：`GOTOOLCHAIN=go1.23.4 sqlc generate`）。
- 本机无 Docker：任务 14/19 的 compose 起服与真连库集成用例在无 Docker 主机上标记 **BLOCKED**，留 CI/Docker 主机；DB 门控测试用 `ARK_TEST_DATABASE_URL` 未设则 `t.Skip`。

## Part A — 数据底座与契约

## 任务 1：`sys_user` 增加 `password_hash` 列并重生成迁移

bcrypt 真实登录需要持久化口令哈希。改 `design/00-common.sql`（真源），重生成 `migrations/000001_init.up.sql`，并加一条守卫防列丢失。

**文件：**
- 修改：`design/00-common.sql`（`CREATE TABLE sys_user` 内，`status` 列之后、`tenant_id` 之前加 `password_hash`）
- 修改：`backend-go/migrations/gen_test.go`（新增 `TestGenerateUp_HasPasswordHash`）
- 生成：`backend-go/migrations/000001_init.up.sql`（`make gen-migrations` 重生成）

- [ ] **步骤 1：写失败的测试（守卫：生成的 up.sql 必含 password_hash）**

在 `backend-go/migrations/gen_test.go` 末尾（`func min` 之前）追加：

```go
// TestGenerateUp_HasPasswordHash 守卫用户口令哈希列进入迁移：bcrypt 真实登录（任务7）
// 依赖 sys_user.password_hash；一旦 design 误删该列，compose 迁移后登录必 500。
func TestGenerateUp_HasPasswordHash(t *testing.T) {
	designDir := os.Getenv("DESIGN_DIR")
	if designDir == "" {
		designDir = "../../design"
	}
	up, err := GenerateUp(designDir)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(strings.ToLower(up), "password_hash") {
		t.Fatal("sys_user 缺 password_hash 列——bcrypt 登录无从存储口令哈希")
	}
}
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend-go && go test ./migrations/ -run TestGenerateUp_HasPasswordHash -v`
预期：FAIL，`sys_user 缺 password_hash 列`。

- [ ] **步骤 3：改 design 加列**

编辑 `design/00-common.sql`，把 `sys_user` 表定义中的这两行之间插入 `password_hash`（原文：`status` CHECK 收尾到 `tenant_id`）：

原文：
```sql
  status          VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                  CHECK (status IN ('ACTIVE','LOCKED','DISABLED')),
  tenant_id       BIGINT       NOT NULL,
```
改为：
```sql
  status          VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                  CHECK (status IN ('ACTIVE','LOCKED','DISABLED')),
  password_hash   VARCHAR(100),                -- bcrypt($2a$10$…) 定长60留裕度；NULL=无口令账号(dev/外联身份)，一律拒登
  tenant_id       BIGINT       NOT NULL,
```

- [ ] **步骤 4：重跑守卫确认通过**

运行：`cd backend-go && go test ./migrations/ -run TestGenerateUp_HasPasswordHash -v`
预期：PASS。

- [ ] **步骤 5：重生成迁移产物**

运行：`cd backend-go && go generate ./migrations/...`
预期：打印 `生成 migrations/000001_init.{up,down}.sql 完成`。
校验新列已落入已提交迁移：`cd backend-go && grep -c "password_hash" migrations/000001_init.up.sql` → 应 ≥1。

- [ ] **步骤 6：跑全量迁移守卫确认零回归**

运行：`cd backend-go && go test ./migrations/ -v`
预期：全部 PASS（含既有 ClickHouse/前向 FK/pg_trgm/重名索引/重名列/保留字守卫 + 新 password_hash 守卫）。

- [ ] **步骤 7：Commit**

```bash
git add design/00-common.sql backend-go/migrations/gen_test.go backend-go/migrations/000001_init.up.sql
git commit -m "feat(design): sys_user 增 password_hash 列并重生成迁移"
```

---

## 任务 2：`000002_seed_auth` 角色 + 演示用户（真实 bcrypt）种子迁移

`golang-migrate` 按版本顺序在 000001 建表后自动应用 000002，注入 8 基础角色与 4 演示用户（口令为本计划实测生成的真实 bcrypt 哈希）。此文件手写、**不**被 `go generate` 覆盖。`sys_user.id`/`sys_role.id` 为 `GENERATED ALWAYS AS IDENTITY`，故 user_role 绑定一律用 code/username 子查询定位、不硬编码 id。

**文件：**
- 创建：`backend-go/migrations/000002_seed_auth.up.sql`
- 创建：`backend-go/migrations/000002_seed_auth.down.sql`

- [ ] **步骤 1：写 up 种子**

`backend-go/migrations/000002_seed_auth.up.sql`（bcrypt 哈希为实测值，勿改；`$2a$10$…` 在 PG 单引号串内是纯文本）：

```sql
-- 000002_seed_auth.up.sql · 手写种子（不参与 go generate）。依赖 000001 已建 sys_role/sys_user/sys_user_role。
-- 演示口令（均为实测 bcrypt cost=10 哈希）：
--   admin/Admin@123456  manager/Manager@123456  staff/Staff@123456  finance/Finance@123456
-- 注意：内置 dev 账号 ark/ark 仅在 pool==nil 的开发回退路径生效（任务7），不在此入库。

-- 1) 8 基础角色（PRD 2.1，租户 1）
INSERT INTO sys_role (code, name, is_builtin, tenant_id) VALUES
  ('R-STAFF',   '科研人员',     TRUE, 1),
  ('R-MANAGER', '科研管理岗',   TRUE, 1),
  ('R-LEADER',  '单位领导',     TRUE, 1),
  ('R-FINANCE', '财务',         TRUE, 1),
  ('R-AUDITOR', '审计',         TRUE, 1),
  ('R-EXPERT',  '评审专家',     TRUE, 1),
  ('R-ETHICS',  '伦理委员会',   TRUE, 1),
  ('R-ADMIN',   '系统管理员',   TRUE, 1);

-- 2) 4 演示用户（租户 1，creator_id=1 自指；sys_role/sys_user 建表后 identity 首值即 1）
INSERT INTO sys_user (username, real_name, email, staff_no, employment_status, security_level, status, password_hash, tenant_id, creator_id) VALUES
  ('admin',   '系统管理员', 'admin@eplugger.com',   'A0001', 'ONBOARD', 'TOP_SECRET', 'ACTIVE', '$2a$10$a1Cu2YSk60mLMlTC7Mq5t.DzD7Suj.jUkigRj1YNdKFRLPb61XTR2', 1, 1),
  ('manager', '科研管理岗', 'manager@eplugger.com', 'A0002', 'ONBOARD', 'SECRET',     'ACTIVE', '$2a$10$kbJo5wGylj7x4r.kb60cM.Ndxu87QO3zu763TZz8aI1nb2SVen5C2', 1, 1),
  ('staff',   '一线研究员', 'staff@eplugger.com',   'A0003', 'ONBOARD', 'INTERNAL',   'ACTIVE', '$2a$10$CsWOrEdaLYnaq5.YV6/Lu.8HMpDv3XJMyd5vPHvtEbD5fpfuZDPiC', 1, 1),
  ('finance', '财务专员',   'finance@eplugger.com', 'A0004', 'ONBOARD', 'SECRET',     'ACTIVE', '$2a$10$bSMrXkIOn.GH5aCTUG8ceeucmaNH2zz6wiTbqQLjdqkdp9VMWdIqm', 1, 1);

-- 3) 用户—角色绑定（用 code/username 子查询定位，避免依赖 identity 具体值）
INSERT INTO sys_user_role (user_id, role_id, tenant_id)
SELECT u.id, r.id, 1 FROM sys_user u, sys_role r
WHERE u.tenant_id=1 AND r.tenant_id=1 AND (
     (u.username='admin'   AND r.code='R-ADMIN')
  OR (u.username='manager' AND r.code IN ('R-MANAGER','R-LEADER'))
  OR (u.username='staff'   AND r.code='R-STAFF')
  OR (u.username='finance' AND r.code='R-FINANCE')
);
```

- [ ] **步骤 2：写 down（逆 FK 序删除，幂等）**

`backend-go/migrations/000002_seed_auth.down.sql`：

```sql
-- 000002_seed_auth.down.sql · 撤销种子（逆 FK 依赖顺序）。000001.down 的 DROP SCHEMA CASCADE 亦会整体清空，此处仅做局部可回退。
DELETE FROM sys_user_role WHERE tenant_id = 1;
DELETE FROM sys_user      WHERE tenant_id = 1 AND username IN ('admin','manager','staff','finance');
DELETE FROM sys_role      WHERE tenant_id = 1 AND code IN
  ('R-STAFF','R-MANAGER','R-LEADER','R-FINANCE','R-AUDITOR','R-EXPERT','R-ETHICS','R-ADMIN');
```

- [ ] **步骤 3：语法自检（迁移成对、编号唯一）**

运行：`cd backend-go && ls migrations/` → 应见 `000001_init.{up,down}.sql` 与 `000002_seed_auth.{up,down}.sql` 成对。
运行：`python3 - <<'PY'
import re,os
f='migrations'
ups=sorted(x for x in os.listdir(f) if x.endswith('.up.sql'))
assert ups==['000001_init.up.sql','000002_seed_auth.up.sql'], ups
print('迁移序号成对且有序:', ups)
PY`
预期：打印 `迁移序号成对且有序: [...]`（python3 本机可用）。

> 真连库执行 `migrate.Up` 由任务 14 的 compose/CI 冒烟覆盖（本机无 Docker 标 BLOCKED）；单测层用 `ARK_TEST_DATABASE_URL` 门控，见任务 9–11。

- [ ] **步骤 4：Commit**

```bash
git add backend-go/migrations/000002_seed_auth.up.sql backend-go/migrations/000002_seed_auth.down.sql
git commit -m "feat(migrations): 000002 角色与演示用户真实 bcrypt 种子"
```

---

## 任务 3：新增模块 U 契约 `12-用户与权限-U.openapi.yaml`

契约是唯一真源：Go 运行期 `oapi.LoadDir` 读它做 passthrough，前端 mock `?raw` 读前端副本，合规测试（任务 4）从它抽 schema。M0 仅对 P 跑 oapi-codegen 生成 DTO；**U 本轮不需要生成 Go 类型**（handler 沿用 `map[string]any`，与 P 一致），只补 YAML + 前端同步。

**文件：**
- 创建：`design/12-用户与权限-U.openapi.yaml`
- 创建（cp 同步）：`frontend/src/api/schema/12-用户与权限-U.openapi.yaml`
- 修改：`frontend/src/api/schema/index.ts`（`MODULE_CODES` 增 `'12':'U'`）

- [ ] **步骤 1：写契约**

`design/12-用户与权限-U.openapi.yaml`（components 复用 P 模块同款 `ApiResponse/PageResult/parameters/responses/securitySchemes`；实体 `User`（无 password_hash）/`Role`/`MeResponse`/`LoginResult`；列表用 P 已验证的 `allOf:[ApiResponse,{data: allOf:[PageResult,{list:items User}]}]` 组合姿势）：

```yaml
openapi: 3.0.3
info:
  title: 科研管理系统 · 12 用户与权限 API（模块 U）
  version: "1.0.0"
  description: >-
    用户/角色/权限垂直 REST 契约。统一响应包裹 ApiResponse{code,message,data,traceId,timestamp}；
    分页 PageResult{list,total,page,size}；认证 Bearer JWT；写方法支持 Idempotency-Key。
    实体字段名与 DDL 列名一致（snake_case），但 password_hash 绝不出现在任何响应。
    授权由服务端 Casbin（RBAC）+ 数据域（ABAC：tenant_id/legal_entity_id/security_level）双重把关。
servers:
  - url: https://{host}/api/v1
    variables:
      host: { default: api.institute.example.com }
tags:
  - { name: auth,      description: 登录与当前用户能力（/auth/login、/auth/me） }
  - { name: user,      description: 用户 CRUD 与状态（仅 R-ADMIN 可写） }
  - { name: role,      description: 角色目录与用户授权 }
security:
  - bearerAuth: []
paths:
  /auth/login:
    post:
      tags: [auth]
      summary: 账号密码登录（bcrypt 校验，签发带数据域的 JWT）
      operationId: login
      security: []
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: '#/components/schemas/LoginRequest' }
      responses:
        '200':
          description: 登录成功
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/LoginResult' }
        '401': { $ref: '#/components/responses/Unauthorized' }
  /auth/me:
    get:
      tags: [auth]
      summary: 当前用户 + 角色 + 能力集合（前端按钮级鉴权依据）
      operationId: getMe
      responses:
        '200':
          description: 当前身份能力
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/MeResponse' }
        '401': { $ref: '#/components/responses/Unauthorized' }
  /admin/users:
    get:
      tags: [user]
      summary: 用户列表（租户隔离 + 分页 + 状态/关键词筛选）
      operationId: listUsers
      parameters:
        - { name: status, in: query, schema: { type: string, enum: [ACTIVE, LOCKED, DISABLED] } }
        - { name: keyword, in: query, description: 匹配 username/real_name/email, schema: { type: string } }
        - $ref: '#/components/parameters/Page'
        - $ref: '#/components/parameters/Size'
      responses:
        '200':
          description: 分页用户列表
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data:
                        allOf:
                          - $ref: '#/components/schemas/PageResult'
                          - type: object
                            properties:
                              list: { type: array, items: { $ref: '#/components/schemas/User' } }
        '401': { $ref: '#/components/responses/Unauthorized' }
        '403': { $ref: '#/components/responses/Forbidden' }
    post:
      tags: [user]
      summary: 新建用户（写 password_hash=bcrypt，绑定 roles）
      operationId: createUser
      parameters: [ { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: '#/components/schemas/UserRequest' }
      responses:
        '200':
          description: 创建后的用户
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/User' }
        '400': { $ref: '#/components/responses/BadRequest' }
        '403': { $ref: '#/components/responses/Forbidden' }
        '409': { $ref: '#/components/responses/Conflict' }
  /admin/users/{id}:
    get:
      tags: [user]
      summary: 用户详情
      operationId: getUser
      parameters: [ { $ref: '#/components/parameters/PathId' } ]
      responses:
        '200':
          description: 用户详情
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/User' }
        '404': { $ref: '#/components/responses/NotFound' }
    put:
      tags: [user]
      summary: 更新用户资料/状态（password 可选：给出即重设）
      operationId: updateUser
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: '#/components/schemas/UserUpdateRequest' }
      responses:
        '200':
          description: 更新后的用户
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/User' }
        '400': { $ref: '#/components/responses/BadRequest' }
        '403': { $ref: '#/components/responses/Forbidden' }
        '404': { $ref: '#/components/responses/NotFound' }
    delete:
      tags: [user]
      summary: 停用（软删 deleted=1，status→DISABLED）
      operationId: deleteUser
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      responses:
        '200':
          description: 操作结果
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { type: object, properties: { id: { type: integer, format: int64 }, deleted: { type: boolean } } }
        '404': { $ref: '#/components/responses/NotFound' }
  /admin/roles:
    get:
      tags: [role]
      summary: 角色目录（本租户）
      operationId: listRoles
      responses:
        '200':
          description: 角色列表
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data:
                        type: object
                        properties:
                          list: { type: array, items: { $ref: '#/components/schemas/Role' } }
  /admin/users/{id}/roles:
    post:
      tags: [role]
      summary: 给用户授予角色
      operationId: assignRole
      parameters: [ { $ref: '#/components/parameters/PathId' }, { $ref: '#/components/parameters/IdempotencyKey' } ]
      requestBody:
        required: true
        content:
          application/json:
            schema: { type: object, required: [role_id], properties: { role_id: { type: integer, format: int64 } } }
      responses:
        '200':
          description: 授权后的用户
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/User' }
        '403': { $ref: '#/components/responses/Forbidden' }
        '409': { $ref: '#/components/responses/Conflict' }
  /admin/users/{userId}/roles/{roleId}:
    delete:
      tags: [role]
      summary: 撤销用户的某角色
      operationId: revokeRole
      parameters:
        - { name: userId, in: path, required: true, schema: { type: integer, format: int64 } }
        - { name: roleId, in: path, required: true, schema: { type: integer, format: int64 } }
        - { $ref: '#/components/parameters/IdempotencyKey' }
      responses:
        '200':
          description: 撤销后的用户
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ApiResponse'
                  - type: object
                    properties:
                      data: { $ref: '#/components/schemas/User' }
        '404': { $ref: '#/components/responses/NotFound' }
components:
  securitySchemes:
    bearerAuth: { type: http, scheme: bearer, bearerFormat: JWT }
  parameters:
    IdempotencyKey: { name: Idempotency-Key, in: header, required: false, schema: { type: string } }
    Page: { name: page, in: query, required: false, schema: { type: integer, minimum: 1, default: 1 } }
    Size: { name: size, in: query, required: false, schema: { type: integer, minimum: 1, maximum: 200, default: 20 } }
    PathId: { name: id, in: path, required: true, schema: { type: integer, format: int64 } }
  responses:
    BadRequest:
      description: 参数校验失败（40001）
      content: { application/json: { schema: { $ref: '#/components/schemas/ApiResponse' } } }
    Unauthorized:
      description: 未认证（40101/40102）
      content: { application/json: { schema: { $ref: '#/components/schemas/ApiResponse' } } }
    Forbidden:
      description: 越权（40301）
      content: { application/json: { schema: { $ref: '#/components/schemas/ApiResponse' } } }
    NotFound:
      description: 不存在（40401）
      content: { application/json: { schema: { $ref: '#/components/schemas/ApiResponse' } } }
    Conflict:
      description: 冲突（40901 用户名重复；40902 角色已授予）
      content: { application/json: { schema: { $ref: '#/components/schemas/ApiResponse' } } }
  schemas:
    ApiResponse:
      type: object
      required: [code, message, traceId, timestamp]
      properties:
        code:      { type: integer }
        message:   { type: string }
        data:      { nullable: true }
        traceId:   { type: string }
        timestamp: { type: integer, format: int64 }
    PageResult:
      type: object
      properties:
        list:  { type: array, items: { type: object } }
        total: { type: integer, format: int64 }
        page:  { type: integer }
        size:  { type: integer }
    LoginRequest:
      type: object
      required: [username, password]
      properties:
        username: { type: string }
        password: { type: string }
        tenant_id: { type: integer, format: int64, nullable: true, description: 缺省 1（M0 单租户演示） }
    LoginResult:
      type: object
      properties:
        token_type:   { type: string, example: Bearer }
        access_token: { type: string }
        expires_in:   { type: integer, format: int64 }
    User:
      type: object
      description: 对外用户形状（DDL sys_user，剔除 password_hash，附 roles[]）。
      properties:
        id:                { type: integer, format: int64 }
        username:          { type: string }
        real_name:         { type: string }
        email:             { type: string, nullable: true }
        phone:             { type: string, nullable: true }
        staff_no:          { type: string, nullable: true }
        employment_status: { type: string, enum: [ONBOARD, RESIGNED, RETIRED, VISITING, GUEST, REHIRE] }
        security_level:    { type: string, enum: [PUBLIC, INTERNAL, SECRET, TOP_SECRET] }
        status:            { type: string, enum: [ACTIVE, LOCKED, DISABLED] }
        tenant_id:         { type: integer, format: int64 }
        legal_entity_id:   { type: integer, format: int64, nullable: true }
        roles:             { type: array, items: { type: string } }
        created_at:        { type: string, format: date-time }
        updated_at:        { type: string, format: date-time }
    UserRequest:
      type: object
      required: [username, real_name, password]
      properties:
        username:          { type: string }
        real_name:         { type: string }
        password:          { type: string, description: 明文，服务端 bcrypt 后落 password_hash }
        email:             { type: string, nullable: true }
        phone:             { type: string, nullable: true }
        staff_no:          { type: string, nullable: true }
        security_level:    { type: string, enum: [PUBLIC, INTERNAL, SECRET, TOP_SECRET] }
        employment_status: { type: string, enum: [ONBOARD, RESIGNED, RETIRED, VISITING, GUEST, REHIRE] }
        roles:             { type: array, items: { type: string }, description: 角色码 R-* 列表 }
    UserUpdateRequest:
      type: object
      properties:
        real_name:      { type: string }
        email:          { type: string, nullable: true }
        phone:          { type: string, nullable: true }
        security_level: { type: string, enum: [PUBLIC, INTERNAL, SECRET, TOP_SECRET] }
        status:         { type: string, enum: [ACTIVE, LOCKED, DISABLED] }
        password:       { type: string, nullable: true, description: 给出即重设口令 }
    Role:
      type: object
      properties:
        id:        { type: integer, format: int64 }
        code:      { type: string }
        name:      { type: string }
        is_builtin: { type: boolean }
        tenant_id: { type: integer, format: int64 }
    MeResponse:
      type: object
      properties:
        user:  { $ref: '#/components/schemas/User' }
        roles: { type: array, items: { type: string } }
        caps:  { type: array, items: { type: string }, description: '"<pathTemplate> <METHOD>"，源自 Casbin policy 命中角色' }
```

- [ ] **步骤 2：YAML 合法性自检**

运行：`cd "D:\SynologyDrive\traecode-workspace\science-research-project" && python3 -c "import yaml; d=yaml.safe_load(open('design/12-用户与权限-U.openapi.yaml',encoding='utf-8')); print('paths:',len(d['paths']),'schemas:',len(d['components']['schemas']))"`
预期：`paths: 7 schemas: 9`。

- [ ] **步骤 3：cp 同步到前端 schema 目录（两套契约必须一致）**

运行：`cp "design/12-用户与权限-U.openapi.yaml" "frontend/src/api/schema/12-用户与权限-U.openapi.yaml"`（仓库根执行）。

- [ ] **步骤 4：前端 MODULE_CODES 登记 U**

编辑 `frontend/src/api/schema/index.ts`：
```ts
const MODULE_CODES: Record<string, string> = {
  '01': 'P', '02': 'E', '03': 'F', '04': 'R', '05': 'T', '06': 'C',
  '07': 'S', '08': 'D', '09': 'G', '10': 'A', '11': 'X', '12': 'U',
}
```

- [ ] **步骤 5：前端契约索引自检**

运行：`cd frontend && npm run typecheck`
预期：`vue-tsc --noEmit` 通过（glob 新增 yaml 不破坏类型；`moduleCodeFromFile` 现能识别 12→U）。

- [ ] **步骤 6：Commit**

```bash
git add design/12-用户与权限-U.openapi.yaml frontend/src/api/schema/12-用户与权限-U.openapi.yaml frontend/src/api/schema/index.ts
git commit -m "feat(contract): 新增模块 U 用户与权限契约并同步前端"
```

- [ ] **步骤 7（执行期发现的计划缺口，必须补）：去硬编码 `TestSpec_LoadCounts` 的文档份数**

新增第 12 份 `design/12-*.openapi.yaml` 会让既有 `backend-go/internal/platform/oapi/spec_test.go` 里 `if len(s.Docs) != 11` 的硬编码断言转红（实际 12）。修法＝不硬编码份数，改为按 design 目录里 `*.openapi.yaml` 的真实文件数断言（对未来再加模块也免疫）：给 `spec_test.go` 的 import 加 `"path/filepath"`，把 `TestSpec_LoadCounts` 内的 `len(s.Docs) != 11` 换成「`os.ReadDir(designDir())` 统计以 `.openapi.yaml` 结尾的文件数 `want`，断言 `len(s.Docs) == want` 且 `want>0`」。运行 `cd backend-go && go test ./internal/platform/oapi/ -run TestSpec_LoadCounts -v` → PASS（docs=12）。Commit：

```bash
git add backend-go/internal/platform/oapi/spec_test.go
git commit -m "test(oapi): LoadCounts 去硬编码份数,按 design/*.openapi.yaml 实际数断言(容第12模块U)"
```

---

## 任务 4：模块 U 契约的纯静态合规测试（无 DB）

沿用 P `contract_test.go` 的 `oapi.Validate/ResolveDataSchema` 主干：从 design 抽 `GET /admin/users` 与 `GET /auth/me` 的 data schema，喂合成 data 断言放行、类型漂移断言被拒。此测试**不需要数据库**，是 CI 快路径的一部分。

**文件：**
- 创建：`backend-go/internal/modules/sysadmin/contract_test.go`

- [ ] **步骤 1：写测试**

`backend-go/internal/modules/sysadmin/contract_test.go`：

```go
package sysadmin

import (
	"os"
	"testing"

	"github.com/eplugger/ark/internal/platform/oapi"
)

// mustSpec 从仓库根 design/ 加载契约。测试工作目录 = backend-go/internal/modules/sysadmin，
// 上溯 4 级到仓库根，故 ../../../../design；DESIGN_DIR 可覆盖。
func mustSpec(t *testing.T) *oapi.Spec {
	d := os.Getenv("DESIGN_DIR")
	if d == "" {
		d = "../../../../design"
	}
	s, err := oapi.LoadDir(d)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func TestContract_ListUsers_ShapeValidated(t *testing.T) {
	spec := mustSpec(t)
	op := spec.Find("GET", "/admin/users")
	if op == nil {
		t.Fatal("未找到 GET /admin/users")
	}
	schema := oapi.ResolveDataSchema(op)
	good := map[string]any{
		"list": []any{
			map[string]any{
				"id": 1, "username": "admin", "real_name": "系统管理员",
				"status": "ACTIVE", "security_level": "TOP_SECRET", "roles": []any{"R-ADMIN"},
			},
		},
		"total": 1, "page": 1, "size": 20,
	}
	if errs := oapi.Validate(good, schema); len(errs) > 0 {
		t.Fatalf("合规 data 被误判: %v", errs)
	}
	// 类型漂移：total 应为整型，给字符串必须被拒
	bad := map[string]any{}
	for k, v := range good {
		bad[k] = v
	}
	bad["total"] = "一"
	if errs := oapi.Validate(bad, schema); len(errs) == 0 {
		t.Fatal("类型漂移(total: string)未被捕获")
	}
}

func TestContract_Me_CapsArrayValidated(t *testing.T) {
	spec := mustSpec(t)
	op := spec.Find("GET", "/auth/me")
	if op == nil {
		t.Fatal("未找到 GET /auth/me")
	}
	schema := oapi.ResolveDataSchema(op)
	good := map[string]any{
		"user":  map[string]any{"id": 1, "username": "admin", "status": "ACTIVE"},
		"roles": []any{"R-ADMIN"},
		"caps":  []any{"/api/v1/admin/users GET", "/api/v1/admin/users POST"},
	}
	if errs := oapi.Validate(good, schema); len(errs) > 0 {
		t.Fatalf("/auth/me 合规 data 被误判: %v", errs)
	}
}
```

- [ ] **步骤 2：运行确认包存在但缺实现即失败**

运行：`cd backend-go && go test ./internal/modules/sysadmin/ -run TestContract -v`
预期：PASS（此测试只依赖契约与已有 `oapi.Validate/ResolveDataSchema`，不依赖未实现 handler）。若 `oapi.Validate`/`ResolveDataSchema` 尚未导出，说明 M0 已有——本任务只新增测试文件；如编译报缺符号，先确认 M0 的 `internal/platform/oapi` 已提供这两个导出（P `contract_test.go` 已在用）。

- [ ] **步骤 3：Commit**

```bash
git add backend-go/internal/modules/sysadmin/contract_test.go
git commit -m "test(go): U 契约纯静态合规守卫(listUsers/me)"
```

---

## Part B — sqlc 类型安全仓储

## 任务 5：sqlc 第二生成块（sys_user / sys_role / sys_user_role 查询）

沿用 M0 已验证的"裁剪 schema + 独立 queries 目录 + 独立生成块"姿势（全量迁移会让 sqlc v1.27 wazero 解析器崩，P 块已如此规避）。第二块输出到 `sysstore` 包，与 P 的 `store` 包并存、互不冲突。读查询用 `SELECT *`（列与表一致→sqlc 直接返回模型类型，免生成 Row 结构），写查询用 `RETURNING *`。

**文件：**
- 创建：`backend-go/db/schema/sys_schema.sql`
- 创建：`backend-go/db/query_sys/sys_user.sql`
- 创建：`backend-go/db/query_sys/sys_role.sql`
- 创建：`backend-go/db/query_sys/sys_user_role.sql`
- 修改：`backend-go/sqlc.yaml`（追加第二个 postgresql 生成块）

- [ ] **步骤 1：写裁剪 schema**

`backend-go/db/schema/sys_schema.sql`（三表原样摘自 `migrations/000001_init.up.sql`，含任务 1 新加的 `password_hash`；与线上同构）：

```sql
-- 裁剪 schema：仅 U 仓储所需 sys_user(+password_hash)/sys_role/sys_user_role。
-- 原因同 P：sqlc v1.27.0 的 wazero 解析器无法处理完整拼接迁移。列定义与 000001 一致。
CREATE TABLE sys_role (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code         VARCHAR(32) NOT NULL,
  name         VARCHAR(64) NOT NULL,
  is_builtin   BOOLEAN     NOT NULL DEFAULT TRUE,
  tenant_id    BIGINT      NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sys_user (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  username        VARCHAR(64)  NOT NULL,
  real_name       VARCHAR(64)  NOT NULL,
  email           VARCHAR(128),
  phone           VARCHAR(32),
  staff_no        VARCHAR(64),
  employment_status VARCHAR(16) NOT NULL DEFAULT 'ONBOARD'
                  CHECK (employment_status IN ('ONBOARD','RESIGNED','RETIRED','VISITING','GUEST','REHIRE')),
  security_level  VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                  CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  status          VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                  CHECK (status IN ('ACTIVE','LOCKED','DISABLED')),
  password_hash   VARCHAR(100),
  tenant_id       BIGINT       NOT NULL,
  legal_entity_id BIGINT,
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  creator_id      BIGINT       NOT NULL,
  modifier_id     BIGINT,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT
);

CREATE TABLE sys_user_role (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES sys_user(id),
  role_id    BIGINT NOT NULL REFERENCES sys_role(id),
  tenant_id  BIGINT NOT NULL,
  granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ
);
```

- [ ] **步骤 2：写用户查询**

`backend-go/db/query_sys/sys_user.sql`：

```sql
-- name: GetUserByUsername :one
SELECT * FROM sys_user
WHERE username = $1 AND tenant_id = $2 AND deleted = 0
LIMIT 1;

-- name: GetUser :one
SELECT * FROM sys_user
WHERE id = $1 AND tenant_id = $2 AND deleted = 0;

-- name: ListUsers :many
SELECT * FROM sys_user
WHERE deleted = 0
  AND tenant_id = @tenant_id
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('keyword')::text IS NULL
       OR username   ILIKE sqlc.narg('keyword')
       OR real_name  ILIKE sqlc.narg('keyword')
       OR email      ILIKE sqlc.narg('keyword'))
ORDER BY id DESC
LIMIT @limit_ OFFSET @offset_;

-- name: CountUsers :one
SELECT count(*)::int AS n
FROM sys_user
WHERE deleted = 0
  AND tenant_id = @tenant_id
  AND (sqlc.narg('status')::text IS NULL OR status = sqlc.narg('status')::text)
  AND (sqlc.narg('keyword')::text IS NULL
       OR username   ILIKE sqlc.narg('keyword')
       OR real_name  ILIKE sqlc.narg('keyword')
       OR email      ILIKE sqlc.narg('keyword'));

-- name: CreateUser :one
INSERT INTO sys_user (
  username, real_name, password_hash, email, phone, staff_no,
  employment_status, security_level, status, tenant_id, legal_entity_id, creator_id
) VALUES (
  $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
)
RETURNING *;

-- name: UpdateUser :one
UPDATE sys_user SET
  real_name      = $3,
  email          = $4,
  phone          = $5,
  security_level = $6,
  status         = $7,
  updated_at     = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0
RETURNING *;

-- name: UpdateUserPassword :exec
UPDATE sys_user SET password_hash = $3, updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0;

-- name: SoftDeleteUser :exec
UPDATE sys_user SET deleted = 1, status = 'DISABLED', updated_at = now()
WHERE id = $1 AND tenant_id = $2 AND deleted = 0;
```

- [ ] **步骤 3：写角色查询**

`backend-go/db/query_sys/sys_role.sql`：

```sql
-- name: ListRoles :many
SELECT id, code, name, is_builtin, tenant_id, created_at, updated_at
FROM sys_role WHERE tenant_id = $1 ORDER BY id;

-- name: ListRoleCodesByUser :many
SELECT r.code
FROM sys_role r JOIN sys_user_role ur ON ur.role_id = r.id
WHERE ur.user_id = $1
  AND (ur.expires_at IS NULL OR ur.expires_at > now());

-- name: ListRoleIDsByUser :many
SELECT ur.role_id FROM sys_user_role ur WHERE ur.user_id = $1;
```

- [ ] **步骤 4：写用户—角色授权查询**

`backend-go/db/query_sys/sys_user_role.sql`：

```sql
-- name: AssignRole :exec
INSERT INTO sys_user_role (user_id, role_id, tenant_id)
VALUES ($1, $2, $3)
ON CONFLICT (user_id, role_id) DO NOTHING;

-- name: RevokeRole :exec
DELETE FROM sys_user_role WHERE user_id = $1 AND role_id = $2 AND tenant_id = $3;
```

- [ ] **步骤 5：sqlc.yaml 追加第二块**

在 `backend-go/sqlc.yaml` 现有 P 块之后（同一 `sql:` 列表内）追加：

```yaml
  - engine: "postgresql"
    # 第二生成块：U 仓储。独立 schema/queries/out，与 P 块并存；package=sysstore。
    schema: "db/schema/sys_schema.sql"
    queries: "db/query_sys"
    gen:
      go:
        package: "sysstore"
        out: "internal/modules/sysadmin/store"
        sql_package: "pgx/v5"
        emit_json_tags: true
        emit_pointers_for_null_types: true
        rename:
          sys_user: SysUser
          sys_role: SysRole
          sys_user_role: SysUserRole
          "@limit_": Limit
          "@offset_": Offset
        overrides:
          - column: "sys_user.created_at"
            go_type: "time.Time"
          - column: "sys_user.updated_at"
            go_type: "time.Time"
          - column: "sys_user.legal_entity_id"
            go_type:
              type: "int64"
              pointer: true
          - column: "sys_user.modifier_id"
            go_type:
              type: "int64"
              pointer: true
          - column: "sys_role.created_at"
            go_type: "time.Time"
          - column: "sys_role.updated_at"
            go_type: "time.Time"
          - column: "sys_user_role.granted_at"
            go_type: "time.Time"
          - column: "sys_user_role.expires_at"
            go_type:
              type: "time.Time"
              pointer: true
```

> `emit_pointers_for_null_types: true` 已把可空列给指针类型；上面 `legal_entity_id`/`modifier_id`/`expires_at` 的显式 override 是**双保险 + 文档意图**（`int64*`/`time.Time*`）。`password_hash/email/phone/staff_no/remark` 可空→`*string` 由该开关自动给出，不覆盖。

- [ ] **步骤 6：Commit（源查询，产物在任务 6 生成后再传）**

```bash
git add backend-go/db/schema/sys_schema.sql backend-go/db/query_sys backend-go/sqlc.yaml
git commit -m "feat(go): sqlc 第二生成块 sys_* 仓储定义"
```

---

## 任务 6：生成 sysstore DAL 并校验编译 + 钉漂移守卫

跑 sqlc（必须 `GOTOOLCHAIN=go1.23.4`）产出 `internal/modules/sysadmin/store/`，验证生成的类型/参数结构可编译，并把新产物纳入 `make drift` 监视，防后续源改而产物未更新。

**文件：**
- 生成：`backend-go/internal/modules/sysadmin/store/`（sys_user.sql.go / sys_role.sql.go / sys_user_role.sql.go / models.go / db.go）
- 创建：`backend-go/internal/modules/sysadmin/store/compile_test.go`
- 修改：`backend-go/Makefile`（`drift` 目标 `git diff --exit-code` 路径增补 `internal/modules/sysadmin/store`）

- [ ] **步骤 1：生成**

运行（git-bash 前缀传环境变量）：
```bash
cd backend-go && GOTOOLCHAIN=go1.23.4 go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate
```
预期：无输出/无报错即成功；`ls internal/modules/sysadmin/store/` 见生成文件。

- [ ] **步骤 2：校验产物可编译**

运行：`cd backend-go && go build ./internal/modules/sysadmin/store/`
预期：无错误。
抽查签名：`cd backend-go && grep -n "func (q \*Queries) ListUsers\|type ListUsersParams\|type CreateUserParams\|PasswordHash" internal/modules/sysadmin/store/*.go`
预期：`ListUsersParams` 含 `Status *string / Keyword *string / Limit int32 / Offset int32 / TenantID int64`；`SysUser` 含 `PasswordHash *string`；`CreateUserParams` 含 12 入参。

- [ ] **步骤 3：写无 DB 的编译守卫测试**

`backend-go/internal/modules/sysadmin/store/compile_test.go`（仅强制引用生成符号，确保形状稳定；不连库）：

```go
package sysstore

import (
	"context"
	"testing"
)

// TestGeneratedShape_Compiles 钉住关键模型/参数结构的存在与字段类型，
// 若 sqlc 生成形状漂移（改名/改类型）此断言先于业务层失败，报错更定位。
func TestGeneratedShape_Compiles(t *testing.T) {
	var u SysUser
	var ph *string = u.PasswordHash
	_ = ph
	var _ int64 = u.ID
	var _ *int64 = u.LegalEntityID

	var lp ListUsersParams
	var _ *string = lp.Status
	var _ *string = lp.Keyword
	var _ int32 = lp.Limit
	var _ int64 = lp.TenantID

	// Queries 构造（nil pool 不连库，仅证明类型存在且方法签名就位）
	var q *Queries
	_ = q
	_ = context.Background
	_ = func() { _, _ = (&Queries{}).GetUserByUsername(context.Background(), GetUserByUsernameParams{}) }
}
```

- [ ] **步骤 4：运行守卫**

运行：`cd backend-go && go test ./internal/modules/sysadmin/store/ -run TestGeneratedShape -v`
预期：PASS（若字段名/类型不符则编译失败——据此校正查询）。

- [ ] **步骤 5：把新产物纳入漂移守卫**

编辑 `backend-go/Makefile` 的 `drift` 目标，在 `git diff --exit-code --` 后追加路径 `internal/modules/sysadmin/store`：

原：
```make
	git diff --exit-code -- internal/modules/p/store api/gen migrations/000001_init.up.sql migrations/000001_init.down.sql \
```
改为：
```make
	git diff --exit-code -- internal/modules/p/store internal/modules/sysadmin/store api/gen migrations/000001_init.up.sql migrations/000001_init.down.sql \
```

- [ ] **步骤 6：Commit**

```bash
git add backend-go/internal/modules/sysadmin/store backend-go/Makefile
git commit -m "chore(go): 生成 sysstore DAL 并纳入 drift 守卫"
```

---

## Part C — bcrypt 真实登录 + 能力派生

## 任务 7：bcrypt 真实登录（保留 dev 回退，零回归）

把 `auth.HandleLogin` 升级为 `auth.NewLoginHandler(secret, ttl, reader)`。`reader==nil`（无库单测/compose 冒烟）仍走内置 `ark/ark`，保证 M0 既有 router 单测不破；`reader!=nil` 经 `auth.UserReader` 接口取回用户身份（存储细节留在 sysadmin 模块，避免 platform→module 反向依赖），用 bcrypt 校验、命中即签发**真实数据域** JWT。登录路由**始终公开**（不进鉴权中间件）。

**文件：**
- 修改：`backend-go/internal/platform/auth/login.go`（`HandleLogin` → `NewLoginHandler` + `UserReader`/`LoginUser`）
- 创建：`backend-go/internal/modules/sysadmin/authreader.go`（`AuthReader` 实现 `auth.UserReader`）
- 修改：`backend-go/internal/router.go`（`RouterDeps` 增 `LoginReader auth.UserReader`；登录路由改 `NewLoginHandler`）
- 修改：`backend-go/cmd/server/main.go`（pool 存在时注入 `sysadmin.NewAuthReader(pool)`）
- 创建：`backend-go/internal/platform/auth/login_test.go`

- [ ] **步骤 1：写失败的测试（dev 回退 + bcrypt 命中/拒绝，均无 DB）**

`backend-go/internal/platform/auth/login_test.go`：

```go
package auth

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"golang.org/x/crypto/bcrypt"
)

// stubReader 实现 UserReader；返回带真实 bcrypt 哈希的 admin 身份，或按 username 返回不同态。
type stubReader struct{ hash string }

func (s stubReader) FindForLogin(_ context.Context, username string, _ int64) (*LoginUser, error) {
	switch username {
	case "admin":
		return &LoginUser{UserID: 1, TenantID: 1, LegalEntityID: 0,
			SecurityLevel: "TOP_SECRET", PasswordHash: s.hash, Roles: []string{"R-ADMIN"}, Active: true}, nil
	case "ghost":
		return nil, nil // 用户不存在
	case "disabled":
		return &LoginUser{UserID: 9, TenantID: 1, PasswordHash: s.hash, Active: false}, nil
	default:
		return &LoginUser{PasswordHash: ""}, nil // 无口令账号
	}
}

func postLogin(handler gin.HandlerFunc, body string) *httptest.ResponseRecorder {
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.POST("/api/v1/auth/login", handler)
	w := httptest.NewRecorder()
	r := httptest.NewRequest("POST", "/api/v1/auth/login", nil)
	r.Header.Set("Content-Type", "application/json")
	r.Body = nopCloserString(body)
	e.ServeHTTP(w, r)
	return w
}

func TestLogin_DevFallback(t *testing.T) {
	w := postLogin(NewLoginHandler("s3cr3t", 3600, nil), `{"username":"ark","password":"ark"}`)
	if w.Code != 200 {
		t.Fatalf("dev ark/ark 应 200，实得 %d body=%s", w.Code, w.Body.String())
	}
	w2 := postLogin(NewLoginHandler("s3cr3t", 3600, nil), `{"username":"ark","password":"wrong"}`)
	if w2.Code != 401 {
		t.Fatalf("dev 错口令应 401，实得 %d", w2.Code)
	}
}

func TestLogin_BcryptOK(t *testing.T) {
	h, _ := bcrypt.GenerateFromPassword([]byte("Admin@123456"), bcrypt.DefaultCost)
	r := stubReader{hash: string(h)}
	w := postLogin(NewLoginHandler("s3cr3t", 3600, r), `{"username":"admin","password":"Admin@123456"}`)
	if w.Code != 200 {
		t.Fatalf("bcrypt 正确口令应 200，实得 %d body=%s", w.Code, w.Body.String())
	}
	var env struct {
		Code int    `json:"code"`
		Data struct {
			AccessToken string `json:"access_token"`
			TokenType   string `json:"token_type"`
		} `json:"data"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	if env.Data.AccessToken == "" || env.Data.TokenType != "Bearer" {
		t.Fatalf("未签发令牌: %+v", env.Data)
	}
	// 校验签发的 Claims 带真实数据域
	claims, err := ParseToken("s3cr3t", env.Data.AccessToken)
	if err != nil {
		t.Fatal(err)
	}
	if claims.UserID != 1 || claims.SecurityLevel != "TOP_SECRET" || !contains(claims.Roles, "R-ADMIN") {
		t.Fatalf("Claims 数据域错误: %+v", claims)
	}
}

func TestLogin_BcryptReject(t *testing.T) {
	h, _ := bcrypt.GenerateFromPassword([]byte("Admin@123456"), bcrypt.DefaultCost)
	r := stubReader{hash: string(h)}
	for _, tc := range []struct{ name, body string }{
		{"错口令", `{"username":"admin","password":"nope"}`},
		{"不存在", `{"username":"ghost","password":"x"}`},
		{"无口令账号", `{"username":"nopass","password":"x"}`},
	} {
		w := postLogin(NewLoginHandler("s3cr3t", 3600, r), tc.body)
		if w.Code != 401 {
			t.Fatalf("%s 应 401，实得 %d", tc.name, w.Code)
		}
	}
	// 停用账号 → 403
	w := postLogin(NewLoginHandler("s3cr3t", 3600, r), `{"username":"disabled","password":"Admin@123456"}`)
	if w.Code != 403 {
		t.Fatalf("停用账号应 403，实得 %d", w.Code)
	}
}

func contains(xs []string, v string) bool {
	for _, x := range xs {
		if x == v {
			return true
		}
	}
	return false
}
```

- [ ] **步骤 2：运行确认失败**

运行：`cd backend-go && go test ./internal/platform/auth/ -run TestLogin -v`
预期：编译失败 `undefined: NewLoginHandler`、`undefined: UserReader`（旧 `HandleLogin` 无 reader 参数）。

- [ ] **步骤 3：重写 login.go**

`backend-go/internal/platform/auth/login.go` 全文替换为：

```go
package auth

import (
	"context"
	"net/http"

	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"golang.org/x/crypto/bcrypt"
)

// LoginUser 是登录所需的用户身份快照，由模块层仓储适配器（sysadmin.AuthReader）组装。
type LoginUser struct {
	UserID        int64
	TenantID      int64
	LegalEntityID int64
	SecurityLevel string
	PasswordHash  string // 空串=无口令账号，一律拒登
	Roles         []string
	Active        bool // status==ACTIVE
}

// UserReader 把"按用户名+租户取登录身份"的存储细节留在模块层；auth 只依赖此接口，无 platform→module 反向依赖。
type UserReader interface {
	FindForLogin(ctx context.Context, username string, tenantID int64) (*LoginUser, error)
}

// NewLoginHandler 登录。reader==nil：内置 ark/ark dev 回退（M0 无库单测/compose 冒烟，零回归）。
// reader!=nil：bcrypt 校验 sys_user.password_hash，命中签发真实数据域 JWT。路由始终公开。
func NewLoginHandler(secret string, ttl int64, reader UserReader) gin.HandlerFunc {
	return func(c *gin.Context) {
		var body struct {
			Username string `json:"username" binding:"required"`
			Password string `json:"password" binding:"required"`
			TenantID *int64 `json:"tenant_id"`
		}
		if err := c.ShouldBindJSON(&body); err != nil {
			httpx.WriteErr(c, http.StatusBadRequest, 40001, "用户名/密码必填")
			return
		}

		if reader == nil {
			if body.Username != "ark" || body.Password != "ark" {
				httpx.WriteErr(c, http.StatusUnauthorized, 40102, "账号或密码错误")
				return
			}
			issue(c, secret, ttl, Claims{
				UserID: 1, TenantID: 1, LegalEntityID: 0,
				SecurityLevel: "INTERNAL", Roles: []string{"R-STAFF", "R-MANAGER"},
			})
			return
		}

		tid := int64(1)
		if body.TenantID != nil {
			tid = *body.TenantID
		}
		u, err := reader.FindForLogin(c.Request.Context(), body.Username, tid)
		// 统一失败码，避免用户名枚举；无口令账号同样拒登
		if err != nil || u == nil || u.PasswordHash == "" ||
			bcrypt.CompareHashAndPassword([]byte(u.PasswordHash), []byte(body.Password)) != nil {
			httpx.WriteErr(c, http.StatusUnauthorized, 40102, "账号或密码错误")
			return
		}
		if !u.Active {
			httpx.WriteErr(c, http.StatusForbidden, 40302, "账号已停用或锁定")
			return
		}
		issue(c, secret, ttl, Claims{
			UserID: u.UserID, TenantID: u.TenantID, LegalEntityID: u.LegalEntityID,
			SecurityLevel: u.SecurityLevel, Roles: u.Roles,
		})
	}
}

func issue(c *gin.Context, secret string, ttl int64, claims Claims) {
	tok, err := GenToken(secret, ttl, claims)
	if err != nil {
		httpx.WriteErr(c, http.StatusInternalServerError, 50001, "签发令牌失败")
		return
	}
	httpx.WriteOK(c, gin.H{"token_type": "Bearer", "access_token": tok, "expires_in": ttl})
}
```

在 `login_test.go` 内补 `nopCloserString` 小工具（放在测试文件末尾）：

```go
func nopCloserString(s string) io.ReadCloser {
	return io.NopCloser(strings.NewReader(s))
}
```
并在测试文件 import 块加 `"io"` 与 `"strings"`。

- [ ] **步骤 4：写 AuthReader（模块层实现 UserReader）**

`backend-go/internal/modules/sysadmin/authreader.go`：

```go
package sysadmin

import (
	"context"
	"errors"

	store "github.com/eplugger/ark/internal/modules/sysadmin/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// AuthReader 实现 auth.UserReader：从 sys_user(+password_hash)/sys_role/sys_user_role 组装登录身份。
type AuthReader struct{ q *store.Queries }

func NewAuthReader(pool *pgxpool.Pool) *AuthReader { return &AuthReader{q: store.New(pool)} }

func (a *AuthReader) FindForLogin(ctx context.Context, username string, tenantID int64) (*auth.LoginUser, error) {
	u, err := a.q.GetUserByUsername(ctx, store.GetUserByUsernameParams{Username: username, TenantID: tenantID})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	codes, err := a.q.ListRoleCodesByUser(ctx, u.ID)
	if err != nil {
		return nil, err
	}
	ph := ""
	if u.PasswordHash != nil {
		ph = *u.PasswordHash
	}
	le := int64(0)
	if u.LegalEntityID != nil {
		le = *u.LegalEntityID
	}
	return &auth.LoginUser{
		UserID: u.ID, TenantID: u.TenantID, LegalEntityID: le,
		SecurityLevel: u.SecurityLevel, PasswordHash: ph,
		Roles: codes, Active: u.Status == "ACTIVE",
	}, nil
}
```

> `store` 为 `sysstore` 包的导入别名——生成包名是 `sysstore`（目录 `internal/modules/sysadmin/store`），故显式 `store "…/sysadmin/store"` 以便与 P 的 `store` 阅读一致；亦可写作 `sysstore` 别名，二选一，本计划统一用 `store` 别名引用 sysstore。

- [ ] **步骤 5：接路由与装配**

`backend-go/internal/router.go`：`RouterDeps` 增字段：
```go
	LoginReader auth.UserReader // nil → 登录走 dev 回退；非 nil → bcrypt 真实登录
```
登录路由改为：
```go
	e.POST("/api/v1/auth/login", auth.NewLoginHandler(d.Cfg.JWTSecret, d.Cfg.JWTTTLSec, d.LoginReader))
```

`backend-go/cmd/server/main.go`：在构造 `RouterDeps` 前派生 reader，并填入：
```go
	var loginReader auth.UserReader
	if pool != nil {
		loginReader = sysadmin.NewAuthReader(pool)
	}
	// ...
	e := internal.Build(internal.RouterDeps{
		Logger:      l,
		Cfg:         cfg,
		Pool:        pool,
		Redis:       rdb,
		Enforcer:    enf,
		Spec:        spec,
		LoginReader: loginReader,
	})
```
import 块加 `"github.com/eplugger/ark/internal/modules/sysadmin"`。

- [ ] **步骤 6：运行测试确认通过**

运行：`cd backend-go && go test ./internal/platform/auth/ -run TestLogin -v`
预期：全部 PASS。
运行回归：`cd backend-go && go build ./... && go test ./internal/... -count=1`
预期：编译通过；既有 router 单测（用 `LoginReader: nil` 或未设）仍走 dev 回退、不破。

- [ ] **步骤 7：Commit**

```bash
git add backend-go/internal/platform/auth/login.go backend-go/internal/platform/auth/login_test.go backend-go/internal/modules/sysadmin/authreader.go backend-go/internal/router.go backend-go/cmd/server/main.go
git commit -m "feat(go): bcrypt 真实登录(UserReader+AuthReader)，保留 pool==nil dev 回退"
```

---

## 任务 8：从 Casbin 策略派生能力集合 `BuildCaps`

`/auth/me` 要回显当前用户的"按钮/操作级"能力。能力集合直接源于与服务端鉴权同款的 `policy.csv`——遍历 `Enforcer.GetPolicy()`，取角色命中的 `p` 规则拼成 `"<obj> <METHOD>"` 去重排序。platform 层实现，供 sysadmin handler（任务 9）与前端（任务 15/18）消费。

**文件：**
- 创建：`backend-go/internal/platform/auth/caps.go`
- 创建：`backend-go/internal/platform/auth/caps_test.go`

- [ ] **步骤 1：写失败的测试**

`backend-go/internal/platform/auth/caps_test.go`：

```go
package auth

import (
	"os"
	"testing"
)

func TestBuildCaps_FromPolicy(t *testing.T) {
	model := os.Getenv("ARK_AUTH_MODEL_PATH")
	if model == "" {
		model = "./model.conf"
	}
	pol := os.Getenv("ARK_AUTH_POLICY_PATH")
	if pol == "" {
		pol = "./policy.csv"
	}
	enf, err := NewEnforcer(model, pol)
	if err != nil {
		t.Fatal(err)
	}
	caps := BuildCaps(enf, []string{"R-ADMIN"})
	if len(caps) == 0 {
		t.Fatal("R-ADMIN 应至少命中若干策略")
	}
	set := map[string]bool{}
	for _, c := range caps {
		set[c] = true
	}
	if !set["/api/v1/* GET"] {
		t.Fatalf("缺 R-ADMIN GET 通配能力: %v", caps)
	}
	// 已排序 & 去重：不应有完全相同项
	for i := 1; i < len(caps); i++ {
		if caps[i] == caps[i-1] {
			t.Fatalf("能力未去重: %v", caps)
		}
	}
	// 未知角色 → 空能力
	if got := BuildCaps(enf, []string{"R-NOPE"}); len(got) != 0 {
		t.Fatalf("未知角色不应有能力: %v", got)
	}
	// nil enforcer → 空（防御）
	if got := BuildCaps(nil, []string{"R-ADMIN"}); len(got) != 0 {
		t.Fatal("nil enforcer 应返回空")
	}
}
```

- [ ] **步骤 2：运行确认失败**

运行：`cd backend-go && go test ./internal/platform/auth/ -run TestBuildCaps -v`
预期：编译失败 `undefined: BuildCaps`。

- [ ] **步骤 3：写实现**

`backend-go/internal/platform/auth/caps.go`：

```go
package auth

import (
	"sort"
	"strings"

	"github.com/casbin/casbin/v2"
)

// BuildCaps 依当前用户角色，从 Casbin 策略集派生能力集合，每项形如 "<obj模板> <METHOD>"。
// 与服务端传输层鉴权同源（同一 model+policy）；前端 auth.can() 据此做按钮/操作级门控。
func BuildCaps(enf *casbin.Enforcer, roles []string) []string {
	if enf == nil {
		return []string{}
	}
	rules, err := enf.GetPolicy()
	if err != nil {
		return []string{}
	}
	in := make(map[string]bool, len(roles))
	for _, r := range roles {
		in[r] = true
	}
	set := map[string]struct{}{}
	for _, p := range rules {
		if len(p) < 3 || !in[p[0]] {
			continue
		}
		set[strings.TrimSpace(p[1]+" "+strings.ToUpper(p[2]))] = struct{}{}
	}
	out := make([]string, 0, len(set))
	for s := range set {
		out = append(out, s)
	}
	sort.Strings(out)
	return out
}
```

- [ ] **步骤 4：运行确认通过**

运行：`cd backend-go && go test ./internal/platform/auth/ -run TestBuildCaps -v`
预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/internal/platform/auth/caps.go backend-go/internal/platform/auth/caps_test.go
git commit -m "feat(go): auth.BuildCaps 从 Casbin 策略派生能力集合"
```

---

## 任务 9：sysadmin Handler 骨架 + 读用户 + `/auth/me` + 映射器

`sysadmin` 模块的读侧与自描述侧。`Handler` 持 `*store.Queries`（sysstore）与 `*casbin.Enforcer`（供 caps）。`ToAPIUser` **绝不**外泄 `password_hash`。`ListUsers/GetUser` 强制 `auth.DomainFrom(c).TenantID`（ABAC 硬隔离）。`GetMe` 回显 `{user, roles, caps}`。

**文件：**
- 创建：`backend-go/internal/modules/sysadmin/mapper.go`
- 创建：`backend-go/internal/modules/sysadmin/mapper_test.go`（无 DB，本地必跑）
- 创建：`backend-go/internal/modules/sysadmin/handler.go`
- 创建：`backend-go/internal/modules/sysadmin/handler_test.go`（`ARK_TEST_DATABASE_URL` 门控）

- [ ] **步骤 1：写失败的映射器测试**

`backend-go/internal/modules/sysadmin/mapper_test.go`：

```go
package sysadmin

import (
	"testing"
	"time"

	store "github.com/eplugger/ark/internal/modules/sysadmin/store"
)

func TestToAPIUser_OmitsPasswordHash(t *testing.T) {
	h := "$2a$10$secretmaterial"
	em := "a@b.co"
	u := store.SysUser{
		ID: 1, Username: "admin", RealName: "管理员",
		EmploymentStatus: "ONBOARD", SecurityLevel: "TOP_SECRET", Status: "ACTIVE",
		PasswordHash: &h, Email: &em, TenantID: 1,
		CreatedAt: time.Now(), UpdatedAt: time.Now(),
	}
	m := ToAPIUser(u, []string{"R-ADMIN"})
	if _, leak := m["password_hash"]; leak {
		t.Fatal("password_hash 泄漏到对外形状")
	}
	if m["username"] != "admin" {
		t.Fatalf("username 缺: %v", m["username"])
	}
	if r, ok := m["roles"].([]string); !ok || len(r) != 1 {
		t.Fatalf("roles 形状错: %#v", m["roles"])
	}
	if m["email"] != "a@b.co" {
		t.Fatalf("email 缺: %v", m["email"])
	}
}

func TestToAPIUser_NilRolesIsEmptyArray(t *testing.T) {
	u := store.SysUser{ID: 2, Username: "staff", Status: "ACTIVE", CreatedAt: time.Now(), UpdatedAt: time.Now()}
	m := ToAPIUser(u, nil)
	if r, ok := m["roles"].([]string); !ok || len(r) != 0 {
		t.Fatalf("nil roles 应序列化为空数组: %#v", m["roles"])
	}
}
```

- [ ] **步骤 2：运行确认失败**

运行：`cd backend-go && go test ./internal/modules/sysadmin/ -run TestToAPIUser -v`
预期：编译失败 `undefined: ToAPIUser`。

- [ ] **步骤 3：写映射器**

`backend-go/internal/modules/sysadmin/mapper.go`：

```go
package sysadmin

import (
	"time"

	store "github.com/eplugger/ark/internal/modules/sysadmin/store"
)

// ToAPIUser 把 sqlc SysUser 行映射为契约 User 形状（snake_case，附 roles[]）。
// 铁律：password_hash 永不进入返回值。
func ToAPIUser(u store.SysUser, roles []string) map[string]any {
	if roles == nil {
		roles = []string{}
	}
	out := map[string]any{
		"id":                u.ID,
		"username":          u.Username,
		"real_name":         u.RealName,
		"employment_status": u.EmploymentStatus,
		"security_level":    u.SecurityLevel,
		"status":            u.Status,
		"tenant_id":         u.TenantID,
		"deleted":           u.Deleted,
		"creator_id":        u.CreatorID,
		"roles":             roles,
		"created_at":        u.CreatedAt.UTC().Format(time.RFC3339Nano),
		"updated_at":        u.UpdatedAt.UTC().Format(time.RFC3339Nano),
	}
	putStr := func(k string, v *string) {
		if v != nil {
			out[k] = *v
		} else {
			out[k] = nil
		}
	}
	putStr("email", u.Email)
	putStr("phone", u.Phone)
	putStr("staff_no", u.StaffNo)
	putStr("remark", u.Remark)
	if u.LegalEntityID != nil {
		out["legal_entity_id"] = *u.LegalEntityID
	} else {
		out["legal_entity_id"] = nil
	}
	return out
}

// ToAPIRole 映射 sys_role → 契约 Role。
func ToAPIRole(r store.SysRole) map[string]any {
	return map[string]any{
		"id":         r.ID,
		"code":       r.Code,
		"name":       r.Name,
		"is_builtin": r.IsBuiltin,
		"tenant_id":  r.TenantID,
		"created_at": r.CreatedAt.UTC().Format(time.RFC3339Nano),
		"updated_at": r.UpdatedAt.UTC().Format(time.RFC3339Nano),
	}
}
```

- [ ] **步骤 4：运行确认映射器通过**

运行：`cd backend-go && go test ./internal/modules/sysadmin/ -run TestToAPIUser -v`
预期：PASS。

- [ ] **步骤 5：写 Handler（读侧 + /auth/me）**

`backend-go/internal/modules/sysadmin/handler.go`：

```go
package sysadmin

import (
	"strconv"

	"github.com/casbin/casbin/v2"
	store "github.com/eplugger/ark/internal/modules/sysadmin/store"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Handler struct {
	q   *store.Queries
	enf *casbin.Enforcer
}

func NewHandler(pool *pgxpool.Pool, enf *casbin.Enforcer) *Handler {
	return &Handler{q: store.New(pool), enf: enf}
}

// pageArgs 与 P 模块同款分页解析（size 上限 200）。
func pageArgs(c *gin.Context) (page, size, limit, offset int32) {
	p, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
	s, _ := strconv.Atoi(c.DefaultQuery("size", "20"))
	if p < 1 {
		p = 1
	}
	if s < 1 {
		s = 20
	}
	if s > 200 {
		s = 200
	}
	return int32(p), int32(s), int32(s), int32((p - 1) * s)
}

func optQuery(c *gin.Context, k string) *string {
	if v := c.Query(k); v != "" {
		return &v
	}
	return nil
}

// ListUsers 租户硬隔离 + 状态/关键词筛选。
func (h *Handler) ListUsers(c *gin.Context) {
	d := auth.DomainFrom(c)
	page, size, limit, offset := pageArgs(c)
	status := optQuery(c, "status")
	var kw *string
	if v := optQuery(c, "keyword"); v != nil {
		w := "%" + *v + "%"
		kw = &w
	}
	rows, err := h.q.ListUsers(c, store.ListUsersParams{
		TenantID: d.TenantID, Status: status, Keyword: kw, Limit: limit, Offset: offset,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50001, "查询失败")
		return
	}
	total, _ := h.q.CountUsers(c, store.CountUsersParams{TenantID: d.TenantID, Status: status, Keyword: kw})
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		codes, _ := h.q.ListRoleCodesByUser(c, r.ID)
		list = append(list, ToAPIUser(r, codes))
	}
	httpx.WriteOK(c, gin.H{"list": list, "total": total, "page": page, "size": size})
}

// GetUser 仅取本租户、未软删的用户，否则 404。
func (h *Handler) GetUser(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	u, err := h.q.GetUser(c, store.GetUserParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "用户不存在")
		return
	}
	codes, _ := h.q.ListRoleCodesByUser(c, u.ID)
	httpx.WriteOK(c, ToAPIUser(u, codes))
}

// GetMe 回显当前登录者：完整 User（DB 取回，租户一致）+ 角色 + 能力集合（Caps 源自 Casbin）。
func (h *Handler) GetMe(c *gin.Context) {
	d := auth.DomainFrom(c)
	roles := d.Roles
	if codes, err := h.q.ListRoleCodesByUser(c, d.UserID); err == nil && len(codes) > 0 {
		roles = codes
	}
	caps := auth.BuildCaps(h.enf, roles)
	var user map[string]any
	if u, err := h.q.GetUser(c, store.GetUserParams{ID: d.UserID, TenantID: d.TenantID}); err == nil {
		user = ToAPIUser(u, roles)
	} else {
		// 资料缺失（如已软删）仍回可辨识骨架，避免 me 端点整体失败
		user = map[string]any{"id": d.UserID, "security_level": d.SecurityLevel, "roles": roles}
	}
	httpx.WriteOK(c, gin.H{"user": user, "roles": roles, "caps": caps})
}
```

- [ ] **步骤 6：写门控集成测试（无库时 SKIP）**

`backend-go/internal/modules/sysadmin/handler_test.go`：

```go
package sysadmin

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/casbin/casbin/v2"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/db"
	"github.com/eplugger/ark/internal/platform/httpx"
	"github.com/gin-gonic/gin"
)

func injectAdmin(c *gin.Context) {
	c.Set(auth.CtxUserID, int64(1))
	c.Set(auth.CtxTenantID, int64(1))
	c.Set(auth.CtxSecurityLevel, "TOP_SECRET")
	c.Set(auth.CtxRoles, []string{"R-ADMIN"})
	c.Next()
}

// newTestEngine 需 ARK_TEST_DATABASE_URL 且库已应用 000001+000002（CI 服务里跑迁移后再测）。
func newTestEngine(t *testing.T) *gin.Engine {
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设置 ARK_TEST_DATABASE_URL")
	}
	pool, err := db.Connect(context.Background(), u)
	if err != nil {
		t.Fatal(err)
	}
	enf, err := auth.NewEnforcer("../../platform/auth/model.conf", "../../platform/auth/policy.csv")
	if err != nil {
		t.Fatal(err)
	}
	gin.SetMode(gin.TestMode)
	e := gin.New()
	e.Use(httpx.TraceID(), injectAdmin)
	api := e.Group("/api/v1")
	Register(api, NewHandler(pool, enf))
	return e
}

func TestListUsers_Endpoint(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/admin/users?page=1&size=20", nil))
	if w.Code != 200 {
		t.Fatalf("HTTP %d body=%s", w.Code, w.Body.String())
	}
	var env struct {
		Code int `json:"code"`
		Data struct {
			List  []map[string]any `json:"list"`
			Total int              `json:"total"`
		} `json:"data"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	if env.Code != 0 || env.Data.Total < 4 || len(env.Data.List) < 4 {
		t.Fatalf("种子用户未返回: %+v", env.Data)
	}
	for _, row := range env.Data.List {
		if _, leak := row["password_hash"]; leak {
			t.Fatal("password_hash 泄漏")
		}
	}
}

func TestGetUser_404WhenMissing(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/admin/users/999999", nil))
	if w.Code != http.StatusNotFound {
		t.Fatalf("期望 404，实得 %d", w.Code)
	}
}

func TestGetMe_ReturnsCaps(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/auth/me", nil))
	if w.Code != 200 {
		t.Fatalf("HTTP %d body=%s", w.Code, w.Body.String())
	}
	var env struct {
		Data struct {
			Roles []string `json:"roles"`
			Caps  []string `json:"caps"`
		} `json:"data"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	if len(env.Data.Caps) == 0 {
		t.Fatalf("R-ADMIN 应有非空 caps: %v", env.Data)
	}
}
```

- [ ] **步骤 7：本地验证（编译/静态 + 无库测试，集成 SKIP）**

运行：`cd backend-go && go build ./... && go vet ./internal/modules/sysadmin/`
预期：无错误（`Register` 在任务 12 落地；若此处报 `undefined: Register`，先建 `routes.go` 空壳或把本步骤与任务 12 合并执行——见任务 12 说明）。
运行：`cd backend-go && go test ./internal/modules/sysadmin/ -count=1`
预期：`TestToAPIUser*`、`TestContract*` PASS；`TestListUsers_Endpoint`/`TestGetUser*`/`TestGetMe*` SKIP（无 `ARK_TEST_DATABASE_URL`）。

- [ ] **步骤 8：Commit**

```bash
git add backend-go/internal/modules/sysadmin/mapper.go backend-go/internal/modules/sysadmin/mapper_test.go backend-go/internal/modules/sysadmin/handler.go backend-go/internal/modules/sysadmin/handler_test.go
git commit -m "feat(go): sysadmin 读用户/GetMe 能力回显 + 映射器(剔除 password_hash)"
```

---

## 任务 10：CreateUser / UpdateUser / DeleteUser（bcrypt 入库 + 角色绑定 + 409 冲突）

写侧。新建用户：`username` 在租户内唯一（`uk_user_username`），重复→409；口令 bcrypt 后落 `password_hash`；`roles` 角色码→`role_id` 逐条绑定。更新：读旧行→合并 body→`UpdateUser`，`password` 给出则重设。删除：软删（`SoftDeleteUser`）。

**文件：**
- 修改：`backend-go/db/query_sys/sys_role.sql`（追加 `GetRoleByCode`）
- 修改：`backend-go/internal/modules/sysadmin/handler.go`（增三方法 + `hashPassword`）
- 修改：`backend-go/internal/modules/sysadmin/handler_test.go`（增写侧集成用例，门控）
- 重生成：`backend-go/internal/modules/sysadmin/store/`（sqlc）

- [ ] **步骤 1：追加角色码→id 查询**

在 `backend-go/db/query_sys/sys_role.sql` 末尾加：

```sql
-- name: GetRoleByCode :one
SELECT id, code, name, is_builtin, tenant_id, created_at, updated_at
FROM sys_role WHERE tenant_id = $1 AND code = $2;
```

重跑生成：`cd backend-go && GOTOOLCHAIN=go1.23.4 go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate`
预期：`store` 包出现 `GetRoleByCode(ctx, GetRoleByCodeParams{TenantID, Code})`。

- [ ] **步骤 2：写纯函数哈希往返测试（本地可跑）**

在 `handler_test.go` 末尾追加（无需 DB）：

```go
func TestHashPassword_Verifiable(t *testing.T) {
	h, err := hashPassword("Admin@123456")
	if err != nil {
		t.Fatal(err)
	}
	if h == "Admin@123456" || len(h) < 50 {
		t.Fatalf("哈希异常: %q", h)
	}
	if bcrypt.CompareHashAndPassword([]byte(h), []byte("Admin@123456")) != nil {
		t.Fatal("bcrypt 往返校验失败")
	}
	if bcrypt.CompareHashAndPassword([]byte(h), []byte("wrong")) == nil {
		t.Fatal("错误口令竟通过")
	}
}
```
import 块加 `"golang.org/x/crypto/bcrypt"`。

- [ ] **步骤 3：写实现**

在 `handler.go` 顶部 import 加 `"errors" "github.com/jackc/pgx/v5" "golang.org/x/crypto/bcrypt"`；末尾追加：

```go
// hashPassword 生成 bcrypt(cost 默认) 哈希，供新用户/改密落库。
func hashPassword(plain string) (string, error) {
	b, err := bcrypt.GenerateFromPassword([]byte(plain), bcrypt.DefaultCost)
	if err != nil {
		return "", err
	}
	return string(b), nil
}

func strPtr(s *string) *string { return s }

// CreateUser 建用户：username 租户内唯一（409），口令 bcrypt 入库，roles 逐条绑定。
func (h *Handler) CreateUser(c *gin.Context) {
	d := auth.DomainFrom(c)
	var body struct {
		Username         string   `json:"username" binding:"required"`
		RealName         string   `json:"real_name" binding:"required"`
		Password         string   `json:"password" binding:"required"`
		Email            *string  `json:"email"`
		Phone            *string  `json:"phone"`
		StaffNo          *string  `json:"staff_no"`
		SecurityLevel    string   `json:"security_level"`
		EmploymentStatus string   `json:"employment_status"`
		Roles            []string `json:"roles"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	ph, err := hashPassword(body.Password)
	if err != nil {
		httpx.WriteErr(c, 500, 50003, "口令加密失败")
		return
	}
	sl := body.SecurityLevel
	if sl == "" {
		sl = "INTERNAL"
	}
	es := body.EmploymentStatus
	if es == "" {
		es = "ONBOARD"
	}
	u, err := h.q.CreateUser(c, store.CreateUserParams{
		Username: body.Username, RealName: body.RealName, PasswordHash: &ph,
		Email: strPtr(body.Email), Phone: strPtr(body.Phone), StaffNo: strPtr(body.StaffNo),
		EmploymentStatus: es, SecurityLevel: sl, Status: "ACTIVE",
		TenantID: d.TenantID, LegalEntityID: nil, CreatorID: d.UserID,
	})
	if err != nil {
		// 23505 = unique_violation（uk_user_username）
		httpx.WriteErr(c, 409, 40901, "用户名已存在或写入冲突")
		return
	}
	for _, code := range body.Roles {
		role, err := h.q.GetRoleByCode(c, store.GetRoleByCodeParams{TenantID: d.TenantID, Code: code})
		if err != nil {
			continue // 未知角色码忽略
		}
		_ = h.q.AssignRole(c, store.AssignRoleParams{UserID: u.ID, RoleID: role.ID, TenantID: d.TenantID})
	}
	codes, _ := h.q.ListRoleCodesByUser(c, u.ID)
	httpx.WriteOK(c, ToAPIUser(store.SysUser(u), codes))
}

// UpdateUser 读旧行→合并可变列→落库；password 给出则重设。
func (h *Handler) UpdateUser(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	cur, err := h.q.GetUser(c, store.GetUserParams{ID: id, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "用户不存在")
		return
	}
	var body struct {
		RealName      *string `json:"real_name"`
		Email         *string `json:"email"`
		Phone         *string `json:"phone"`
		SecurityLevel *string `json:"security_level"`
		Status        *string `json:"status"`
		Password      *string `json:"password"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, 400, 40001, "请求参数错误")
		return
	}
	// 合并（未给出的沿用旧值；NOT NULL 列 real_name/security_level/status 缺省回填旧值）
	realName := cur.RealName
	if body.RealName != nil {
		realName = *body.RealName
	}
	sl := cur.SecurityLevel
	if body.SecurityLevel != nil {
		sl = *body.SecurityLevel
	}
	st := cur.Status
	if body.Status != nil {
		st = *body.Status
	}
	updated, err := h.q.UpdateUser(c, store.UpdateUserParams{
		ID: id, TenantID: d.TenantID, RealName: realName,
		Email: body.Email, Phone: body.Phone, SecurityLevel: sl, Status: st,
	})
	if err != nil {
		httpx.WriteErr(c, 500, 50004, "更新失败")
		return
	}
	if body.Password != nil && *body.Password != "" {
		ph, err := hashPassword(*body.Password)
		if err == nil {
			_ = h.q.UpdateUserPassword(c, store.UpdateUserPasswordParams{ID: id, TenantID: d.TenantID, PasswordHash: &ph})
			updated.PasswordHash = &ph
		}
	}
	codes, _ := h.q.ListRoleCodesByUser(c, id)
	httpx.WriteOK(c, ToAPIUser(store.SysUser(updated), codes))
}

// DeleteUser 软删（deleted=1 + status=DISABLED）。
func (h *Handler) DeleteUser(c *gin.Context) {
	d := auth.DomainFrom(c)
	id, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	if _, err := h.q.GetUser(c, store.GetUserParams{ID: id, TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, 404, 40401, "用户不存在")
		return
	}
	if err := h.q.SoftDeleteUser(c, store.SoftDeleteUserParams{ID: id, TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, 500, 50005, "停用失败")
		return
	}
	httpx.WriteOK(c, gin.H{"id": id, "deleted": true})
}
```

> `errors`/`pgx` 若最终未被引用（CreateUser 冲突处理走"总是 409"简化），删除对应 import，避免 `go vet` 未用 import 报错。`store.SysUser(u)` 转换：`CreateUser`/`UpdateUser` 用 `RETURNING *` 生成的是 `SysUser` 值，若 sqlc 以命名 Row 类型返回则按需 `store.SysUser(row)` 转换——本查询列与表完全一致，sqlc 直接返回 `SysUser`，无需转换；若生成结果类型不同，据此微调。

- [ ] **步骤 4：补写侧集成用例（门控）**

在 `handler_test.go` 追加：

```go
func TestCreateUser_DuplicateUsername409(t *testing.T) {
	e := newTestEngine(t)
	// 复用固定 Idempotency-Key 无关；两次相同 username 第二次应 409
	body := `{"username":"tester1","real_name":"测试员","password":"Test@123456","security_level":"INTERNAL","roles":["R-STAFF"]}`
	for i := 0; i < 2; i++ {
		w := httptest.NewRecorder()
		r := httptest.NewRequest("POST", "/api/v1/admin/users", nil)
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("Idempotency-Key", "itest-create-1")
		r.Body = nopCloserString(body)
		e.ServeHTTP(w, r)
		if i == 0 && w.Code != 200 {
			t.Fatalf("首次创建应 200，实得 %d body=%s", w.Code, w.Body.String())
		}
		if i == 1 && w.Code != http.StatusConflict {
			t.Fatalf("重复用户名应 409，实得 %d", w.Code)
		}
	}
}
```
并在 `handler_test.go` import 块补 `"strings"` 与定义 `nopCloserString`（同 login 测试的小工具，放本文件一份即可）：

```go
func nopCloserString(s string) io.ReadCloser { return io.NopCloser(strings.NewReader(s)) }
```
（import 加 `"io"`、`"strings"`。）

- [ ] **步骤 5：本地验证**

运行：`cd backend-go && go build ./... && go vet ./internal/modules/sysadmin/`
预期：无错误。
运行：`cd backend-go && go test ./internal/modules/sysadmin/ -run TestHashPassword -v`
预期：PASS（纯 bcrypt 往返，不连库）。集成用例 SKIP。

- [ ] **步骤 6：Commit**

```bash
git add backend-go/db/query_sys/sys_role.sql backend-go/internal/modules/sysadmin/store backend-go/internal/modules/sysadmin/handler.go backend-go/internal/modules/sysadmin/handler_test.go
git commit -m "feat(go): sysadmin 用户新建/更新/软删(bcrypt 入库 + 角色绑定 + 409 冲突)"
```

---

## 任务 11：ListRoles / AssignRole / RevokeRole

角色目录 + 用户授权（授予/撤销）。跨租户防护：授予前用 `GetRole(role_id, tenant)` 校验角色属本租户、用 `GetUser` 校验目标用户属本租户，任一缺失→404。`AssignRole` 借 `ON CONFLICT DO NOTHING` 幂等（重复授权不报错，返回当前态）。

**文件：**
- 修改：`backend-go/db/query_sys/sys_role.sql`（追加 `GetRole`）
- 修改：`backend-go/internal/modules/sysadmin/handler.go`（增三方法）
- 修改：`backend-go/internal/modules/sysadmin/handler_test.go`（增授权集成用例，门控）
- 重生成：`backend-go/internal/modules/sysadmin/store/`

- [ ] **步骤 1：追加 GetRole 查询并重生**

`backend-go/db/query_sys/sys_role.sql` 末尾加：

```sql
-- name: GetRole :one
SELECT id, code, name, is_builtin, tenant_id, created_at, updated_at
FROM sys_role WHERE id = $1 AND tenant_id = $2;
```

运行：`cd backend-go && GOTOOLCHAIN=go1.23.4 go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate`
预期：`store.GetRole(ctx, GetRoleParams{ID, TenantID})` 就位。

- [ ] **步骤 2：写实现**

在 `handler.go` 追加：

```go
// ListRoles 本租户角色目录。
func (h *Handler) ListRoles(c *gin.Context) {
	d := auth.DomainFrom(c)
	rows, err := h.q.ListRoles(c, d.TenantID)
	if err != nil {
		httpx.WriteErr(c, 500, 50006, "查询失败")
		return
	}
	list := make([]map[string]any, 0, len(rows))
	for _, r := range rows {
		list = append(list, ToAPIRole(r))
	}
	httpx.WriteOK(c, gin.H{"list": list})
}

// AssignRole 授予角色：校验角色与用户均属本租户，幂等绑定后回显用户。
func (h *Handler) AssignRole(c *gin.Context) {
	d := auth.DomainFrom(c)
	userID, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	var body struct {
		RoleID int64 `json:"role_id" binding:"required"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		httpx.WriteErr(c, 400, 40001, "role_id 必填")
		return
	}
	if _, err := h.q.GetRole(c, store.GetRoleParams{ID: body.RoleID, TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, 404, 40402, "角色不存在或跨租户")
		return
	}
	u, err := h.q.GetUser(c, store.GetUserParams{ID: userID, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "用户不存在")
		return
	}
	if err := h.q.AssignRole(c, store.AssignRoleParams{UserID: userID, RoleID: body.RoleID, TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, 500, 50007, "授权失败")
		return
	}
	codes, _ := h.q.ListRoleCodesByUser(c, userID)
	httpx.WriteOK(c, ToAPIUser(u, codes))
}

// RevokeRole 撤销角色（DELETE /admin/users/:id/roles/:roleId），回显撤销后的用户。
func (h *Handler) RevokeRole(c *gin.Context) {
	d := auth.DomainFrom(c)
	userID, _ := strconv.ParseInt(c.Param("id"), 10, 64)
	roleID, _ := strconv.ParseInt(c.Param("roleId"), 10, 64)
	u, err := h.q.GetUser(c, store.GetUserParams{ID: userID, TenantID: d.TenantID})
	if err != nil {
		httpx.WriteErr(c, 404, 40401, "用户不存在")
		return
	}
	if err := h.q.RevokeRole(c, store.RevokeRoleParams{UserID: userID, RoleID: roleID, TenantID: d.TenantID}); err != nil {
		httpx.WriteErr(c, 500, 50008, "撤销失败")
		return
	}
	codes, _ := h.q.ListRoleCodesByUser(c, userID)
	httpx.WriteOK(c, ToAPIUser(u, codes))
}
```

- [ ] **步骤 3：补授权集成用例（门控）**

在 `handler_test.go` 追加：

```go
func TestListRoles_ReturnsSeededEight(t *testing.T) {
	e := newTestEngine(t)
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/admin/roles", nil))
	if w.Code != 200 {
		t.Fatalf("HTTP %d body=%s", w.Code, w.Body.String())
	}
	var env struct {
		Data struct {
			List []map[string]any `json:"list"`
		} `json:"data"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	if len(env.Data.List) < 8 {
		t.Fatalf("8 基础角色未返回: %d", len(env.Data.List))
	}
}

func TestAssignRevokeRole(t *testing.T) {
	e := newTestEngine(t)
	// admin(user id=1) 已被授予 R-ADMIN；给 staff 追加 R-EXPERT 需先取 role id。
	// 简化：对 admin 再授予 R-ADMIN（幂等，ON CONFLICT DO NOTHING）应 200。
	w := httptest.NewRecorder()
	r := httptest.NewRequest("POST", "/api/v1/admin/users/1/roles", nil)
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("Idempotency-Key", "itest-assign-1")
	// R-ADMIN 的 id：种子第 8 个角色，identity=8（fresh 库）
	r.Body = nopCloserString(`{"role_id":8}`)
	e.ServeHTTP(w, r)
	if w.Code != 200 {
		t.Fatalf("幂等再授权应 200，实得 %d body=%s", w.Code, w.Body.String())
	}
}
```

- [ ] **步骤 4：本地验证**

运行：`cd backend-go && go build ./... && go vet ./internal/modules/sysadmin/`
预期：无错误。集成用例 SKIP（无库）。

- [ ] **步骤 5：Commit**

```bash
git add backend-go/db/query_sys/sys_role.sql backend-go/internal/modules/sysadmin/store backend-go/internal/modules/sysadmin/handler.go backend-go/internal/modules/sysadmin/handler_test.go
git commit -m "feat(go): sysadmin 角色目录/授予/撤销(跨租户校验 + 幂等)"
```

---

## 任务 12：路由注册 `Register` + 接入受保护分组 + passthrough 共存

把 sysadmin 挂进 `router.Build` 的受保护 `/api/v1` 组。同时契约 revoke 路径参数 `{userId}` 统一改 `{id}`（与 gin `:id` 及 assign 路由一致，消除同方法树参数名冲突）。**共存证明**：`Pool==nil` 时 sysadmin 路由不注册，`GET /api/v1/admin/users` 落到契约 passthrough（NoRoute 不经鉴权中间件），返回 `code=0` 示例包络——保证"Go 直接替换 Node"后整系统对未实现契约仍可用。

**文件：**
- 修改：`design/12-用户与权限-U.openapi.yaml`（revoke `{userId}`→`{id}`）+ 重 cp 前端
- 创建：`backend-go/internal/modules/sysadmin/routes.go`
- 修改：`backend-go/internal/router.go`（受保护组内注册 sysadmin）
- 创建：`backend-go/internal/router_sysadmin_test.go`

- [ ] **步骤 0：对齐契约 revoke 路径**

编辑 `design/12-用户与权限-U.openapi.yaml`：把 `/admin/users/{userId}/roles/{roleId}:` 段整体改为 `/admin/users/{id}/roles/{roleId}:`，并把其下 `parameters` 中 `{ name: userId ... }` 改 `{ name: id, in: path, required: true, schema: { type: integer, format: int64 } }`。重 cp：`cp "design/12-用户与权限-U.openapi.yaml" "frontend/src/api/schema/12-用户与权限-U.openapi.yaml"`。

- [ ] **步骤 1：写 routes.go**

`backend-go/internal/modules/sysadmin/routes.go`：

```go
package sysadmin

import "github.com/gin-gonic/gin"

// Register 把 U 路由挂到受保护分组（相对 /admin、/auth 前缀；/api/v1 由 router.Build 分组提供）。
// gin v1.10 的 gin.IRoutes 无 Group()，直接 r.GET/.POST 相对路径注册（与 P 模块同款）。
// 参数名统一 :id（用户）/:roleId，避免同方法树 wildcard 名冲突导致 gin panic。
func Register(r gin.IRoutes, h *Handler) {
	r.GET("/auth/me", h.GetMe)
	r.GET("/admin/users", h.ListUsers)
	r.POST("/admin/users", h.CreateUser)
	r.GET("/admin/users/:id", h.GetUser)
	r.PUT("/admin/users/:id", h.UpdateUser)
	r.DELETE("/admin/users/:id", h.DeleteUser)
	r.GET("/admin/roles", h.ListRoles)
	r.POST("/admin/users/:id/roles", h.AssignRole)
	r.DELETE("/admin/users/:id/roles/:roleId", h.RevokeRole)
}
```

- [ ] **步骤 2：接入 router.Build**

`backend-go/internal/router.go`：import 加 `"github.com/eplugger/ark/internal/modules/sysadmin"`；把受保护组注册块改为：

```go
	if d.Pool != nil {
		p.Register(api, p.NewHandler(d.Pool))
		sysadmin.Register(api, sysadmin.NewHandler(d.Pool, d.Enforcer))
	}
```

- [ ] **步骤 3：写 passthrough 共存测试（无 DB）**

`backend-go/internal/router_sysadmin_test.go`：

```go
package internal

import (
	"encoding/json"
	"net/http/httptest"
	"testing"

	"github.com/eplugger/ark/internal/config"
	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/oapi"
	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
)

// Pool==nil：sysadmin 未注册，GET /admin/users 落 passthrough（契约已定义），应 code=0、HTTP 200。
func TestBuild_SysadminFallsBackToPassthrough(t *testing.T) {
	gin.SetMode(gin.TestMode)
	l := zap.NewNop()
	cfg := &config.Config{Env: "test", JWTSecret: "s3cr3t", JWTTTLSec: 3600, DesignDir: "../../design"}
	enf, err := auth.NewEnforcer("../platform/auth/model.conf", "../platform/auth/policy.csv")
	if err != nil {
		t.Fatal(err)
	}
	spec, err := oapi.LoadDir("../../design")
	if err != nil {
		t.Fatal(err)
	}
	e := Build(RouterDeps{Logger: l, Cfg: cfg, Enforcer: enf, Spec: spec}) // Pool 缺省 nil
	w := httptest.NewRecorder()
	e.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/admin/users", nil))
	if w.Code != 200 {
		t.Fatalf("passthrough 应 200，实得 %d body=%s", w.Code, w.Body.String())
	}
	var env struct {
		Code int `json:"code"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &env)
	if env.Code != 0 {
		t.Fatalf("passthrough 包络 code 应为 0: %+v", env)
	}
}
```

- [ ] **步骤 4：运行确认通过**

运行：`cd backend-go && go test ./internal/ -run TestBuild_Sysadmin -v`
预期：PASS（契约有 `/admin/users`，passthrough 合成示例数据）。

- [ ] **步骤 5：全量后端回归**

运行：`cd backend-go && go build ./... && go vet ./... && go test ./... -count=1`
预期：编译/vet 无错；单测（无库）全 PASS 或 SKIP，集成用例 SKIP。

- [ ] **步骤 6：Commit**

```bash
git add design/12-用户与权限-U.openapi.yaml frontend/src/api/schema/12-用户与权限-U.openapi.yaml backend-go/internal/modules/sysadmin/routes.go backend-go/internal/router.go backend-go/internal/router_sysadmin_test.go
git commit -m "feat(go): sysadmin 路由注册进受保护组；契约 revoke 参数对齐 :id；passthrough 共存测试"
```

---

## Part D — 授权策略与合规

## 任务 13：扩展 `policy.csv` 覆盖 8 角色 + U 管理路由，并写传输层鉴权回归矩阵

`policy.csv` 当前只有 4 行（`R-ADMIN` 的 `/api/v1/*` GET/POST、`R-STAFF` 的 `/api/v1/apply/*` GET/POST），既不覆盖 8 基础角色，也没有 U 管理路由的 PUT/DELETE——`middleware.Auth` 逐角色 `Enforce(role, fullPath, method)`，因此 `UpdateUser(PUT)`/`DeleteUser(DELETE)` 现在对 R-ADMIN 也会被拒（策略只授 GET/POST）。本任务把策略补全成一套可审计的矩阵：**① U 管理写路由仅 R-ADMIN；② R-AUDITOR 全量只读（含 admin 读、不可写）；③ 每角色都能 `GET /auth/me`（登录后引导）；④ 业务域（apply/expense/review/ethics）按角色分派**。`model.conf` 用 `keyMatch2`，`*` 是后缀通配（含斜杠），故 `/api/v1/admin/*` 命中 `/api/v1/admin/users/1/roles/2`。策略源仍为静态文件（决策③：不入库），改动后须与前端 `can()`、`BuildCaps` 输出对齐（能力串 = 策略 obj 原样，含 `/api/v1` 前缀——见任务 15 的容错匹配）。

**文件：**
- 修改：`backend-go/internal/platform/auth/policy.csv`（全量重写为下表）
- 创建：`backend-go/internal/platform/auth/policy_test.go`（真 `model.conf`+`policy.csv` 的 role×path×method 断言矩阵，无 HTTP、无 DB，本地可跑）

- [ ] **步骤 1：写失败的回归矩阵测试**

`backend-go/internal/platform/auth/policy_test.go`：

```go
package auth

import (
	"os"
	"testing"
)

// 真 model.conf + 真 policy.csv（同服务端运行期），断言鉴权矩阵。
// 无 HTTP、无 DB：直接调 Enforcer.Enforce，本地与 CI 都能跑。
func TestAuthMatrix_TransportLayer(t *testing.T) {
	model := os.Getenv("ARK_AUTH_MODEL_PATH")
	if model == "" {
		model = "./model.conf"
	}
	pol := os.Getenv("ARK_AUTH_POLICY_PATH")
	if pol == "" {
		pol = "./policy.csv"
	}
	enf, err := NewEnforcer(model, pol)
	if err != nil {
		t.Fatal(err)
	}

	type c struct {
		role, path, method string
		want               bool
	}
	cases := []c{
		// —— U 管理写：仅 R-ADMIN ——
		{"R-ADMIN", "/api/v1/admin/users", "POST", true},
		{"R-ADMIN", "/api/v1/admin/users/1", "PUT", true},
		{"R-ADMIN", "/api/v1/admin/users/1", "DELETE", true},
		{"R-ADMIN", "/api/v1/admin/users/1/roles/2", "DELETE", true},
		{"R-AUDITOR", "/api/v1/admin/users", "POST", false},
		{"R-AUDITOR", "/api/v1/admin/users/1", "PUT", false},
		{"R-AUDITOR", "/api/v1/admin/users/1", "DELETE", false},
		{"R-MANAGER", "/api/v1/admin/users", "GET", false},
		{"R-STAFF", "/api/v1/admin/users", "GET", false},
		// —— R-AUDITOR 只读：admin 读放行、写全拒 ——
		{"R-AUDITOR", "/api/v1/admin/users", "GET", true},
		{"R-AUDITOR", "/api/v1/admin/roles", "GET", true},
		{"R-AUDITOR", "/api/v1/apply/projects", "GET", true},
		// —— /auth/me：每个已认证角色都要能读自己 ——
		{"R-ADMIN", "/api/v1/auth/me", "GET", true},
		{"R-AUDITOR", "/api/v1/auth/me", "GET", true},
		{"R-MANAGER", "/api/v1/auth/me", "GET", true},
		{"R-STAFF", "/api/v1/auth/me", "GET", true},
		{"R-FINANCE", "/api/v1/auth/me", "GET", true},
		{"R-LEADER", "/api/v1/auth/me", "GET", true},
		{"R-EXPERT", "/api/v1/auth/me", "GET", true},
		{"R-ETHICS", "/api/v1/auth/me", "GET", true},
		// —— 业务域按角色 ——
		{"R-MANAGER", "/api/v1/apply/projects", "POST", true},
		{"R-MANAGER", "/api/v1/apply/projects/9", "PUT", true},
		{"R-STAFF", "/api/v1/apply/projects", "GET", true},
		{"R-STAFF", "/api/v1/expense/claims", "POST", false},
		{"R-FINANCE", "/api/v1/expense/claims", "POST", true},
		{"R-EXPERT", "/api/v1/review/tasks/3", "POST", true},
		{"R-EXPERT", "/api/v1/expense/claims", "POST", false},
		{"R-ETHICS", "/api/v1/ethics/reviews", "POST", true},
		// —— 未知角色：一律拒 ——
		{"R-NOPE", "/api/v1/auth/me", "GET", false},
	}
	for _, tc := range cases {
		got, _ := enf.Enforce(tc.role, tc.path, tc.method)
		if got != tc.want {
			t.Errorf("Enforce(%s,%s,%s)=%v，期望 %v", tc.role, tc.path, tc.method, got, tc.want)
		}
	}
}

// BuildCaps 须与鉴权矩阵同源：R-AUDITOR 的能力里不得出现任何写动作。
func TestBuildCaps_NoWritesForAuditor(t *testing.T) {
	model := os.Getenv("ARK_AUTH_MODEL_PATH")
	if model == "" {
		model = "./model.conf"
	}
	pol := os.Getenv("ARK_AUTH_POLICY_PATH")
	if pol == "" {
		pol = "./policy.csv"
	}
	enf, err := NewEnforcer(model, pol)
	if err != nil {
		t.Fatal(err)
	}
	for _, cap := range BuildCaps(enf, []string{"R-AUDITOR"}) {
		if hasSuffixAny(cap, " POST", " PUT", " DELETE") {
			t.Errorf("R-AUDITOR 不应有写能力: %q", cap)
		}
	}
}

func hasSuffixAny(s string, suffixes ...string) bool {
	for _, suf := range suffixes {
		if len(s) >= len(suf) && s[len(s)-len(suf):] == suf {
			return true
		}
	}
	return false
}
```

- [ ] **步骤 2：运行确认失败**

运行：`cd backend-go && go test ./internal/platform/auth/ -run 'TestAuthMatrix_TransportLayer|TestBuildCaps_NoWritesForAuditor' -v`
预期：FAIL——现策略缺 R-AUDITOR/R-MANAGER/…/R-ETHICS 全部条目，`/auth/me` 对多数角色 false、admin 写路由 PUT/DELETE 对 R-ADMIN 也 false，矩阵大量不符。

- [ ] **步骤 3：全量重写 `policy.csv`**

`backend-go/internal/platform/auth/policy.csv`（整文件替换；`/api/v1/auth/login` 为公开路由不进此表）：

```
# 传输层 API 鉴权策略（Casbin；model=keyMatch2，obj 为完整请求路径含 /api/v1 前缀）。
# 公开：POST /api/v1/auth/login —— 不进受保护组、不在此表。
# 铁律：U 管理写路由仅 R-ADMIN；R-AUDITOR 全量只读；每个已认证角色都能 GET /auth/me。

# ---- 超级管理员：全域读写（含 U 管理、状态变更）----
p, R-ADMIN, /api/v1/*, GET
p, R-ADMIN, /api/v1/*, POST
p, R-ADMIN, /api/v1/*, PUT
p, R-ADMIN, /api/v1/*, DELETE

# ---- 审计员：只读（业务 + 管理均不可变更）----
p, R-AUDITOR, /api/v1/*, GET

# ---- 申报域：研究员读写、主管可改、领导审批 ----
p, R-STAFF,   /api/v1/apply/*, GET
p, R-STAFF,   /api/v1/apply/*, POST
p, R-MANAGER, /api/v1/apply/*, GET
p, R-MANAGER, /api/v1/apply/*, POST
p, R-MANAGER, /api/v1/apply/*, PUT
p, R-LEADER,  /api/v1/apply/*, GET
p, R-LEADER,  /api/v1/apply/*, PUT

# ---- 经费/报销：财务读写 ----
p, R-FINANCE, /api/v1/expense/*, GET
p, R-FINANCE, /api/v1/expense/*, POST
p, R-FINANCE, /api/v1/expense/*, PUT
p, R-FINANCE, /api/v1/apply/*, GET

# ---- 评审专家：读申报 + 提交评审结论 ----
p, R-EXPERT,  /api/v1/apply/*, GET
p, R-EXPERT,  /api/v1/review/*, GET
p, R-EXPERT,  /api/v1/review/*, POST

# ---- 伦理委员会：读申报 + 伦理批复 ----
p, R-ETHICS,  /api/v1/apply/*, GET
p, R-ETHICS,  /api/v1/ethics/*, GET
p, R-ETHICS,  /api/v1/ethics/*, POST

# ---- 每个已认证角色都能读自身身份/能力（前端登录后引导依赖）----
p, R-STAFF,   /api/v1/auth/me, GET
p, R-MANAGER, /api/v1/auth/me, GET
p, R-LEADER,  /api/v1/auth/me, GET
p, R-FINANCE, /api/v1/auth/me, GET
p, R-AUDITOR, /api/v1/auth/me, GET
p, R-EXPERT,  /api/v1/auth/me, GET
p, R-ETHICS,  /api/v1/auth/me, GET
```

（R-ADMIN 的 `/api/v1/* GET` 已覆盖其 `/auth/me`，故不单列，避免 `BuildCaps` 出重复项。）

- [ ] **步骤 4：运行确认通过**

运行：`cd backend-go && go test ./internal/platform/auth/ -run 'TestAuthMatrix_TransportLayer|TestBuildCaps|TestAuth' -v`
预期：PASS——矩阵全中；`TestBuildCaps_NoWritesForAuditor` 通过（R-AUDITOR 仅有 `... GET` 能力）；任务 8 的 `TestBuildCaps_FromPolicy`（R-ADMIN 含 `/api/v1/* GET`）仍绿。

- [ ] **步骤 5：策略改动同步进镜像说明（决策③落点）**

`policy.csv` 随 Go 镜像 `COPY` 分发（沿用 M0：策略文件与 `model.conf` 打进 `backend` 镜像 `internal/platform/auth/`），运行期 `config.AuthPolicyPath` 指向镜像内文件。**不引入 `casbin_rule` 表、不引入 `sys_menu/sys_permission` 表**（P-U1-dyn 再动态化）。本步无代码改动，仅确认 `backend-go/Dockerfile`（M0 已建）`COPY . .` 覆盖到本目录；若 Dockerfile 用 `COPY go.mod ...` 式白名单，则补一行 `COPY internal/platform/auth/model.conf internal/platform/auth/policy.csv ./internal/platform/auth/`（执行时以现 Dockerfile 实际写法为准，二选一，勿重复打包）。

- [ ] **步骤 6：Commit**

```bash
git add backend-go/internal/platform/auth/policy.csv backend-go/internal/platform/auth/policy_test.go backend-go/Dockerfile
git commit -m "feat(go): Casbin policy.csv 覆盖 8 角色 + U 管理路由；增鉴权回归矩阵"
```

---

## 任务 14：新端点契约合规集成测试（真响应 vs 契约）+ 全栈 compose 冒烟脚本

任务 4 用合成 data 静态校验契约；本任务补两类收口：**①（DB 门控）真响应体合规**——`ARK_TEST_DATABASE_URL` 就绪时，起 `sysadmin.Handler` 打真实 DB，经 httptest 发真请求取回 JSON，用 `oapi.Validate` 对 `design/12` 的 data schema 断言零违规，钉死「实现产出 == 契约承诺」；无库则 `t.Skip`。**②全栈 compose 冒烟脚本**（M0 的 `scripts/compose-smoke.sh` 仍用 `ark/ark`，bcrypt 上线后带库后端登录不再吃硬编码口令）——新增 `scripts/compose-smoke-auth.sh`：真实种子账号登录 → `/auth/me` 校验角色+能力 → 管理员列用户命中种子 `admin` → 越权用户访问 admin 得 403（证明传输层鉴权端到端生效）。本机无 Docker → 脚本仅 `bash -n` 语法校验，实跑 BLOCKED 留 CI/Docker 主机。

**文件：**
- 创建：`backend-go/internal/modules/sysadmin/integration_contract_test.go`
- 创建：`scripts/compose-smoke-auth.sh`

- [ ] **步骤 1：写 DB 门控的真响应合规测试**

`backend-go/internal/modules/sysadmin/integration_contract_test.go`：

```go
package sysadmin

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/eplugger/ark/internal/platform/auth"
	"github.com/eplugger/ark/internal/platform/oapi"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

// dbPool：仅当 ARK_TEST_DATABASE_URL 就绪时建池，否则 t.Skip（本地无库零回归）。
func dbPool(t *testing.T) *pgxpool.Pool {
	u := os.Getenv("ARK_TEST_DATABASE_URL")
	if u == "" {
		t.Skip("未设 ARK_TEST_DATABASE_URL，跳过真响应集成用例")
	}
	pool, err := pgxpool.New(context.Background(), u)
	if err != nil {
		t.Fatalf("建池失败: %v", err)
	}
	if err := pool.Ping(context.Background()); err != nil {
		pool.Close()
		t.Skipf("数据库不可达，跳过: %v", err)
	}
	t.Cleanup(pool.Close)
	return pool
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

// 真 GET /admin/users 响应体必须符合契约 data schema，且不得外泄 password_hash。
func TestIntegration_ListUsers_RealResponseConforms(t *testing.T) {
	pool := dbPool(t)
	e, err := auth.NewEnforcer(
		envOr("ARK_AUTH_MODEL_PATH", "../../platform/auth/model.conf"),
		envOr("ARK_AUTH_POLICY_PATH", "../../platform/auth/policy.csv"),
	)
	if err != nil {
		t.Fatal(err)
	}
	h := NewHandler(pool, e)

	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.GET("/admin/users", h.ListUsers)

	// 直接注入数据域上下文（复现 middleware.Auth 放行 R-ADMIN 后的 gin.Context），
	// 与任务 9/10/11 的 handler_test.go 同构：不经 HTTP 中间件，仅验 handler→DB→序列化。
	rec := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(rec)
	c.Request = httptest.NewRequest("GET", "/admin/users?page=1&size=10", nil)
	c.Set(auth.CtxUserID, int64(1))
	c.Set(auth.CtxTenantID, int64(1))
	r.ServeHTTP(rec, c)

	if rec.Code != 200 {
		t.Fatalf("期望 200，实得 %d body=%s", rec.Code, rec.Body.String())
	}
	var envelope struct {
		Code int             `json:"code"`
		Data json.RawMessage `json:"data"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &envelope); err != nil {
		t.Fatal(err)
	}
	if envelope.Code != 0 {
		t.Fatalf("包络 code 应为 0: %d", envelope.Code)
	}

	spec := mustSpec(t)
	op := spec.Find("GET", "/admin/users")
	if op == nil {
		t.Fatal("契约缺 GET /admin/users")
	}
	schema := oapi.ResolveDataSchema(op)
	var data any
	if err := json.Unmarshal(envelope.Data, &data); err != nil {
		t.Fatal(err)
	}
	if errs := oapi.Validate(data, schema); len(errs) > 0 {
		t.Fatalf("真响应违反契约: %v", errs)
	}
	// 安全断言：序列化后的响应体绝不含 password_hash 字段（mapper 已剔除）。
	body := rec.Body.String()
	if strings.Contains(body, "password_hash") || strings.Contains(body, "PasswordHash") {
		t.Fatalf("响应泄漏口令散列: %s", body)
	}
}
```

> 手法说明：不依赖 HTTP 中间件、直接 `c.Set(auth.CtxTenantID, …)` 复现数据域，是仓储 ABAC（粒度③）的单测范式（任务 9/10/11 同款）。`mustSpec`/`Find` 复用任务 4 `contract_test.go` 里同包定义的 `mustSpec`（两个 `_test.go` 同属 `package sysadmin`，可直接共用）。

- [ ] **步骤 2：运行确认为 SKIP（本地无库）**

运行：`cd backend-go && go build ./... && go test ./internal/modules/sysadmin/ -run TestIntegration -v`
预期：编译通过（无 unused）；未设 `ARK_TEST_DATABASE_URL` 时 `--- SKIP`。有库主机/CI：PASS 且响应体零契约违规。

- [ ] **步骤 3：写全栈 auth 冒烟脚本**

`scripts/compose-smoke-auth.sh`：

```bash
#!/usr/bin/env bash
# bcrypt 上线后的全栈鉴权冒烟：真实种子账号 → /auth/me 能力 → 管理员列用户 → 越权 403。
# 前提：docker compose up -d --build（backend 为 Go 镜像，已跑 000001+000002 迁移种子）。
# 覆盖地址用 SMOKE_BASE；本机无 Docker 时仅 CI/Docker 主机执行。
set -euo pipefail
BASE="${SMOKE_BASE:-http://127.0.0.1:8787}"
PY="${PYTHON:-python3}"

login() { # $1=user $2=pass -> echo token
  curl -fsS -X POST "$BASE/api/v1/auth/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"$1\",\"password\":\"$2\"}" \
    | "$PY" -c 'import sys,json;print(json.load(sys.stdin)["data"]["access_token"])'
}

echo "[1/5] healthz"
curl -fsS "$BASE/healthz" | grep -q '"ok":true'

echo "[2/5] 真实 bcrypt 登录(admin/Admin@123456)"
ADMIN_TOKEN=$(login admin 'Admin@123456')
[ -n "$ADMIN_TOKEN" ] || { echo "admin 未取得 token"; exit 1; }

echo "[3/5] /auth/me：角色含 R-ADMIN、caps 非空"
curl -fsS "$BASE/api/v1/auth/me" -H "Authorization: Bearer $ADMIN_TOKEN" \
  | "$PY" -c '
import sys,json
d=json.load(sys.stdin)
assert d["code"]==0, d
me=d["data"]
assert "R-ADMIN" in me["roles"], me["roles"]
assert len(me["caps"])>0, "caps 不应为空"
print("caps:", me["caps"][:3], "...")'

echo "[4/5] 管理员列用户：命中种子 admin（证明走真 handler 非 passthrough）"
curl -fsS "$BASE/api/v1/admin/users?page=1&size=50" -H "Authorization: Bearer $ADMIN_TOKEN" \
  | "$PY" -c '
import sys,json
d=json.load(sys.stdin)
assert d["code"]==0, d
names=[u["username"] for u in d["data"]["list"]]
assert "admin" in names, names
assert all("password_hash" not in u for u in d["data"]["list"]), "泄漏口令"
print("users:", names)'

echo "[5/5] 越权：R-STAFF 访问 admin 列表应 HTTP 403"
STAFF_TOKEN=$(login staff 'Staff@123456')
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/v1/admin/users" -H "Authorization: Bearer $STAFF_TOKEN")
[ "$code" = "403" ] || { echo "期望 403，实得 $code"; exit 1; }

echo "compose auth smoke OK"
```

赋可执行位：`chmod +x scripts/compose-smoke-auth.sh`（Windows/git-bash 下 `git update-index --chmod=+x scripts/compose-smoke-auth.sh`）。

- [ ] **步骤 4：语法校验（本机可做）**

运行：`bash -n scripts/compose-smoke-auth.sh && echo "syntax ok"`
预期：`syntax ok`。
**实跑 BLOCKED**（本机无 Docker）：需 `docker compose up -d --build` 起 postgres+redis+backend(Go)+frontend，待 backend healthy 后 `SMOKE_BASE=http://127.0.0.1:8787 bash scripts/compose-smoke-auth.sh`。此步留 CI/Docker 主机；本计划交付脚本本身。

- [ ] **步骤 5：后端全量回归**

运行：`cd backend-go && go build ./... && go vet ./... && go test ./... -count=1`
预期：编译/vet 无错；auth 包鉴权矩阵 PASS；无库环境 sysadmin 集成用例 SKIP；其余单测 PASS/SKIP。

- [ ] **步骤 6：Commit**

```bash
git add backend-go/internal/modules/sysadmin/integration_contract_test.go scripts/compose-smoke-auth.sh
git commit -m "test(go): sysadmin 真响应契约合规集成用例 + bcrypt 全栈 auth 冒烟脚本"
```

---

## Part E — 前端（登录态 · 守卫 · 菜单过滤 · 管理页）

前端无测试框架（`frontend/package.json` 只有 `typecheck`，无 vitest）；每个任务的「测试步骤」即 `cd frontend && npm run typecheck`（vue-tsc 全量类型检查）+ 必要时 `npm run build`。所有能力判定/守卫逻辑写成可被 typecheck 覆盖的纯 TS。

**能力串对齐（消歧 · 贯穿任务 15/18）**：`BuildCaps` 产出的能力是策略 obj **原样**（含 `/api/v1` 前缀、可能以 `/*` 通配），例：R-ADMIN 的 `"/api/v1/* GET"`、R-AUDITOR 的 `"/api/v1/admin/users GET"`。故前端 `auth.can(want)` 必须**容错匹配**：`want` 可写简写 `"/admin/users POST"`，内部补 `/api/v1` 前缀，并把授予项的 `/*` 后缀按「前缀命中」判定。这样同一 `can('/admin/users POST')` 对通配授予和精确授予都成立。`/auth/me` 的 `caps: string[]` 契约类型不变（任务 3），故 mock 模式下 generator 造的是随机串——按钮门控在 mock 下不作真值保证，仅真实后端（任务 19）生效；页面级 `meta.roles` 与后端传输层鉴权才是硬边界。

## 任务 15：`src/api/auth.ts` 组合式登录态 store（reactive 单例，无 pinia）

**文件：**
- 创建：`frontend/src/api/auth.ts`

- [ ] **步骤 1：写 store**

`frontend/src/api/auth.ts`：

```ts
/**
 * 登录态与权限能力单一来源（reactive 单例，项目无 pinia）。
 * token 落 localStorage（try/catch 兜底，隐私模式不崩）。
 * 与 client.ts 解耦：client 通过 setAuthProvider 注册取令牌/未授权回调，避免 auth↔client 循环 import。
 */
import { reactive } from 'vue'
import { api, setAuthProvider } from './client'

export interface MeUser {
  id: number
  username: string
  real_name?: string
  status?: string
  security_level?: string
  roles?: string[]
  [k: string]: unknown
}

interface AuthState {
  token: string
  user: MeUser | null
  roles: string[]
  caps: string[]
  ready: boolean // loadMe 成功过一次
}

const TOKEN_KEY = 'ark_token'

const state = reactive<AuthState>({
  token: '',
  user: null,
  roles: [],
  caps: [],
  ready: false,
})

function lsGet(k: string): string {
  try {
    return localStorage.getItem(k) ?? ''
  } catch {
    return ''
  }
}
function lsSet(k: string, v: string): void {
  try {
    if (v) localStorage.setItem(k, v)
    else localStorage.removeItem(k)
  } catch {
    /* 忽略：隐私模式/无 localStorage */
  }
}

// —— 能力容错匹配 ——
function withPrefix(p: string): string {
  if (p.startsWith('/api/v1')) return p
  return '/api/v1' + (p.startsWith('/') ? p : '/' + p)
}
function pathMatch(grantPath: string, wantPath: string): boolean {
  const g = withPrefix(grantPath)
  const w = withPrefix(wantPath)
  if (g === w) return true
  if (g.endsWith('/*')) return w.startsWith(g.slice(0, -1)) // "/api/v1/*" -> "/api/v1/"
  if (g.endsWith('*')) return w.startsWith(g.slice(0, -1))
  return false
}
// cap 形如 "<obj> <METHOD>"；拆最后一段为动作
function splitCap(cap: string): [string, string] {
  const i = cap.lastIndexOf(' ')
  if (i < 0) return [cap, '']
  return [cap.slice(0, i), cap.slice(i + 1)]
}
function matchAnyCap(caps: string[], want: string): boolean {
  const [wp, wa] = splitCap(want)
  const wantAct = wa.toUpperCase()
  for (const c of caps) {
    const [gp, ga] = splitCap(c)
    if (ga.toUpperCase() !== wantAct) continue
    if (pathMatch(gp, wp)) return true
  }
  return false
}

export const auth = {
  get token(): string {
    return state.token
  },
  get user(): MeUser | null {
    return state.user
  },
  get roles(): string[] {
    return state.roles
  },
  get caps(): string[] {
    return state.caps
  },
  get isAuthed(): boolean {
    return !!state.token
  },
  get isReady(): boolean {
    return state.ready
  },

  /** 应用启动时同步恢复令牌（角色/能力待 loadMe）。须在挂载 router 前调用。 */
  init(): void {
    state.token = lsGet(TOKEN_KEY)
    // 注册给 client：请求自动带 Bearer；401 触发登出
    setAuthProvider(
      () => state.token,
      () => auth.logout(),
    )
  },

  async login(username: string, password: string): Promise<void> {
    const res = await api.post<{ access_token: string; token_type?: string; expires_in?: number }>(
      '/auth/login',
      { username, password },
    )
    state.token = res.access_token
    lsSet(TOKEN_KEY, state.token)
    await this.loadMe()
  },

  async loadMe(): Promise<void> {
    if (!state.token) return
    const me = await api.get<{ user: MeUser; roles: string[]; caps: string[] }>('/auth/me')
    state.user = me.user
    state.roles = me.roles ?? []
    state.caps = me.caps ?? []
    state.ready = true
  },

  logout(): void {
    state.token = ''
    state.user = null
    state.roles = []
    state.caps = []
    state.ready = false
    lsSet(TOKEN_KEY, '')
  },

  /** 页面/菜单可见性判定：roles 为空视为「所有已登录可见」。 */
  hasAnyRole(roles: string[] | undefined): boolean {
    if (!roles || roles.length === 0) return true
    return roles.some((r) => state.roles.includes(r))
  },

  /** 按钮/操作级门控：want 可用简写 "/admin/users POST"。 */
  can(want: string): boolean {
    return matchAnyCap(state.caps, want)
  },
}
```

- [ ] **步骤 2：typecheck 确认 store 自身类型通过（client 需先有 `setAuthProvider`）**

运行：`cd frontend && npm run typecheck`
预期：FAIL——`setAuthProvider` 未在 `client.ts` 导出（任务 16 补）。故本任务与任务 16 步骤 1 顺序耦合：**先做任务 16 步骤 1（给 client.ts 加 `setAuthProvider`），再回来跑本步 typecheck**。若严格 TDD 想单跑，可在本步临时于 `client.ts` 追加 `export function setAuthProvider(_t: () => string, _u: () => void) {}` 空实现占位（任务 16 会替换成真实现）。

- [ ] **步骤 3：Commit**

```bash
git add frontend/src/api/auth.ts
git commit -m "feat(web): 组合式登录态 store(auth) —— token/roles/caps + 容错能力匹配"
```

---

## 任务 16：`client.ts` 真实 Bearer + 401 登出；`router/index.ts` 补 `meta.roles` + 管理路由 + `beforeEach` 守卫

**文件：**
- 修改：`frontend/src/api/client.ts`（`Authorization` 改从注册的 provider 取；401→登出并抛）
- 修改：`frontend/src/router/index.ts`（各路由 `meta.roles`；新增 `/admin/users`、`/admin/roles`、`/forbidden`；导出并注册 `beforeEach`）

- [ ] **步骤 1：`client.ts` 增 provider 注册 + 改请求头 + 401 处理**

在 `frontend/src/api/client.ts` 顶部（`API_PREFIX` 定义之后）加：

```ts
// —— 认证 provider（由 auth.init() 注册；避免 auth↔client 循环 import）——
let tokenProvider: () => string = () => ''
let onUnauthorized: () => void = () => {}
export function setAuthProvider(getToken: () => string, handle401: () => void): void {
  tokenProvider = getToken
  onUnauthorized = handle401
}
```

把 `request<T>` 里的 headers 构造改为（删掉硬编码 `Authorization: 'Bearer mock-jwt-dev'`）：

```ts
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(opts.headers || {}),
  }
  const t = tokenProvider()
  if (t) headers['Authorization'] = 'Bearer ' + t
```

并在 `const res = await fetch(...)` 之后、`if (!res.ok)` 之前插入 401 分支：

```ts
  if (res.status === 401) {
    onUnauthorized()
    throw new ApiError(40101, '未认证或令牌过期')
  }
```

> mock 模式说明：`VITE_USE_MOCK!=='false'` 时 fetch 被 mock 全量拦截，`tokenProvider()` 通常空串——不带 Authorization 也不影响 mock 造数（mock 不校验令牌）。接真后端（任务 19）时 auth.login 已存真令牌，自动带上。

- [ ] **步骤 2：`router/index.ts` 重写（meta.roles + 新路由 + 守卫）**

`frontend/src/router/index.ts`（整文件替换）：

```ts
import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { auth } from '@/api/auth'

// meta.roles：空/缺省 = 所有已登录可见；非空 = 命中任一角色才可达（页面/路由级粒度①）。
// meta.public = 免登录可达（/forbidden 需要在未导航成功时也能渲染）。
declare module 'vue-router' {
  interface RouteMeta {
    zh?: string
    en?: string
    roles?: string[]
    public?: boolean
  }
}

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/dash' },
  { path: '/dash', name: 'dash', meta: { zh: '工作台驾驶舱', en: 'DASHBOARD' }, component: () => import('@/views/DashView.vue') },
  { path: '/bigscreen', name: 'bigscreen', meta: { zh: '经费监督大屏', en: 'SUPERVISION SCREEN', roles: ['R-LEADER', 'R-FINANCE', 'R-AUDITOR', 'R-ADMIN'] }, component: () => import('@/views/BigscreenView.vue') },
  { path: '/guide', name: 'guide', meta: { zh: '申报指南', en: 'GUIDELINES' }, component: () => import('@/views/GuideView.vue') },
  { path: '/editor', name: 'editor', meta: { zh: '申报书撰写', en: 'APPLICATION EDITOR', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] }, component: () => import('@/views/EditorView.vue') },
  { path: '/review', name: 'review', meta: { zh: '评审工作台', en: 'PEER REVIEW', roles: ['R-MANAGER', 'R-EXPERT', 'R-ETHICS', 'R-LEADER', 'R-ADMIN'] }, component: () => import('@/views/ReviewView.vue') },
  { path: '/projects', name: 'projects', meta: { zh: '我的项目', en: 'MY PROJECTS', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] }, component: () => import('@/views/ProjectsView.vue') },
  { path: '/project/:id?', name: 'project', meta: { zh: '项目详情', en: 'PROJECT DETAIL' }, component: () => import('@/views/ProjectView.vue') },
  { path: '/expense', name: 'expense', meta: { zh: '报销填单', en: 'EXPENSE FORM', roles: ['R-STAFF', 'R-MANAGER', 'R-FINANCE'] }, component: () => import('@/views/ExpenseView.vue') },
  { path: '/claim', name: 'claim', meta: { zh: '成果认领', en: 'OUTPUT CLAIM', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] }, component: () => import('@/views/ClaimView.vue') },
  { path: '/transfer', name: 'transfer', meta: { zh: '转化看板', en: 'TECH TRANSFER', roles: ['R-MANAGER', 'R-LEADER', 'R-ADMIN'] }, component: () => import('@/views/TransferView.vue') },
  { path: '/procurement', name: 'procurement', meta: { zh: '采购与合同', en: 'PROCUREMENT & CONTRACT', roles: ['R-MANAGER', 'R-FINANCE', 'R-ADMIN'] }, component: () => import('@/views/ProcurementView.vue') },
  { path: '/asset', name: 'asset', meta: { zh: '资产与耗材台账', en: 'ASSET & CONSUMABLE', roles: ['R-MANAGER', 'R-FINANCE', 'R-ADMIN'] }, component: () => import('@/views/AssetView.vue') },
  { path: '/portrait', name: 'portrait', meta: { zh: 'PI 画像', en: 'RESEARCHER PORTRAIT', roles: ['R-LEADER', 'R-MANAGER', 'R-ADMIN'] }, component: () => import('@/views/PortraitView.vue') },
  // —— 模块 U 管理页（新）——
  { path: '/admin/users', name: 'admin-users', meta: { zh: '用户管理', en: 'USER ADMIN', roles: ['R-ADMIN'] }, component: () => import('@/views/admin/UsersView.vue') },
  { path: '/admin/roles', name: 'admin-roles', meta: { zh: '角色与权限', en: 'ROLES & PERMISSIONS', roles: ['R-ADMIN', 'R-AUDITOR'] }, component: () => import('@/views/admin/RolesView.vue') },
  // —— 越权兜底 ——
  { path: '/forbidden', name: 'forbidden', meta: { zh: '无访问权限', en: 'FORBIDDEN', public: true }, component: () => import('@/views/ForbiddenView.vue') },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// 路由/菜单级守卫（粒度①）：未登录→触发登录浮层(重定向到 /dash?needLogin)；越权→/forbidden。
router.beforeEach(async (to) => {
  if (to.meta.public) return true
  if (!auth.isAuthed) return { path: '/dash', query: { needLogin: '1' } }
  if (!auth.isReady) {
    try {
      await auth.loadMe()
    } catch {
      auth.logout()
      return { path: '/dash', query: { needLogin: '1' } }
    }
  }
  if (to.meta.roles && to.meta.roles.length > 0 && !auth.hasAnyRole(to.meta.roles)) {
    return { path: '/forbidden' }
  }
  return true
})

export default router
```

- [ ] **步骤 3：`main.ts` 挂载前 `auth.init()`**

`frontend/src/main.ts`：在 `import router from './router'` 之后、`bootstrap()` 调用前，加 `import { auth } from './api/auth'` 与一行 `auth.init()`（恢复令牌 + 注册 client provider）。守卫在首次导航即读到 `isAuthed`。

```ts
import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { auth } from './api/auth'
import './styles/prototype.css'
import './styles/app.css'

auth.init() // 同步恢复令牌 + 注册认证 provider（必须先于挂载 router/app）

async function bootstrap() {
  if (import.meta.env.VITE_USE_MOCK !== 'false') {
    const { installMock } = await import('./api/mock')
    installMock()
  }
  createApp(App).use(router).mount('#app')
}
bootstrap()
```

- [ ] **步骤 4：typecheck（新页面文件尚不存在会报错，先建空壳或延到任务 18）**

`router` 引用了 `@/views/admin/UsersView.vue`、`RolesView.vue`、`ForbiddenView.vue`。为使本任务可独立 typecheck 通过，**先创建三个最小可编译占位组件**（任务 18 再填实现）：

`frontend/src/views/ForbiddenView.vue`（本任务定稿，无需再改）：

```vue
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
```

`frontend/src/views/admin/UsersView.vue`、`frontend/src/views/admin/RolesView.vue`：先放「可编译空壳」，任务 18 用完整实现覆盖：

```vue
<script setup lang="ts"></script>
<template>
  <div class="card" style="padding:24px">加载中…（任务 18 落地实现）</div>
</template>
```

运行：`cd frontend && npm run typecheck`
预期：PASS（store、client、router、main、占位页类型齐备）。

- [ ] **步骤 5：Commit**

```bash
git add frontend/src/api/client.ts frontend/src/router/index.ts frontend/src/main.ts frontend/src/views/ForbiddenView.vue frontend/src/views/admin/UsersView.vue frontend/src/views/admin/RolesView.vue
git commit -m "feat(web): client 真实 Bearer+401 登出；router meta.roles 守卫 + 管理/越权路由；main 挂载 auth.init"
```

---

## 任务 17：`App.vue` 真实登录提交 + 按角色过滤侧栏 + 真实用户标识/登出

把装饰性登录浮层与固定 role-chip 接到 `auth`：提交走 `auth.login`、侧栏按 `hasAnyRole` 过滤、顶部显示真实用户名与角色并可退出。新增「系统」菜单分组承载用户/角色管理页入口。

**文件：**
- 修改：`frontend/src/App.vue`

- [ ] **步骤 1：改 `<script setup>`**

在 `frontend/src/App.vue` 的 `<script setup lang="ts">` 顶部 import 处把 `import { ref, computed } from 'vue'` 扩为 `import { ref, computed, reactive } from 'vue'`，并补 `import { auth } from '@/api/auth'`，然后把与登录/菜单相关的逻辑替换为下述（保留 `toast`、`crumbZh/en`、`go` 原样）：

```ts
const router = useRouter()
const route = useRoute()

// 登录浮层：未登录即显示；带 needLogin 查询(守卫回跳)时也强制显示。
const showLogin = computed(() => !auth.isAuthed || route.query.needLogin === '1')

// 登录表单（真实提交；reactive 使 v-model 生效）
const loginForm = reactive({ username: '', password: '' })
const logging = ref(false)
const loginErr = ref('')
async function submitLogin() {
  logging.value = true
  loginErr.value = ''
  try {
    await auth.login(loginForm.username.trim(), loginForm.password)
    // 清掉 needLogin，避免守卫再次拦截回跳
    await router.replace({ name: 'dash' })
    toast('登录成功 · 欢迎回来，' + (auth.user?.real_name || auth.user?.username || ''))
  } catch (e: any) {
    loginErr.value = e?.message || '账号或密码错误'
  } finally {
    logging.value = false
  }
}

function doLogout() {
  auth.logout()
  router.replace({ path: '/dash', query: { needLogin: '1' } })
  toast('已退出登录')
}

interface NavItem { v: string; ic: string; label: string; badge?: number; roles?: string[] }
interface NavGroup { t: string; items: NavItem[] }

const groups: NavGroup[] = [
  { t: '总 览', items: [
    { v: 'dash', ic: '◈', label: '工作台驾驶舱' },
    { v: 'bigscreen', ic: '▣', label: '经费监督大屏', roles: ['R-LEADER', 'R-FINANCE', 'R-AUDITOR', 'R-ADMIN'] },
  ]},
  { t: '项目管理', items: [
    { v: 'guide', ic: '◉', label: '申报指南', badge: 6 },
    { v: 'editor', ic: '✎', label: '申报书撰写', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] },
    { v: 'review', ic: '☰', label: '评审工作台', badge: 3, roles: ['R-MANAGER', 'R-EXPERT', 'R-ETHICS', 'R-LEADER', 'R-ADMIN'] },
    { v: 'projects', ic: '▦', label: '我的项目', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] },
    { v: 'project', ic: '◫', label: '项目详情' },
  ]},
  { t: '经费 · 成果', items: [
    { v: 'expense', ic: '¥', label: '报销填单', roles: ['R-STAFF', 'R-MANAGER', 'R-FINANCE'] },
    { v: 'claim', ic: '✧', label: '成果认领', badge: 12, roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] },
    { v: 'transfer', ic: '⇄', label: '转化看板', roles: ['R-MANAGER', 'R-LEADER', 'R-ADMIN'] },
  ]},
  { t: '资 产 · 采 购', items: [
    { v: 'procurement', ic: '⧉', label: '采购与合同', badge: 5, roles: ['R-MANAGER', 'R-FINANCE', 'R-ADMIN'] },
    { v: 'asset', ic: '▤', label: '资产与耗材台账', roles: ['R-MANAGER', 'R-FINANCE', 'R-ADMIN'] },
  ]},
  { t: '人 员', items: [
    { v: 'portrait', ic: '◍', label: 'PI 画像', roles: ['R-LEADER', 'R-MANAGER', 'R-ADMIN'] },
  ]},
  { t: '系 统', items: [
    { v: 'admin-users', ic: '⚑', label: '用户管理', roles: ['R-ADMIN'] },
    { v: 'admin-roles', ic: '⚙', label: '角色与权限', roles: ['R-ADMIN', 'R-AUDITOR'] },
  ]},
]

// 菜单可见性（粒度①）：登录后依 hasAnyRole 过滤，整组皆不可见则隐组。
const visibleGroups = computed(() =>
  groups
    .map((g) => ({ ...g, items: g.items.filter((it) => auth.hasAnyRole(it.roles)) }))
    .filter((g) => g.items.length > 0),
)

const userName = computed(() => auth.user?.real_name || auth.user?.username || '未登录')
const userSub = computed(() =>
  auth.roles.length ? auth.roles.map(roleLabel).join(' / ') : '访客',
)
const userAvatar = computed(() => (userName.value[0] || '访'))

const ROLE_LABEL: Record<string, string> = {
  'R-STAFF': '研究员', 'R-MANAGER': '主管', 'R-LEADER': '领导',
  'R-FINANCE': '财务', 'R-AUDITOR': '审计', 'R-EXPERT': '评审专家',
  'R-ETHICS': '伦理委员', 'R-ADMIN': '系统管理员',
}
function roleLabel(r: string): string {
  return ROLE_LABEL[r] || r
}
```

删除旧的 `const showLogin = ref(...)`、`interface NavItem/NavGroup` 旧定义、旧 `groups`、旧 `enter()`。`crumbZh/crumbEn/go/toast` 保留。

- [ ] **步骤 2：改 `<template>`（登录浮层绑定 + 侧栏用 visibleGroups + 真实用户条）**

登录卡输入与按钮改为受控：

```html
      <h2>科研管理系统</h2>
      <div class="sub">ResearchOS · Scientific Research Management · V9</div>
      <div class="fld"><label>账号</label><input v-model="loginForm.username" placeholder="请输入登录账号" @keyup.enter="submitLogin" /></div>
      <div class="fld"><label>密码</label><input type="password" v-model="loginForm.password" placeholder="••••••••" @keyup.enter="submitLogin" /></div>
      <div v-if="loginErr" style="color:#c0392b;font-size:13px;margin:-4px 0 8px">{{ loginErr }}</div>
      <button class="btn seal login-btn" :disabled="logging" @click="submitLogin">{{ logging ? '登录中…' : '登 录' }}</button>
      <div class="login-foot">演示账号 <b>admin/Admin@123456</b> · <b>staff/Staff@123456</b> · <b>finance/Finance@123456</b></div>
```

（删除登录卡里的 `<span class="login-close" @click="enter">✕</span>`——未登录不允许点叉绕过；`login-wrap` 的 `:class="{ on: showLogin }"` 保留。）

侧栏 `v-for` 由 `groups` 改 `visibleGroups`：

```html
      <nav class="nav">
        <div class="nav-group" v-for="g in visibleGroups" :key="g.t">
          <div class="t">{{ g.t }}</div>
          <div class="nav-item" :class="{ active: route.name === item.v }"
               v-for="item in g.items" :key="item.v" @click="go(item.v)">
            <span class="ic">{{ item.ic }}</span>{{ item.label }}
            <span class="bdg" v-if="item.badge">{{ item.badge }}</span>
          </div>
        </div>
      </nav>
```

顶部用户条换真实信息 + 退出：

```html
        <div class="role-chip" @click="doLogout" title="点击退出登录">
          <div class="av">{{ userAvatar }}</div>
          <div class="nm"><b>{{ userName }}</b><span>{{ userSub }}</span></div>
        </div>
```

删除旧 `bell` 的演示角色切换 `toast` 文案与写死的「周明远/研究员」。

- [ ] **步骤 3：typecheck**

运行：`cd frontend && npm run typecheck`
预期：PASS（`loginForm` 已 `reactive`、`showLogin/visibleGroups/userName/...` 均为 `computed`，模板 `v-model`/`v-for` 类型齐备；`auth` 与 `api` 已由任务 15/16 提供）。若报 `reactive` 未使用或 `ref/computed` 缺 import，核对步骤 1 的 import 扩展行。

- [ ] **步骤 4：Commit**

```bash
git add frontend/src/App.vue
git commit -m "feat(web): App.vue 真实登录提交+角色过滤侧栏+真实用户条/登出；系统菜单分组"
```

---

## 任务 18：用户管理页 + 角色权限页 + `v-perm` 按钮门控指令

三个前端产物：**① `views/admin/UsersView.vue`**——列表/分页/按用户名筛选 + 新建/编辑抽屉 + 停用（软删 `status=DISABLED` 或 DELETE）+ 角色分配/回收；**② `views/admin/RolesView.vue`**——8 基础角色目录（`/admin/roles`）+ 每角色可见页面只读矩阵（镜像 `meta.roles`）+ 当前用户能力清单（`/auth/me` caps）；**③ `directives/perm.ts`**——`v-perm="'/admin/users POST'"` 依 `auth.can()` 对按钮/操作级（粒度②）禁用或移除元素。所有形状对齐 `design/12`（本地声明 TS 接口，无跨端类型生成）。**注意 `UserUpdateRequest` 不含 `roles`**——角色变更只走 `POST /admin/users/{id}/roles` 与 `DELETE /admin/users/{id}/roles/{roleId}`，编辑抽屉资料/状态/口令与角色分配分开。

**文件：**
- 创建：`frontend/src/views/admin/UsersView.vue`
- 创建：`frontend/src/views/admin/RolesView.vue`
- 创建：`frontend/src/directives/perm.ts`
- 修改：`frontend/src/main.ts`（注册 `v-perm` 指令）

- [ ] **步骤 1：`v-perm` 指令**

`frontend/src/directives/perm.ts`：

```ts
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
```

> 说明：`caps` 在 `loadMe` 后为**响应式** `state.caps`，但指令默认不订阅响应式源。管理页进入即已登录且 caps 就绪，`mounted/updated` 求值足够；若需登录态变化后实时刷新按钮，可在宿主组件用 `:key="auth.caps.length"` 或在 `v-if="auth.can(...)"` 处直接条件渲染（本计划 UsersView 的写操作按钮即用 `v-if`/`v-perm` 混合作演示）。

- [ ] **步骤 2：`main.ts` 注册指令**

`frontend/src/main.ts` 的 `import { auth }` 之后加 `import { perm } from './directives/perm'`；把挂载行改为：

```ts
  createApp(App).use(router).directive('perm', perm).mount('#app')
```

- [ ] **步骤 3：`UsersView.vue` 完整实现**

`frontend/src/views/admin/UsersView.vue`：

```vue
<script setup lang="ts">
import { reactive, ref, computed, onMounted } from 'vue'
import { api, list, ApiError } from '@/api/client'
import { auth } from '@/api/auth'

interface User {
  id: number
  username: string
  real_name: string
  email?: string | null
  phone?: string | null
  staff_no?: string | null
  employment_status?: string
  security_level?: string
  status?: 'ACTIVE' | 'LOCKED' | 'DISABLED'
  tenant_id?: number
  legal_entity_id?: number | null
  roles: string[]
  created_at?: string
  updated_at?: string
}
interface Role {
  id: number
  code: string
  name: string
  is_builtin?: boolean
  tenant_id?: number
}

// —— 列表状态 ——
const rows = ref<User[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const keyword = ref('')
const loading = ref(false)
const err = ref('')

const ROLE_OPTIONS = [
  'R-STAFF', 'R-MANAGER', 'R-LEADER', 'R-FINANCE',
  'R-AUDITOR', 'R-EXPERT', 'R-ETHICS', 'R-ADMIN',
]
const rolesCatalog = ref<Role[]>([])

const canCreate = computed(() => auth.can('/admin/users POST'))
const canWrite = computed(() => auth.can('/admin/users PUT') || auth.can('/admin/users DELETE'))

async function reload() {
  loading.value = true
  err.value = ''
  try {
    const params: Record<string, any> = { page: page.value, size: size.value }
    if (keyword.value.trim()) params.q = keyword.value.trim()
    const r = await list<User>('/admin/users', params)
    rows.value = r.rows
    total.value = r.total
  } catch (e: any) {
    err.value = (e as ApiError)?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadRoles() {
  try {
    const d = await api.get<{ list: Role[] }>('/admin/roles')
    rolesCatalog.value = d?.list ?? []
  } catch {
    rolesCatalog.value = []
  }
}

function goPage(p: number) {
  const max = Math.max(1, Math.ceil(total.value / size.value))
  page.value = Math.min(Math.max(1, p), max)
  reload()
}

// —— 抽屉表单 ——
const drawer = reactive({ open: false, mode: 'create' as 'create' | 'edit' })
const form = reactive({
  id: 0,
  username: '',
  real_name: '',
  password: '',
  email: '',
  phone: '',
  staff_no: '',
  security_level: 'INTERNAL',
  employment_status: 'ONBOARD',
  status: 'ACTIVE' as 'ACTIVE' | 'LOCKED' | 'DISABLED',
  roles: [] as string[],
})

function openCreate() {
  drawer.mode = 'create'
  Object.assign(form, {
    id: 0, username: '', real_name: '', password: '', email: '', phone: '', staff_no: '',
    security_level: 'INTERNAL', employment_status: 'ONBOARD', status: 'ACTIVE', roles: [],
  })
  drawer.open = true
}

function openEdit(u: User) {
  drawer.mode = 'edit'
  Object.assign(form, {
    id: u.id, username: u.username, real_name: u.real_name,
    password: '', email: u.email ?? '', phone: u.phone ?? '', staff_no: u.staff_no ?? '',
    security_level: u.security_level ?? 'INTERNAL',
    employment_status: u.employment_status ?? 'ONBOARD',
    status: (u.status as any) ?? 'ACTIVE',
    roles: [...(u.roles ?? [])],
  })
  drawer.open = true
}

const saving = ref(false)
async function save() {
  saving.value = true
  err.value = ''
  try {
    if (drawer.mode === 'create') {
      const created = await api.post<User>('/admin/users', {
        username: form.username, real_name: form.real_name, password: form.password,
        email: form.email || undefined, phone: form.phone || undefined, staff_no: form.staff_no || undefined,
        security_level: form.security_level, employment_status: form.employment_status,
        roles: form.roles,
      })
      // 角色已在 create 内绑定（后端 CreateUser 处理 roles[]）
      ;(window as any).toast?.('已创建用户 ' + created.username)
    } else {
      const body: Record<string, any> = {
        real_name: form.real_name, email: form.email || null, phone: form.phone || null,
        security_level: form.security_level, status: form.status,
      }
      if (form.password) body.password = form.password // 给出即重设
      await api.put<User>(`/admin/users/${form.id}`, body)
      await syncRoles(form.id, form.roles)
      ;(window as any).toast?.('已更新用户')
    }
    drawer.open = false
    await reload()
  } catch (e: any) {
    err.value = (e as ApiError)?.message || '保存失败'
  } finally {
    saving.value = false
  }
}

// 编辑：目标角色集 vs 现有 → 差异调用 assign/revoke
async function syncRoles(userId: number, target: string[]) {
  const cur = rows.value.find((r) => r.id === userId)?.roles ?? []
  const add = target.filter((r) => !cur.includes(r))
  const del = cur.filter((r) => !target.includes(r))
  for (const code of add) {
    const role = rolesCatalog.value.find((x) => x.code === code)
    if (!role) continue
    await api.post(`/admin/users/${userId}/roles`, { role_id: role.id })
  }
  for (const code of del) {
    const role = rolesCatalog.value.find((x) => x.code === code)
    if (!role) continue
    await api.del(`/admin/users/${userId}/roles/${role.id}`)
  }
}

async function disable(u: User) {
  if (!confirm(`确认停用「${u.real_name || u.username}」？`)) return
  try {
    await api.put(`/admin/users/${u.id}`, { status: 'DISABLED' })
    ;(window as any).toast?.('已停用')
    await reload()
  } catch (e: any) {
    err.value = (e as ApiError)?.message || '操作失败'
  }
}

onMounted(async () => {
  await loadRoles()
  await reload()
})
</script>

<template>
  <div class="card" style="padding:18px">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
      <h3 style="margin:0">用户管理</h3>
      <input v-model="keyword" placeholder="按用户名/姓名检索" @keyup.enter="page=1;reload()"
             style="flex:1;max-width:280px" />
      <button class="btn" @click="reload">刷新</button>
      <button class="btn seal" v-if="canCreate" @click="openCreate">＋ 新建用户</button>
    </div>
    <div v-if="err" style="color:#c0392b;margin-bottom:8px">{{ err }}</div>

    <table class="tbl" width="100%" style="border-collapse:collapse">
      <thead>
        <tr style="text-align:left">
          <th>账号</th><th>姓名</th><th>状态</th><th>密级</th><th>角色</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="u in rows" :key="u.id" :style="{opacity: u.status==='DISABLED'?.45:1}">
          <td>{{ u.username }}</td>
          <td>{{ u.real_name }}</td>
          <td>{{ u.status }}</td>
          <td>{{ u.security_level }}</td>
          <td>{{ (u.roles||[]).join(' · ') }}</td>
          <td>
            <button class="btn sm" v-if="canWrite" @click="openEdit(u)">编辑</button>
            <button class="btn sm" v-perm="'/admin/users PUT'"
                    v-if="u.status!=='DISABLED'" @click="disable(u)">停用</button>
          </td>
        </tr>
        <tr v-if="!rows.length"><td colspan="6" style="opacity:.6;padding:16px">{{ loading?'加载中…':'暂无数据' }}</td></tr>
      </tbody>
    </table>

    <div style="display:flex;gap:8px;align-items:center;margin-top:12px">
      <button class="btn sm" :disabled="page<=1" @click="goPage(page-1)">上一页</button>
      <span>第 {{ page }} 页 / 共 {{ Math.max(1,Math.ceil(total/size)) }} 页（{{ total }} 条）</span>
      <button class="btn sm" :disabled="page>=Math.ceil(total/size)" @click="goPage(page+1)">下一页</button>
    </div>

    <!-- 抽屉 -->
    <div v-if="drawer.open" class="drawer-mask" style="position:fixed;inset:0;background:rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;z-index:60">
      <div class="drawer" style="background:#fff;width:min(520px,92vw);max-height:88vh;overflow:auto;padding:20px;border-radius:10px">
        <h3 style="margin-top:0">{{ drawer.mode==='create'?'新建用户':'编辑用户' }}</h3>
        <div class="fld"><label>账号</label><input v-model="form.username" :disabled="drawer.mode==='edit'" /></div>
        <div class="fld"><label>姓名</label><input v-model="form.real_name" /></div>
        <div class="fld"><label>{{ drawer.mode==='create'?'初始密码':'重置密码(留空不改)' }}</label>
          <input v-model="form.password" type="password" :required="drawer.mode==='create'" /></div>
        <div class="fld"><label>邮箱</label><input v-model="form.email" /></div>
        <div class="fld"><label>手机</label><input v-model="form.phone" /></div>
        <div class="fld"><label>密级</label>
          <select v-model="form.security_level">
            <option value="PUBLIC">PUBLIC</option><option value="INTERNAL">INTERNAL</option>
            <option value="SECRET">SECRET</option><option value="TOP_SECRET">TOP_SECRET</option>
          </select></div>
        <div class="fld" v-if="drawer.mode==='edit'"><label>状态</label>
          <select v-model="form.status">
            <option value="ACTIVE">ACTIVE</option><option value="LOCKED">LOCKED</option><option value="DISABLED">DISABLED</option>
          </select></div>
        <div class="fld"><label>角色</label>
          <div style="display:flex;flex-wrap:wrap;gap:6px">
            <label v-for="r in ROLE_OPTIONS" :key="r" style="display:flex;align-items:center;gap:4px">
              <input type="checkbox" :value="r" v-model="form.roles" />{{ r }}
            </label>
          </div>
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
          <button class="btn" @click="drawer.open=false">取消</button>
          <button class="btn seal" :disabled="saving" @click="save">{{ saving?'保存中…':'保存' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **步骤 4：`RolesView.vue` 完整实现**

`frontend/src/views/admin/RolesView.vue`：

```vue
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api } from '@/api/client'
import { auth } from '@/api/auth'

interface Role { id: number; code: string; name: string; is_builtin?: boolean; tenant_id?: number }
const roles = ref<Role[]>([])
const loading = ref(false)
const err = ref('')

// 角色 → 可见页面（镜像 router meta.roles；粒度①的只读呈现，非后端 caps）
const PAGES: Array<{ name: string; zh: string; roles: string[] }> = [
  { name: 'dash', zh: '工作台', roles: [] },
  { name: 'bigscreen', zh: '监督大屏', roles: ['R-LEADER', 'R-FINANCE', 'R-AUDITOR', 'R-ADMIN'] },
  { name: 'editor', zh: '申报撰写', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] },
  { name: 'review', zh: '评审工作台', roles: ['R-MANAGER', 'R-EXPERT', 'R-ETHICS', 'R-LEADER', 'R-ADMIN'] },
  { name: 'expense', zh: '报销填单', roles: ['R-STAFF', 'R-MANAGER', 'R-FINANCE'] },
  { name: 'claim', zh: '成果认领', roles: ['R-STAFF', 'R-MANAGER', 'R-LEADER'] },
  { name: 'procurement', zh: '采购合同', roles: ['R-MANAGER', 'R-FINANCE', 'R-ADMIN'] },
  { name: 'asset', zh: '资产台账', roles: ['R-MANAGER', 'R-FINANCE', 'R-ADMIN'] },
  { name: 'portrait', zh: 'PI 画像', roles: ['R-LEADER', 'R-MANAGER', 'R-ADMIN'] },
  { name: 'admin-users', zh: '用户管理', roles: ['R-ADMIN'] },
  { name: 'admin-roles', zh: '角色权限', roles: ['R-ADMIN', 'R-AUDITOR'] },
]

function canSeePage(role: string, p: { roles: string[] }): boolean {
  if (p.roles.length === 0) return true // 所有已登录可见
  if (p.roles.includes(role)) return true
  if (role === 'R-ADMIN') return true // 超管兜底（与后端 /api/v1/* 对齐）
  return false
}

// 当前登录用户自身能力（粒度②），来自 /auth/me
const myCaps = computed(() => auth.caps)
const isAdmin = computed(() => auth.roles.includes('R-ADMIN'))

async function reload() {
  loading.value = true
  err.value = ''
  try {
    const d = await api.get<{ list: Role[] }>('/admin/roles')
    roles.value = d?.list ?? []
  } catch (e: any) {
    err.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(reload)
</script>

<template>
  <div class="card" style="padding:18px">
    <h3 style="margin-top:0">角色与权限</h3>
    <div v-if="err" style="color:#c0392b">{{ err }}</div>
    <p style="opacity:.7;font-size:13px">
      页面可见性为静态配置（镜像路由 <code>meta.roles</code>，粒度①）；「我的能力」为后端 <code>/auth/me</code> 依 Casbin 策略派生的按钮/操作级集合（粒度②）。本轮角色↔权限不入库、不可在线编辑（P-U1-dyn）。
    </p>

    <h4>角色目录（{{ roles.length }}）</h4>
    <table class="tbl" style="border-collapse:collapse;width:100%;margin-bottom:18px">
      <thead><tr style="text-align:left"><th>code</th><th>名称</th><th>内置</th></tr></thead>
      <tbody>
        <tr v-for="r in roles" :key="r.id">
          <td>{{ r.code }}</td><td>{{ r.name }}</td>
          <td>{{ r.is_builtin ? '是' : '否' }}</td>
        </tr>
        <tr v-if="!roles.length"><td colspan="3" style="opacity:.6">{{ loading?'加载中…':'无' }}</td></tr>
      </tbody>
    </table>

    <h4>页面可见性矩阵</h4>
    <div style="overflow:auto">
      <table class="tbl" style="border-collapse:collapse;font-size:13px">
        <thead>
          <tr>
            <th>页面 \ 角色</th>
            <th v-for="r in roles" :key="r.code" style="text-align:center">{{ r.code.replace('R-','') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in PAGES" :key="p.name">
            <td>{{ p.zh }}</td>
            <td v-for="r in roles" :key="r.code" style="text-align:center">
              {{ canSeePage(r.code, p) ? '✓' : '·' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <h4 style="margin-top:18px">我的能力（当前登录 · {{ auth.roles.join('/') || '无' }}）</h4>
    <div v-if="isAdmin" style="opacity:.7;font-size:12px;margin-bottom:6px">R-ADMIN 拥有 <code>/api/v1/*</code> 通配能力，列表为策略原文截取。</div>
    <div style="display:flex;flex-wrap:wrap;gap:6px">
      <span v-for="c in myCaps" :key="c"
            style="background:#eef;border-radius:4px;padding:2px 6px;font-size:12px">{{ c }}</span>
      <span v-if="!myCaps.length" style="opacity:.6">（无 / 尚未加载）</span>
    </div>
  </div>
</template>
```

- [ ] **步骤 5：typecheck + 构建**

运行：`cd frontend && npm run typecheck && npm run build`
预期：typecheck PASS；`vite build` 成功产出 `dist/`（`UsersView`/`RolesView`/`perm`/`ForbiddenView` 编译进分包）。
> `list<User>` 的 `params` 里我传了 `q`（关键字）——后端 `ListUsers`（任务 9）当前按 `optQuery` 白名单过滤（username/status 等）。若后端未支持 `q`，多余 query 参数被 mock/后端忽略即可（不影响返回）；关键字真正生效依赖后端加 `username ILIKE` 过滤（P-U1 之后）。本任务前端先把检索框接上，行为降级为「客户端不过滤/后端忽略」不报错。

- [ ] **步骤 6：Commit**

```bash
git add frontend/src/views/admin/UsersView.vue frontend/src/views/admin/RolesView.vue frontend/src/directives/perm.ts frontend/src/main.ts
git commit -m "feat(web): 用户管理页/角色权限页 + v-perm 操作级门控指令"
```

---

## 任务 19：切换到真实后端（关 mock + 开发代理）与端到端联调

前端逻辑已「契约无关后端」：mock 与真后端同构，切真只需关 mock。`main.ts` 已按 `VITE_USE_MOCK` 条件动态 import mock，`vite.config.ts` 已配 `/api → http://127.0.0.1:8787` 代理（`changeOrigin:true`）。本任务把默认开发/构建环境显式设为关 mock，并串起 bcrypt 登录→守卫→菜单过滤→管理页的端到端。**实跑 BLOCKED（本机无 Docker/无 Go 服务）**：需要 `docker compose up -d --build`（含 backend=Go 镜像，跑 000001+000002 迁移种子）或本地起 Go 服务；本任务交付配置与联调清单，验证留 Docker 主机/CI。

**文件：**
- 创建/修改：`frontend/.env.development`（`VITE_USE_MOCK=false`，联调期）
- 创建/修改：`frontend/.env.production`（`VITE_USE_MOCK=false`，生产关 mock）
- 只读确认：`frontend/vite.config.ts`（代理已在，无需改）

- [ ] **步骤 1：写关 mock 的环境文件**

`frontend/.env.development`：

```
# 联调真实后端：关 mock 拦截，/api 走 vite 代理到 :8787（Go 服务）。
VITE_USE_MOCK=false
```

`frontend/.env.production`：

```
# 生产构建：关 mock，接口同构打真实后端。
VITE_USE_MOCK=false
```

> 若仓库已存在这两个文件且含 `VITE_USE_MOCK=true`，改成 `false` 并保留其它变量。`.env.*` 是构建期内联变量（`VITE_USE_MOCK` 为 vite 构建期常量），关 mock 须在 build/dev 时生效——沿用 M0 结论。

- [ ] **步骤 2：构建产物验证主包瘦身（本机可做）**

运行：`cd frontend && npm run build`
预期：成功。因 `VITE_USE_MOCK=false`，`main.ts` 条件分支不动态 import mock，faker/generator/契约 yaml 依赖不进主包（M0 实测主包 ~102KB、mock 独立异步块）。此步本机可跑（纯前端构建，不需后端）。

- [ ] **步骤 3：端到端联调清单（BLOCKED：需后端 + DB）**

在有 Docker 主机执行 `docker compose up -d --build`，随后：

1. 打开前端（`http://127.0.0.1:5178` 或 compose 暴露端口）。首屏因 `auth.init()` 无令牌 → 守卫回 `/dash?needLogin` → 登录浮层出现。
2. 用 `admin/Admin@123456` 登录 → `auth.login` 打 `POST /api/v1/auth/login`（bcrypt 校验 DB）→ 存令牌 → `loadMe` 拉 `/auth/me`（角色 `R-ADMIN` + 能力）→ 浮层关闭。
3. 侧栏出现全部菜单含「系统」组（用户管理/角色权限）；进 `/admin/users` 见种子 4 用户，新建/编辑/停用/分配角色可用。
4. 退出，换 `staff/Staff@123456` 登录 → 「系统」组隐藏；手输 `#/admin/users` → 守卫 `hasAnyRole(['R-ADMIN'])` 失败 → 跳 `/forbidden`；即便绕过前端，后端 `middleware.Auth` 对 R-STAFF `GET /api/v1/admin/users` 也 403（双保险，任务 13 已证）。
5. 浏览器 Network 核对 `Authorization: Bearer <真令牌>` 自动附带（`setAuthProvider`）。

复跑脚本级验证（可选）：`SMOKE_BASE=http://127.0.0.1:8787 bash scripts/compose-smoke-auth.sh`（任务 14 已交付）。

- [ ] **步骤 4：前端全量校验（本机）**

运行：`cd frontend && npm run typecheck && npm run build`
预期：PASS + 构建成功。

- [ ] **步骤 5：Commit**

```bash
git add frontend/.env.development frontend/.env.production
git commit -m "chore(web): 关 mock 切真实后端(.env)，联调清单与主包瘦身分册"
```

---

## Part F — 收尾与全量验证

## 任务 20：端到端全量验证 + Definition-of-Done 对账

跨前后端跑一遍「契约→后端→前端」一致性，并把四条锁定决策 + 三种权限粒度逐项对账到已交付任务，确认无遗漏、无漂移。本机可跑项（`go build/vet/test`、`npm typecheck/build`、契约漂移）全部执行；依赖 Docker/真库项标 BLOCKED 留 CI。

**文件：** 无新增（纯验证）。

- [ ] **步骤 1：后端全量（本机）**

运行：
```bash
cd backend-go
go build ./...
go vet ./...
go test ./... -count=1
```
预期：build/vet 无错；单测 PASS、集成用例在无 `ARK_TEST_DATABASE_URL` 时 SKIP、compose 相关不在本地跑。auth 包鉴权矩阵（任务 13）PASS；`sysadmin` 契约静态测试（任务 4）PASS；`TestBuild_SysadminFallsBackToPassthrough`（任务 12）PASS。

- [ ] **步骤 2：DAL 生成漂移守卫（本机可生成，比对留 CI）**

运行（需 sqlc 的 go1.23.4 工具链）：
```bash
cd backend-go
GOTOOLCHAIN=go1.23.4 go run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate
git diff --exit-code -- internal/modules/p/store internal/modules/sysadmin/store migrations/000001_init.up.sql
```
预期：`generate` 无报错；`git diff --exit-code` 返回 0（提交态与再生成一致，钉住「codegen 产物入库、CI 防漂移」）。若本机不便跑 sqlc，此步由 CI 的 `make drift` 覆盖。

- [ ] **步骤 3：迁移漂移守卫**

运行：`cd backend-go && go generate ./migrations/... && git diff --exit-code -- migrations/000001_init.up.sql migrations/000001_init.down.sql`
预期：0（`000001` 由 `gen.go` 从 `design/*.sql` 重生成一致；`000002_seed_auth` 为手写种子，`WriteFiles` 只写 `000001`，不受 regen 影响——任务 1/2 已保证）。`gen_test.go` 的 `TestGenerateUp_HasPasswordHash`（任务 1）PASS。

- [ ] **步骤 4：前端全量（本机）**

运行：
```bash
cd frontend
npm run typecheck
npm run build
```
预期：typecheck PASS；`vite build` 成功，`dist/` 产出，主包因 `VITE_USE_MOCK=false` 不含 mock 依赖（任务 19 步骤 2 已证）。

- [ ] **步骤 5：契约↔前端副本一致性校验（本机）**

运行：`diff -q design/12-用户与权限-U.openapi.yaml frontend/src/api/schema/12-用户与权限-U.openapi.yaml && echo "contract synced"`
预期：`contract synced`（任务 3/12 的 cp 同步未漂移；mock 读的是前端副本，两套必须逐字节一致）。

- [ ] **步骤 6：全栈 compose 冒烟（BLOCKED：无 Docker）**

在 Docker 主机/CI：
```bash
docker compose up -d --build
# 等 backend healthy
SMOKE_BASE=http://127.0.0.1:8787 bash scripts/compose-smoke-auth.sh
```
预期：`compose auth smoke OK`（真实 bcrypt 登录、`/auth/me` 角色+能力、管理员列用户命中种子 `admin`、越权 R-STAFF→403）。本机标 **BLOCKED**（无 Docker），验证留 Docker 主机/CI。

- [ ] **步骤 7：Commit（若前述守卫触发的重生成/微调）**

```bash
git add -A
git commit -m "chore: 用户管理与权限(U)全量验证通过，锁定 codegen/migration/contract 无漂移"
```

---

## Definition-of-Done 对账（四条锁定决策 × 三种权限粒度）

**四条锁定决策**

| 决策 | 落点任务 | 完成判据 |
|---|---|---|
| 范围 = **全栈完整多页** | 任务 1-20 全覆盖 | 后端 sysadmin 用户 CRUD/角色目录/授权 + `/auth/me` 能力 + bcrypt 登录 + 契约 `12-U` + 前端登录态/守卫/菜单过滤/用户页/角色页/越权页；compose 里 backend 仍是唯一 Go 服务 |
| 登录 = **本轮加 bcrypt 真实登录** | 任务 1（`password_hash` 列）、任务 2（真实哈希种子）、任务 7（`NewLoginHandler` bcrypt + dev 回退）、任务 14（auth 冒烟） | 带库后端登录经 bcrypt 校验，非硬编码；`Pool==nil` 保留 `ark/ark` 使无库单测零回归；冒烟用 `admin/Admin@123456` 真口令 |
| 策略源 = **继续 policy.csv**（不入库、不建菜单/权限表） | 任务 13（扩策略）、任务 8（`BuildCaps` 读 `GetPolicy`）、任务 5/9（仓储不建 `casbin_rule`/`sys_menu`） | 全链路策略仍来自 `internal/platform/auth/policy.csv`；DDL 无 `casbin_rule`/`sys_menu`/`sys_permission`；P-U1-dyn 再动态化 |
| 粒度 = **路由/菜单 + 按钮/操作 + 数据可见性 ABAC（三者全要）** | 见下表 | 三种粒度各有独立实现与判据 |

**三种权限粒度**

| 粒度 | 机制 | 落点任务 | 判据 |
|---|---|---|---|
| ① 路由/菜单级 | 前端 `router/index.ts` `meta.roles` + `beforeEach` 守卫 + 侧栏 `hasAnyRole` 过滤 | 任务 16（meta.roles/守卫）、任务 17（菜单过滤） | R-STAFF 进 `#/admin/users` 被守卫拒 → `/forbidden`；无权限菜单项不渲染 |
| ② 按钮/操作级 | 后端 `GET /auth/me` 依 `policy.csv` `GetPolicy` 派生 `caps[]`；前端 `auth.can()` + `v-perm` | 任务 8（BuildCaps）、任务 9（GetMe）、任务 13（策略）、任务 15（can 容错匹配）、任务 18（v-perm/按钮） | R-AUDITOR 的 caps 无写动作 → 用户页写按钮禁用/隐藏；`TestBuildCaps_NoWritesForAuditor` 守住 |
| ③ 数据可见性 ABAC | 仓储层强制 `auth.DomainFrom(c).TenantID` 作首参；`security_level` 写入落列、读取谓词留 hook | 任务 9/10/11（Handler 注入 TenantID + `security_level` 落列/注释 hook） | 跨租户行天然不可见（查询按 tenant_id 过滤）；无库时用 dev 回退 tenant=1 |
| （传输层）API 鉴权 | 现有 `middleware.Auth`：JWT 解析 + Casbin `Enforce(role, fullPath, method)` | 任务 13（策略矩阵）、任务 12（挂受保护组） | 越权请求后端直接 403（任务 14 冒烟第 5 步证明前端绕不过） |

**明确不在本轮（YAGNI，登记后续计划）**：`casbin_rule` 持久化、在线策略/角色编辑 UI、`sys_menu`/`sys_permission` 表、自助改密/找回、`sys_org` 部门树、三员强制分立、跨法人数据域细分、`ListUsers` 关键字 ILIKE 服务端过滤（任务 18 前端先接检索框，后端过滤留 P-U1+）。这些与 M0 解耦表（§0）中的 P-U1-dyn / P-U2-org 对齐。

---

## 执行移交（writing-plans 收尾：二选一）

计划已保存至 `docs/superpowers/plans/2026-10-14-user-management.md`。共 **20 个任务 / 6 个 Part**，每个任务含确切文件路径、完整可编译代码、TDD 步骤（失败测试→确认失败→最小实现→确认通过→commit）与本机/CI 可跑性标注。下一步执行有两种方式：

**方式一 · 子 Agent 驱动（推荐）** —— 我按任务顺序为每个任务 dispatch 一个全新 subagent（携带该任务全文 + 相关上下文），任务间做两阶段审查（实现者自检 + 我复核），快速迭代、上下文隔离。适合本计划这种任务边界清晰、代码量大的场景。

**方式二 · 顺序执行** —— 在当前 session 按任务 1→20 顺序实现，每个任务后跑验证再 commit，批次处设检查点。

无论哪种：遵循既有约定——**不自动推 master**，工作在 `develop`；是否把本计划文档 commit 进 `develop`、是否发起 PR/merge 均留你确认。本机无 Docker/真库的项（任务 7/8/9/10/11 的连库集成用例、任务 14/19 的 compose 起服）执行时如实标 **BLOCKED** 留 CI/Docker 主机，其余本机可验证。

要选哪种执行方式？
