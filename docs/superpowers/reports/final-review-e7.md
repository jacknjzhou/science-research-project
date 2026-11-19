# E-7 终审报告：跨域 body/path id 裸查收口（activity / confsec / funding / transform）

- 评审对象：`develop` 分支 `git diff 1b1b55f..a17db11`（4 commits：`e2d297a` activity、`91830e1` confsec、`d317245` funding、`a17db11` transform）
- 评审方式：只读源码 + 跑测试 + 独立探针（探针全部写在 `/tmp/e7probe/`，未向仓库新增任何文件；本次唯一写入的文件是本报告）
- 基线：`579 passed, 19 warnings`；回退-恢复后复跑仍 `579 passed`
- 证据口径：所有状态码/金额均为实测输出；标注「代码判读」的条目未构造出可执行链，仅按源码形态判定

---

## VERDICT

**REQUEST_CHANGES —— 不可推送 `develop`。**

四个域里 activity、confsec 的收口是干净的；transform 主链收口到位但漏了两条支路；**funding 只收口了「单据」而没有收口「预算行」**，导致报销 / 外拨 / 借款三条链都能用一个本租户单据挂上他租户的 `budget_line_id`，把租户 B 的预算行冻结、扣减甚至实扣（实测 `amount_used=300.00`、`amount_frozen=400.00`）。这与 E-7 的安全目标（跨租户一律不可读写）直接冲突，属于必须本期修的 Critical。

另有 5 项 Important：transform 谈判可跨租户读取他租户企业风控字段、confsec 审计日志可由请求体指定他租户、funding 科目删除存在存在性预言机、以及一条**假绿测试**（`GET /disclosure/{id}` 根本没有路由，`test_transform_tenant.py:37` 的 404 与租户无关）。

修完 Critical + Important（至少 C1–C4、I1–I3）并复跑全量后，可再审。Minor 项可作为后续清理。

---

## 一、Critical（必须修，附可复现攻击链）

### C1. funding 报销链：跨租户建单 → 提交冻结 → 审批实扣他租户预算行

- 落库不校验：`backend-django/apps/funding/api.py:786-800`，`project_id=b["project_id"]`、`budget_line_id=b.get("budget_line_id")` 原样写入，无归属校验。
- 提交冻结无租户：`backend-django/apps/funding/api.py:849-856`
  ```python
  line = FBudgetLine.objects.select_for_update().filter(id=e.budget_line_id, deleted=0).first()
  ...
  line.amount_frozen = _d2(line.amount_frozen + e.amount)
  ```
- 审批实扣无租户：`backend-django/apps/funding/api.py:914-917`
  ```python
  FBudgetLine.objects.filter(id=e.budget_line_id, deleted=0).update(
      amount_frozen=F("amount_frozen") - e.amount,
      amount_used=F("amount_used") + e.amount, updated_at=dj_tz.now())
  ```
- 驳回解冻同样无租户：`backend-django/apps/funding/api.py:933-936`。

**实测攻击链**（`/tmp/e7probe/test_e7e.py`，租户 2 的 FBudgetLine，租户 1 的 R-STAFF + R-MANAGER）：

```
[expense.create] 200          # body budget_line_id = tenant2 的预算行
[expense.submit] 200          # status=SUBMITTED，tenant2 行 amount_frozen=100.00
[expense.approval {"action":"approve"}] 200   # status=APPROVED
[expense.final] tenant2 line frozen=0.00 used=300.00
```

即：A 租户普通员工建单 + A 租户经理审批，就能把 B 租户的预算行 `amount_used` 加上 300 元，B 的 `remaining` 被实扣。攻击者不需要读 B 的任何数据，只需要知道（或枚举）一个 `budget_line_id`。

### C2. funding 外拨链：跨租户终审实扣

- 落库不校验：`backend-django/apps/funding/api.py:991-996`（`budget_line_id` 在 `:993`）。
- 终审扣减无租户：`backend-django/apps/funding/api.py:1046-1050`
  ```python
  line = FBudgetLine.objects.select_for_update().filter(id=o.budget_line_id, deleted=0).first()
  ...
  line.amount_used = _d2(line.amount_used + o.amount)
  ```

**实测**（`/tmp/e7probe/test_e7.py`，租户 1 的 R-LEADER）：

```
[funding.outward.create.foreign_line] status=200
[funding.outward.approve.foreign_line] status=200   # status=APPROVED
[funding.outward] tenant2 line amount_used=50.00
```

### C3. funding 借款链：跨租户冻结 /（代码判读）释放与放款结转

- 落库不校验：`backend-django/apps/funding/api.py:2183` `budget_line_id=b.get("budget_line_id") or b.get("budgetLineId")`（注意 project 校验 `:2174` 是带 tenant 的，唯独预算行漏了）。
- 提交冻结无租户：`backend-django/apps/funding/api.py:2225-2232`。
- 审批驳回/退回释放无租户：`backend-django/apps/funding/api.py:2283-2286`。
- 放款结转无租户：`backend-django/apps/funding/api.py:2316-2320`。

**实测**（租户 1 R-MANAGER，租户 2 预算行）：

```
[loan.create] 200    # budgetLineId = tenant2 行
[loan.submit] 200    # SUBMITTED
[loan.final] tenant2 line frozen=400.00
```

`approve_loan` 的多步链没走完（`pay` 仍 409「仅 APPROVED 状态可放款」），因此 `:2283`、`:2316` 是按代码判读的残留：三处 `FBudgetLine.objects.filter(id=loan.budget_line_id, deleted=0)` 都没有 `tenant_id`，与 `:2225` 形态完全一致，一旦链走通即可跨租户释放/结转。**修复时四处一起改，不要只改已实测到的两处。**

> 根因是同一类：本期把「单据查询」加了租户，但没有把「单据指向的预算行」加租户，也没有在 create 时校验 `budget_line_id` 归属。只在 create 校验或只在 query 加 tenant 都是单点；建议两处都做（query 加 `tenant_id=d.tenant_id`，create 校验不存在/他租户 → 404）。

### C4. transform 公示异议：任意租户可终止他租户的交易

- `backend-django/apps/transform/api.py:636-661` `handle_objection` 只按 `deal_id` 取公示，取到后直接改 `deal.status`：
  ```python
  p = TPublicity.objects.filter(deal_id=dealId, deleted=0).order_by("-id").first()   # :638 无 tenant
  ...
  if hs == "SUSTAINED":
      p.status = "TERMINATED"; deal.status = "TERMINATED"; deal.terminated_reason = "OBJECTION_SUSTAINED"
  ```
  `dom` 只用于 `modifier_id`，全程没有租户过滤。
- 前置信息由公开接口免费提供：`GET /publicity/{dealId}`（`apps/transform/api.py:573`，无鉴权）返回 `objections` 明细，含 `objection_id` 与 `handle_status`；公示 URL 形态是 `/public/transform/deal/{id}`（`publish_publicity` 写入），deal_id 可顺序枚举。
- 可达性：`config/casbin/policy.csv:647` `p, R-MANAGER, /api/v1/publicity/*, POST`，keyMatch2 的 `*` 匹配多段，R-MANAGER 可打到 `/publicity/{dealId}/objection/handle`。

**实测**（`/tmp/e7probe/test_e7.py`）：

```
[transform.publicity.get.public] status=200                 # 无鉴权读到 objection 明细
[transform.objection.handle.cross_tenant] status=200        # 租户2 R-MANAGER 处理租户1 的异议
[transform.objection] tenant1 deal status=TERMINATED reason=OBJECTION_SUSTAINED
```

影响不是「读」，而是**状态破坏**：租户 B 的交易被外部单方面终止，且 `terminated_reason` 落成 `OBJECTION_SUSTAINED`，事后无法区分是合法异议还是越权操作。

---

## 二、Important

### I1. transform 谈判：`enterpartner_id` 跨租户读取他租户企业风控字段

`backend-django/apps/transform/api.py:296`：

```python
ep = TEnterpartner.objects.filter(id=deal.enterpartner_id, deleted=0).first()
```

`deal.enterpartner_id` 来自请求体（`save_negotiation` / `create_deal` 路径写入），无归属校验；随后把 `ep.check_abnormal`、`ep.last_checked_at` 写进本租户 deal（对外可见）。

**实测**（`/tmp/e7probe/test_e7.py`）：`[transform.deal.negotiation.foreign_enterpartner] status=200`，`[transform.negotiation] deal.partner_check_abnormal=True partner_checked_at=2026-11-19 07:33:53`。泄露字段本身敏感度中等，但它是「他租户数据被写进本租户可读对象」的确定性通道，性质与 E-7 一致。

### I2. confsec 审计日志：请求体可指定 `tenantId`，写入他租户审计链

`backend-django/apps/confsec/api.py:635-652`，关键行 `:641-642`：

```python
log = _sec_log(b.get("tenantId") or dom.tenant_id, ...)
```

`_chain_intact`（`:655-663`）按租户校验哈希链，所以这不是「读」，而是**往 B 租户的审计链尾部追加一条 A 租户伪造的事件**。

**实测**（`/tmp/e7probe/test_e7b.py`）：R-ADMIN 令牌 + body `tenantId: 2` → `status=200`，`[confsec.sec_log] tenant2 rows 0 -> 1`。要求 R-ADMIN 是唯一门槛，但租户管理员作恶/误操作都会污染对端审计证据，合规上不可接受。改法：删除 `b.get("tenantId")`，固定 `dom.tenant_id`；若确需代写，必须校验目标租户=当前租户并留痕。

### I3. funding 科目删除：跨租户存在性预言机（残留裸查）

`backend-django/apps/funding/api.py:212-224` 的 `delete_subject`，其保护查询：

- `:214` `FSubject.objects.filter(parent_id=id, deleted=0)`
- `:216` `FBudgetLine.objects.filter(subject_id=id, deleted=0)`

两条都不带 tenant，命中则 409、未命中则 404，于是返回码随**对方数据形态**变化。

**实测**（`/tmp/e7probe/test_e7d.py`，租户 1 R-MANAGER 打租户 2 的科目）：

```
[funding.subject.delete.foreign_with_children] 409 {"code":40901,"message":"存在下级科目，禁止删除"}
[funding.subject.delete.foreign_leaf]          404 {"code":40401,"message":"科目不存在"}
[funding.subject.delete.foreign_used_by_budget] 409 "科目已被预算引用，禁止删除"
[funding.subject.update.foreign_leaf]          404      # PUT 是租户安全的，对照
```

同一他租户 id，409/404 两态可区分「存在 + 有子科目 / 被预算引用」与「不存在」，违反 M1/M2 反复强调的「不泄露对方是否存在」。虽然是既存问题（不在本期 diff 内），但它在本次四个域之一的 funding 里，且正是 E-7 要消灭的形态。

### I4. 测试假绿：`test_transform_tenant.py:37` 的 `GET /disclosure/{id}` 断言与租户无关

`backend-django/tests/test_transform_tenant.py:33-40` 第一行：

```python
assert c.get(f"/api/v1/disclosure/{d.id}", **bearer(1, T_ROLES, tenant_id=2)).status_code == 404
```

但 `config/api.py:648-651` 只注册了 `GET|POST /disclosure`、`POST /disclosure/{id}/submit`、`POST /disclosure/{id}/valuation`，**没有 `GET /disclosure/{id}`**；`design/05-科技成果转化-T.openapi.yaml` 同样没有该路径。请求落进 `core/stub.py` 的兜底 `stub_view`，返回 `err(..., 404, "接口不存在")`。

**实测**（同一探针对比同租户/他租户）：

```
[transform.disclosure.get.own_tenant]   status=404 body={"code":40401,"message":"接口不存在",...}
[transform.disclosure.get.other_tenant] status=404 body={"code":40401,"message":"接口不存在",...}
own==other? True
```

同租户也 404，说明该断言证明的只是「路由不存在」，与 E-7 修复零关系。该文件其余 4 个断言在回退后真红（见第四节），所以文件整体不算假绿，但这一行必须删掉或改成真实端点（`POST /disclosure/{id}/submit` 已经在下一行覆盖了同一语义）。同源问题：`policy.csv:605`/`:609` 的 `p, R-*/api/v1/disclosure/*, GET` 是悬空授权。

### I5. `/indirect-fees/calculate` 在 policy.csv 无任何角色行，仅 R-ADMIN 通配可达

`config/casbin/policy.csv` 只有裸路径 `/api/v1/indirect-fees` 的行（`:306`/`:307` R-MANAGER、`:371`/`:372` R-FINANCE），而 `keyMatch2` 下裸路径不匹配子路径（policy.csv 自己的注释 `:416` 已写明这一点，`cost-pools/calculate` 也因此单独加了行 `:423`/`:442`）。

**实测**（`/tmp/e7probe/test_e7b.py`）：

```
[policy.indirect-fees/calculate.R-FINANCE] status=403
[policy.indirect-fees/calculate.R-MANAGER] status=403
[policy.indirect-fees/calculate.R-ADMIN]   status=200
```

即间接费计算对财务/负责人角色**不可用**，只有 R-ADMIN 通配能过。新测试 `test_funding_tenant.py:136-144` 正是用 R-ADMIN 令牌绕过了这一点，于是把一个鉴权缺陷冻结成了「正常」——这也是掩盖性证据，建议测试改用 R-FINANCE 并同步补 policy 行。该缺口属既存问题，但本期测试让它更难被发现，故列入 Important 的「测试设计」项。

---

## 三、Minor

1. **跨租户 409 与「一律 404」口径漂移**。`submit_budget`、`submit_expense`、`pay_loan` 用「带 status 过滤的查询 + 409」表达不可见（如 `apps/funding/api.py:838-841`），返回 `409 {"code":40901,"message":"仅 DRAFT 状态可提交"}`，与 `design/03-科研经费管理-F.openapi.yaml:2375`「404 = 资源不存在或越权（跨租户/跨法人过滤后不可见）」不一致。不泄露存在性（对外租户同一返回），但与设计口径冲突；测试用 `in (404, 409)` 把它固化了（`tests/test_funding_tenant.py:47`、`:67`、`:78`）。要么统一 404，要么在 design 里显式写明「不可见按状态冲突处理」。
2. **funding create 不校验 `project_id`**：`create_expense`（`:788`）、`create_outward`（`:992`）、`create_loan`（`:2174` 只用于取 legal_entity，未拒绝）接受外租户/不存在项目。实测 `project_id=987654` → 200。影响是数据污染与记账归属（外拨终审 `:1058` 用 `EProject.objects.filter(id=o.project_id)` 取 `legal_entity_id`），不构成读取泄漏。
3. **transform `create_disclosure` 不校验 `output_id`/`project_id`**（`apps/transform/api.py:151-160`）：实测不存在 id → 200。泄露面有限（只存 id，不回填对端数据）。
4. **两处「看起来漏、实际安全」但应加注释**：`apps/funding/api.py:438` `EProjectCategory.objects.filter(id=p.category_id...)`（`p` 已带 tenant，派生 id 安全）；`:1058` 同上。留着无防护会让下一个人误判。
5. **提交说明与 diff 不符**：`d317245` 标题含「冲销」，但 `write_off_loan`（`apps/funding/api.py:2308-2347` 区间）在 `1b1b55f` 已带 `tenant_id`，本期零改动（`git diff` 中 `write_off` 命中 0 次）。结论本身没错（它确实安全），但「本期修了冲销」是误记，E-7 台账会因此高估进度。
6. **工作区脏**：`docs/.DS_Store` 修改、6 个 `docs/*.png/jpeg` 删除、`backend-django/uv.lock`、`docs/superpowers/plans/*.md`(7 个)、`docs/superpowers/reports/`、`frontend/pnpm-lock.yaml`、`frontend/pnpm-workspace.yaml`、`dump.rdb`、`memory:r9b`、`scripts/ocr_*` 未跟踪。与本期 4 commit 无关，但推送前应清理或单独提交，避免误带。
7. **policy.csv 悬空授权**：`/api/v1/disclosure/* GET`（`:605`/`:609`）指向不存在的路由（见 I4），应删。
8. **activity 无 domain 级测试**：`tests/` 下只有新增的 `test_activity_tenant.py`，没有 activity 的既有功能回归文件；本次靠该文件 + 其它套件兜底。建议补一个最小 happy-path。

---

## 四、覆盖核查表（四域 × 原有裸查点 / 是否已改 / 残留）

| 域 | 原有裸查点 | 本期是否已改 | 残留 | 判定 |
|---|---|---|---|---|
| activity | `_get_activity_or_404` 内 `VActivity.filter(id=activity_id, deleted=0)`；参与人 list/add/remove 直接按 `activity_id` 查 | 是：helper 加 `tenant_id`（`apps/activity/api.py:66-71`），11 个调用点全部传 `d.tenant_id`；参与人三个入口先校验活动归属（`:347`、`:368`） | 无 | **通过** |
| confsec | revoke / export approve / release / 详情 / classify 五处按 id 裸查 | 是：`:434`、`:500`、`:542`、`:568`、`:610` 均加 `tenant_id`；classify 对外租户 target 保持 200+审计（不泄露存在性，与测试预期一致） | `write_sec_log` 的 `b.get("tenantId")`（`apps/confsec/api.py:641-642`，属审计写入，非 id 裸查） | **通过（I2 另记）** |
| funding | 预算 helper + 8 个动作；报销 get/submit/approve/批量；create_budget 项目归属；carryover/indirect-fee 的 project_id；write-off expenseId | 部分：预算与单据均已加租户（`_get_budget_or_404` `:227-232`、create_budget 项目校验 `:245-247`、carryover `:1278`、indirect fee `:1368`、write-off 基线已安全）；**预算行与建单归属未加** | 详见下方 6 条 | **不通过** |
| transform | 三 helper（disclosure/deal/income）+ valuation/contract/distribution rule/record | 大部分：三 helper 改签名且 14 个调用点全部传 `dom.tenant_id`；contract/publicity/distribution 查询加租户 | `handle_objection` `:638`；`_apply_negotiation` 的 `TEnterpartner` `:296`；`create_disclosure` 的 output/project 校验；公开通道 `:574`/`:609`（设计如此） | **不通过（支路）** |

funding 残留明细（全部已实测或代码判读）：

| 位置 | 查询 | 风险 |
|---|---|---|
| `apps/funding/api.py:849-856` | submit_expense 冻结预算行，无 tenant | **C1** 已实测冻结 |
| `apps/funding/api.py:914-917` | 报销审批实扣，无 tenant | **C1** 已实测实扣 300 |
| `apps/funding/api.py:933-936` | 报销驳回解冻，无 tenant | 代码判读，同形态 |
| `apps/funding/api.py:1046-1050` | 外拨终审实扣，无 tenant | **C2** 已实测实扣 50 |
| `apps/funding/api.py:2225-2232` | 借款提交冻结，无 tenant | **C3** 已实测冻结 400 |
| `apps/funding/api.py:2283-2286` | 借款释放，无 tenant | 代码判读，同形态 |
| `apps/funding/api.py:2316-2320` | 放款结转，无 tenant | 代码判读，同形态 |
| `apps/funding/api.py:788`、`:993`、`:2183` | create 时 budget_line_id 原样落库 | 上述三条链的入口 |
| `apps/funding/api.py:214`、`:216` | 科目删除的存在性检查 | **I3** 预言机 |

transform 残留明细：

| 位置 | 查询 | 风险 |
|---|---|---|
| `apps/transform/api.py:638` | `TPublicity.objects.filter(deal_id=dealId, deleted=0)` | **C4** 跨租户终止交易 |
| `apps/transform/api.py:296` | `TEnterpartner.objects.filter(id=deal.enterpartner_id, deleted=0)` | **I1** 跨租户读取 |
| `apps/transform/api.py:151-160` | create_disclosure 的 output_id/project_id | Minor，仅存 id |
| `apps/transform/api.py:574`、`:609` | get_publicity / submit_objection 无鉴权 | 设计为公开通道（PRD §11），本身不算残留；但它为 C4 提供了 objection_id |

「看起来漏但实际安全」的已判读条目（供后续 review 参考）：`activity` 的 `:171`/`:172`/`:348`/`:369`（父活动已校验）；`confsec` 的 `:781`（`_grant_exists` 带 tenant）；`funding` 的 `:335`/`:373`（带 `budget_id` 且父预算已校验）、`:880`/`:1077`/`:1263`（先按租户取到对象再回读）、`:2291`/`:2320`/`:2357`/`:2364`/`:2388`/`:2395`（按已校验 `loan.id`）；`transform` 的 `:334`/`:435`/`:547`（deal 已校验）。

---

## 五、测试真实性验证（回退到 1b1b55f 实测）

方法：`git show 1b1b55f:./backend-django/apps/<域>/api.py > /tmp/e7probe/bak/...` → `cp` 覆盖 → 跑该域新测试 → `cp` 回新文件 → `git status backend-django/apps` 干净。

| 测试文件 | 用例数 | 回退 1b1b55f 后结果 | 结论 |
|---|---|---|---|
| `tests/test_activity_tenant.py` | 4 | **4 failed** | 真红，有效 |
| `tests/test_confsec_tenant.py` | 5 | **5 failed** | 真红，有效 |
| `tests/test_funding_tenant.py` | 10 | **9 failed, 1 passed** | 真红（9 条）；`test_related_loan_and_expense_id_reject_foreign` 在新旧代码都绿——`write_off_loan` 基线已带 tenant，该条锁定的是既存安全，不是本期修复的证据 |
| `tests/test_transform_tenant.py` | 5 | **5 failed** | 真红（4 条真红 + `GET /disclosure/{id}` 那条见 I4） |

失败原文摘录（回退态）：

```
tests/test_transform_tenant.py::test_cross_tenant_contract_and_income_are_404
  assert 200 == 404        # GET /api/v1/contract/1
  assert 200 == 404        # POST /api/v1/income/1/match，body status=MATCHED
tests/test_funding_tenant.py::test_cross_tenant_budget_read_and_lines_are_404
  assert 200 == 404        # GET /api/v1/budgets/{id}
```

恢复后：

```
$ .venv/bin/python -m pytest -q
579 passed, 19 warnings in 42.61s
$ git status --porcelain backend-django/apps
（空）
```

补充说明两点：

1. `test_transform_tenant.py` 实际是 **5** 个测试（任务书写的是 6），`test_funding_tenant.py` 实际是 **10** 个（任务书写的是 9）。用例数与文档不符，属台账小错，不影响结论。
2. `test_funding_tenant.py` 的断言强度偏弱：多处 `assert r.status_code in (404, 409)` / `in (404, 422)` / `in (400, 404)`（`:47`、`:67`、`:78`、`:124`、`:137`），把「语义不确定」写进了测试，掩盖了 Minor 1 的口径漂移，也让回归时更难判断是否退化。建议改为精确断言 + 单独用一条测试锁定「跨租户不泄露存在性（与不存在同码）」。

假绿专项结论：**`test_transform_tenant.py:37` 一行是假绿**（同租户同样 404「接口不存在」）；其余 24 个断言的 404/403 均来自代码里的租户校验（回退即变 200），不是路由/casbin 造成的。

---

## 六、功能性回归（本租户内合法操作）

- 既有域套件：`pytest -q tests/test_phase4_confsec.py tests/test_phase4_transform.py tests/test_funding_domain.py tests/test_funding_m1a.py tests/test_funding_m1b.py tests/test_funding_m1c.py` → **125 passed**。
- funding 同租户预算→报销→审批→实扣（`/tmp/e7probe/test_e7.py`）：
  ```
  [regression.expense.create.same_tenant] 200
  [regression.expense.submit.same_tenant] 200
  [regression.expense] own line frozen=100.00
  [regression.expense.approve.same_tenant] 200
  [regression.expense] own line frozen=0.00 used=100.00
  ```
- transform 同租户 disclosure→deal→contract→income→distribution 全链（`/tmp/e7probe/test_e7c.py`，`Ran 1 test OK`）：
  ```
  disclosure.create 200 DRAFT → submit 200 SUBMITTED → deal.create 200 DRAFT
  → negotiation 200 NEGOTIATING → contract.draft 200 DRAFT → sign 200 SIGNED
  → income.register 200 PENDING → income.match 200 MATCHED → rule.create 200 ACTIVE
  → distribution.generate 200 GENERATED total 5000 team 3500 institute 1000 individual 500
  ```
  说明：sign 前在 DB 层把 `TContract.status` 置 `SIGNED`、`TDeal.status` 置 `APPROVED` 以越过正交状态机；这是探针为缩短链路所做的构造，不是代码缺陷。初次跑时遇到的三次 409/400（缺 `payment_method`、缺 `deal_type/contract_amount`、deal 未到 SIGNED）均为参数/状态机校验，与租户无关。
- activity：无既有 domain 测试文件，仅由 `test_activity_tenant.py`（4 passed）+ 全量套件覆盖；参与人 GET/POST/DELETE 在本租户的正常路径未被独立验证（建议补，见 Minor 8）。

结论：本期改动没有破坏同租户合法链路；回归风险集中在「预算行未校验」的补丁本身（修 C1–C3 时别把同租户链路挡掉，尤其是 `budget_line_id` 为空（包干制）的分支必须保持跳过）。

---

## 七、契约 / DDL 一致性

`git diff 1b1b55f..a17db11 -- design/ frontend/src/api/schema/` 为空——**这是合理的**：

1. 本期没有新增/删除路由，没有字段与枚举变化，没有错误码新增，属于纯服务端过滤条件收紧；
2. `design/03-科研经费管理-F.openapi.yaml:2375` 早就写明 404 =「资源不存在或越权（跨租户/跨法人过滤后不可见）」，实现向契约靠拢而不是相反；
3. DDL 未变（无新列/索引），预算行的 `tenant_id` 早已存在（`apps/funding/models.py:70`），所以不需要迁移。

但有两处**契约/配置漂移**应跟进（不属于 design/ 目录，但属于同一份「契约面」）：

- `config/casbin/policy.csv` 缺 `/api/v1/indirect-fees/calculate` 的角色行（I5），实现与「财务角色可算间接费」的产品预期不符；
- `config/casbin/policy.csv:605`/`:609` 的 `GET /api/v1/disclosure/*` 是悬空授权，指向不存在的路由（I4）。

另外 Minor 1 的 409/404 口径问题，建议在 design/03 的 404 定义旁补一句「同一租户内状态不符返回 409」，否则实现与契约会持续互相打脸。`design/09` 里「跨租户 403」的口径是采购域历史遗留，与 E-7 的 404 不同，不必在本期统一，但值得记进台账。

---

## 八、提交卫生

| commit | 文件 | 规模 |
|---|---|---|
| `e2d297a` fix(activity) | README.md、apps/activity/api.py、tests/test_activity_tenant.py | 104+/14− |
| `91830e1` fix(confsec) | README.md、apps/confsec/api.py、tests/test_confsec_tenant.py | 97+/8− |
| `d317245` fix(funding) | README.md、apps/funding/api.py、tests/test_funding_domain.py、tests/test_funding_tenant.py | 202+/29− |
| `a17db11` fix(transform) | README.md、apps/transform/api.py、tests/test_transform_tenant.py | 104+/28− |

- 每个 commit 只含相关文件，README 四处（含 backend-django 计数）一致更新为 579，与实际 `579 passed` 相符（README.md:5、:29、:99）。
- `git status` **不干净**（见 Minor 6），但脏文件均不在本期 4 个 commit 内，属于工作区遗留；推送前请清理或确认不随之推送。
- 未验证项：README 声称「PG 端到端冒烟 30 项全过」，本次评审在 sqlite 测试库上完成，未连 PG 复跑冒烟（环境限制），建议推送前补跑 `backend-django/scripts/smoke_p3.py`、`smoke_p4.py`。

---

## 九、遗留建议（不属于本期，但应登记）

1. **E-7 台账更新**：`docs/superpowers/reports/final-review-security-hardening.md:96-101` 记「93 处」，本期实际收口不完整，剩余条目应显式登记：funding 预算行 7 处、funding create 归属 3 处、funding 科目删除 2 处、transform `handle_objection` + `TEnterpartner` 2 处、confsec `write_sec_log` 1 处。否则下一轮会以为 E-7 已清零。
2. **`/indirect-fees/calculate` 鉴权**：已核实 R-FINANCE / R-MANAGER 均 403，仅 R-ADMIN 通配可达；建议补 `p, R-FINANCE, /api/v1/indirect-fees/calculate, POST`（对照 `cost-pools/calculate` 的既有行），并把新测试从 R-ADMIN 改成 R-FINANCE。
3. **公开通道的防滥用**：`GET /publicity/{dealId}` 与 `POST /publicity/{dealId}/objection` 按 PRD 是公开的，但当前无速率限制、无验证码、deal_id 可枚举，且 `objection/handle` 的鉴权只到角色级（R-MANAGER 即可），这正是 C4 的放大器。建议至少给 handle 加「公示所属租户 == 令牌租户」。公开读接口可保留。
4. **预算行归属的服务层约束**：`FExpense.budget_line_id` / `FOutward.budget_line_id` / `FLoan.budget_line_id` 是「逻辑租户外键」，模型层没有约束。除本期修 query 外，建议在 `apps/funding/services.py`（或同等位置）加统一的 `resolve_budget_line(tenant_id, line_id)`，所有写入路径复用它，避免第四个入口再漏。
5. **policy 悬空行清理**：`/api/v1/disclosure/* GET` 两行删除；同时可加一条 CI 检查「policy.csv 中的 obj 必须能在 `config/api.py` 找到对应路由」，防止再出现「授权了不存在的路径」。
6. **测试断言收紧**：把 `in (404, 409)` 收敛为精确码，并补一条「跨租户与不存在返回完全相同 body」的对比断言（这是 M1/M2 的硬要求，也是这类修复唯一能防回归的写法）。

---

## 十、复现方式（命令）

```bash
cd /Users/jacky/works/science-research-project/backend-django

# 全量
.venv/bin/python -m pytest -q

# 四个新测试
.venv/bin/python -m pytest -q tests/test_activity_tenant.py tests/test_confsec_tenant.py \
    tests/test_funding_tenant.py tests/test_transform_tenant.py

# 探针（均为 /tmp 下的 Django TestCase，未入库）
PYTHONPATH=/tmp DJANGO_SETTINGS_MODULE=config.settings.test \
  .venv/bin/python -m django test e7probe.test_e7.E7Probe.test_probes -v 2
PYTHONPATH=/tmp DJANGO_SETTINGS_MODULE=config.settings.test \
  .venv/bin/python -m django test e7probe.test_e7b -v 1
PYTHONPATH=/tmp DJANGO_SETTINGS_MODULE=config.settings.test \
  .venv/bin/python -m django test e7probe.test_e7d -v 1
PYTHONPATH=/tmp DJANGO_SETTINGS_MODULE=config.settings.test \
  .venv/bin/python -m django test e7probe.test_e7e -v 1

# 回退验证（示例：funding）
git show 1b1b55f:./backend-django/apps/funding/api.py > /tmp/e7probe/bak/funding_api_old.py
cp /tmp/e7probe/bak/funding_api_old.py apps/funding/api.py
.venv/bin/python -m pytest -q tests/test_funding_tenant.py
cp /tmp/e7probe/bak/funding_api_new.py apps/funding/api.py   # 恢复
git status --porcelain apps/   # 应为空
```

探针文件：`/tmp/e7probe/test_e7.py`（C1/C2/C3 前半、C4、I1、公开通道）、`test_e7b.py`（policy 缺口、sec_log 覆盖）、`test_e7c.py`（同租户 transform 全链）、`test_e7d.py`（科目删除预言机）、`test_e7e.py`（报销跨租户实扣全链 + 同租户回归）。它们属于一次性验证脚本，未提交，请勿把它们当作回归测试使用——正式回归请落在 `backend-django/tests/` 下。
