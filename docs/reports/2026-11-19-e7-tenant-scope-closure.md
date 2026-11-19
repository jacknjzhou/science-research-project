# E-7 跨域租户边界收口：闭环报告

- 期次：E-7（安全收口系列第 7 项，M2 之后横切安全债）
- 基线：`1b1b55f`（E-8 部署凭据收口）
- 终态：`385914a`（已推送 `origin/develop`）
- 周期：2026-11-19
- 规模：11 commits / 22 文件 / +1536 −211
- 测试：555 → **611 passed**（新增 56 例，其中 32 例集中在越权回归文件）

---

## 1. 为什么做这一期

横向检查发现：18 个业务域里大量写接口用 `Model.objects.filter(id=<路径参数>)` 取出对象后直接落库，**不带 `tenant_id` 条件**。系统虽然在这类表上都有 `tenant_id` 列（PG 行级隔离是应用层实现，没有 RLS），但只要攻击者知道资源 id，就能用本租户账号读写他租户数据。

典型攻击面（均已实测复现过）：

- 用 tenant-1 的 R-FINANCE 调 `POST /expenses/{id}/approval`，可把他租户项目的预算行 `frozen → used` 实扣；
- 用 tenant-1 的 R-ETHICS 调 `POST /ethics/amendment/{id}/decision`，可把他租户的修正案从 `SUBMITTED` 推到 `APPROVED`；
- 用 tenant-1 的 R-MANAGER 建一条评审任务指向 tenant-2 的成果，再 conclude，可把他租户成果从 `CLAIMED` 改成 `ASSIGNED_TO_PROJECT`（成果认领状态被污染）；
- 匿名访问公示接口可拿到异议人真实姓名与手机号。

用户指示「按域依次处理」，因此分四个业务域推进（activity → confsec → funding → transform），每一域独立提交、独立测试。

---

## 2. 提交清单

| commit | 内容 |
|---|---|
| `e2d297a` | activity：活动与参与人按租户收口 |
| `91830e1` | confsec：授权/输出审批/降密按租户收口 |
| `d317245` | funding：预算/报销/拨款按租户收口 |
| `a17db11` | transform：披露/交易/合同/到账按租户收口 |
| `bd55718` | 终审 r1 修复：预算行/公示异议/企业档案收租户、confsec 审计租户、间接费试算补策略 |
| `9fe262b` | 终审 r2：预算行零行命中即阻断、公示 PII 脱敏、异议状态守卫、悬空策略清理（迁移 0019） |
| `2a9248b` | 创建类接口拒他租户项目/法人/预算/成果引用（foreign-only 口径） |
| `57ac05f` | 补扫 ethics/project/output 裸查、引用校验含软删、公示自由文本脱敏、迁移只清已知下线授权 |
| `d98b305` | 修正案/纪检档案/人遗备案/团队/访客/人员/资产/成果写入收租户（r4 C-1..C-7） |
| `36cca20` | 访客审批收租户 + N 域评审回写链收租户（r5 C-1/C-2） |
| `385914a` | 补 MID_CHECK/FINAL_ACCEPT 越权回归 + 文案澄清（r6 Minor） |

---

## 3. 六轮独立终审：发现 → 修法

每轮都是独立 subagent、干净导出树、只读、自带攻击探针；结论写 `docs/superpowers/reports/final-review-e7-r*.md`。

| 轮 | verdict | 关键发现 | 修法 |
|---|---|---|---|
| r1 | REQUEST_CHANGES | 报销/外拨/借款跨租户**实扣资金**；公示异议可跨租户终止交易；企业档案、confsec 审计、间接费 policy 缺失 | `bd55718` |
| r2 | APPROVED_WITH_MINOR | 存量脏单（预算行已被软删/换租户）审批时静默成功；公开公示泄露 PII；异议无状态守卫；策略只看 CSV 不看 DB | `9fe262b`：`_update_budget_line_or_409()` 零行命中 409 回滚；`to_api_publicity_public()` 掩码；`submit_objection` 状态守卫；迁移 0019 |
| r3 | APPROVED_WITH_MINOR | 三个存量 Critical：ethics 案卷、project 任务、output 认领；软删绕过；`handle_result` 原样公开；0019 广谱 purge 会误删自定义授权 | `57ac05f`：`_get_case_or_404(request, ...)`、`_get_project_or_404(request, ...)`、认领加租户、`_reject_foreign_ref` 去 `deleted=0`、`handle_result` 置 None、0019 改为只删已知下线规则 |
| r4 | REQUEST_CHANGES | 「声称闭环未闭环」：ethics 修正案、project 分类仍裸查；output/staff/asset helper 家族未收口；团队/访客整族未收口 | `d98b305`：7 个 helper 收租户 + 凭证回调加租户 + 7 条回归 |
| r5 | REQUEST_CHANGES | 访客审批漏接（`_get_visitor_or_404` 写好却零调用）；**N 域评审回写链**：`create_review.target_id` → `conclude_output_eval` 裸 id 直写，可污染他租户成果 | `36cca20`：`approve_visitor` 收租户；`_assert_target_owned()` 在 create/invite/conclude 三处；四个单一写者加可选 `tenant_id` 双层拦截 |
| r6 | APPROVED_WITH_MINOR | 两条 Critical 均真闭环（9 条探针 404、本租户 6 条 200）；剩余 3 条 Minor | `385914a`：补 MID_CHECK/FINAL_ACCEPT 用例外 + 文案澄清 |

**r4/r5 的经验**：终审说「闭环」要按**资源级**核，不能按「改了几行」核。r4 点名的 handler 改了，但同一域里同构的 helper 没改，于是 r5 又扫出一条完整写链。

---

## 4. 验证证据

```
$ .venv/bin/python -m pytest -q
611 passed, 19 warnings in 43.63s

$ .venv/bin/python manage.py makemigrations --check --dry-run
No changes detected

$ git diff 1b1b55f..385914a -- design/ frontend/src/api/schema/ | wc -c
0
```

- README 第 5/29/99 行：611 / 611 / 611
- 新增/改写回归用例 56 例，其中 **32 例**在 `tests/test_e7_review_fixes.py`（每条都做过「回滚实现 → 必须红」验证，例如 r5 的 2 条在 `d98b305` 上 2 failed，r4 的 7 条在 `57ac05f` 上 7 failed）
- 四个域各自的租户回归：activity 4、confsec 5、funding 10、transform 5

### 设计取舍（记录在案）

1. **创建类接口用 foreign-only 口径**：`_reject_foreign_ref()` 只在「对象存在且属他租户」时 404，对象不存在则放行。理由：严格 `.exists()` 会让 29 条既有用例红（测试大量使用 `project_id=11` 这类未建档 id，表上无 FK 约束）；真正的越权面是「能指向别人的对象」。r3 复审判定该取舍可接受，但要求堵软删绕过——已去掉 `deleted=0`。
2. **单一写者保留无租户旧签名**：`conclude_output_eval(output_id, passed, tenant_id=None)` 等加**可选**参数，N 域入口必传、内部/测试调用不传仍按旧语义。这样既不破 55 条既有调用，又让 HTTP 攻击面全部收口。
3. **迁移 0019 不做广谱 purge**：`sync_permissions_from_csv` 只增不删，旧库会残留已下线端点的授权行；但全表清理会误删运行期在管理界面自定义的授权，所以只删 `GET /api/v1/disclosure/*` 这一条已知下线规则。

---

## 5. 生产上线检查单

E-7 范围内已无可达的跨租户写。上线前请确认：

- [x] `385914a` 已合入 `develop` 并部署到目标环境
- [x] 迁移 `0018_resync_permissions_e7`、`0019_purge_stale_policy_e7` 已执行（Casbin 运行时权威是 **DB**，只改 `policy.csv` 不生效）
- [x] 环境变量 `ARK_JWT_SECRET` ≥ 32 位且非内置默认；`ARK_DEV_LOGIN` 未开启（E-8 守卫）
- [ ] **archive 域处置口径书面确认**：`apps/archive/api.py` 整域仍是裸 id（见第 6 节）。若本期对多租户开放档案写接口，必须先做 E-7b 或加补偿控制（网关层限定单租户部署 / 关闭该域写接口）
- [ ] 存量脏单数据质量扫描：`project_id` / `legal_entity_id` 等引用 id 是否指向已不存在或跨租户的行（建议出一份孤儿引用报表）

---

## 6. 未收口与后续

**本期已知欠账（唯一）**：`apps/archive/api.py` 整域裸 id——`delete_document`、`update_archive`、`delete_archive`、`fill_item`、`delete_item`、`_set_borrow_status`，另 3 个读列表（`list_borrows`、`search_documents`、条目列表）。r3 起登记为存量，本期 0 文件变更。判据与 E-7 同构，5 个写 handler + 3 个读列表，预计 1 期可收（E-7b）。

**建议排序**：

1. **E-7b archive 收口**（安全债，阻塞「archive 多租户开放」）
2. M3 / 横向技术债：E-6 契约漂移（04-R / 08-D / 14-M）、`to_api_income` snake_case、幂等竞窗 DB 约束、`/indirect-fees/calculate` 遗留、M6 死代码 `apps/transform/api.py:302-305`
3. 剩余 Minor 观测项：`_assert_target_owned` 与 `_reject_foreign_ref` 的「不存在放行」语义，可在数据质量扫描落地后收紧为强校验

---

## 7. 复审报告索引

| 报告 | 行数 | verdict |
|---|---|---|
| `docs/superpowers/reports/final-review-e7.md` | 382 | REQUEST_CHANGES |
| `docs/superpowers/reports/final-review-e7-r2.md` | 333 | APPROVED_WITH_MINOR |
| `docs/superpowers/reports/final-review-e7-r3.md` | 448 | APPROVED_WITH_MINOR |
| `docs/superpowers/reports/final-review-e7-r4.md` | 519 | REQUEST_CHANGES |
| `docs/superpowers/reports/final-review-e7-r5.md` | 385 | REQUEST_CHANGES |
| `docs/superpowers/reports/final-review-e7-r6.md` | 227 | APPROVED_WITH_MINOR |
