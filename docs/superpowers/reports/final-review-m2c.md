# M2-c 全分支合并前终审报告

- 评审范围：`9f087e9..2079f9c`（11 commits，39 files，+3261/−79）
- 评审基准：`HEAD=2079f9c`，工作树中与本变更无关的 docs 删除/未跟踪文件未触碰
- 评审方式：只读源码 + 独立动态探针；**未修改任何源码、未提交 git**；唯一新增文件为本报告
- 评审日期：2026-11-19
- 评审对象：roadmap M2-c（C3 外部专家 / C4 外部供应商 / C5 外部消息通道）

## 0. 结论

**verdict：REQUEST_CHANGES**

**合并门槛结论：不能合并。** C5 要求的三条外部主链路——专家邀请、供应商询价邀请、立项决议——仍然零邮件（实测 `mail.outbox == 0`）；同时新供应商门户对黑名单/资质过期供应商放行（实测 200 且可应价）。这两项修好并补上可钉住缺陷的负例测试后，才具备合并条件。

本期变更的“单条 N 域读写收口”“供应商门户数据范围/脱敏/幂等”“契约双份一致”主体是成立的；但 C5 的接线完成度、供应商准入硬控制、信用档案计算和若干测试有效性不足，达不到 M2-c 的验收口径。

---

## 1. 我亲自跑过的验证（命令与数字）

| # | 命令 | 结果 |
|---|---|---|
| 1 | `cd backend-django && .venv/bin/python -m pytest -q` | **449 passed, 5 warnings in 18.67s** |
| 2 | `cd backend-django && .venv/bin/python -m pytest -q tests/test_auth_m2c.py tests/test_expertreview_m2c.py tests/test_notify_m2c.py tests/test_procure_m2c.py` | **31 passed in 4.28s** |
| 3 | `cd frontend && ./node_modules/.bin/vue-tsc --noEmit` | **exit 0，0 行输出**（用 `PIPESTATUS` 复核，不是 `tail` 的退出码） |
| 4 | `cd backend-django && .venv/bin/python manage.py makemigrations --check --dry-run` | **No changes detected**，exit 0；仅伴随 PG `127.0.0.1:5432 connection refused` 的 RuntimeWarning |
| 5 | 临时 sqlite：`migrate` + `seed_demo` 连跑两次 | 第一次 `legal +2，staff +11，p +6，project +17，funding +23，output +7，expert +6，activity +4，archive +6，performance +6，transform +13，ethics +5，procure +15，asset +9，confsec +7，notify +5，partner +6，users +4，dicts +5，items +26，grants +88`；第二次仅 `seed_demo 完成（幂等）：`（全部 0）。**PASS** |
| 6 | 16 对 `design/*.openapi.yaml` ↔ `frontend/src/api/schema/*.openapi.yaml` 的 Python `filecmp` | **13 SAME / 3 DIFF**；DIFF 为 `04-科研成果管理-R`、`08-数据分析与决策-D`、`14-科研绩效评价-M`，三对在 `9f087e9` 基线即 DIFF；本期改的 `09-采购与合同管理-G`、`15-专家与评审管理-N` 均 **SAME** |
| 7 | `git diff --numstat 9f087e9..2079f9c -- design/09-* design/15-* frontend/src/api/schema/09-* frontend/src/api/schema/15-*` | 09-G **120/120**、15-N **257/257**，双份行数一致 |
| 8 | `pytest -q tests/test_rbac.py::test_m2b_partner_denied_admin_and_secret_domains` | **1 passed**（X/涉密域对外部角色仍全拒） |
| 9 | 独立探针：N 域跨租户列表/抽专家 | tenant2 建专家与评审，tenant1 R-MANAGER `GET /api/v1/experts` → **200，返回体含 `tenant_id: 2`**；`GET /api/v1/reviews` → **200，返回 `[2,1]`**；tenant1 任务 draw → **`{"drawn":[1]}`**（唯一 ACTIVE 专家是 tenant2 的） |
| 10 | 独立探针：供应商门户黑名单/PENDING | `GSupplier(status="IN_LIBRARY", blacklist=True)` 且被邀 → `GET /portal/supplier/inquiries` **200 且含该 bid**，`POST ...:quote` **200**、`"1.00"` 落库；`status="PENDING"` → list **200 `[]`**、quote **403 40301「当前机构未绑定供应商」** |
| 11 | 独立探针：门户列表历史数据 | `bids_json=[{"supplierId": s.id}]`（无 `totalAmount`）→ `GET /portal/supplier/inquiries` **KeyError: 'totalAmount'，500** |
| 12 | 独立探针：邀请/发标邮件 | `POST /reviews/{id}/invite` → **200，`mail.outbox` 0 封**；`POST /procurement/bids`（含 `invited_supplier_ids`）→ **200，`mail.outbox` 0 封** |
| 13 | 独立探针：未受邀打分 | ACTIVE 专家未受邀，`POST /reviews/{id}/scores {"total_score":90}` → **200，90.00 落库** |
| 14 | 独立探针：内部 R-STAFF 被授 R-EXPERT | 内部 `user_source=INTERNAL` + R-STAFF 用户，造 CANDIDATE，R-MANAGER audit APPROVE → `SysUserRole=['R-EXPERT','R-STAFF']`；真实 `/auth/login` → **200，JWT roles == ['R-EXPERT']** |
| 15 | 静态复核 `values()+annotate()` 全仓 | 无第二处“返回 dict 按对象属性取键”；`apps/procure/api.py:493-494` 已修为 `row["contract_id"]/row["paid_sum"]` |

---

## 2. Critical（本期引入，阻断合并）

### C-1 C5 外部主链路仍有三处零邮件，专家/供应商不会收到邀请

**严重度：Critical（门槛）**

**证据（代码）**

- `backend-django/apps/expertreview/api.py:290-305` `invite_experts`：只把任务改为 `INVITING`；MID_CHECK 分支只回填 `expert_ids`，**没有任何 `notify_user` / `notify_inapp` 调用**。
- `backend-django/apps/procure/api.py:293-318` `create_bid`：只校验 `invited_supplier_ids` 的供应商可用性并建 `GBid`，**没有任何通知**。
- `backend-django/apps/p/api.py:996-1029` `decide_application`：仍调用旧 `_notify`（`apps/p/api.py:166-176`），该函数只写 `SysNotification`，**不发邮件**。
- `backend-django/apps/procure/portal.py:97-134` `quote_inquiry`：应价成功只更新 `bids_json`，**没有回执通知**（计划 Task 8 明确要求“应价成功回执”）。

**证据（实测）**

- 专家邀请：建 ACTIVE 专家（有 email）+ DRAWN 任务 + 邀请行，R-MANAGER `POST /api/v1/reviews/{id}/invite` → **200，`mail.outbox` 0 封**。
- 供应商邀请：建 `WAY_DECIDED` 采购申请 + 已绑机构/供应商/机构用户，R-MANAGER `POST /api/v1/procurement/bids`（含 `invited_supplier_ids`）→ **200，`mail.outbox` 0 封**。
- `decide_application`：代码只走 `_notify`，全仓无 email 分支。

**对照计划**

`docs/superpowers/plans/2026-11-19-m2c-expert-supplier-channel.md:561`：

> 四处接线：`invite` 给每位被邀专家发「评审邀请」+ 邮件；`audit_expert_application` 结论；`create_bid` 给 `invited_supplier_ids` 对应机构联系人发询价邀请；`decide_application` 给 PI（外部则同时给机构邮箱）发决议。

实际只落了 `audit_expert_application`（`apps/expertreview/portal.py:176-181` 的 `_notify_both`）、`award_bid`（`apps/procure/api.py:373-395`）、task-book 双签、guide-suggestion 审核。**四处中三处缺失**，加上 `quote` 回执共四处。

**影响**

C5 的验收句是“站内信 + 邮件（外部用户能收到邮件）”。外部专家被邀请时、外部供应商被询价时，都不会收到任何邮件；外部 PI 的立项决议也不会收到邮件。门户页面虽然能看邀请，但 C5 的主链路没有闭环。

**修复建议**

1. `invite_experts`：对每个 `NReviewInvitation` 关联的 `NExpert.user_id` 调 `notify_user(d.tenant_id, uid, "REVIEW", "评审邀请", ..., biz_ref=f"review-invite:{inv.id}")`；无邮箱时仍落站内信。
2. `create_bid`：对 `invited_supplier_ids` 逐个取 `GSupplier.org_id` 下的 ACTIVE 用户（复用 `_notify_bid_result` 的收件人选择逻辑），发“询价邀请”。
3. `decide_application`：改为 `notify_user`；PI 为外部（`is_external_only` 或 `user_source=EXTERNAL`）时同时给机构联系人邮箱发一份。
4. `quote_inquiry`：给应价供应商机构联系人发“报价已收到”回执。
5. 测试必须断言 `mail.outbox` 至少 1 封、收件人 email 正确、租户/机构正确；不能只断 200。

---

## 3. Important（本期引入，应修但非唯一门槛）

### I-1 新供应商门户放行黑名单/资质过期供应商，违反“硬拦截”注释

**文件/行号**

- `backend-django/apps/procure/api.py:768-778` `_my_supplier`
- 对照：`backend-django/apps/procure/api.py:107-116` `_check_supplier_usable`

**证据（代码）**

`_my_supplier` 的注释写：

> `# 只认已入库供应商：PENDING/REJECTED/EXPIRED/黑名单都不得进门户`

实际过滤条件只有：

```python
return GSupplier.objects.filter(
    tenant_id=d.tenant_id, org_id=org_id, deleted=0, status="IN_LIBRARY"
).first()
```

**没有** `blacklist=False`、**没有** `qualification_expire_date`、**没有** `SysPartnerOrg.status` 校验。`_check_supplier_usable` 在邀标/定标时确实拦黑名单、非在库、资质过期，但门户侧绕过了它。

**证据（实测）**

- `GSupplier(status="IN_LIBRARY", blacklist=True)` 且被邀 → `GET /api/v1/portal/supplier/inquiries` **200 且列表含该 bid**；`POST /api/v1/portal/supplier/inquiries/{id}:quote` **200**，`"1.00"` 落库。
- `status="PENDING"` → list **200 `[]`**，quote **403 40301**。说明 2079f9c 新增的 `status="IN_LIBRARY"` 过滤对 PENDING 生效，但黑名单/过期未覆盖。

**影响**

黑名单供应商若此前被邀或 `invited_supplier_ids` 被直接写入，可以查看询价标题/分类/开标时间并提交报价。虽然 `award_bid` 的 `_check_supplier_usable` 使其无法中标，但“黑名单不得进门户”的硬控制已被绕过，且门户可被用于报价骚扰/信息探测。

**修复建议**

在 `_my_supplier` 复用 `_check_supplier_usable` 的判定（或抽 `supplier_is_usable(s)` 纯函数）：`status == "IN_LIBRARY"`、`not blacklist`、`qualification_expire_date is None or >= today`；可选校验 `SysPartnerOrg.status == "APPROVED"`。返回 None 时按现有语义给空列表/403。补 PENDING/REJECTED/EXPIRED/blacklist 四组负例。

### I-2 内部 R-EXPERT 账号在登录时被剥光内部角色，且无数据迁移

**文件/行号**

- `backend-django/core/org_scope.py:11` `EXTERNAL_ROLES = ("R-PARTNER", "R-EXPERT")`
- `backend-django/core/auth/deps.py:62-69`、`backend-django/core/auth/api.py:61-65` 的 `external_roles_of` 裁剪
- `backend-django/apps/expertreview/portal.py:185-195` `_grant_expert_role`
- `backend-django/apps/expertreview/api.py:108-124` `create_expert`

**证据（代码）**

`_grant_expert_role` 只做：

```python
SysUserRole.objects.get_or_create(user_id=user_id, role_id=role.id, tenant_id=tenant_id)
```

不校验 `SysUser.user_source`、不校验 `tenant_id`、不检查该用户是否已有内部角色。`create_expert` 默认 `status="CANDIDATE"`、`source="EXTERNAL"`，且接受任意 `user_id`。因此存在路径：管理员为内部 R-STAFF 用户建 CANDIDATE 专家档案 → 审核 APPROVE → 该用户同时持有 `R-STAFF` 与 `R-EXPERT` → 下次登录时 `ark_auth` / `login` 的“含任一外部角色即只保留外部集”把它裁成只剩 `R-EXPERT`，内部权限静默丢失。

**证据（实测）**

内部 `user_source=INTERNAL`、仅 R-STAFF 的用户 + 造 CANDIDATE + R-MANAGER audit APPROVE：

- `SysUserRole` 行变为 `['R-EXPERT','R-STAFF']`
- 真实 `/auth/login` → 200，**JWT `roles == ['R-EXPERT']`**

M2-c 把 R-EXPERT 加入 `EXTERNAL_ROLES` 之前，这段裁剪只针对 R-PARTNER，不会发生；属本期引入的回归风险（不是提权，是降权/锁定）。

**影响**

存量“内部 R-STAFF + R-EXPERT”账号（在 M2-c 前 `assign_role` 只拦 R-PARTNER 混合，允许这种组合）升级后会在令牌有效期内失去内部角色；新走“管理员建 CANDIDATE → 审核”的路径也会制造同样的混合账号。当前没有数据迁移、没有告警、没有测试。

**修复建议**

1. `_grant_expert_role` 前查 `SysUser(id=user_id, tenant_id=tenant_id, deleted=0)`；若 `user_source != "EXTERNAL"` 或已有内部角色，拒绝并提示“内部账号不能授外部专家角色”，或走“外部身份转换”显式流程。
2. `audit_expert_application` 只审核 `source="EXTERNAL"` 的申请；`create_expert` 不要给内部用户默认 `source="EXTERNAL"`。
3. 增加数据迁移/管理命令：扫描 `SysUserRole` 中同时有 R-EXPERT 与内部角色的用户，按 `user_source` 决策（转外部或移除 R-EXPERT），并记录审计。
4. 增加“内部 R-STAFF + R-EXPERT 登录后角色”的回归测试。

### I-3 信用档案 `review_count` / `last_review_at` 永远不更新

**文件/行号**

- `backend-django/apps/expertreview/portal.py:239-252` `_expert_credit`
- `backend-django/apps/expertreview/api.py:350-378` `submit_score`
- `backend-django/apps/expertreview/models.py:39-40`

**证据（代码 + grep）**

`_expert_credit` 直接返回：

```python
"review_count": e.review_count or 0,
"last_review_at": fmt_ts(e.last_review_at),
```

但全仓 `review_count` / `last_review_at` 只出现在：

- `models.py:39-40` 字段定义
- `mappings.py:34` 专家详情输出
- `portal.py:242,251` 信用档案输出
- `migrations/0001_initial.py:44-45`

`submit_score` 只写 `NReviewScore`，没有更新 `NExpert.review_count` / `last_review_at`，也没有信号。种子数据也未写这两个字段。

**影响**

新信用档案的“评审次数”永远 0，“最近评审时间”永远 null，即使该专家已经打了很多分。`accept_rate`/`avg_score` 是从邀请/分数实时聚合的，唯独这两项是陈旧字段，前端会展示自相矛盾的信用档案。

**修复建议**

不要依赖冗余字段，直接在 `_expert_credit` 聚合：

```python
agg = NReviewScore.objects.filter(expert_id=e.id).aggregate(
    cnt=Count("id"), last=Max("created_at")
)
```

或在 `submit_score` 的“首次创建分数”分支更新 `review_count += 1`、`last_review_at = now`（注意 upsert 不能重复计数）。补“打分后 credit.review_count == 1、last_review_at 非空”的测试。

### I-4 驳回置 `SUSPENDED` 与计划书冲突，且申请人无法自行重新申请

**文件/行号**

- `backend-django/apps/expertreview/portal.py:166-171` REJECT 分支
- `backend-django/apps/expertreview/portal.py:70-73` `apply_expert` 幂等检查
- 计划书：`docs/superpowers/plans/2026-11-19-m2c-expert-supplier-channel.md:304,330`

**证据（代码）**

计划书写：

> 有 reason → status 保持 CANDIDATE

实现写：

```python
e.status = "SUSPENDED"
e.remark = reason
```

而 `apply_expert` 对 `(tenant_id, user_id, deleted=0)` **任意状态**已存在即 409：

```python
if NExpert.objects.filter(
    tenant_id=d.tenant_id, user_id=d.user_id, deleted=0
).exists():
    raise ApiError(409, CODE_CONFLICT, "已提交过专家申请")
```

`audit_expert_application` 又要求 `status == "CANDIDATE"` 才能审核（`portal.py:158-159`）。因此被驳回的申请人不能重提，也不能被再次审核；只能管理员先用 `PUT /experts/{id}/status` 手动改回 CANDIDATE，再走审核。计划书没有这个额外步骤，测试 `test_reject_requires_reason` 反而把断言改成了 `SUSPENDED`，固化了偏差。

**影响**

C3 的“申请—驳回—补充材料—再申请”闭环断裂；真实用户被驳回后没有任何自助恢复路径，客服/管理员需要手工改库或改状态。

**修复建议**

二选一并与计划书对齐：

- 按计划保持 `CANDIDATE` + `remark`，允许申请人修改后重新提交（`apply_expert` 对 CANDIDATE 做更新而非 409）；或
- 若产品决定“驳回即终态”，提供显式“重新申请”入口（新记录或重置状态），并在契约/前端/测试中写清楚。

### I-5 审核/授角色没有校验用户租户与来源，存在跨租户授角色面

**文件/行号**

- `backend-django/apps/expertreview/portal.py:185-195` `_grant_expert_role`
- `backend-django/apps/expertreview/portal.py:140-181` `audit_expert_application`
- `backend-django/apps/expertreview/api.py:108-124` `create_expert`

**证据（代码）**

`_grant_expert_role(tenant_id, user_id)` 用调用方传入的 `tenant_id` 建 `SysUserRole`，但**不校验 `SysUser.id=user_id` 的 `tenant_id` 是否等于该值**，也不校验 `user_source`。`create_expert` 接受任意 `user_id`；`audit_expert_application` 只校验 `NExpert.tenant_id` 与 `status`，不校验 `e.user_id` 的租户/来源。结果是：tenant1 的 R-MANAGER 可以给 tenant2 的用户建/审 CANDIDATE，并在 tenant1 写入一条 `SysUserRole`；该用户登录（`core/auth/api.py:57` 按 `user_id` 查角色，无 tenant 过滤）会拿到 R-EXPERT。

**影响**

跨租户角色授予（需要管理员操作，非外部直接可利用），以及 I-2 的内部角色混合路径。属于 tenant 隔离缺口，虽不是外部提权，但违反“外部身份落 Casbin 独立角色域 + tenant 隔离”的验收口径。

**修复建议**

`_grant_expert_role` 内查 `SysUser.objects.filter(id=user_id, tenant_id=tenant_id, deleted=0).first()`，不存在则 400/404；要求 `user_source == "EXTERNAL"`（或走显式转换）；`audit` 只接受 `e.source == "EXTERNAL"`；`create_expert` 的 `user_id` 也做同样租户校验。

### I-6 2079f9c 的 `status="IN_LIBRARY"` 修复没有任何回归测试钉住

**文件/行号**

- `backend-django/apps/procure/api.py:768-778`
- `backend-django/tests/test_procure_m2c.py` 的 `_supplier` 辅助

**证据**

`tests/test_procure_m2c.py` 的 `_supplier` 全部写死 `status="IN_LIBRARY"`；没有任何用例构造 PENDING/REJECTED/EXPIRED/blacklist 供应商再断言空列表/403。2079f9c 的 commit message 声称“PENDING/REJECTED/EXPIRED 不得进门户”，但测试只能证明“IN_LIBRARY 能进”。如果未来有人把 `status` 过滤删掉，测试仍全绿。

**影响**

修复不可回归；且掩盖了 I-1 的黑名单/过期缺口。

**修复建议**

至少 4 个参数化负例：PENDING、REJECTED、EXPIRED（`qualification_expire_date` 过去）、`blacklist=True`；分别断言 `list == []`、`quote == 403`。再加一个 `IN_LIBRARY` 正例。

---

## 4. Minor（本期引入，建议修）

### M-1 `my_amount` 对历史 `bids_json` 缺键会 500

- `backend-django/apps/procure/portal.py:91`

```python
"my_amount": mine[-1]["totalAmount"] if mine else None,
```

`bids_json` 是 JSONField，历史/手工数据可能是 `[{"supplierId": 1}]`。实测该形状下 `GET /portal/supplier/inquiries` 抛 `KeyError: 'totalAmount'` → 500。建议 `mine[-1].get("totalAmount")`，并对 `supplierId` 的 `int()` 做容错。

### M-2 `notify_user` 的站内信写入不在 try 内，“永不阻断”只对邮件成立

- `backend-django/apps/notify/email.py:90-92`

`notify_inapp(...)` 在 `try` 之外；只有邮件分支被 `try/except` 包住。`apps/p/api.py:863/891/1179` 等调用点没有外层 try，站内信 DB 异常会向上抛。邮件失败确实不阻断（PASS），但“notify_user 失败不阻断业务”这个总承诺不成立。建议把 `notify_inapp` 也包进 try（或明确它只可能因 DB 故障抛，并在调用方统一兜底）。

### M-3 前端口径 / policy / seed 三方不一致（fail-closed，非提权）

- `frontend/src/router/index.ts:60`、`frontend/src/App.vue:216`：`/portal/expert-apply` 对 **R-STAFF** 开放；`config/casbin/policy.csv:910-911` 只有 R-PARTNER/R-EXPERT，`seed_demo.py:121` 也没有 R-STAFF。R-STAFF 能打开页面，提交必 403。
- `frontend/src/api/mock/overrides/auth.ts:52-62`：R-LEADER 多出 `POST /api/v1/portal/expert-apply`，policy 没有。
- `frontend/src/api/mock/overrides/auth.ts:51`：R-EXPERT 用 `W(['GET'])` 覆盖所有 GET，但缺 `POST /portal/expert-apply`；policy:911 有。
- `frontend/src/api/mock/overrides/auth.ts:64-86`：R-MANAGER caps 未列 `/portal/supplier/inquiries`；policy:924 有。
- `frontend/src/router/index.ts:64`、`App.vue:205`：admin-expert-applications 对 R-ADMIN 开放；policy 的 `/api/v1/*` 通配允许，但 `seed_demo.py:120` 的 PAGE_GRANTS 只给 R-MANAGER。

这些差异都是“前端多开、后端拒绝”或“前端少开、后端允许”，不构成提权；但违背 `auth.ts` 注释“镜像 policy.csv / seed_demo.PAGE_GRANTS”。建议以 policy.csv 为唯一真源，生成/校验两份前端映射；至少修 R-STAFF 路由与 R-LEADER 的 mock 多余 POST。

### M-4 `totalAmount` 与 G 域 snake_case 风格不一致

- `design/09-采购与合同管理-G.openapi.yaml` 的 `SupplierQuoteRequest` / quote response 使用 `totalAmount`；同文件列表用 `my_amount`。
- 计划书 `:421` 本就写 body `{"totalAmount":...}`，handler 也返回 `totalAmount`，所以**契约与实现一致**，不是 bug；但 G 域其余字段均 snake_case。属风格不一致，建议统一为 `total_amount`（若改需同步前端/测试/双份 yaml）。

### M-5 policy 多授 R-MANAGER 供应商询价列表

- `backend-django/config/casbin/policy.csv:924`

```text
p, R-MANAGER, /api/v1/portal/supplier/inquiries, GET
```

计划书没有这一行。经理通常无 `org_id`，`_my_supplier` 返回 None，实际得到空列表；但若某经理被绑到供应商机构，就能看该供应商询价。属多余授权，建议删除或补计划说明。

### M-6 死代码 / 未使用常量

- `backend-django/apps/procure/portal.py:45` `_my_bid_or_404` 定义后全仓无调用，`quote_inquiry` 重复实现同一段查询。
- `backend-django/apps/procure/portal.py:139-142` `_CONTRACT_MASK_KEYS` 定义后未使用（白名单硬编码在 `_api_contract_for_supplier`）。
- `backend-django/tests/test_expertreview_m2c.py:20-22` `_post_tenant` 与 `_post` 完全相同。
- `backend-django/apps/dataops/api.py:64` `dept_rows` 聚合结果从未使用。

不影响安全/功能，但会误导后续维护，建议删除或真正使用。

### M-7 `_assert_account_active` 对“库中不存在的 uid”放行

- `backend-django/core/auth/deps.py:34-49`

真实用户停用/软删 → 403 + 40302（PASS，测试覆盖）；`row is None` 直接 return。若签名密钥未泄露，只有“用户被硬删除后、旧令牌仍在 2h 有效期内”的场景可通过；不是远程可利用的提权。属防御纵深问题，建议 fail-closed，或仅在测试 settings 下放行虚拟 uid，并在注释/配置中显式说明。

### M-8 seed 专家门户演示账号仍未落地，2079f9c 的 commit 描述与事实不符

- `backend-django/apps/sysadmin/management/commands/seed_demo.py:1192-1201`
- `backend-django/apps/sysadmin/management/commands/seed_demo.py:34-39`
- 计划书 `:634`

`seed_demo` 查：

```python
SysUser.objects.filter(tenant_id=T1, username="expert", deleted=0).first()
```

但 `USERS` 只有 `admin/manager/staff/finance`，`partner` 在 `:1076` 单独创建，**没有 `expert`**。临时 sqlite 实测：`SysUser.username='expert'` 为空；`NExpert` 的 `user_id` 为 `[0,0,5]`（王振华/刘敏未绑，合作单位联系人绑 partner）。计划 Task 9 要求的是 `expert_ext`（`user_source=EXTERNAL`、R-EXPERT、无 org）+ ACTIVE NExpert + VActivityParticipant；实际都没有。

2079f9c 的 commit message 写“种子专家档案绑定改用实际存在的账号”，但查询的 `expert` 仍不存在，绑定分支永远不执行。影响仅限演示/种子（真实用户可走申请—审核），但 C3 的“专家门户”开箱演示不成立。建议按计划创建 `expert_ext` 并绑定 ACTIVE NExpert + 活动参与记录，或删除这段死绑定并修正 commit 描述。

### M-9 信用档案测试没有覆盖 `review_count` / `last_review_at`

- `backend-django/tests/test_expertreview_m2c.py:256-258`

只断言 `accept_rate == "0.50"`、`on_time_rate == "1.00"`、`avg_score == "88.00"`，没有断言 `review_count` 与 `last_review_at`，所以 I-3 的缺陷不会红。补断言即可暴露。

---

## 5. 8 项重点逐项结论

### ① N 域专家/评审跨租户、跨机构 — **PARTIAL / 仍有既有越界**

**PASS 的部分**

- `_get_expert_or_404(tenant_id, expert_id)`（`apps/expertreview/api.py:55`）与 `_get_task_or_404(tenant_id, task_id)`（`:63`）都带 `tenant_id`；全部调用点均传 `domain_from(request).tenant_id`（`:105/129/149/160/236/259/267/292/310/341/352/402/442/457`，`_get_task_or_404` 另有 draw/invite 等）。
- `_my_expert_or_403` 按 `tenant_id + user_id + deleted=0` 查，且仅允许 `ACTIVE`/`CANDIDATE`。
- `_respond`（`:308-328`）与 `submit_score`（`:350-378`）只认令牌身份；body 里的 `expert_id` 只在 `None/""/本人` 之外抛 40001「不得代他人响应邀请」「不得代他人打分」。实测 B 令牌 + body A → 400，A 的邀请仍 PENDING；B 未受邀 → 404；B 打分指向 A → 400，A 无分、B 的 88 分落库。

**FAIL 的部分（既有，不计本期门槛）**

- `list_experts`（`:89-104`）只 `NExpert.objects.filter(deleted=0)`，无 tenant。
- `list_reviews`（`:222-232`）只 `NReviewTask.objects.filter(deleted=0)`，无 tenant。
- `draw_experts`（`:265-287`）只 `NExpert.objects.filter(status="ACTIVE", deleted=0)`，无 tenant；随后按抽中的 `expert_id` 建 `NReviewInvitation`，会把异租户专家写进本租户任务。
- `invite_experts` 的 MID_CHECK 分支 `NExpert.objects.filter(id=iv.expert_id)`（`:299`）无 tenant。
- `submit_score` 不校验本人是否 ACCEPT 邀请、任务是否可打分；实测未受邀 ACTIVE 专家 `POST /reviews/{id}/scores` → 200，90.00 落库（既有）。

`git show 9f087e9` 确认上述 list/draw 三处基线即无 tenant，属既有遗留；但它们直接违反 M2-c「tenant 隔离覆盖」验收，建议单独立项修复。

### ② 外部角色归一 — **PASS（无外部→内部提权），但有本期引入的降权问题**

**PASS**

- `core/org_scope.py:11` `EXTERNAL_ROLES=("R-PARTNER","R-EXPERT")`；`external_roles_of` 保序去重；`has_external_role` 任一命中；`is_external_only` fail-closed。
- `core/auth/deps.py:62-69` 与 `core/auth/api.py:61-65` 两处裁剪一致：令牌含任一外部角色 → 只保留 `EXTERNAL_ROLES ∩ roles`。
- `create_user`（`apps/sysadmin/api.py:194-198`）外部账号只允许 R-PARTNER/R-EXPERT；`_assert_role_consistency`（`:146-169`）拦外部+内部混合；`assign_role`（`:337-342`）拦外部账号追加内部角色。
- 未发现“多角色/复合/直接签发”让外部用户拿到内部角色的路径；混合角色（R-PARTNER+R-STAFF）会被裁成只有 R-PARTNER。
- `_assert_account_active` 对真实停用/软删用户 → 403 40302（测试 PASS）。

**问题**

- 反向：内部 R-STAFF + R-EXPERT 会被裁成只剩 R-EXPERT（I-2），属本期引入的降权/锁定，且无迁移。
- `_assert_account_active` 对不存在 uid 放行（M-7），属防御纵深 Minor，不是远程提权。
- `login` 查 `SysUserRole` 不带 tenant（`core/auth/api.py:57`），若历史脏数据有跨租户角色行，claims 会带上；当前授权入口已拦混合，但建议补 tenant 过滤。

### ③ 供应商门户隔离 — **数据范围/幂等/脱敏 PASS；准入 FAIL**

**PASS**

- `list_supplier_inquiries` 只返回 `tenant_id` 内、`s.id in invited_supplier_ids` 的 bid；未绑机构 → 空列表。
- `quote_inquiry`：`select_for_update` + tenant + invited 校验；未受邀/不存在 → 404；`status != PUBLICIZING` → 409；同 `supplierId` 先删后 append，重复报价覆盖不重复；实测 `AWARDED` 再报 → 409 40901。
- `list_supplier_contracts` 只返回 `tenant_id + supplier_id=本人` 的合同；未绑 → 空列表。
- 脱敏白名单 10 键：`id/code/name/amount/signed_at/end_date/status/pay_phase_count/paid_amount/paid_ratio`；`party_a/party_b/remark/ai_risk_json/requisition/est_amount` 均不出现；实测 40000/100000 → `0.40`。

**FAIL**

- `_my_supplier` 不拦 `blacklist` / `qualification_expire_date`（I-1），黑名单供应商可看可报价。
- `my_amount` 对缺 `totalAmount` 的历史 `bids_json` 抛 KeyError → 500（M-1）。
- `_CONTRACT_MASK_KEYS` 未使用（M-6）；`list_supplier_contracts` 每合同 2 次聚合/计数查询，`Sum("id")` 的 `n` 未使用（性能 Minor）。
- `list_supplier_inquiries` 只扫描最近 500 条 bid，超出的历史受邀询价不可见（Scalability Minor）。

### ④ 门户过滤 — **PASS（口径一致，未绑/PENDING 安全）；机构状态未单独校验**

- `_my_supplier` 通过 `current_org_id(d)` 取 `SysUser.org_id`，与 `core/org_scope.py:27-38` 同源，口径一致。
- 未绑机构 → 列表空、quote 403；供应商 PENDING → 列表空、quote 403 40301（实测）。
- 机构未批（PENDING）的账号由 `register_partner` 建为 `LOCKED`，登录即 40302，因此“机构未批”没有实际门户入口；但 `_my_supplier` **不校验 `SysPartnerOrg.status`**，若机构在账号 ACTIVE 后被置 REJECTED/SUSPENDED（当前无 API，仅数据运维可能），门户仍可进。建议与 I-1 一起补 `SysPartnerOrg.status == "APPROVED"`（或明确机构状态由账号状态兜底）。

### ⑤ 通知通道 — **邮件失败不阻断 PASS；邮件路由租户正确 PASS；C5 主链路不完整 FAIL**

- `notify_user` 邮件分支有 try/except，失败只 warning，不阻断（PASS）；`apps/p/api.py:863/891/1179` 的调用点未包 try，但那是站内信分支（M-2）。
- `notify_user` 按 `id + tenant_id + deleted=0` 查 `SysUser.email`；`_notify_bid_result` 按 `bid.tenant_id + s.org_id` 找机构用户；未发现跨租户误发。
- 但 `invite_experts` / `create_bid` / `decide_application` / `quote_inquiry` 未接邮件（C-1），C5 不完整。
- `_notify_bid_result` 的收件人是机构下全部 ACTIVE 用户，不是单一联系人；可接受但建议在契约/文案中说明。

### ⑥ 契约与实现一致 — **PASS（本期两份 SAME；全仓 13/16，3 对既有漂移）**

- `09-G` 新增 120 行、`15-N` 新增 257 行，双份 numstat 一致；`cmp` **SAME**。
- `09-G` 的 quote 请求/响应 `totalAmount`、列表 `my_amount` 与 handler 返回键一致；`15-N` 的 `ExpertCredit` snake_case 与 `_expert_credit` 一致；`ExpertApplication` 的 `NEX-年-...` 与 `_expert_code` 的 `NEX-{year}-{id:06d}` 一致。
- 全仓 16 对中 **13 SAME / 3 DIFF**：`04-R`、`08-D`、`14-M` 在 `9f087e9` 基线即 DIFF（design 多 journal/reprint/push、dataio、portrait 等段），属既有漂移，不计本期门槛；但“全仓 cmp 必须一致”的 CI 若存在，会被这三对卡住，建议单独立项同步。
- `totalAmount` 与 G 域 snake_case 风格不一致（M-4），契约/实现自身一致，不是 bug。
- policy/前端/seed 不同口径（M-3、M-5）：R-STAFF 路由、R-LEADER mock POST、R-MANAGER mock 缺 supplier、R-ADMIN seed 缺 page grant、policy 多授 R-MANAGER supplier。均为 fail-closed 或空列表，不构成提权。

### ⑦ 测试有效性 — **PARTIAL：31 个新测试全绿，但关键负例缺失**

- 31 个新增测试全绿；未发现 `or True` 等恒真断言；`test_supplier_sees_only_invited_inquiries` 用精确 id 列表、`test_supplier_contracts_only_mine_and_masked` 用 banned 子串检查 6 个敏感字段，能钉住串数据/脱敏。
- 但缺：
  - PENDING/REJECTED/EXPIRED/blacklist 供应商（I-1、I-6）
  - invite / create_bid / decide_application 的 `mail.outbox`（C-1）
  - 未受邀/未 ACCEPT 打分（既有，但应在外部专家上线前补）
  - `list_experts` / `list_reviews` 跨租户（既有）
  - credit `review_count` / `last_review_at`（I-3）
  - 内部 R-STAFF + R-EXPERT 登录后角色（I-2）
  - admin `list_contracts` 的 `paid_sum`（I-9/既有）
- `_post_tenant` 与 `_post` 相同（死代码）；`test_portal_credit_only_self` 的 docstring 说“他人 id 走门户即 404”，实际两次都断言 200 且返回本人（名实不符，没有验证“他人 id”负例）。
- 无法从仓库证明这些测试曾“真红过”；2079f9c 的 `status` 过滤没有测试钉住（I-6）。

### ⑧ 回归风险（`values()+annotate()` 同类 bug） — **PASS**

- 全仓扫描 `.values(` + `.annotate(`：无第二处“返回 dict 却按对象属性取键”。
- `apps/procure/api.py:487-495` 已修 `row["contract_id"]/row["paid_sum"]`；`apps/dataops/api.py:87/215`、`apps/activity/api.py:335/338` 均按键取值正确。
- `apps/dataops/api.py:64` 的 `dept_rows` 聚合结果从未使用（死代码，M-6）。
- 但同一语句的聚合字段仍是 `Sum("plan_amount")`（I-9，既有语义问题）：`_api_contract` 把该值输出为 `paid_sum`，实际是“计划付款额”而非“已付额”。种子引入付款计划后该分支被覆盖，建议改为 `Sum("paid_amount")` 并补 admin 合同列表测试。

---

## 6. 既有遗留（只列，不计本期门槛）

以下均在 `9f087e9` 基线存在（`git show 9f087e9` 复核），不因本次变更引入；但 M2-c 的“tenant 隔离覆盖”验收未覆盖，建议单独排期。

### E-1 N 域列表/抽专家跨租户（Critical）

- `apps/expertreview/api.py:89-104` `list_experts` 无 tenant
- `:222-232` `list_reviews` 无 tenant
- `:265-287` `draw_experts` 无 tenant
- `:299` MID_CHECK 邀请回填 `NExpert.objects.filter(id=...)` 无 tenant

实测：tenant1 R-MANAGER 能读到 tenant2 的专家/评审，能把 tenant2 唯一 ACTIVE 专家抽进 tenant1 任务。属既有 Critical，直接违反本期验收口径，但按“既有不计门槛”处理。

### E-2 G 域跨租户写（Critical）

- `apps/procure/api.py:78-82` `_get_req_or_404`、`:85-89` `_get_contract_or_404` 无 tenant
- `:304` `create_bid` 的 `GSupplier.objects.filter(id=..., deleted=0)` 无 tenant
- `:326` `award_bid` 的 `GBid.objects.filter(id=id, deleted=0)` 无 tenant
- `:337` `award_bid` 的供应商查询无 tenant
- `:382` `_notify_bid_result` 的供应商查询无 tenant
- `:448` `create_contract`、`:528` 的供应商查询无 tenant

tenant1 可按 id 对 tenant2 的采购申请发标/定标/建合同，或把 tenant2 供应商写进 tenant1 合同。既有 Critical，建议独立安全单。

### E-3 `ark/ark` dev 后门（Critical）

- `core/auth/api.py:24-25` `DEV_USER/DEV_PASSWORD="ark"`
- `:37` 仅当不是 ark/ark 才查库
- `:50-52` `user is None` 即签发 `uid=1, tenant=1, roles=["R-STAFF","R-MANAGER"]`，无 DEBUG/env 门禁

`git log -S'DEV_USER'` 指向初始脚手架 `655f5d7`，属既有。生产若暴露登录端点，任何知道 ark/ark 的人可拿管理员级内部令牌。建议立即用 `settings.DEBUG` 或显式 env 开关封死。

### E-4 未受邀专家可对同租户任意评审任务打分（Critical/Important）

- `apps/expertreview/api.py:350-378` `submit_score` 只校验 `_my_expert_or_403` + tenant 任务，不校验 `NReviewInvitation` 是否存在/ACCEPT、任务状态是否可打分。
- 实测未受邀 ACTIVE 专家 → 200，90.00 落库；且 `submitted >= accepted` 的计数会把任务推进 `COLLECTING`，数据完整性受影响。

既有；M2-c 把外部专家接进来后，暴露面变大，建议在 C3 上线前一并修。

### E-5 admin 合同列表 `paid_sum` 取的是 `plan_amount`（Important）

- `apps/procure/api.py:488-495` `.annotate(paid_sum=Sum("plan_amount"))`
- `:500-514` `_api_contract` 把 `paid_sum` 输出为已付

供应商门户用的是 `Sum("paid_amount")`（`apps/procure/portal.py:181-183`），admin 列表却用计划额；种子付款计划（plan 100000 / paid 40000）下 admin 会显示 100000。既有语义 bug，本期种子使其可见。建议改 `Sum("paid_amount")`。

### E-6 契约 3 对既有漂移（Minor）

- `04-科研成果管理-R.openapi.yaml`
- `08-数据分析与决策-D.openapi.yaml`
- `14-科研绩效评价-M.openapi.yaml`

`9f087e9` 与 `2079f9c` 均 DIFF；design 侧多 journal/reprint/push、dataio、portrait 等段。不计本期门槛，但全仓 cmp 门禁需要单独立项同步。

---

## 7. 合并前最小修复清单（按顺序）

1. **C-1**：补 `invite_experts` / `create_bid` / `decide_application` / `quote_inquiry` 的 `notify_user` 接线；每个至少 1 条 `mail.outbox` 断言，收件人 email/tenant 正确。
2. **I-1 + I-6**：`_my_supplier` 补 `blacklist` / `qualification_expire_date` / `SysPartnerOrg.status`；补 PENDING/REJECTED/EXPIRED/blacklist 四组负例。
3. **I-2 + I-5**：`_grant_expert_role` / `audit` 校验 `user_source=EXTERNAL` 与用户 tenant；补数据迁移/管理命令处理存量内部 R-EXPERT；补“内部 R-STAFF + R-EXPERT 登录后角色”测试。
4. **I-3**：信用档案 `review_count`/`last_review_at` 改为实时聚合或 `submit_score` 更新；补测试。
5. **I-4**：与计划书对齐 REJECT 状态；提供重新申请/管理员重置路径；测试不要固化偏差。
6. **M-1/M-2/M-3/M-4/M-5/M-6/M-7/M-8/M-9**：按各条建议清理；至少 M-1 的 `.get("totalAmount")` 与 M-3 的 R-STAFF 路由/R-LEADER mock 多余 POST 应在本期修掉。
7. 既有 E-1/E-2/E-3/E-4/E-5 单独立项，不阻塞本次合并，但建议在 M2-c 对外上线前至少修 E-4 与 E-3。

---

## 8. 附：关键探针复现方式

所有探针均为临时 pytest 文件（`/tmp/test_probe*.py`）+ `tests.conftest`，通过 `--ds=config.settings.test` 跑，不写入仓库。核心步骤：

```bash
cd backend-django
.venv/bin/python -m pytest -q /tmp/test_probe_m2c.py -p tests.conftest --ds=config.settings.test -s
```

- 跨租户列表：tenant2 建 `NExpert/NReviewTask`，tenant1 `bearer(manager, ["R-MANAGER"])` 请求 `/api/v1/experts`、`/api/v1/reviews`。
- 抽专家：tenant1 建 task，`POST /api/v1/reviews/{id}/draw`，观察 `drawn` 含 tenant2 专家 id。
- 黑名单门户：`GSupplier(status="IN_LIBRARY", blacklist=True)` + `GBid(invited_supplier_ids=[s.id])`，R-PARTNER 请求 list/quote。
- 邮件：`django.core.mail.outbox` 清空后调 invite/create_bid，断言长度。
- 内部角色：`SysUser(user_source="INTERNAL")` + R-STAFF，建 CANDIDATE，R-MANAGER audit，再 `/auth/login` 解 JWT。
- 500：`GBid.bids_json=[{"supplierId": s.id}]`，R-PARTNER GET inquiries。

以上结果已写入第 1 节表格；报告未修改任何源码或测试。

---

**最终结论：REQUEST_CHANGES。** 本期在“单条 N 域收口、门户数据范围/脱敏/幂等、契约双份、密码/停用即时失效”上完成度较高；但 C5 的外部主链路邮件缺失、供应商门户黑名单准入缺口、信用档案字段失真、内部 R-EXPERT 降权与 seed 专家演示缺失，尚不足以合并。
