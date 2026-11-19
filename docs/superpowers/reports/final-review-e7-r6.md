# E-7 终审报告（第六轮 / r5 C-1、C-2 修复确认）：跨域 id 收口

- 评审对象：`develop` 分支 `git diff 1b1b55f..36cca20`（10 commits）。本轮新增 `36cca20 fix(跨域): 访客审批与 N 域评审回写链收租户（E-7 r5 C-1/C-2）`，父提交为 r5 评审的 `d98b305`。
- 评审方式：只读。全部测试/探针在 `git archive 36cca20` 的干净导出树 `/tmp/e7r6-clean` 执行；红测在 `d98b305` 导出树 `/tmp/e7r6-red` 执行；探针脚本只写 `/tmp` 且跑完即删。真实仓库本次**唯一写入是本报告**（源码/测试/契约/policy 零改动）。
- 基线：`610 passed, 19 warnings in 45.73s`。
- 证据口径：状态码、落库值、响应体片段均为本轮实测；仅有源码判读的结论单独标注「代码判读」。

---

## VERDICT

**APPROVED_WITH_MINOR —— `1b1b55f..36cca20` 可推送 `develop`；上生产为「有条件通过」。**

r5 的两条 Critical 均已**真闭环**，不是只加断言：

1. **C-1 访客审批**：`apps/staff/api.py:624` 已改为 `v = _get_visitor_or_404(request, id)`，该文件 `SVisitor.objects.filter(id=` 裸查 **0 处**；实测 tenant-1 令牌审批 tenant-2 访客 → **404**，访客 `status=APPLIED`、`permissions_scope` 原样未动（r5 为 200/APPROVED/`role_codes:["R-ADMIN"]`）。
2. **C-2 评审回写链**：`apps/expertreview/api.py:238-256` 新增 `_assert_target_owned(tenant_id, biz_type, target_id)`，在 `create_review`（`:270`）、`invite_experts`（`:324`）、`conclude_review`（`:493`）三处调用；四个单一写者同时加可选租户门。实测 OUTPUT_EVAL / MID_CHECK / FINAL_ACCEPT 三条路径的「跨租户 create」与「绕过入口的脏任务 conclude/invite」全部 **404 且目标数据不变**；本租户同路径全部 200 且写生效；不带 tenant 直调单一写者仍是旧语义（兼容）。

剩余问题是 **1 条范围外存量 Important（archive 整域裸 id，r3 D-4 遗留，本轮无变化）** 和 3 条 Minor（文档/覆盖/语义说明），不构成本期阻断。

---

## 一、实测数字

| # | 项目 | 本轮实测 | 期望/上轮 |
|---|---|---|---|
| 1 | HEAD / 提交数 | `36cca20` / 10 | 10 |
| 2 | `1b1b55f..36cca20` 总量 | 22 文件 +1489 / −210 | — |
| 3 | `36cca20` 自身 | 6 文件 +124 / −27（与提交说明一致） | 6 文件 |
| 4 | 全量 pytest（干净树、探针已删） | **610 passed, 19 warnings in 45.73s** | 610 |
| 5 | `makemigrations --check --dry-run` | **No changes detected** | No changes |
| 6 | `git diff 1b1b55f..36cca20 -- design/ frontend/src/api/schema/` | **0 字节** | 空 |
| 7 | README 第 5/29/99 行 | 610 / 610 / 610 | 610 |
| 8 | r5 新增 2 条用例 @`d98b305` 实现 | **2 failed, 29 deselected in 3.06s** | 2 红 |
| 9 | 同一批用例 @`36cca20` | 全绿（含在 610 内） | 绿 |
| 10 | C-1 跨租户访客审批 | **404**，`status=APPLIED`，`permissions_scope` 不变 | 404/不变 |
| 11 | C-2 OUTPUT_EVAL 跨租户 | create **404**；脏任务 conclude **404**；成果 `CLAIMED / is_claimed=False` | 404/不变 |
| 12 | C-2 MID_CHECK 跨租户 | create **404**；invite **404** 且 `expert_ids=[]`；conclude **404** 且 `PLANNED/None` | 404/不变 |
| 13 | C-2 FINAL_ACCEPT 跨租户（补充） | create **404**；conclude **404** 且 `status=APPLIED` | 404/不变 |
| 14 | 反向（本租户） | 访客 200/APPROVED；OUTPUT_EVAL 200→`ASSIGNED_TO_PROJECT/True`；MID_CHECK invite 200→`expert_ids=[1]`；FINAL_ACCEPT 200→`APPROVED` | 全 200 |
| 15 | 兼容性（不传 tenant） | `conclude_output_eval(o.id, True)` 仍写；`set_mid_check_experts(id, [7,8])` 仍写；`target_id` 不存在时 create 放行 200 | 保持旧语义 |
| 16 | F 段无 tenant 的 `filter(id=`/`get(id=` 候选 | 42 行；本轮仅新增 `:253`（只读 `exists()` 校验），**无新增可达跨租户写** | 0 新增 |
| 17 | archive 域 | `1b1b55f..36cca20` 内 **0 文件**变更，存量裸 id 未动 | 范围外 |

---

## 二、A 段：r5 C-1 复测（访客审批）

### 代码

`apps/staff/api.py:622-625`：

```python
@transaction.atomic
def approve_visitor(request: HttpRequest, id: int):
    dom = domain_from(request)
    v = _get_visitor_or_404(request, id)
```

`_get_visitor_or_404`（`apps/staff/api.py:60-67`）按 `id + tenant_id + deleted=0` 取；r5 的死代码本轮已接线。`grep -n "SVisitor.objects.filter(id=" apps/staff/api.py` → 无输出（0 处）。

### 实测（`tests/test_probe_r6.py`）

```
C1.visitor.cross 404 APPLIED {'modules': ['project']}
C1.visitor.own 200 APPROVED {'role_codes': ['R-STAFF']}
```

- 跨租户：tenant-1 `R-MANAGER` 审批 tenant-2 的 `SVisitor(status=APPLIED, permissions_scope={"modules":["project"]})` → **404**，状态仍 `APPLIED`，`permissions_scope` 未被追加 `role_codes`（r5 实测为 `200 APPROVED {'role_codes':['R-ADMIN']}`）。
- 反向：本租户访客审批 → **200 APPROVED**，`role_codes` 正常写入。

**结论：C-1 真闭环。**

---

## 三、B 段：r5 C-2 复测（评审回写链）

### 代码

`apps/expertreview/api.py:238-256`：

```python
def _assert_target_owned(tenant_id: int, biz_type: str | None, target_id: int | None) -> None:
    if not target_id:
        return
    model = {"MID_CHECK": EMidCheck, "FINAL_ACCEPT": EFinalAccept,
             "OUTPUT_EVAL": ROutput}.get(biz_type or "")
    if model is None:
        return
    foreign = model.objects.filter(id=target_id).exclude(tenant_id=tenant_id).exists()
    if foreign:
        raise ApiError(404, CODE_NOT_FOUND, "评审目标不存在")
```

- 三处调用：`create_review` `:270`、`invite_experts` `:324`、`conclude_review` `:493`（均在写前）。
- `_conclude_writeback(..., tenant_id=t.tenant_id)`（`:505`）把租户透传给四个单一写者；写者内部 `if tenant_id is not None: qs = qs.filter(tenant_id=...)`（`apps/output/api.py:302-304`、`apps/project/api.py:1300-1302`、`:1369-1371`、`:1404-1406`）。

### 实测（`tests/test_probe_r6.py`）

```
C2.create.cross 404 40401
C2.conclude.cross 404 CLAIMED False DRAFT
C2.output.own 200 200 ASSIGNED_TO_PROJECT True
C2.mid.create.cross 404 40401
C2.mid.invite.cross 404 []
C2.mid.conclude.cross 404 PLANNED None
C2.mid.invite.own 200 [1]
```

- **OUTPUT_EVAL**：tenant-1 创建指向 tenant-2 成果的评审 → **404**（`40401`）；另用 ORM 造一条绕过入口的 `NReviewTask(tenant_id=1, biz_type=OUTPUT_EVAL, target_id=<tenant-2 成果>)`，conclude → **404**，成果仍 `CLAIMED / is_claimed=False`，任务仍 `DRAFT`（写前拦截，未先改任务状态）。
- **MID_CHECK**：跨租户 create → **404**；脏任务 invite → **404 且 `expert_ids=[]` 未被回填**；脏任务 conclude → **404，`status=PLANNED / conclusion=None`**。
- **FINAL_ACCEPT（补充验证，`tests/test_probe_r6b.py`）**：`C2.final.create.cross 404 40401`、`C2.final.conclude.cross 404 APPLIED`；反向 `C2.final.own 200 200 APPROVED`。

**结论：C-2 三条回写路径真闭环（不是只挡入口，conclude/invite 处有兜底）。**

---

## 四、C 段：反向验证（未过度收紧）

```
C1.visitor.own 200 APPROVED {'role_codes': ['R-STAFF']}
C2.output.own 200 200 ASSIGNED_TO_PROJECT True
C2.mid.invite.own 200 [1]
C2.final.own 200 200 APPROVED
```

- 本租户访客审批、OUTPUT_EVAL 回写（`CLAIMED→ASSIGNED_TO_PROJECT`、`is_claimed=True`）、MID_CHECK invite 回填 `expert_ids=[1]`、FINAL_ACCEPT 回写 `APPROVED` 全部 200 且落库。

## 五、D 段：兼容性（不传 tenant 的直调）

```
COMPAT.conclude_output_eval ASSIGNED_TO_PROJECT True
COMPAT.missing_target 200 0
COMPAT.set_mid_check_experts [7, 8]
```

- `conclude_output_eval(o3.id, True)` 不传 tenant → 仍按旧语义写 `ASSIGNED_TO_PROJECT / is_claimed=True`；`set_mid_check_experts(mc.id, [7,8])` 不传 tenant → 仍回填。N 域内部/测试调用不受影响。
- `target_id` 不存在时 create 放行（`200`）——这是设计声明（兼容历史数据），写回阶段仍受租户过滤保护；仅作为语义备注（见 M-2）。

---

## 六、E 段：回归与卫生

- **全量回归**：`610 passed, 19 warnings in 45.73s`（= r5 的 608 + 本轮 2 条）。
- **`makemigrations --check --dry-run`**：`No changes detected`。
- **契约零 diff**：`git diff 1b1b55f..36cca20 -- design/ frontend/src/api/schema/` 输出 0 字节。
- **README**：第 5 行「全量 610 pytest 通过」、第 29 行「tests/（610 个）」、第 99 行「当前 610 passed」。
- **红测**：把 `36cca20` 的 `tests/test_e7_review_fixes.py` 覆盖到 `d98b305` 实现上，跑两条新用例 → `2 failed, 29 deselected in 3.06s`，失败点为 `test_visitor_approve_is_tenant_scoped`（断言 404 实得 200）与 `test_expertreview_writeback_rejects_foreign_target`（断言 404 实得 200 / 成果被改）。
- **新用例质量**（`tests/test_e7_review_fixes.py:530-578`）：
  - 访客用例断言 404 + `status=APPLIED` + `role_codes` 未写入；
  - 评审用例覆盖**双层**：HTTP create 404（并断言未落任务）+ ORM 脏任务 conclude 404（并断言成果 `CLAIMED/is_claimed=False`）——正好钉住「入口 + 单一写者」两道门。
- **逐 commit `--stat`**：10 个 commit 均为「本域实现 + 本域测试（+ README）」，无脚本、无 lockfile、无 `.venv`、无 `_reference/`、无生成物；`36cca20` 的 6 个文件与提交说明逐条对应。
- **工作树**：`docs/IMG_*.jpeg` 的删除与 `docs/.DS_Store` 修改为 11/16 遗留噪声（目录 mtime 可证），非本次评审产生；真实仓库除本报告外零写入。

---

## 七、F 段：全仓再扫（决定上生产口径）

扫描口径同 r5：`apps/*/api.py` 中 `objects.filter(id=` / `objects.get(id=` 且未带 `tenant_id` 的位置；窄口径计数 **42 行**（r5 为 66 行，差异在过滤模式，判定结论一致）。逐行复核后：

### F-1 本轮新增代码

仅 `apps/expertreview/api.py:253` 一处裸 id（`_assert_target_owned` 内的 `filter(id=target_id).exclude(tenant_id=...)`），**只读 `exists()`，不写**；其余新增行均带 tenant。**无新增可达跨租户写。**

### F-2 范围外存量：archive 整域（Important，r3 D-4 遗留）

`1b1b55f..36cca20` 内 `backend-django/apps/archive` **0 文件改动**，裸 id 现状与 r5 一致：

| 位置 | 写/读 | 可达性 |
|---|---|---|
| `apps/archive/api.py:53 _get_doc_or_404`、`:60 _get_archive_or_404` | 基座 | 被下列 handler 共用 |
| `:181-192 delete_document` | 写（软删） | `DELETE /documents/{id}`，R-ADMIN（policy:259） |
| `:255-272 update_archive` | 写 | `PUT /archives/{id}`，R-MANAGER（policy:248） |
| `:274-284 delete_archive` | 写（软删） | `DELETE /archives/{id}`，R-ADMIN（policy:260） |
| `:307-318 fill_item`、`:321-327 delete_item` | 写 | 清单条目写/硬删 |
| `:493-506 _set_borrow_status` | 写 | 借阅审批/归还（policy:261/262） |
| `:472-489 list_borrows`、`:221-236 list_archives`、`:193-213 search_documents` | 读 | 跨租户列全部 |

不属 E-7 收口范围（r1 为 activity/confsec/funding/transform，r3 起追加 ethics/project/output/staff/asset，archive 从未列入），r3/r4/r5 均作为 backlog 记录。**处置建议：单开一期**（同 E-7 手法），或在上生产前对 `R-ADMIN DELETE /documents/*`、`R-ADMIN DELETE /archives/*` 加受控运维通道 + 书面确认。

### F-3 仅读低危（Minor，与 r5 相同）

`apps/staff/api.py:341`（合作网络补姓名）、`apps/p/api.py:633`（任务存在性）、`apps/expertreview/api.py:305/321/526`（专家姓名/邮箱）、`apps/project/api.py:1580`（文档存在性）——均无写，建议随下一期收。

---

## 八、问题清单

### Critical

**无。** r5 的 C-1、C-2 已闭环且经反向/兼容/兜底三类实测验证。

### Important

**I-1 archive / document / borrows 整域裸 id（存量、范围外）**

- 位置与影响见 F-2 表；`delete_document`、`update_archive`、`delete_archive`、`fill_item`、`delete_item`、`_set_borrow_status`、`list_borrows`、`search_documents` 均可由本租户角色跨租户触达。
- 本期未变化、未新增回归；**上生产前必须处置**（单开一期优先；若排期不允许，至少对两个 DELETE 加补偿控制并书面确认）。

### Minor

- **M-1** `apps/sysadmin/migrations/0019_purge_stale_policy_e7.py:7` docstring 写「只删这**两**条已知下线的规则」，`STALE_POLICY` 只有 1 条（r4 M-1 起未改）。
- **M-2** `_assert_target_owned` 对「目标不存在」放行是显式设计（兼容历史数据）；建议在 docstring 补一句「放行仅针对历史/无目标任务，写回端仍按 tenant 过滤」，避免后来者误读为校验缺口。
- **M-3** 新增 2 条用例只覆盖访客与 OUTPUT_EVAL 回写；MID_CHECK / FINAL_ACCEPT 的跨租户拦截目前只有本报告的探针，无仓库内用例。建议补 1 条参数化用例（`biz_type` 三值）钉住 `_assert_target_owned` 的表映射。

---

## 九、结论：本期验收口径

1. **验收面**：r5 的 C-1/C-2 + r4 已闭环的 C-1..C-7（修正案、纪检、人遗备案、项目分类、成果族、团队/人员/资产、访客）+ E-7 各域。
2. **判据**：跨租户写 = Critical（阻断）；跨租户读 = Important（限期）；文档/覆盖 = Minor。
3. **本期实测**：C-1 跨租户 404 且数据不变、C-2 三条回写路径（OUTPUT_EVAL / MID_CHECK / FINAL_ACCEPT）入口与兜底双层 404、本租户反向全 200、兼容调用保持旧语义；610 绿、契约零 diff、2 条新用例在 `d98b305` 上 2 红。**E-7 范围内已无可达的跨租户写。**
4. **能否推 develop**：**能。** `1b1b55f..36cca20` 可推送 `develop`。
5. **能否上生产**：**有条件通过。** E-7 范围内可上；archive 域的单开一期收口或补偿控制需在上生产前落地并书面确认。若产品本期不开放 archive 的删除/案卷写接口，则可直接上生产。
6. **archive 是否单开一期**：**建议单开**（范围、判据、修法都与 E-7 同构，5 个写 handler + 3 个读列表，预计 1 期可收）。

---

## 十、末段：verdict 与最关键三条

**VERDICT：APPROVED_WITH_MINOR。** `1b1b55f..36cca20` 可推 `develop`；上生产为「E-7 范围内可上、archive 域需单开一期或补偿控制」的条件通过。

最关键三条：

1. **两条 Critical 都是真修，不是加断言**：`approve_visitor` 换成 `_get_visitor_or_404`（`apps/staff/api.py:624`）后，跨租户 404 且 `status/permissions_scope` 不变；`_assert_target_owned` 在 create/invite/conclude 三处 + 四个单一写者的可选租户门形成双层防护，实测脏任务 conclude 也 404 且成果 `CLAIMED/is_claimed=False`。
2. **反向与兼容未受伤**：本租户访客审批、OUTPUT_EVAL 回写、MID_CHECK invite 回填、FINAL_ACCEPT 回写全部 200 且落库；不传 tenant 直调单一写者仍是旧语义（内部调用/测试不受影响）。
3. **唯一剩余风险在范围外**：archive 整域裸 id（`apps/archive/api.py:53/:60` + 8 个 handler）自 r3 D-4 起未动，本轮也未碰；它不阻断 develop，但决定「能否上生产」时必须单列处置——单开一期最干净，退路是受控运维通道 + 书面确认。
