# E-7 终审报告（第五轮 / r4 修复确认）：跨域 id 收口

- 评审对象：`develop` 分支 `git diff 1b1b55f..d98b305`（9 commits）。本轮新增 `d98b305 fix(跨域): 修正案/纪检档案/人遗备案/团队/访客/人员/资产/成果写入收租户（E-7 复审 r4 C-1..C-7）`，其父为 r4 评审的 `57ac05f`。
- 评审方式：只读。全部测试/探针在 `git archive d98b305` 的干净导出树 `/tmp/e7r5-clean` 执行；探针脚本只写 `/tmp`；真实仓库本次**唯一写入是本报告**（源码/测试/契约/policy 零改动）。
- 基线：`608 passed, 19 warnings in 47.76s`；本轮无回退。
- 证据口径：状态码、落库值、原始响应片段均为本轮实测；无法构造 HTTP 链的仅凭源码判读，文中标注「代码判读」。

---

## VERDICT

**REQUEST_CHANGES —— 不可推送 `develop`，不可上生产。**

r4 的 C-1、C-2、C-3、C-4、C-6、C-7 已**真闭环**：16 个跨租户探针里 15 个由 200/落库变为 404/库不变（含 2 个读探针），本租户反向 14 条全部仍 200；回归 608 绿、契约零 diff、7 条新用例在 `57ac05f` 上 7 红。但 **C-5 只闭环了一半**：`approve_visitor` 仍裸 `SVisitor.objects.filter(id=id)`，本轮实测 tenant-1 令牌可把他租户访客审批为 `APPROVED` 并写入 `role_codes: ["R-ADMIN"]`（200）；同文件 `_get_visitor_or_404`（`apps/staff/api.py:60`）已写好却**零调用**——是「写漏接」而不是设计取舍。

此外 F 段再扫出**一条未收口的跨租户写链**（非 r4 清单内）：`POST /api/v1/reviews` 的 `target_id` 不做归属校验，`conclude` 经单一写者 `conclude_output_eval` 直接改他租户成果（实测 `CLAIMED→ASSIGNED_TO_PROJECT`、`is_claimed=False→True`）。同类的 `MID_CHECK` 邀请回填同构（代码判读）。

因此本轮问题不在「修得对不对」，而在「还有两处收口没接上」。C-1/C-2 均为数行修复，修完并补两条用例即可复审通过。存量 `apps/archive`（document/案卷/借阅）仍整域裸 id，属 r3 D-4 / r4 附录的已知 backlog，不构成本期新增回归，但需在结论里明确处置口径。

---

## 一、实测数字

| # | 项目 | 本轮实测 | 期望/上轮 |
|---|---|---|---|
| 1 | HEAD / 提交数 | `d98b305` / 9 | 9 |
| 2 | `1b1b55f..d98b305` 总量 | 21 文件 +1371 / −189 | — |
| 3 | `d98b305` 自身 | 7 文件 +217 / −67 | — |
| 4 | 全量 pytest（干净树） | **608 passed, 19 warnings in 47.76s** | 608 |
| 5 | `makemigrations --check --dry-run` | **No changes detected** | No changes |
| 6 | `git diff 1b1b55f..d98b305 -- design/ frontend/src/api/schema/` | **空**（0 字节输出） | 空 |
| 7 | README 第 5/29/99 行 | 608 / 608 / 608 | 608 |
| 8 | r4 的 7 条新用例 @`57ac05f` 实现 | **7 failed, 22 deselected in 3.42s** | 7 红 |
| 9 | 同一批用例 @`d98b305` | 全绿（含在 608 内） | 绿 |
| 10 | 跨租户写探针（r4 C-1..C-7 复测） | **16 项：15×404，1×200** | 16×404 |
| 11 | 本租户反向探针 | **14 项：14×200** | 全 200 |
| 12 | r4 A 段回归（ethics 详情/提交、任务、认领） | 3/3 与 r4 一致（404/404/`success=false`） | 不变 |
| 13 | helper 调用点计数 | team 4、staff 11、visitor **0**、asset 7、output 5、ethics 6 | 全接线 |
| 14 | `apps/*/api.py` 无 tenant 的 `filter(id=`/`get(id=`/`select_for_update` 候选 | 66 行；可达跨租户写 **2 处**（访客审批、评审回写），存量 1 域（archive） | 0 |
| 15 | 新增跨租户写链实测 | `R.create 200` → `R.conclude 200 ASSIGNED_TO_PROJECT True` | 404/不变 |

---

## 二、A 段：r4 的 C-1..C-7 是否真闭环（逐条）

探针 `/tmp/e7r5-clean/backend-django/tests/test_probe_r5.py`（3 passed），tenant-1 令牌打 tenant-2 资源，输出按资源逐行打印。

### A-1 ethics 修正案决定（r4 C-1）—— 已闭环

`apps/ethics/api.py:425-431` 新增 `_get_amendment_or_404(request, aid)`：

```python
a = CAmendment.objects.filter(
    id=aid, tenant_id=domain_from(request).tenant_id, deleted=0).first()
if a is None:
    raise ApiError(404, CODE_NOT_FOUND, "修正案不存在")
```

`decide_amendment`（`:454`）改用该 helper；`CAmendment.objects.filter(id=` 裸查全仓 0 处。实测：

```
X.amendment 404 SUBMITTED
```

即 404 且修正案状态仍 `SUBMITTED`（r4 为 `200 / APPROVED`）。反向本租户 `O.amendment 200 APPROVED`。

### A-2 project 分类挂接（r4 C-2）—— 已闭环

`apps/project/api.py:1010-1012`：

```python
n = EProject.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).update(
    category_id=category_id, updated_at=dj_tz.now())
```

实测 `X.project.category 404 None`（r4 为 `200` 且 category 被改成 tenant-1 的 1）；反向 `O.project.category 200 5`。

### A-3 output 成果族（r4 C-3）—— 已闭环

`apps/output/api.py:92-96` 改为 `_get_output_or_404(request, output_id)`，5 个调用点（`:181` get_output、`:271` link_projects、`:402` create_reprint、`:483` set_patent_stage、`:499` create_patent_fee）全部传 `request`；`:486` 的 `ROutput.objects.get(id=id, tenant_id=domain_from(request).tenant_id)` 也补了租户。实测：

```
X.output.link 404 ASSIGNED_TO_PROJECT
X.output.stage 404 PRE_APPLY
X.output.fee 404
X.output.reprint 404
X.output.get 404
```

五个写/读端点全 404 且成果状态未变（r4 分别为 200/ASSIGNED_TO_PROJECT、200/APPLIED、200 建费用、200 建转载、200 跨租户读）。反向：`O.output.link/stage/fee/reprint/get` 全 200，stage 落 `APPLIED`。

`conclude_output_eval`（`:295-305`）仍是裸 `filter(id=output_id, deleted=0)`，但 docstring 已改为「tenant 由调用方保证」——这条纪律本身在 F 段被击穿，见 C-2。

### A-4 staff 人员/团队/访客（r4 C-4、C-5）—— 人员与团队已闭环，**访客审批未闭环**

- `apps/staff/api.py:69-77` `_get_staff_or_404(request, sid)`，11 个调用点全部接线；实测 `X.staff.transfer 404 ACTIVE ACTIVE`、`X.staff.get 404`（r4 为 `200 / RESIGNED / INACTIVE`、`200` 全量档案）。
- `apps/staff/api.py:51-58` `_get_team_or_404(request, tid)`，4 个调用点（`:484/:501/:518/:539`）；实测 `X.team.add 404 []`、`X.team.members 404`。
- **`apps/staff/api.py:622-643` `approve_visitor` 未改**：

```python
def approve_visitor(request: HttpRequest, id: int):
    dom = domain_from(request)
    v = SVisitor.objects.filter(id=id, deleted=0).first()   # ← :624，无 tenant
    ...
    v.status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    if decision == "APPROVE":
        scope = v.permissions_scope or {}
        if b.get("role_codes"):
            scope["role_codes"] = b["role_codes"]            # ← :637，写入请求体给的 role_codes
        v.permissions_scope = scope
```

而 `apps/staff/api.py:60-67` 的 `_get_visitor_or_404(request, vid)` 已写好却**全仓零调用**（`grep -rn _get_visitor_or_404 apps` 只命中定义行）。实测：

```
X.visitor.approve 200 APPROVED {'role_codes': ['R-ADMIN']}
```

即 tenant-1 的 R-MANAGER 把 tenant-2 的访客审批通过，并把 `role_codes=["R-ADMIN"]` 写进该访客的权限范围。反向 `O.visitor.approve 200 APPROVED` 正常。**这是本轮唯一未闭环的 r4 项，且提交标题明确声称修了「访客」。**

### A-5 asset 资产（r4 C-6）—— 已闭环

`apps/asset/api.py:77-83` `_get_asset_or_404(request, aid)` 带 tenant，7 个调用点（`:280/:303/:350/:375/:396/:684/:779`）；凭证回调 `:649-651` 的 `ADepreciation.objects.filter(id=..., tenant_id=dom.tenant_id, deleted=0)`。实测 `X.asset.issue 404 IDLE None`（r4 为 200 且 IDLE→IN_USE、project_id=1）；反向 `O.asset.issue 200 IN_USE 1`。

### A-6 ethics 纪检/人遗备案（r4 C-7）—— 已闭环

`apps/ethics/api.py:434-440` `_get_integrity_or_404`、`:443-449` `_get_hgr_or_404`；`update_integrity_record`（`:619`）、`delete_integrity_record`（`:714`）、`sync_hgr_filing`（`:767`）、`get_integrity_record`/`appeal` 全部改用。实测：

```
X.integrity.put 404 原结论
X.integrity.get 404
X.integrity.delete 404 0
X.hgr.sync 404 DRAFT
```

r4 分别为 200/改写、200、200/软删、200/NATIONAL_RECEIVED。反向三条全 200 且落库。

### A-7 反向验证汇总（未过度收紧）

```
O.amendment 200 APPROVED          O.integrity.put 200 本租户改写
O.hgr.sync 200 NATIONAL_RECEIVED  O.project.category 200 5
O.output.link 200                 O.output.stage 200 APPLIED
O.output.fee 200                  O.output.reprint 200
O.output.get 200                  O.staff.transfer 200 RESIGNED INACTIVE
O.team.add 200 1                  O.team.get 200
O.visitor.approve 200 APPROVED    O.asset.issue 200 IN_USE 1
```

14/14 通过，覆盖 lead 点名的 5 个关键端点。

---

## 三、B 段：I-1 软删绕过（复核）

`d98b305` 未触碰 `apps/funding`、`apps/transform`（`git diff --name-only 57ac05f..d98b305` 仅 7 个文件：README、asset/ethics/output/project/staff 的 api.py、tests）。I-1 的修法仍是 `apps/funding/api.py:241-254` 的 `_reject_foreign_ref`：

```python
if model.objects.filter(id=oid).exclude(tenant_id=tenant_id).exists():
    raise ApiError(404, CODE_NOT_FOUND, f"{label}不存在")
```

其应用点 `:817-818`（create_expense，EProject+SysLegalEntity）、`:1040-1044`（create_outward）、`:2235`（create_loan）与 `apps/transform/api.py:153-167`（create_disclosure，ROutput/EProject 同口径）均未改。r4 实测两条：

```
B expense soft-deleted 404 {"code": 40401, "message": "项目不存在"}
B disclosure soft-deleted 404 {"code": 40401, "message": "成果不存在"}
```

结论：B 段维持 r4 的 PASS（软删/不存在一律 404，不再放行）。

---

## 四、C 段：I-2 公示脱敏（复核）

`apps/transform/{api,mappings}.py` 本轮零 diff：

- `apps/transform/mappings.py:243-278`：`_mask_name`（首字+`*`）、`_mask_contact`（≥7 位前 3+`****`+后 4）、`to_api_publicity_public`（`handle_result: None`）。
- 公开路由 `config/api.py:671 GET /publicity/{dealId}`（无 auth）→ `get_publicity` → `to_api_publicity_public`（`apps/transform/api.py:589-598`）。
- 内部 `handle_objection`（`:660-666`）响应仍用 `to_api_publicity`，保留 `handle_result`。

r4 实测（本轮路径未变）：公开 GET 响应体 `[{"objection_id":"OBJ1","submitter":"张**","contact":"138****0000","content":"权属存在争议","handle_status":"PROCESSING","handled_at":null,"handle_result":null}]`，不含 `张三丰`/`13800000000`；内部 handle 后响应 `handle_result == "已处理 张三丰"`。C 段维持 PASS。

---

## 五、D 段：I-3 迁移 0019（复核）

`d98b305` 未改迁移。`apps/sysadmin/migrations/0019_purge_stale_policy_e7.py`：

```python
STALE_POLICY = [("/api/v1/disclosure/*", "GET")]
```

只删该 `(obj, act)` 的 `SysRolePermission` 与 `SysPermission`，随后 `sync_permissions_from_csv`（只增不删）；`purge_stale_policy_rows` 全仓 0 残留（含 tests，除 pycache）。r4 在已 seed 库上先 `migrate sysadmin 0018` 再 `0019` 实测：`stale 1→0`、`custom 1→1`、`same_obj_other_act 1→1`。D 段维持 PASS。

遗留 Minor 不变：docstring 第 7 行称「只删这**两**条已知下线的规则」，`STALE_POLICY` 只有 1 条。另：原地改写 0019 意味着已执行旧版 0019 的库不会重跑新逻辑，部署时需确认存量库的 `sys_role_permission` 现状（r4 已提，非本轮新增）。

---

## 六、E 段：回归与卫生

- **全量回归**（干净树、探针已删）：`608 passed, 19 warnings in 47.76s`。数量 = r4 的 601 + 本轮 7 条。
- **`makemigrations --check --dry-run`**：`No changes detected`。
- **契约零 diff**：`git diff 1b1b55f..d98b305 -- design/ frontend/src/api/schema/` 输出为空。
- **README**：第 5 行「全量 608 pytest 通过」、第 29 行「tests/（608 个）」、第 99 行「当前 608 passed」。
- **红测**：把 `d98b305` 的 `tests/test_e7_review_fixes.py` 覆盖到 `57ac05f` 实现上，跑 7 条新用例 → `7 failed, 22 deselected in 3.42s`，失败点均为 `_is_tenant_scoped` 断言（非 import/签名错误），说明用例真正钉住行为而不是钉住实现：
  - `test_ethics_amendment_decision_is_tenant_scoped`（`:428`）
  - `test_ethics_integrity_update_is_tenant_scoped`（`:444`）
  - `test_project_category_attach_is_tenant_scoped`（`:459`）
  - `test_output_link_projects_is_tenant_scoped`（`:469`）
  - `test_staff_transfer_is_tenant_scoped`（`:482`）
  - `test_team_add_member_is_tenant_scoped`（`:498`）
  - `test_asset_issue_is_tenant_scoped`（`:515`）
- **测试夹带检查**：`d98b305` 对测试文件只有 +112/−0；对既有测试的改动仅出现在早期 commit，且都是随语义收紧的正当调整（`test_funding_domain.py` 改为先建本租户项目；`test_funding_m1a.py` 把「悬空预算行在提交时才 404」改为「建单即 404」），无删断言、无 skip/xfail。
- **逐 commit `--stat`**：9 个 commit 均为「本域实现 + 本域测试（+ 必要的 README/policy）」，无脚本、无可执行产物、无 `_reference/`、无 lockfile、无 `.venv`。`d98b305` 的 7 个文件与提交标题一一对应（唯一的例外是标题声称的「访客」并未真正接上，见 A-4）。
- **工作树**：真实仓库除本报告外零写入；评审开始前后 `git status --porcelain` 的未跟踪 docs/ 图片等噪声与本次无关（本轮未触碰）。

---

## 七、F 段：全仓再扫（决定能否上生产）

扫描口径：`apps/*/api.py` 中所有 `objects.filter(id=` / `objects.get(id=` / `select_for_update()` 且所在行/条件串未带 `tenant_id` 的位置，共 66 行；逐行判断「是否 HTTP 可达」「是否后接写」「上游是否有租户校验」。

### F-1 仍可跨租户写 —— 2 处（本轮新增 / 未闭环）

**F-1.1 【Critical】访客审批（r4 C-5 漏接）**

- 位置：`apps/staff/api.py:622-643`，裸查在 `:624`。
- 路由/策略：`config/api.py:749 POST /visitors/{id}/approve`；`config/casbin/policy.csv:739 p, R-MANAGER, /api/v1/visitors/*/approve, POST`。
- 实测（见 A-4）：`200 APPROVED {'role_codes': ['R-ADMIN']}`，租户 2 的访客被租户 1 改写状态与权限范围。
- 修复：`:624` 换成已存在的 `_get_visitor_or_404(request, id)`（一行）。

**F-1.2 【Critical】评审回写链：`create_review.target_id` 无归属校验 → 单一写者直写他租户成果**

- 入口：`apps/expertreview/api.py:242-256` `create_review` 原样接收 `target_id`、`project_id`（仅要求 `biz_type`/`title`）：

```python
t = NReviewTask.objects.create(
    ..., tenant_id=d.tenant_id, biz_type=b["biz_type"], target_type=b.get("target_type"),
    target_id=b.get("target_id"), project_id=b.get("project_id"), ...)
```

- 出口：`apps/expertreview/api.py:464-478` `conclude_review` → `:481-498` `_conclude_writeback` → `apps/output/api.py:295-305` `conclude_output_eval(output_id, passed)`：

```python
o = ROutput.objects.filter(id=output_id, deleted=0).first()   # 无 tenant
...
o.status = "ASSIGNED_TO_PROJECT"; o.is_claimed = True
```

- 路由/策略：`config/api.py:478 POST /reviews`、`:491 POST /reviews/{id}/conclude`；`config/casbin/policy.csv:218/:224` 均允许 R-MANAGER。
- 实测（`tests/test_probe_r5b.py`，1 passed）：

```
R.create 200 1
R.conclude 200 ASSIGNED_TO_PROJECT True
```

tenant-2 成果（`CLAIMED / is_claimed=False`）被 tenant-1 的两次请求改成 `ASSIGNED_TO_PROJECT / is_claimed=True`，全程不需要读 tenant-2 任何数据，只需知道 output id。
- 同构路径（代码判读，未逐一构造 HTTP 链）：`biz_type=MID_CHECK` → `:305` → `apps/project/api.py:1292-1296 set_mid_check_experts`（`EMidCheck.objects.filter(id=...)` 无 tenant，写 `expert_ids`）；`conclude_mid_check`（`:1354`）/`conclude_final_accept`（`:1384`）同样以裸 id 进入、tenant 取自行记录。
- 根因：单一写者（`conclude_output_eval`/`set_mid_check_experts`/`conclude_mid_check`/`conclude_final_accept`）只靠 docstring 声明「tenant 由调用方保证」，入口 `create_review` 又允许请求体指定 `target_id`，纪律链断在第一环。
- 修复建议：`create_review` 对 `target_id` 做归属校验（按 `biz_type` 分派到 ROutput/EMidCheck/EFinalAccept/PGuideline，`tenant_id=d.tenant_id`），或在 `_conclude_writeback` 前校验 `target.tenant_id == t.tenant_id`。

### F-2 存量、E-7 范围外 —— 1 域（archive/document/borrows）

`apps/archive/api.py` 整域未收租户（r3 D-4 已列，r4 附录已记，本轮无变化）：

| 位置 | 写/读 | 可达性 | 判定 |
|---|---|---|---|
| `:53 _get_doc_or_404`、`:60 _get_archive_or_404` | 基座 | 被以下 handler 共用 | — |
| `:181-192 delete_document` | 写（软删） | `DELETE /documents/{id}`，R-ADMIN（policy:259） | 跨租户删文档 |
| `:255-272 update_archive` | 写 | `PUT /archives/{id}`，R-MANAGER（policy:248） | 跨租户改标题/密级/保管年限 |
| `:274-284 delete_archive` | 写（软删） | `DELETE /archives/{id}`，R-ADMIN（policy:260） | 跨租户删案卷 |
| `:307-318 fill_item` | 写 | `PUT /archives/{id}/items/{item_id}`，R-MANAGER | 跨租户改清单条目 |
| `:321-327 delete_item` | 写（硬删） | `DELETE /archives/{id}/items/{item_id}` | 跨租户删条目 |
| `:493-506 _set_borrow_status` | 写 | approve/reject/return（policy:261/262） | 跨租户改借阅状态 |
| `:472-489 list_borrows` | 读 | `GET /borrows`，R-MANAGER/R-ADMIN | 跨租户列全部借阅 |
| `:221-236 list_archives`、`:193-213 search_documents` | 读 | `GET /archives`、`GET /documents/search` | 跨租户列案卷/全文检索 |

按 E-7 的判据（跨租户写 = Critical），这一域**足以单独判 Critical**；但它不在 E-7 的收口范围（r1 范围是 activity/confsec/funding/transform，r3 起追加 ethics/project/output/staff/asset），且 r3/r4 均已作为 backlog 记录。本报告将其列为 **Important（存量、范围外）**，不构成本期新增回归；但「能否上生产」的答案必须把它算进去（见 §九）。

### F-3 判定为安全 / 仅读的候选（抽查 12 处，均有上游租户校验或不可达）

| 位置 | 结论 |
|---|---|
| `apps/project/api.py:661/:683 EChangeRequest.update(id=change_id)` | 安全：`_advance_change`（`:625-627`）先按 `id+tenant_id` 取 `row`，更新点在同租户 row 上 |
| `apps/project/api.py:1231/:1254/:1281 EApplication.update` | 安全：`approve_application`/`application_to_project` 先 `filter(id=id, tenant_id=d.tenant_id)` |
| `apps/project/api.py:1294/:1358/:1389`（mid-check/final-accept 单一写者） | 内部入口，不挂 HTTP；`conclude_mid_check` 用 `tenant_id=mc.tenant_id` 反查项目（`:1367`）。风险已并入 F-1.2 |
| `apps/project/api.py:251 ETask.filter(id=task_id, project_id=id)` | 安全：项目先经 `_get_project_or_404(request, id)` |
| `apps/performance/api.py:293/:317 MSchemeFactor` | 安全：`_scheme_or_404(request, id)` 先收租户，factor 绑 `scheme_id` |
| `apps/dataops/api.py:73 EProject.filter(id=b.project_id)` | 仅读：`b` 来自本租户 budgets |
| `apps/funding/api.py:926/:1137/:1323 .get(id=id)` | 仅读：都是刚按 tenant 写入/查询后的回读 |
| `apps/funding/api.py:2359-2464 FLoan.update(id=loan.id)` | 安全：`loan` 来自带 tenant 的 `select_for_update` 查询 |
| `apps/activity/api.py:369 VActivityParticipant.delete(id=pid, activity_id=id)` | 安全：先 `_get_activity_or_404(d.tenant_id, id)` |
| `apps/p/api.py:719 NReviewTask.filter(id=id)` | 安全：随后 `if id not in _my_review_task_ids(d.user_id): 403` |
| `apps/procure/api.py:392 FBudgetLine.filter(id=<remark 解析>)` | 仅读：行 id 来自本租户单据 remark |
| `apps/sysadmin/api.py:860 SysPartnerOrg.select_for_update().get(id=org.id)` | 安全：`org.id` 来自本请求已取到的行 |

### F-4 仅读、低危（Minor）

| 位置 | 说明 |
|---|---|
| `apps/staff/api.py:341 SStaff.filter(id=other_id)` | 合作网络图里补 `name`；边按 tenant 收口，但 `other_id` 可能是他租户人员 → 跨租户读姓名 |
| `apps/p/api.py:633 NReviewTask.filter(id=task_id)` | `ai_review_draft` 无归属校验 → 跨租户「任务存在性」预言机（不返回任务内容） |
| `apps/expertreview/api.py:305/:321/:526 NExpert.filter(id=iv.expert_id)` | `NExpert.tenant_id` 存在但查询未带；`expert_id` 来自本租户抽取池，仅可能泄露姓名/邮箱（通知） |
| `apps/archive/api.py:430 ODocument.filter(id=it.doc_id)` | 条目文档元数据；已并入 F-2 |
| `apps/project/api.py:1580 ODocument.filter(id=doc_id).exists()` | 存在性检查无 tenant，可能探测他租户文档 id；无写 |

---

## 八、问题清单（按级别）

### Critical（阻断）

**C-1 访客审批跨租户写（r4 C-5 未闭环，提交标题声称已修）**

- 位置：`apps/staff/api.py:622-643`（裸查 `:624`；`role_codes` 写入 `:637`）；`_get_visitor_or_404` 定义在 `:60-67` 但零调用。
- 复现：
  1. tenant-2 建 `SVisitor(status="APPLIED")`；
  2. tenant-1 `bearer(1, ["R-MANAGER"])` `POST /api/v1/visitors/{id}/approve {"decision":"APPROVE","role_codes":["R-ADMIN"]}`；
  3. 实测 `200`，`v.status=APPROVED`，`permissions_scope={"role_codes":["R-ADMIN"]}`。
- 影响：跨租户改写安全相关字段；若后续 token 签发读取 `permissions_scope`，即为提权前置（当前代码全仓未见消费点，故按「跨租户写 + 权限暂存污染」计）。
- 修复：`v = _get_visitor_or_404(request, id)`；补 `test_visitor_approve_is_tenant_scoped`。

**C-2 评审回写链跨租户写成果**

- 位置：`apps/expertreview/api.py:242-256`（`target_id` 未校验）、`:464-478`、`:481-498`；`apps/output/api.py:295-305`。
- 复现：
  1. tenant-2 建 `ROutput(status="CLAIMED", is_claimed=False)`；
  2. tenant-1 `bearer(1,["R-MANAGER"])` `POST /api/v1/reviews {"biz_type":"OUTPUT_EVAL","target_id":<oid>,"project_id":1,"title":"x"}` → `200`；
  3. `POST /api/v1/reviews/{rid}/conclude {"conclusion":"PASS"}` → `200`；
  4. 实测成果变 `ASSIGNED_TO_PROJECT`、`is_claimed=True`。
- 影响：跨租户改成果状态/认领位；同构可达 `MID_CHECK` 的 `expert_ids`。
- 修复：`create_review` 按 `biz_type` 校验 `target_id` 归属；或在 `_conclude_writeback` 前校验目标 `tenant_id == t.tenant_id`；补 `test_review_target_is_tenant_scoped`。

### Important

**I-1 archive/document/borrows 整域裸 id（存量、r3 D-4 遗留）**

- 位置与影响见 F-2 表；`apps/archive/api.py:53/:60` 两个 helper 无 tenant，`delete_document`、`update_archive`、`fill_item`、`delete_item`、`_set_borrow_status`、`list_borrows`、`search_documents` 均直接可达。
- 现状：r3 已列 D-4，r4 附录已记；本轮复扫确认**未变化**。
- 建议：单开一期（同 E-7 手法：`_get_*_or_404(request, ...)` + 调用点接线 + 5–8 条红转绿用例）；在上生产前至少对 `R-ADMIN DELETE /documents/*`、`R-ADMIN DELETE /archives/*` 加补偿控制。

**I-2 单一写者纪律无强制点（C-2 的根因）**

- `conclude_output_eval`（`apps/output/api.py:295`）、`set_mid_check_experts`（`apps/project/api.py:1292`）、`conclude_mid_check`（`:1354`）、`conclude_final_accept`（`:1384`）均只靠 docstring 声明「tenant 由调用方保证」。一旦入口（如 `create_review`）漏校验即穿透。
- 建议：单一写者内部按记录 `tenant_id` 反查并断言与 `project_id` 一致（或把 `tenant_id` 作为显式参数，签名漂移即测试红）。

**I-3 C-5 的测试盲区**

- `tests/test_e7_review_fixes.py` 的 7 条新用例（`:428-527`）覆盖修正案、纪检、分类、关联、人员、团队、资产，**没有访客**；`grep -n visitor tests/test_e7_review_fixes.py` 无命中。因此 608 绿不能证明 C-5 闭环——这也是「helper 写好但未接线」能逃过回归的直接原因。
- 建议：本轮修复必须同时补 `visitor approve` 与 `review target` 两条用例，且先在 `d98b305` 上验证它们红。

**I-4 只读泄漏（低敏）**

- `apps/staff/api.py:341`（合作网络补姓名）、`apps/p/api.py:633`（任务存在性）、`apps/expertreview/api.py:305/321/526`（专家姓名/邮箱）、`apps/project/api.py:1580`（文档存在性）。均可由本租户角色触发，返回信息有限，建议随下一期一并收。

### Minor

- **M-1** `apps/sysadmin/migrations/0019_purge_stale_policy_e7.py:7` docstring 写「这两条」，`STALE_POLICY` 只有 1 条（r4 M-1 未改）。
- **M-2** `conclude_output_eval` 的 docstring 已正确声明调用方责任，但没有指向 `create_review` 这个具体调用方，读代码的人无法判断「谁保证」。建议在 docstring 写明「唯一 HTTP 入口是 expertreview.create_review，必须校验 target 归属」。
- **M-3** `_get_visitor_or_404` 目前是死代码（也会被 lint 的「unused」类规则盯上）；随 C-1 修复即消失。
- **M-4** 干净树导出 113MB、跑一轮全量约 48s；本轮 3 个探针文件已全部删除，未污染仓库。

---

## 九、结论：本期验收口径

1. **范围**：以 r4 报告 §9 的 C-1..C-7 + 本轮 F 段「可 HTTP 直达的跨租户写」为验收面；archive/document/borrows 作为 r3 D-4 存量 backlog 单列，不计入本期新增回归，但计入上生产判断。
2. **判据**：跨租户写 = Critical（阻断）；跨租户读 = Important（不阻断合并，限期）；文档/注释/死代码 = Minor。
3. **本期实测**：7 类中 6 类真闭环（16 个跨租户探针里 15 个 404、反向 14 个 200）；1 类（访客）为假闭环；F 段另发现 1 条未收口写链（评审回写）。因此 **`1b1b55f..d98b305` 不能推 `develop`**。
4. **复审门槛**：修 C-1（一行接 `_get_visitor_or_404`）+ C-2（`create_review` 的 `target_id` 归属校验或 writeback 前断言），各补 1 条「先红后绿」用例；复跑全量应为 610 passed，契约零 diff。其余 Important 可作为同一 PR 的附加项，不作阻断。
5. **上生产口径**：**当前不可上生产**——C-1/C-2 都是「知道 id 就能改他租户数据」的写路径，且 C-2 会污染成果认领状态；archive 域的 `R-ADMIN DELETE /documents/*`、`R-ADMIN DELETE /archives/*` 跨租户软删更严重，若本期不上 archive 收口，至少要有「只允许超管在受控运维通道执行」的补偿控制并书面确认。修完 C-1/C-2 后，可判「可上生产但带 archive 已知 backlog（有补偿控制）」。

---

## 十、末段：verdict 与最关键三条

**VERDICT：REQUEST_CHANGES。** `1b1b55f..d98b305` 不能推 `develop`，也不能上生产；C-1/C-2 修完（预计 10 行内改动 + 2 条用例）即可转 APPROVED。

最关键三条：

1. **C-5 是假闭环**：`apps/staff/api.py:624` 的 `approve_visitor` 仍裸 id，实测 tenant-1 可把他租户访客审批为 `APPROVED` 并写入 `role_codes:["R-ADMIN"]`（200）；同文件 `:60` 的 `_get_visitor_or_404` 零调用，提交标题却声称修了「访客」。
2. **F 段扫出一条跨租户写链**：`POST /reviews` 的 `target_id` 不校验归属，`conclude` 经 `conclude_output_eval` 直写他租户成果，实测 `200 / ASSIGNED_TO_PROJECT / is_claimed=True`；同构可达 `MID_CHECK.expert_ids`，根因是单一写者只靠 docstring 约束。
3. **修复质量本身是好的**：其余 6 类（修正案、纪检、人遗备案、项目分类、成果族、人员/团队、资产）15 个跨租户探针全部 404 且库不变，反向 14 条全 200，608 绿、契约零 diff、7 条新用例在 `57ac05f` 上 7 红——问题只在「漏接一处 + 漏了一个入口」，不是方向性错误。
