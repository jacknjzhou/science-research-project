# 后端重写规格说明（SPEC）：backend-django 技术设计

**日期**：2026-10-17
**上游**：`docs/superpowers/plans/2026-10-17-backend-django-rewrite-plan.md`（PLAN）
**契约真源**：`design/*.openapi.yaml` · **PRD 规约**：`PRD/README.md` 2.1–2.15
**原则**：TDD（红-绿-重构）；与 Go 版行为逐字节对齐优先于"更优雅"的重设计；YAGNI。

---

## 一、通用信封与错误码（对齐 `httpx/envelope.go`）

所有 `/api/v1` 响应（含错误与 stub）统一：

```json
{ "code": 0, "message": "ok", "data": {...}, "traceId": "tr-xxxx", "timestamp": 1739740000000 }
```

- `code=0` 成功；业务错误 `code` 非 0，HTTP 状态表达传输层（PRD 2.5）；
- `traceId`：优先取请求头 `X-Trace-Id`，否则生成；响应头回写 `X-Trace-Id`；
- `timestamp`：Unix 毫秒。

**实现**：`core/httpx/envelope.py`

```python
def envelope_ok(data, trace_id) -> dict
def envelope_err(status: int, code: int, msg: str, trace_id) -> HttpResponse
class ApiError(Exception):      # 业务异常基类
    def __init__(self, status: int, code: int, message: str)
```

django-ninja 注册自定义 renderer + 异常处理器，任何视图只抛 `ApiError`。

**错误码段（沿用 Go 版已用值，集中登记于 `core/httpx/errors.py`）**：

| code | 语义 |
|------|------|
| 0 | 成功 |
| 40001 | 参数校验失败 |
| 40101 | 未认证 / token 失效 |
| 40301 | Casbin 拒绝（policy 门禁） |
| 40401 | 资源不存在 |
| 40901 | 状态机冲突（非法迁移/重复提交） |
| 42901 | 幂等键冲突返回原响应（非错误，语义见 §三） |
| 50301 | 依赖缺失（如 Storage 未配置） |
| 50001 | 内部错误 |

> 规则：Django 版必须逐条盘点 Go 版 `WriteErr` 调用点，错误码 1:1 迁移，不得自行发明新码；新需求用未占用号段并登记。

---

## 二、认证与授权（对齐 `platform/auth` + `middleware.Auth`）

### 2.1 登录

- `POST /api/v1/auth/login` `{username, password}` → `{token, refreshToken, user, caps}`；
- 密码校验：Django `check_password`（新库 seed 用 Django hasher 写入；dev 回退账号 `ark/ark` 语义保留：`LoginReader` 为空时的行为对齐 Go 版）；
- JWT：HS256，claims `{sub, tenantId, roles[], orgId, legalEntityId, exp, iat, jti}`，TTL 对齐 `ARK_JWT_TTL_SEC`；refresh token 端点同 Go 版语义。

### 2.2 请求鉴权

django-ninja 全局 auth 依赖（公开端点白名单：`/healthz`、`/auth/login`）：

1. 解 JWT → 注入 `request.auth_user`（含 roles/tenantId）；
2. Casbin 检查：`enforcer.enforce(role, path, method)`——**`config/casbin/model.conf` 与 `policy.csv` 从 backend-go 复制零修改**；
3. 通过后进入 ninja handler；未通过抛 `ApiError(403, 40301, ...)`。

**依赖**：`django-casbin`（或直接 `casbin` + 自建 adapter；policy 从 CSV 静态加载，与 Go 版一致）。

### 2.3 caps 与页面可见性

- `/auth/me` 返回 `caps`（权限点集合）——计算逻辑移植 Go 版 `auth/me` handler；
- 页面可见性矩阵 `page_grant`（PRD 2.9 在线配置，实时生效）：模型 `sysadmin.PageGrant`，读路径带 Redis 缓存（TTL 30s，写路径失效），保证"管理员勾选即生效"。

---

## 三、幂等中间件（对齐 `middleware.Idempotency`）

- 作用域：`/api/v1` 内所有写方法（POST/PUT/PATCH/DELETE）；
- 请求头 `Idempotency-Key` 存在时：Redis `SETNX ark:idem:{key}` TTL 24h；重复请求返回**首次响应快照**（状态码+信封整体）；
- 行为对齐 Go 版：首次处理完成后才落快照；处理中重复请求返回 42901/冲突语义（以 Go 版实测为准，写契约测试固化）。

**实现**：`core/idempotency/middleware.py`（Django middleware，位于 ninja auth 之后）。

---

## 四、平台层模型与引擎

### 4.1 两级审批（`core/approval`，对齐 `platform/approval`）

**职责边界不变**：业务表 `status` 是状态唯一真源；本引擎只管"流水 + 规则 + 开关"。

- 配置：`TwoStep(first_role, second_role)` 按业务域注册；全局开关 `ARK_APPROVAL_TWOSTEP=on`（settings 读 env）；
- 流水表（schema 照抄 Go 迁移）：

```sql
sys_approval_log(id, tenant_id, biz_type, biz_id, step,  -- 0=提交 1=首审 2=终审
                 actor_id, actor_role, action,            -- SUBMIT/APPROVE/REJECT/RETURN
                 comment, acted_at)
```

- 服务接口：`approval.log(tx, LogParam)`（与业务同事务）、`approval.list_logs(tenant_id, biz_type, biz_id)`；
- PRD 2.3 的加签/转办/并行在 `sys_approval_log` 之上以 `step` 扩展实现，Phase 2+ 渐进。

### 4.2 编号中心（`core/numbering`，PRD 2.11）

- 表：`seq_prefix_registry`（前缀注册表）、`seq_allocation`（租户+前缀+年份号段）；
- 取号：`SELECT ... FOR UPDATE` 行锁递增（起步不加 Redis 号段，量小；接口预留 `async allocate()` 以便后续 Redis 双写）；
- 格式 `{PREFIX}-{YYYY}-{000123}`；幂等取号：同请求重试返回同号（由幂等中间件覆盖）。

### 4.3 字典（`core/dict` → `apps/sysadmin`）

- `sys_dict` / `sys_dict_item`（多语言、生效时段、排序，PRD 2.8）；
- 前端 `useDict` 组合式函数直接消费 `/api/v1/dicts` 系列端点，契约对齐 `12-U`。

### 4.4 通知（`apps/notify`）

- `sys_notification` + 已读状态 + `sys_import_log`（dataio 配套）；
- `Notifier` 协议：funding/project 以依赖注入方式获得 notifier（对齐 Go `SetNotifier` 装配），触达 best-effort 失败不回滚业务；
- 异步任务（预警扫描等）Phase 0 用管理命令 + cron 起步，Phase 2 迁 Celery Beat。

### 4.5 审计（`core/audit`）

- `sys_audit_log`：CUD 全记录，字段级 diff（`django-dirty-fields` 或 model.save 对比 `__dict__`）；
- 操作上下文（traceId、actor、IP）经 `threading.local` / `contextvars` 传递。

### 4.6 Excel 导入导出（`core/dataio`）

- 导出：openpyxl 流式写（`write_only` 模式，1 万行 < 30s 达标）；
- 导入：模板校验 → 预览（错误行清单）→ 确认 → 落库 + `sys_import_log` + 撤销（对齐 Go dataio 三段式语义与测试用例）。

---

## 五、契约实现策略（替代 Go passthrough）

1. **契约加载**：启动时解析 `design/*.openapi.yaml`（PyYAML），构建 `{operationId → spec}` 注册表；
2. **三层路由**（ninja router 装配顺序）：
   - L1 手工实现端点（各业务 app 注册）；
   - L2 contract stub：L1 未覆盖的契约端点返回 `{code:0, data:{items:[], total:0}}`（列表型）或最小合规对象，附响应头 `X-Stub: true` 与 log 去重打印；
   - L3 未登记路径：404 信封；
3. **契约测试**（`tests/contract/`）：
   - 对每个 operation：请求构造（按 schema 生成最小合法体）→ 断言状态码、信封结构、必填字段存在、`X-Stub` 标记；
   - 报表按 Phase 输出"已实现 / stub 命中"清单，stub 数递减至 Phase 4 归零；
4. **schemathesis 可选**：CI 起步用自研断言（轻、可控），稳定后接入 schemathesis 模糊测试。

---

## 六、业务 App 建模规范

**通用规则**（每个 app 遵守）：

- Model 表名沿用 Go 迁移中的表名（含大写前缀域表如 `E_PROJECT`——`db_table` 显式指定，不做风格改写）；
- 通用字段：`id BIGSERIAL PK`、`code`、`tenant_id`、`status`（大写蛇形 token，choices 用 `TextChoices`，token=中文映射常量集中放 `apps/<x>/consts.py`）、`deleted`、`creator_id/modifier_id`、`created_at/updated_at`、`remark`（PRD 2.2）；
- 金额 `DecimalField(max_digits=18, decimal_places=2)`；时区 `TIME_ZONE = "Asia/Shanghai"`，`USE_TZ = True`；
- 逻辑删除：默认 manager 过滤 `deleted=0`，物理删除禁止；
- Handler/service 分层：ninja controller 只做参数绑定 + 权限 + 信封；业务写在 `services.py`；查询在 `repositories.py`（对齐 Go handler/store 边界，便于测试移植）；
- 权限：角色判断走 caps + casbin；数据域隔离（PI 视角 vs R-ADMIN 全量等）在 repositories 层以 queryset 过滤实现，**逐条移植 Go 版对应测试**（如 `TestListMyProjects_AdminSeesAll`）。

**分域映射表**（model 清单 = Go `db/query_*/` + `migrations` 合成 schema，此处列域级粒度）：

| Django app | 对应 Go 模块 | 核心模型（表） |
|------------|--------------|----------------|
| `apps.sysadmin` | sysadmin | SysUser/SysRole/SysUserRole/SysAdminDuty/SysOrg/SysLegalEntity/SysDict/SysDictItem/PageGrant/RoleAdmin |
| `apps.notify` | notify | SysNotification/SysImportLog/SysTask |
| `apps.p` | p | PGuideline/PTemplate/PApplication/PApplicationDoc/PBudgetDraft/PReviewTask/PReviewResult/PTaskBook |
| `apps.project` | project | EProject/ETask/EMilestone/EProgressReport/EMidCheck/EChangeRequest/EFinalAccept/EProjectDoc/EHealthHistory/EArchiveChecklist/ECategory/EApplyPlan/ETraceNode |
| `apps.funding` | funding | FSubject/FBudget/FBudgetLine/FIncome/FExpense/FExpenseApproval/FInvoice/FVoucherSync/FIndirectFee/FSettlement/FAnomaly/FBudgetForecast/FCostPool/FAccountingEntry/FDisbursement/FCarryover/Outward/FSubjectAdmin |
| `apps.output` | output | ROutput + R{Paper,Patent,Software,Standard,Award,Book}Ext/RClaimRecord/RMetricSnapshot/RPushItem |
| `apps.performance` | performance | MScheme/MSchemeFactor/MRecord/MRecordItem/MPayout/MPortrait |
| `apps.activity` | activity | VActivity/VParticipant/VReview |
| `apps.archive` | archive | ODocument/OArchive/OArchiveItem/OArchiveCheck/OBorrow |
| `apps.expertreview` | expertreview | NExpert/NExpertGroup/NReviewTask/NReviewInvitation/NReviewScore/NReviewFee |
| `apps.dataops` | dataops | （聚合查询，无新表） |

> Phase 4 预留域（T/C/S/D/G/A/X）模型在对应迁移建表时按 `design/00-common.sql` 转写，本 spec 不展开。

---

## 七、svc-ai（FastAPI AI 微服务）

**边界**：无状态；不直连业务库；输入输出纯 JSON/文件；Django 是唯一调用方。

```
POST /ai/taskbook/parse        # 任务书 PDF → 结构化字段（pdfplumber + LLM 抽取）
POST /ai/expense/review        # 报销单/发票 → {verdict: PASS|REVIEW, confidence, reasons[]}
POST /ai/contract/risk         # 合同条款风险提示（Phase 4）
POST /ai/rag/qa                # 制度问答（Phase 4，pgvector）
GET  /healthz
```

- 降级契约：`ARK_LLM_BASE_URL` 未配置或上游超时 → 返回 `{verdict:"REVIEW", confidence:0, reasons:["llm-unavailable"]}`，HTTP 200（**与 Go 版"AI 未配置自动降级 REVIEW 不阻塞业务"逐字对齐**）；
- LLM 网关：NewAPI OpenAI 兼容 `10.26.8.43:3002`，`ARK_LLM_MODEL` 可配；
- 部署：独立 uvicorn 进程（systemd），Nginx 内网 location `/ai/` 反代；Django 侧 `core/llm` 客户端带超时熔断（30s 默认）。

---

## 八、配置与环境变量（对齐 Go `ARK_*` 命名，保留前缀以便迁移）

| 变量 | 用途 | 默认 |
|------|------|------|
| `ARK_DATABASE_URL` | PostgreSQL DSN | `postgres://ark:ark@localhost:5432/ark` |
| `ARK_REDIS_ADDR` | Redis | `127.0.0.1:6379` |
| `ARK_JWT_SECRET` / `ARK_JWT_TTL_SEC` | JWT | dev-secret / 7200 |
| `ARK_APPROVAL_TWOSTEP` | 两级审核开关 | off |
| `ARK_S3_ENDPOINT/ACCESS_KEY/SECRET_KEY/BUCKET` | MinIO | minioadmin.../ark-docs |
| `ARK_LLM_BASE_URL/API_KEY/MODEL/TIMEOUT_SEC` | LLM 网关 | 10.26.8.43:3002 / gpt-4o-mini / 30 |
| `ARK_SEED_DEMO` | 演示数据播种 | 1 |
| `DJANGO_SETTINGS_MODULE` | settings 选择 | config.settings.dev |

---

## 九、部署形态

### 9.1 开发（docker-compose，Phase 0 后切换）

```yaml
backend:  # build backend-django/Dockerfile，gunicorn config.wsgi -b 0.0.0.0:8787
  healthcheck: http://127.0.0.1:8787/healthz  (start_period 覆盖 migrate)
worker:   # celery -A config worker -c 4
beat:     # celery -A config beat
svc-ai:   # uvicorn svc_ai.main:app --port 8900
frontend / postgres / redis / minio 不变
```

### 9.2 生产（裸机 systemd，非容器化——对齐部署偏好）

- `django-api.service`：gunicorn 多 worker（`2*CPU+1`），多实例 + Nginx upstream 多活；
- `django-worker.service` / `django-beat.service`：Celery；
- `svc-ai.service`：uvicorn；
- `django-migrate.service`（oneshot）：部署时先跑 migrate；
- Nginx：TLS 终结、静态文件（前端 dist）、`/api/ → upstream django`、`/ai/ → upstream svc-ai`（内网）。

---

## 十、任务分解（TDD 任务卡，每卡 2–5 分钟级）

**Phase 0**
1. [ ] 骨架：pyproject、settings 分层、healthz、信封 renderer（先写 envelope 测试，移植 Go `envelope_test.go`）
2. [ ] TraceID 中间件（X-Trace-Id 透传/生成，测试对齐 trace.go）
3. [ ] 登录/refresh/me + JWT（claims/TTL/40101 语义，测试对齐 auth 包）
4. [ ] casbin 装配 + 40301（用 Go 同一份 policy.csv 跑同一批 allow/deny 用例）
5. [ ] 幂等中间件（快照回放/冲突，测试对齐 idempotency 语义）
6. [ ] SysUser/Role/Org/LegalEntity/Dict/PageGrant models + 迁移
7. [ ] sysadmin 端点（字典 CRUD/角色目录/页面矩阵，移植 handler_dict/handler_role/handler_page_grant 测试）
8. [ ] notify 模块（通知/导入日志/任务，移植 notify_test.go）
9. [ ] 契约测试框架 + stub 层（先对 12-U 域全绿）
10. [ ] seed_demo 管理命令（移植 seed_demo.sql + testdata）
11. [ ] docker-compose 切换 backend → Django；smoke 直连跑通

**Phase 1–4** 按同法逐 app 拆卡（每 app：models+迁移 → repositories → services → ninja 端点 → 契约/单测 → smoke），此处不逐条展开，进入各 Phase 时再细化。

---

## 十一、验收标准（整体）

1. `pytest` 全绿；契约测试对 16 域 400+ operation 无 L3 未登记路径；
2. 6 个前端 smoke 脚本直连 Django 全部通过，**前端仓库零 diff**；
3. casbin 鉴权双跑对比：Go（tag 快照）与 Django 对同一用例集判定一致；
4. 空库 `ARK_SEED_DEMO=1` 启动 → 演示数据齐备 → 核心流程（登录→申报→立项→报销审批→大屏）手工走通；
5. LLM 未配置场景：AI 端点全部 REVIEW 降级，业务流程不阻塞。
