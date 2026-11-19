# E-7 跨域 id 收口 · 第四轮（终局）终审 r4

- 审查对象：`develop` @ `57ac05f`，BASE `1b1b55f`，共 8 个 commit（e2d297a / 91830e1 / d317245 / a17db11 / bd55718 / 9fe262b / 2a9248b / 57ac05f）
- 上轮结论：`docs/superpowers/reports/final-review-e7-r3.md` — APPROVED_WITH_MINOR，可推 develop、不可上生产；同时点出 3 处存量 Critical（D-1 ethics 案卷 / D-2 project 任务 / D-3 output 认领）与 I-1/I-2/I-3
- 本轮声明（`57ac05f` commit message）：「补扫 ethics/project/output 跨租户裸查 + 引用校验含软删 + 公示自由文本脱敏 + 迁移只清已知下线授权（E-7 复审 r3）」→ 闭环 D-1/D-2/D-3 + I-1/I-2/I-3
- 评审方式：只读。全部测试/探针在 `git archive 57ac05f` 的干净导出树 `/tmp/e7r4-clean` 执行；真实仓库本次评审**唯一写入是本报告**，探针全部在 `/tmp`。

## 0. 审查口径

r3 报告第 37 行已经把口径写死：

> 「若把『E-7 跨域裸查收口』的验收标准定义为**全仓清零**，则本报告应读作 **REQUEST_CHANGES**——D-1/D-2/D-3 正是本计划要消灭的漏洞类别。」

本期名称是「E-7 跨域 id 收口」，`57ac05f` 的 message 又明确声称闭环 D-1/D-2/D-3，因此本轮按**资源类清零**口径验收：不仅看 r3 点名的那 3 个 handler，还要看同一资源下同形态的写接口是否一并收口。这也是本轮必查 F 段（漏网再扫）存在的原因。

---

## 1. VERDICT

**REQUEST_CHANGES**

> 不能上生产；也不建议以「D-1/D-2/D-3 已闭环」的口径推 develop——r3 为 D-1、D-2 各自点名的修法项（`decide_amendment`、`attach_project_category`）**原样未改**，且同资源的 output 关联/专利、staff 人员/团队、asset 资产仍存在可实测的跨租户写，output 详情还可跨租户读。回归本身干净（601 passed、契约零 diff、5 条新用例在 `2a9248b` 全红），问题是「收口范围」而不是「代码质量」。

---

## 2. 实测数字表

| # | 指标 | 期望 | 实测 |
|---|---|---|---|
| 1 | 提交数 / 变更量 | 8 commits | 8；19 文件 `+1158/−126` |
| 2 | 全量回归（干净树，恢复后） | 601 passed | **601 passed, 19 warnings in 46.34s** |
| 3 | 全量回归（首次，探针加入前） | 601 passed | **601 passed in 45.89s** |
| 4 | `makemigrations --check --dry-run` | No changes | **No changes detected** |
| 5 | 契约 diff `design/ frontend/src/api/schema/` | 0 行 | **0 行**（`git diff --stat` 空） |
| 6 | README 第 5/29/99 行 | 601 | **601 / 601 / 601** |
| 7 | 5 条新用例 @ `2a9248b` 实现 | 全红 | **5 failed, 17 deselected in 2.76s** |
| 8 | A-1 ethics 跨租户 GET / submit / formal-check | 404 + 状态不变 | **404 / 404 / 404**，DRAFT、FORMAL_CHECK 均不变 |
| 9 | A-1 反向：本租户 GET / submit | 200 | **200 / 200** |
| 10 | A-2 project 跨租户 PUT task / 反向 | 404 / 200 | **404（TODO 不变）/ 200（DONE）** |
| 11 | A-2 helper 定义与调用点 | 2 定义 + 全调用带 request | **2 处定义（:94、:1465）均带 tenant；7 个调用点全传 request** |
| 12 | A-3 output claim 跨租户 / 反向 | success=false / true | **success=false（UNCLAIMED 不变）/ success=true** |
| 13 | B 软删项目 create_expense / 软删成果 create_disclosure | 404 | **404 40401 / 404 40401**，未建单 |
| 14 | C 公开 GET 的 PII 子串 / handle_result | 不含 / None | **不含「张三丰」「13800000000」 / None** |
| 15 | C 内部 handle 响应含 handle_result | 有 | **有**（"已处理 张三丰"） |
| 16 | D 迁移：stale 指派 / 自定义授权 / 同 obj 其它 act | 1→0 / 1→1 / 1→1 | **1→0 / 1→1 / 1→1** |
| 17 | D `purge_stale_policy_rows` 残留引用 | 0 | **0**（全仓 grep 仅 pycache 无源码命中） |
| 18 | F 实测跨租户写 / 读（probe 200；写操作落库） | 0 | **12 次写探针（11 个写端点）+ 2 个读端点**，见 §8 |
| 19 | 探针总数（A/B/C/D/F） | — | **22 条断言全过**（A/B/C 断言「应拒绝」，F 断言「确实越权」） |

> 第 18 行的口径：probe 用 tenant-1 令牌打 tenant-2 资源，写操作要求 HTTP 200 且 DB 落库才算一条；`decide_amendment` 用 R-ADMIN 与 R-ETHICS 各打一次，故写探针 12 次对应 11 个写端点。

---

## 3. A. D-1 / D-2 / D-3 是否真闭环

### A-1 ethics 案卷（D-1）——**请求侧已闭环，同资源仍有漏口**

`apps/ethics/api.py:81-88` 已改为：

```python
def _get_case_or_404(request: HttpRequest, cid: int) -> CEthicsCase:
    tenant_id = domain_from(request).tenant_id
    c = CEthicsCase.objects.filter(id=cid, tenant_id=tenant_id, deleted=0).first()
    if c is None:
        raise ApiError(404, CODE_NOT_FOUND, "伦理案卷不存在")
    return c
```

12 个调用点全部传 `request`：`:160` get、`:179` submit、`:196` ai-prescreen、`:217` formal_check、`:239` assign_reviewers、`:271` submit_opinion、`:300` meeting_check_in、`:321` meeting_vote、`:363` issue_decision_letter、`:412` submit_amendment、`:451` report_adverse_event、`:472` submit_annual_review（grep 计数 1 定义 + 12 调用，与声明一致）。

实测（tenant-2 案卷 `ETH-P-A1`，tenant-1 `bearer(1,["R-STAFF"])`）：

```
A.get           404 {"code": 40401, "message": "伦理案卷不存在"}
A.submit        404 {"code": 40401, "message": "伦理案卷不存在"}
A.case_after    DRAFT
A2.formal_check 404 {"code": 40401, "message": "伦理案卷不存在"}
A2.case_after   FORMAL_CHECK
A4.own_get      200
A4.own_submit   200
```

**但**：r3 在 D-1 的「修法」里点名了 `decide_amendment`（`CAmendment.objects.filter(id=id, case__tenant_id=dom.tenant_id, deleted=0)`），`57ac05f` 未改，见 §9 C-1。

### A-2 project 任务（D-2）——**任务已闭环，helper 重复定义，分类写仍越权**

`apps/project/api.py:94-100` 与 `:1465-1471` 是**两份逐字相同**的定义，均已带租户：

```python
def _get_project_or_404(request: HttpRequest, project_id: int) -> EProject:
    """按租户取项目（E-7 补扫）：跨租户 id 与不存在同口径 404。"""
    tenant_id = domain_from(request).tenant_id
    p = EProject.objects.filter(id=project_id, tenant_id=tenant_id, deleted=0).first()
    if p is None:
        raise ApiError(404, CODE_NOT_FOUND, "项目不存在")
    return p
```

调用点 `:133` get_project、`:137` list_tasks、`:145` list_milestones、`:246` update_task、`:1480` list_risk_warnings、`:1555` get_archive_checklist、`:1567` update_checklist_item 全部传 `request`。另有既存 `_get_project_or_404_tenant(project_id, tenant_id)`（`:103`），8 个调用点带 tenant。**无漏改调用点**（全仓 grep 已核）。

实测：

```
A2.update_task 404 {"code": 40401, "message": "项目不存在"}
A2.task_after  TODO
A4.own_task    200  status=DONE
```

**但**：r3 在 D-2 的「修法」里点名了 `attach_project_category`（`EProject.objects.filter(id=id, deleted=0).update(...)` 加 `tenant_id`），`57ac05f` 未改，见 §9 C-2。重复定义本身是维护隐患（§9 M-1）。

### A-3 output 认领（D-3）——**认领已闭环**

`apps/output/api.py:236-238`：

```python
o = (ROutput.objects.filter(id=oid, tenant_id=d.tenant_id, deleted=0).first()
     if oid else None)
if o is None:
    results.append({"output_id": oid, "success": False, "message": "成果不存在或状态冲突"})
    continue
```

实测：

```
A3.claim  200 {"data": {"batch_id": "Bdmz28kxxxwf4", "results": [{"output_id": 1,
              "success": false, "message": "\u6210\u679c\u4e0d\u5b58\u5728\u6216\u72b6\u6001\u51b2\u7a81"}]}}
A3.after  claim_status=UNCLAIMED status=PENDING_CLAIM
A4.own_claim  200 {"success": true}
```

`_process_claim` 是 CLAIM / REJECT / MARK_NOT_MINE 三个入口的公共实现（`:254/:258/:262`），三入口一并收口。

**但**：同文件的 `_get_output_or_404`（`:92-96`）仍是 `filter(id=..., deleted=0)`，支撑 `link_projects` / `create_reprint` / `set_patent_stage` / `create_patent_fee` / `get_output` 五个入口，见 §9 C-3。

### A-4 反向验证（不得过度收紧）

| 场景 | 结果 |
|---|---|
| tenant-1 自己的伦理案卷 GET / submit | 200 / 200 |
| tenant-1 自己的项目任务 PUT | 200，status=DONE |
| tenant-1 自己的成果 claim | 200，success=true |
| tenant-1 自己的软删引用（B 之外未测） | 见 §9 I-4（仍放行，属既有取舍） |

结论：**A 段「指定的 3 个 handler」全部真闭环，且没有过度收紧；但 D-1、D-2 各自点名的另一条修法项未执行，D-3 的 helper 家族未收口**。「D-1/D-2/D-3 闭环」作为资源级结论不成立。

---

## 4. B. I-1 软删绕过

`apps/funding/api.py:241-254` 已去掉 `deleted=0`：

```python
def _reject_foreign_ref(model, obj_id, tenant_id: int, label: str) -> None:
    """E-7：body 引用不得指向他租户对象（存在性不强制——历史数据无 FK 约束）。"""
    if obj_id is None:
        return
    oid = int(obj_id)
    if model.objects.filter(id=oid).exclude(tenant_id=tenant_id).exists():
        raise ApiError(404, CODE_NOT_FOUND, f"{label}不存在")
```

应用点：`create_expense`（`:817-818` EProject + SysLegalEntity，另 `:821-825` 预算行带 `tenant_id+deleted=0`）、`create_outward`（`:1040-1044`）、`create_loan`（`:2235`）。`apps/transform/api.py:153-167` 的 `create_disclosure` 用同口径 `.exclude(tenant_id=dom.tenant_id)`（output 与 project 两处）。

实测（tenant-2 对象 `deleted=1`，tenant-1 令牌）：

```
B.expense    404 {"code": 40401, "message": "项目不存在"}
B.expense_db FExpense count 0
B.disclosure 404 {"code": 40401, "message": "成果不存在"}
B.discl_db   TDisclosure count 0
```

通过。**取舍说明**：`filter(id=oid)` 不带 `deleted` 意味着「不存在」与「他租户已删」都走 `.exclude(tenant_id=...)`→ 前者放行（保留历史脏数据兼容），后者 404；本租户软删对象仍放行（§9 I-4，Minor）。这一取舍与 r3 建议一致，可以在注释里再写清「own deleted 允许」以免下一轮被当成漏洞。

---

## 5. C. I-2 公示 handle_result 脱敏

`apps/transform/mappings.py:243-278`：

```python
def _mask_name(v): ...            # 首字 + *，空值 → None
def _mask_contact(v): ...         # len>=7: 前3+****+后4；>4: 前2+****+后2；否则全 *
def to_api_publicity_public(r):
    data = to_api_publicity(r)
    data["objections"] = [
        {**o, "submitter": _mask_name(o.get("submitter")),
         "contact": _mask_contact(o.get("contact")), "handle_result": None}
        for o in (r.objections or [])
    ]
    return data
```

接线：`apps/transform/api.py:591-598` 的公开 `get_publicity` 改调 `to_api_publicity_public(p)`；`config/api.py:671` 该路由无 auth。内部 `handle_objection`（`apps/transform/api.py:660-666`）响应仍用 `to_api_publicity`，返回全量 `handle_result`。

实测（公示 objections：submitter=`张三丰`、contact=`13800000000`、handle_result=`已联系张三丰 13800000000 补交权属材料`）：

```
C.public_get  200  含"张三丰"=False 含"13800000000"=False
C.public_obj  [{"objection_id": "OBJ1", "submitter": "张**", "contact": "138****0000",
               "content": "权属存在争议", "handle_status": "PROCESSING",
               "handled_at": null, "handle_result": null}]
C.internal    200  handle_result="已处理 张三丰"
```

通过。附带核实：匿名 `POST /publicity/{dealId}/objection` 的成功响应是 `return ok(request, {"objection_id": oid})`（`apps/transform/api.py:628-655`），**不**复用未脱敏序列化器——r3 阶段对 `:624` 的怀疑不成立（`:624` 的 `to_api_publicity` 属于需 auth 的 `publish_publicity`）。

残留：`to_api_publicity` 还原样返回 `summary_json`（`mappings.py:284`），若发布方把联系人写进摘要仍会公开；不在本期 PII 字段清单内，记 Minor（§9 M-4）。

---

## 6. D. I-3 迁移 0019

`apps/sysadmin/migrations/0019_purge_stale_policy_e7.py`（全文 33 行）：`STALE_POLICY = [("/api/v1/disclosure/*", "GET")]`（`:12-15`），循环按 `(obj, act)` 精确删 `SysPermission` 与其 `SysRolePermission`（`:24-27`），再 `sync_permissions_from_csv`（`:28`）。广谱函数 `purge_stale_policy_rows` 已从 `apps/sysadmin/permissions.py` 删除，全仓 grep 无源码残留（`9fe262b` 的旧版本曾调用它）。

迁移探针（`transaction=True`，先 `migrate sysadmin 0018` 再 `0019`，库里预置三条：CSV 内 stale 指派、CSV 没有的自定义 `("/api/v1/local/report","POST")`、同 obj 其它 act `("/api/v1/disclosure/*","POST")`）：

```
BEFORE custom=1 same_obj_other_act=1 stale=1
AFTER  custom=1 same_obj_other_act=1 stale=0
1 passed
```

通过：只删 disclosure GET，自定义运行期授权与同 obj 其它 act 均保留。

两处需注意（不阻塞本期判定，见 §9 I-2 / M-2）：

1. **原地改写已发布的迁移**。`0019` 在 `9fe262b` 就已存在且内容不同（全表清理）。任何已经跑过旧 `0019` 的库，`migrate` 不会重跑新逻辑——被误删的自定义授权不会自动恢复。若共享 staging 已执行过旧版，需要单独的修复迁移/脚本，而不是改 `0019`。
2. **docstring 与实现不一致**：`:7` 写「只删这两条已知下线的规则」，`STALE_POLICY` 只有 1 条。要么是漏了一条（需要补），要么是文案没跟着改（需要改）。当前 CSV 中确实只剩 `disclosure/* GET` 一条悬空，倾向于文案问题。

---

## 7. E. 回归与卫生

全部在 `/tmp/e7r4-clean/backend-django`（`git archive 57ac05f` 导出，113MB）执行：

```bash
$ .venv/bin/python -m pytest -q
601 passed, 19 warnings in 46.34s          # 恢复探针改动后复跑；首次（未加探针）45.89s 同为 601

$ .venv/bin/python manage.py makemigrations --check --dry-run
No changes detected

$ git -C /Users/jacky/works/science-research-project diff --stat 1b1b55f..57ac05f -- design/ frontend/src/api/schema/
（空）

$ sed -n '5p;29p;99p' README.md
…全量 601 pytest 通过…
│   └── tests/               # pytest 套件（601 个）
…当前 601 passed…
```

逐 commit `--stat`（`git log --reverse --format='%h %s' --shortstat 1b1b55f..57ac05f`）：

| commit | 主题 | 文件 | 行数 |
|---|---|---|---|
| e2d297a | activity 域收口 | 3 | +104/−14 |
| 91830e1 | confsec 域收口 | 3 | +97/−8 |
| d317245 | funding 域收口 | 4 | +202/−29 |
| a17db11 | transform 域收口 | 3 | +104/−28 |
| bd55718 | 预算行/公示异议/企业档案 + confsec 审计 | 10 | +243/−31 |
| 9fe262b | 零行命中阻断 + PII 脱敏 + 悬空策略清理 | 8 | +252/−9 |
| 2a9248b | 创建类接口拒他租户引用 | 4 | +90/−7 |
| 57ac05f | 补扫 ethics/project/output + 软删 + 脱敏 + 迁移 | 10 | +139/−73 |

- 8 个 commit 均为「README 测试数 + 本域实现 + 本域测试」，无脚本、无生成物、无格式化夹带；`bd55718` 跨 3 域但主题一致（终审补扫）。
- 逐 commit 合计 `+1231/−199` 大于合并 diff `+1158/−126`，差额来自 README 在 8 个 commit 中反复改写同一批行，属正常。
- 5 条新用例在 `2a9248b` 实现上应红——实测（把导出树的 6 个实现文件换成 `2a9248b` 版本，跑完后按 `git show 57ac05f:` 逐字节恢复并 diff 校验）：

```
FAILED tests/test_e7_review_fixes.py::test_ethics_case_is_tenant_scoped
FAILED tests/test_e7_review_fixes.py::test_project_task_update_is_tenant_scoped
FAILED tests/test_e7_review_fixes.py::test_output_claim_rejects_foreign_output
FAILED tests/test_e7_review_fixes.py::test_create_expense_rejects_soft_deleted_foreign_project
FAILED tests/test_e7_review_fixes.py::test_public_publicity_hides_handle_result
5 failed, 17 deselected in 2.76s
```

其中最后一条的失败证据正是修复前公开响应带 PII：

```
>       assert "张三丰" not in body and "13800000000" not in body
E       assert ('张三丰' not in '{"code": 0,...95078311406}'
E         '张三丰' is contained here: ... 张 13800000000 补交权属材料"}]}
```

- 卫生：探针只写 `/tmp`；导出树里的探针文件已删除；真实仓库 `git status --porcelain backend-django/apps backend-django/tests backend-django/config README.md` 为空。

**E 段结论：通过。**

---

## 8. F. 漏网再扫（决定能否上生产）

扫描口径：`apps/*/api.py` 中 `objects.filter(id=` / `objects.get(id=` / `select_for_update()` 后紧跟写、且行内无 `tenant_id` 的路径；再按「id 是否可由 HTTP path/body 控制」逐个判定。

### 8.1 逐模块结论

| 模块 | 结论 | 依据 |
|---|---|---|
| `apps/expertreview` | **未发现问题** | `_get_expert_or_404`/`_get_task_or_404` 均带 tenant（`:60`、`:68`）；`NExpert.objects.filter(id=iv.expert_id)`（`:305/:321/:526`）的 id 来自本租户 invitation，不可由请求指定；score/invitation 均按 `task_id` 派生 |
| `apps/procure` | **未发现问题** | `GRequisition/GContract/GBid/GSupplier` 均带 tenant（`:83/:90/:359/:821`）；`:392` 预算行 id 从本租户单据 `remark` 解析，非直接入参；`:702-710` 以 tenant 过滤后再派生 |
| `apps/asset` | **仍可跨租户写** | `_get_asset_or_404`（`:77-83`）无 tenant，支撑 7 个 handler；`:637-658` 凭证回调按 body `depreciationId` 改他租户折旧单 |
| `apps/staff` | **仍可跨租户写/读** | `_get_staff_or_404`（`:51-56`）无 tenant，11 个调用点；团队 4 个 handler（`:463/:500/:523`、list members）；访客审批 `:610` |
| `apps/ethics` | **仍可跨租户写** | `decide_amendment`（`:429`）、`update_integrity_record`（`:599`）、`delete_integrity_record`（`:698`）、`sync_hgr_filing`（`:753`）；案卷 12 接口已收口 |
| `apps/project` | **仍可跨租户写** | `attach_project_category`（`:1010`）；`:1578` 清单项可挂他租户文档 id；mid/final-check 的 `select_for_update` 由 N 域内部单一写者调用且 `mc/fa` 自带 tenant，判可接受 |
| `apps/output` | **仍可跨租户写/读** | `_get_output_or_404`（`:92`）无 tenant；`:295` 内部回写；`:482` `ROutput.objects.get(id=id)` |
| `apps/archive`（附，r3 D-4 遗留） | **仍可跨租户写** | `_get_doc_or_404`（`:53`）/`_get_archive_or_404`（`:60`）无 tenant，R-MANAGER 有 `PUT /archives/*`（policy.csv:248）；本轮未探针，仅静态确认与 r3 一致 |

### 8.2 「仍可跨租户写」实测清单（tenant-1 令牌 → tenant-2 资源，全部 200 且落库）

| # | 端点 | 角色 | 落库效果 | 源码 |
|---|---|---|---|---|
| 1 | `POST /api/v1/ethics/amendment/{id}/decision` | R-ADMIN | amendment.status `SUBMITTED→APPROVED` | `apps/ethics/api.py:427-443` |
| 2 | 同上 | **R-ETHICS** | 同上（`/api/v1/ethics/*` 实测匹配 5 段路径） | policy.csv:660 |
| 3 | `POST /api/v1/projects/{id}/category` | R-STAFF | `EProject.category_id := 1`（tenant-1 分类） | `apps/project/api.py:1004-1011` |
| 4 | `PUT /api/v1/output/{id}/projects` | R-MANAGER | output.status `→ASSIGNED_TO_PROJECT`；非空 pids 时还写 tenant-1 的 ROutputProject 行指向他租户成果 | `apps/output/api.py:268-285` |
| 5 | `POST /api/v1/patents/{id}/stage` | R-MANAGER | `stage PRE_APPLY→APPLIED` | `apps/output/api.py:475-489` |
| 6 | `POST /api/v1/patents/{id}/fees` | R-MANAGER | 为他租户专利建费用行（tenant_id=1） | `apps/output/api.py:491-506` |
| 7 | `POST /api/v1/papers/{id}/reprints` | R-MANAGER | 为他租户论文建 RPaperReprint（tenant_id=1） | `apps/output/api.py:391-403` |
| 8 | `POST /api/v1/teams/{id}/members` | R-MANAGER | 建 SMembership（tenant_id=1，team=他租户），并改 team.member_ids 快照 | `apps/staff/api.py:500-521` |
| 9 | `PUT /api/v1/integrity/records/{id}` | R-AUDITOR | decision `→"跨租户改写"` | `apps/ethics/api.py:596-627` |
| 10 | `POST /api/v1/hgr/filing/{id}/sync` | R-MANAGER | status `DRAFT→NATIONAL_RECEIVED` | `apps/ethics/api.py:750-770` |
| 11 | `POST /api/v1/asset/{id}/issue` | R-STAFF | 他租户资产 `IDLE→IN_USE`、project_id 被改、建 AStockTxn | `apps/asset/api.py:77-83, 346-367` |
| 12 | `POST /api/v1/staff/{id}/transfer` | R-MANAGER | 他租户员工 `RESIGNED`、status `INACTIVE` | `apps/staff/api.py:51-56, 195-216` |

跨租户**读**（同源，未单列）：

| # | 端点 | 角色 | 效果 |
|---|---|---|---|
| 13 | `GET /api/v1/output/{id}` | R-STAFF | 200，`data.tenant_id=2`，含 title「他租户机密成果」 |
| 14 | `GET /api/v1/staff/{id}` | R-STAFF | 200，他租户员工全量档案（含 `tenant_id: 2`） |

静态确认但未单独探针的同类写：`staff` 的 remove_team_member（`:523`）、approve_visitor（`:610`）、get_team/list_team_members（`:463/:482` 读）；`ethics` 的 delete_integrity_record（`:695`）；`asset` 的 return/transfer/disposal/lifecycle/trace/ai-fill（`:277/:299/:346/:371/:391/:678/:774`）与凭证回调（`:637-658`）；`archive` 的 doc/archive 更新（`:53/:60`）；`project` 清单项文档引用（`:1578`）。

**F 段结论：不通过。** 12 个写端点、2 个读端点可实测跨租户，覆盖 asset / staff / ethics / project / output 五域，其中 ethics / project / output 正是 `57ac05f` 声称收口的三个域。

---

## 9. 问题清单

### Critical（A 组：本期声称闭环的 D-1/D-2/D-3 残留）

#### C-1 `decide_amendment` 仍可跨租户改修正案状态（D-1 修法项未执行）

- 位置：`apps/ethics/api.py:427-443`，路由 `config/api.py:704`，策略 `policy.csv:660`（R-ETHICS `/api/v1/ethics/*`，实测可匹配 `/ethics/amendment/{id}/decision`）与 `:7`（R-ADMIN `/api/v1/*`）
- 代码：`a = CAmendment.objects.filter(id=id, deleted=0).first()`，随后写 `status / decided_at / decision_note / modifier_id`
- 复现：

```python
# tenant-2 的 CAmendment(status=SUBMITTED)，tenant-1 令牌
POST /api/v1/ethics/amendment/{id}/decision  {"decision": "APPROVE"}
# → 200 {"code":0,...}, 刷新后 status=APPROVED, modifier_id=1
```

- 原始输出：`decide_amendment R-ADMIN 200 ... "status": "APPROVED"`；`decide_amendment R-ETHICS 200 status= APPROVED`
- 影响：租户 1 的伦理委员会/管理员可批准或驳回租户 2 的修正案，并留下本租户操作痕迹。r3 已给出精确修法（`case__tenant_id=dom.tenant_id`），一行未改。
- 修法：`CAAmendment.objects.filter(id=id, case__tenant_id=dom.tenant_id, deleted=0).first()`；补一条 R-ETHICS 跨租户 404 用例。

#### C-2 `attach_project_category` 仍可跨租户改项目分类（D-2 修法项未执行）

- 位置：`apps/project/api.py:1004-1011`，路由 `config/api.py:216`，策略 `policy.csv:326-327`（R-MANAGER / R-STAFF）
- 代码：`n = EProject.objects.filter(id=id, deleted=0).update(category_id=category_id, ...)`；`n==0` 才 404，跨租户命中 `n==1` 直接 200
- 复现：

```python
POST /api/v1/projects/{tenant2_pid}/category  {"category_id": 1}   # tenant-1 R-STAFF
# → 200 {"id": pid, "category_id": 1}，库内项目 category_id 被改为 tenant-1 的分类
```

- 原始输出：`F attach_category 200 {"data": {"id": 1, "category_id": 1}}`
- 影响：项目分类是经费/统计口径的输入，跨租户改写会污染他租户报表；且这是 r3 D-2 明确写进修法的一项。
- 修法：`filter(id=id, tenant_id=d.tenant_id, deleted=0)`，或先 `_get_project_or_404(request, id)` 再 update。

#### C-3 output `_get_output_or_404` 家族仍可跨租户写/读（D-3 残留）

- 位置：`apps/output/api.py:92-96`（无 tenant）；调用 `:179` get_output、`:269` link_projects、`:396` create_reprint、`:477` set_patent_stage、`:493` create_patent_fee；另 `:482` `ROutput.objects.get(id=id)`、`:295` `conclude_output_eval`
- 路由/策略：`config/api.py:437-438`（`PUT /output/{id}/projects`，policy.csv:161 R-MANAGER）、`:452`（`POST /papers/{id}/reprints`，:182）、`:461-463`（`POST /patents/{id}/stage|fees`，:186/:188）
- 复现（tenant-2 output）：

```python
PUT  /api/v1/output/{oid}/projects   {"project_ids": []}            # → 200, status=ASSIGNED_TO_PROJECT
POST /api/v1/patents/{oid}/stage     {"stage": "APPLIED"}           # → 200
POST /api/v1/patents/{oid}/fees      {"year": 2026, "amount": 1200} # → 200，费用行 tenant_id=1
POST /api/v1/papers/{oid}/reprints   {"name": "转载-1"}             # → 200，reprint tenant_id=1
GET  /api/v1/output/{oid}                                           # → 200，tenant_id=2
```

- 原始输出：`F link_projects 200 {"linked": 0} status= ASSIGNED_TO_PROJECT`；`F patent stage 200 stage= APPLIED`；`F patent fee 200 "amount": "1200.00"`；`create_reprint 200 ...`；`F output GET 200 {"tenant_id": 2, ... "title": "他租户机密成果"}`
- 影响：专利阶段是法律状态，费用/转载是财务与署名数据；跨租户写比读更严重。`create_reprint` 还会长时间「占用」他租户成果的转载记录。
- 修法：`_get_output_or_404(output_id, tenant_id=None)`，五处调用传 `domain_from(request).tenant_id`；`:482` 改用命中对象；`conclude_output_eval` 保留内部入口但显式注释「跨域回写，tenant 由调用方保证」。

### Critical（B 组：本轮 F 段新扫出，阻塞上生产）

#### C-4 staff `_get_staff_or_404` 无租户，人员档案跨租户读写

- 位置：`apps/staff/api.py:51-56`；调用 `:188` get_staff、`:200` transfer_staff、`:226` get_portrait、`:257` refresh_portrait、`:299` get_collab_graph、`:337` ai_expertise、`:365` ai_resume、`:439`（team 创建时 `pi_staff_id`）、`:508`（团队成员 `staff_id`）、`:648`（`register_student` 的 `supervisor_staff_id`）、`:669`（`list_talent_plans`）
- 策略：`policy.csv:715-723`（R-STAFF `/staff/*` GET、R-MANAGER `/staff/*/transfer` POST）
- 复现：

```python
POST /api/v1/staff/{tenant2_sid}/transfer  {"action": "RESIGN", "reason": "跨租户"}   # tenant-1 R-MANAGER
# → 200；员工 employment_status=RESIGNED、status=INACTIVE、remark 追加本租户文字
GET  /api/v1/staff/{tenant2_sid}                                                    # → 200，全量档案
```

- 原始输出：`staff transfer 200 employment= RESIGNED status= INACTIVE remark= 跨租户; 交接 PI: None`；`staff get 200 {"tenant_id": 2, "status": "INACTIVE", ...}`
- 影响：人员异动/离职是 HR 主数据，跨租户改状态会直接破坏他租户的在编统计与权限派生；`refresh_portrait`（`:254-290`）还会以 tenant-1 身份为他租户员工建 `SPortrait`（`update_or_create` 的 `tenant_id=1, staff=tenant-2`），造成租户错配数据。
- 修法：helper 增 `tenant_id` 参数并用 `domain_from(request)`；所有 11 个调用点传参；`refresh_portrait` 的 `update_or_create` 加 tenant 过滤。

#### C-5 staff 团队/成员/访客跨租户写

- 位置：`apps/staff/api.py:463` get_team、`:478` list_team_members、`:500` add_team_member、`:523` remove_team_member、`:610` approve_visitor；均 `filter(id=id, deleted=0)` 无 tenant
- 策略：`policy.csv:732-735`（R-MANAGER `GET/POST /teams/*`、`/teams/*/members`、`/members/remove`）、`:739`（`/visitors/*/approve`）
- 复现：

```python
POST /api/v1/teams/{tenant2_tid}/members  {"staff_id": 1, "role": "MEMBER"}   # tenant-1 R-MANAGER
# → 200 {"team_member_count": 1}；SMembership.tenant_id=1 指向 tenant-2 团队，team.member_ids 被改
```

- 原始输出：`F team add member 200 ... "team_member_count": 1` + `F membership tenant: 1`
- 影响：`_sync_team_snapshot(t)` 按 `SMembership.objects.filter(team=t)` 重算，会把本租户成员计入他租户团队快照，形成双向污染；`remove_team_member` 可把他租户成员置 `LEFT`。
- 修法：四个 handler 的 `STeam` 查询统一改 `_get_team_or_404(request, id)`（新建），成员写操作的 `SMembership.tenant_id` 取 team.tenant_id 并断言等于当前租户；`approve_visitor` 同理。

#### C-6 asset `_get_asset_or_404` 无租户，7 个资产 handler 跨租户写

- 位置：`apps/asset/api.py:77-83`；handler `:277-278` lifecycle、`:299-301` trace、`:346-348` issue、`:371-373` return、`:391-394` transfer、`:678-681` disposal、`:774-776` ai-fill；另 `:637-658` 凭证回调按 body `depreciationId` 写 `ADepreciation.voucher_id/status`（同样 `filter(id=..., deleted=0)` 无 tenant）
- 策略：`policy.csv:790-808`（R-STAFF issue/return/ai-fill；R-MANAGER transfer/disposal）
- 复现：

```python
POST /api/v1/asset/{tenant2_aid}/issue  {"projectId": 1, "custodianId": 1}   # tenant-1 R-STAFF
# → 200；资产 IDLE→IN_USE，project_id 改为 tenant-1 项目，并建 AStockTxn(tenant_id=1)
```

- 原始输出：`asset issue cross-tenant 200 status= IN_USE project= 1`
- 影响：资产领用/调拨/处置是国有资产台账动作，跨租户写会同时污染两台台账；凭证回调可把他租户折旧单标记为已入账。
- 修法：helper 加 tenant；`voucher_callback` 的 `ADepreciation` 查询加 `tenant_id=dom.tenant_id` 或校验所属资产租户。

#### C-7 ethics 纪检档案与人遗备案跨租户写

- 位置：`apps/ethics/api.py:596-627` update_integrity_record、`:695-707` delete_integrity_record（软删）、`:750-770` sync_hgr_filing；均 `filter(id=id, deleted=0)`
- 策略：`policy.csv:683/:688`（R-AUDITOR / R-ADMIN `PUT /integrity/records/*`）、`:704/:705`（DELETE）、`:699`（R-MANAGER `/hgr/filing/*/sync`）
- 复现：

```python
PUT  /api/v1/integrity/records/{tenant2_rid}  {"decision": "跨租户改写"}   # tenant-1 R-AUDITOR
POST /api/v1/hgr/filing/{tenant2_fid}/sync                                # tenant-1 R-MANAGER
# → 200；decision 被改写；filing DRAFT→NATIONAL_RECEIVED 并生成 national_approval_no
```

- 原始输出：`F integrity update 200 ... decision= 跨租户改写`；`F hgr sync 200 ... status= NATIONAL_RECEIVED`
- 影响：纪检结论与人类遗传资源备案号都是强合规数据，跨租户改写属审计事故级别。
- 修法：三处查询加 `tenant_id=domain_from(request).tenant_id`；`delete_integrity_record` 同样处理。

### Important

#### I-1 5 条新用例只覆盖「被点名的 handler」，未覆盖同资源兄弟端点

- 证据：`grep -rn "decide_amendment|attach_project_category|_get_output_or_404|add_team_member|approve_visitor|_get_asset_or_404" tests/` → 仅命中 pycache，无源码用例。
- 影响：601 全绿不能证明「资源类收口」，本轮 7 条 Critical 全部在绿灯下存在。
- 建议：每条 Critical 配一条「跨租户 404 + 库内不变」用例；至少覆盖 C-1/C-2/C-3/C-4。

#### I-2 迁移 0019 原地改写：已执行旧版的环境不会重跑

- 位置：`apps/sysadmin/migrations/0019_purge_stale_policy_e7.py`（`9fe262b` 版本内容不同）
- 影响：旧 `0019` 会按 CSV 全表清理，已跑过的 staging/生产库中运行期自定义授权已被删除；改文件不会恢复，也不会再执行新逻辑。
- 建议：不要改已发布迁移；新增 `0020` 做精确清理，另附一份「被误删授权」的排查/恢复脚本（按审计日志或 CSV 重建）。

#### I-3 `project` 归档清单可引用他租户文档 id

- 位置：`apps/project/api.py:1578` `if not ODocument.objects.filter(id=int(doc_id), deleted=0).exists():`
- 影响：清单项（本租户项目）可挂一个他租户 `ODocument`，形成跨租户引用；当前只校验存在性，未校验 `tenant_id`。
- 建议：与 `_reject_foreign_ref` 同口径，或直接 `filter(id=doc_id, tenant_id=d.tenant_id, deleted=0)`。

#### I-4 `_reject_foreign_ref` 对本租户软删对象仍放行

- 位置：`apps/funding/api.py:241-254`、`apps/transform/api.py:153-167`
- 影响：`create_expense` 可指向本租户已软删项目、`create_disclosure` 可指向本租户已软删成果，形成悬挂引用（不跨租户，但与 B 段「软删不得用于新建」的意图不一致）。
- 建议：明确产品口径。若「own deleted 也拒绝」，改成 `filter(id=oid, deleted=0).exclude(tenant_id=...).exists() or (exists and deleted=1 and own)`；若保留，注释写清并补一条用例锁定行为。

#### I-5 公开异议通道可改任意租户公示状态（设计取舍，需登记）

- 位置：`apps/transform/api.py:628-655`（`submit_objection` 仅按 deal_id 查 `TPublicity`，成功后置 `OBJECTION_PENDING`）
- 判定：这是产品要求的匿名通道（`config/api.py:673` 无 auth），不应加租户校验；但它意味着任何人可让任意公示进入异议状态。建议在安全基线/运维手册中登记为已知风险，并确认状态变更留痕 + 限流。

### Minor

- **M-1 `_get_project_or_404` 重复定义两次**（`apps/project/api.py:94` 与 `:1465`，逐字相同）。Python 调用时解析后者，当前行为一致，但两份定义会漂移；建议删一份。
- **M-2 迁移 docstring 与实现不一致**：`0019` 第 7 行「只删这两条」，`STALE_POLICY` 仅 1 条；改文案或补齐规则。
- **M-3 `_mask_contact` 边界偏弱**：`len == 7` 时「前 3 + **** + 后 4」= 原 7 位全部可见；`len >= 7` 统一策略对 7 位座机等于没脱敏。建议 `len >= 11` 才用 3+4，其余用 2+2。
- **M-4 公开序列化仍原样返回 `summary_json`**（`apps/transform/mappings.py:284`）：若发布方把联系人写进摘要会公开；不在本期字段清单，建议契约层标注「摘要不得含 PII」。
- **M-5 `_sync_team_snapshot` 不校验 tenant**：`apps/staff/api.py` 内按 `team=t` 重算，跨租户成员会被计入快照；修 C-5 时一并加 `tenant_id=team.tenant_id`。

---

## 10. §结论「本期验收口径」

1. **按「r3 点名的 3 个 handler」验收**：A-1 GET+submit、A-2 update_task、A-3 claim 全部真闭环，反向验证不误伤，I-1/I-2 通过，回归 601 绿，契约零 diff。这一口径下 `57ac05f` 是合格增量，可给 APPROVED_WITH_MINOR。
2. **按「D-1/D-2/D-3 闭环」验收（commit message 的口径）**：不成立。D-1 的修法清单包含 `decide_amendment`，D-2 的修法清单包含 `attach_project_category`，两者原样未改且可实测越权；D-3 只修了 `_process_claim`，同文件 `_get_output_or_404` 家族的 4 个写入口仍在。
3. **按「E-7 跨域 id 收口（资源类清零）」验收（本期名称的口径）**：不通过。F 段实测 12 个跨租户写端点 + 2 个跨租户读端点，覆盖 5 个域；r3 的 D-4 候选（asset）与未列入的 staff 同样是可复现越权。
4. **上生产判断**：任何一条 C-1～C-7 都足以在等保/审计里被判高危（跨租户写主数据）。即使只按第 1 条口径合并，也必须把 C-1～C-7 单开一期（E-8）并明确「E-7 未完成全仓收口」，不能以「E-7 已收口」对外表述。
5. **建议的最小闭环路径**（按性价比排序）：C-1、C-2、C-3 各一行查询改造 + 3 条 404 用例（半天）；C-4/C-5 抽 `_get_staff_or_404(request, sid)` / `_get_team_or_404(request, tid)` 两个 helper（1 天）；C-6/C-7 各 3-4 处查询加 tenant（1 天）；I-2 新开 `0020` 与恢复脚本（半天）。

---

## 11. 末段

**VERDICT：REQUEST_CHANGES。** 不推 develop（至少不能以「D-1/D-2/D-3 已闭环」的表述推），不可上生产。

最关键的三条发现：

1. **r3 点名的修法项被漏掉，而 commit 声称已闭环**：`apps/ethics/api.py:427-443` 的 `decide_amendment` 仍按裸 id 查 `CAmendment`，tenant-1 的 **R-ETHICS** 就能把 tenant-2 的修正案改成 `APPROVED`（实测 200 + 落库）；`apps/project/api.py:1004-1011` 的 `attach_project_category` 仍可被 tenant-1 的 **R-STAFF** 改写 tenant-2 项目分类。这两条在 r3 报告的「修法」里逐字写明，属于「声称闭环但未执行」，不是新发现。
2. **D-3 只修了认领，没修 helper 家族**：`_get_output_or_404`（`apps/output/api.py:92`）支撑的 link_projects / patent stage / patent fee / reprint 四个写入口仍可跨租户操作，`GET /output/{id}` 还直接返回他租户成果详情（`tenant_id: 2`）。这正是 r3 在 D-3 里「建议一并加 tenant_id」的部分。
3. **F 段再扫出两个未登记的高危域**：`apps/staff` 的 `_get_staff_or_404` 让 tenant-1 R-MANAGER 可把他租户员工改成 `RESIGNED/INACTIVE`、可往他租户团队塞 `tenant_id=1` 的成员并改团队快照；`apps/asset` 的 `_get_asset_or_404` 让 tenant-1 R-STAFF 可把他租户资产领用/调拨/处置。这两域在 r3 的 D-4 表里没有（asset 有、staff 没有），说明上一轮的静态扫描本身也有盲区。

正面结论也要记：`57ac05f` 的三处核心修复（案卷 helper、项目 helper 双定义、claim 过滤）质量是好的，A/B/C/D 四段实测全部符合预期，601 回归与契约零 diff 干净，5 条新用例在旧实现上全红——问题只在「收口半径」与「宣称口径」，不在已改代码的正确性。
