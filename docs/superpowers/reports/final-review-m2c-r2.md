# M2-c 修复复审报告（r2）

- 复审范围：`9f087e9..b825029`（12 commits，15 files，+640/−68）；修复集中在 `b825029`
- 上轮报告：`docs/superpowers/reports/final-review-m2c.md`（基准 `2079f9c`，verdict REQUEST_CHANGES）
- 复审方式：只读源码 + 独立真实端点探针；**未修改任何源码、未提交 git**；唯一新增文件为本报告
- 复审日期：2026-11-19

## 0. 结论

**verdict：REQUEST_CHANGES**

**合并门槛：C-1 仍有两处收件人缺口（外部 PI 的机构副本、应价回执对象），且本轮新放的 I-4 复查口把 BLACKLIST 也一并复位成 CANDIDATE，黑名单专家可自助洗白；把这三处修掉（均为十行内改动）即可合并，其余只剩 Minor。**

修复方向整体是对的：四条外部主链路现在**真的会发邮件**，收件人在单租户正例下均正确；I-1 的四类不可用供应商被"空列表 + 403"硬拦；I-2 的登录角色裁剪在真实 `/auth/login` 上生效；I-5 的跨租户授角色 400 且整体回滚。与上轮 449 passed、C-1 四条零邮件、门户放行黑名单相比，`b825029` 是实质性推进，不是"改注释式修复"。

但按上轮报告自己写的验收口径（"测试必须断言 `mail.outbox` 至少 1 封、**收件人 email 正确、租户/机构正确**"，以及"外部 PI 同时给机构邮箱"），C-1 还不能算完全关闭；I-4 则引入了新的控制绕过。因此本轮不给 APPROVED。

---

## 1. 我亲自跑过的验证（命令与数字）

| # | 命令 / 探针 | 结果 |
|---|---|---|
| 1 | `cd backend-django && .venv/bin/python -m pytest -q` | **465 passed, 5 warnings in 18.02s**（首跑 18.73s；与声称的 465 一致） |
| 2 | `cd frontend && ./node_modules/.bin/vue-tsc --noEmit` | **exit 0，0 行输出** |
| 3 | `cd backend-django && .venv/bin/python manage.py makemigrations --check --dry-run` | **No changes detected，exit 0**；仅伴随 PG `127.0.0.1:5432 connection refused` 的 RuntimeWarning |
| 4 | 16 对 `design/*.openapi.yaml` ↔ `frontend/src/api/schema/*.openapi.yaml` 的 `filecmp` | **13 SAME / 3 DIFF**；DIFF 为 `04-科研成果管理-R`、`08-数据分析与决策-D`、`14-科研绩效评价-M`，三对在 `9f087e9` 基线即 DIFF；`09-采购与合同管理-G`、`15-专家与评审管理-N` 均 **SAME** |
| 5 | 临时 sqlite（`ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/m2c_seed.sqlite3`）`migrate` + `seed_demo` 连跑两次 | 第一次各域有增量（expert +6、user +1、users +4、partner +6 等）；**第二次仅输出 `seed_demo 完成（幂等）：`，全部 0**。查询 `expert_ext`：user id=6、`user_source=EXTERNAL`、`status=ACTIVE`、机构 `PTN-2026-000001`、角色 `['R-EXPERT']`，绑定 `NExpert id=1 status=ACTIVE` |
| 6 | 真红抽样：用 `git show b825029^:<file>` 临时覆盖源码后跑对应用例，再 `git checkout` 恢复 | 6 组全部**真红**（明细见 §2 I-6）；恢复后 `cmp` 校验 `restored=OK`，`git status backend-django/apps` 干净，全量重跑仍 **465 passed** |
| 7 | 探针：四条 C-1 链路 + 专家审核（真实 HTTP + `mail.outbox`） | invite/bid/quote/decide/audit 均 200 且各有邮件；收件人见 §2 C-1（3/4 正确，decide 缺机构副本，quote 只发采购发起人） |
| 8 | 探针：供应商门户准入五情形 | 合规供应商 list 200 含 bid、quote 200；blacklist / 过期 1 天 / `status=PENDING` / 机构 `PENDING` / 用户无 org 五类均 **list `[]` + quote 403** |
| 9 | 探针：院内 staff 授 R-EXPERT 后真实登录 | `/auth/login` 返回 roles **`['R-STAFF','R-EXPERT']`**，`GET /api/v1/project/mine` **200**；但 `GET /api/v1/apply/applications` **`[]`**、`POST /api/v1/apply/applications` **403 `外部账号未绑定机构，无法申报`** |
| 10 | 探针：专家信用档案 | `POST /reviews/{id}/scores` → **200**，`NExpert.review_count=1`、`last_review_at` 非空（同租户） |
| 11 | 探针：专家申请复查 | `SUSPENDED` 重申请 → **200** 且复用原档案（不新增行）；`CANDIDATE` → **409**；`BLACKLIST` → **200 且状态被复位 `CANDIDATE`**（问题，见 §3 N-1） |
| 12 | 探针：跨租户授角色 | 审核台把 `NExpert.user_id` 指向 tenant2 用户 → **400**，档案状态仍 `CANDIDATE`（回滚成立） |
| 13 | 探针：`notify_user` 跨租户调用 | `notify_user(1, <tenant2 用户 id>, ...)` 不抛错，落一条 `tenant_id=1 / user_id=<tenant2>` 的孤儿站内信，无邮件 |
| 14 | 探针：N 域列表/抽专家跨租户（上轮 E-1 复现） | tenant1 R-MANAGER 的 `GET /experts` 仍返回 tenant2 专家名，`GET /reviews` 仍返回 tenant2 任务标题，tenant1 任务 draw 仍能抽到 tenant2 的唯一 ACTIVE 专家 |
| 15 | 探针：`notify_user` 站内信失败兜底 | monkeypatch `notify_inapp` 抛 `RuntimeError` → `notify_user` 不抛，且邮件仍发出（`to=[['m2@example.com']]`） |

探针文件：`/tmp/m2cprobe/test_r2_probe.py`（10 例，只打印不断言），通过 `--ds=config.settings.test` + `pytest_plugins=["tests.conftest"]` 运行，未写入仓库。命令样例：

```bash
cd backend-django
.venv/bin/python -m pytest -q /tmp/m2cprobe/test_r2_probe.py --ds=config.settings.test -s
```

---

## 2. 上轮各条逐条复核

### 2.1 总表

| 上轮条目 | 本轮结论 | 一句话证据 |
|---|---|---|
| **C-1** 四条外部主链路缺邮件 | **部分关闭** | 四条都发信了，收件人 3/4 正确；缺"外部 PI → 机构邮箱副本"；应价回执发采购发起人而非供应商；测试不断言 `to` |
| **I-1** 门户放行黑名单/过期/未批机构 | **已关闭** | 五类不可用供应商全部 `[]`+403，合规供应商可用（实测） |
| **I-2** 院内 R-EXPERT 登录被剥光内部角色 | **已关闭**（角色层） | 真实登录 `['R-STAFF','R-EXPERT']`，内部端点 200；但 P 域仍按外部收口（新问题 N-4） |
| **I-3** `review_count/last_review_at` 无人更新 | **已关闭** | 打分后 count=1、时间非空；回退后用例真红（0≠1） |
| **I-4** SUSPENDED 后无法重申请 | **部分关闭** | SUSPENDED 200 复用档案；但 BLACKLIST 也被复位（N-1），且 `remark` 未清、`reject_reason` 是死赋值 |
| **I-5** 跨租户授角色 | **已关闭** | 跨租户审核 400 且事务回滚（档案仍 CANDIDATE） |
| **I-6** `IN_LIBRARY` 修复无回归测试钉住 | **已关闭** | 删掉 `status="IN_LIBRARY"` 后 `test_i1[kwargs2]` 真红 |
| **M-1** 历史 `bids_json` 缺 `totalAmount` 500 | **已关闭** | 缺字段列表 200；回退后 `KeyError: 'totalAmount'` 真红 |
| **M-2** `notify_user` 站内信不在 try | **已关闭** | `notify_inapp` 抛错时 `notify_user` 不抛且邮件照发 |
| **M-3** 前端/policy/seed 口径不一 | **部分关闭** | 路由已去 R-STAFF，但侧栏 `App.vue:216` 仍给 R-STAFF 显死链；mock 仍是 `W(['GET'])` 通配 |
| **M-8** seed 缺外部专家账号 | **已关闭** | 两遍幂等；`expert_ext` = EXTERNAL/机构 A/R-EXPERT 且已绑生效档案 |

---

### C-1 —— 部分关闭

**已实测通过的部分**（真实端点，`mail.outbox` 非空、收件人正确）：

| 链路 | 端点 | outbox 收件人 | 主题 |
|---|---|---|---|
| 专家邀请 | `POST /api/v1/reviews/{id}/invite`（R-MANAGER）→ 200 | `expert1@example.com`（被邀专家本人） | `[科研管理] 评审邀请` |
| 发标通知 | `POST /api/v1/procurement/bids` → 200 | `a3@example.com`、`b3@example.com`（供应商机构全部 ACTIVE 用户） | `[科研管理] 询价邀请` |
| 应价回执 | `POST /api/v1/portal/supplier/inquiries/{bid}:quote`（R-PARTNER）→ 200 | `buyer3@example.com`（**采购发起人**） | `[科研管理] 收到供应商报价` |
| 立项决议 | `POST /api/v1/apply/applications/{id}:decide` → 200 | `pi4@example.com`（PI） | `[科研管理] 申报评审结果已发布` |
| 专家审核（补充核对） | `POST /api/v1/expert-applications/{id}/audit` → 200 | `cand@example.com` | `[科研管理] 专家申请已通过` |

跨租户方面：发标只取 `tenant_id=bid.tenant_id` 的机构用户，tenant2 同机构用户 `c3` **未**收到，符合预期；专家邀请在正例下也只发给本租户专家。

**未关闭的三处：**

1. **外部 PI 的机构邮箱副本缺失**。计划书 `2026-11-19-m2c-expert-supplier-channel.md:561` 明确"`decide_application` 给 PI（**外部则同时给机构邮箱**）"，上轮 C-1 修复建议第 3 条也重申。实现（`apps/p/api.py:1022-1030`）只有一次 `_notify_user(d.tenant_id, a.pi_user_id, ...)`。实测外部 PI `pi4@example.com` 收到，机构联系人 `org4@example.com` **未**收到。
2. **应价回执对象与上轮建议相反**。上轮建议"给应价供应商机构联系人发'报价已收到'回执"；实现 `apps/procure/portal.py:145-153` 只通知 `b.creator_id`（采购发起人），供应商侧没有任何回执。新增用例名也写成 `test_c1_quote_receipt_notifies_purchaser`（`tests/test_m2c_review_fixes.py:95`），把偏差固化进了测试。
3. **测试没有钉收件人**。四个 C-1 用例只断言 `len(mail.outbox)` 与 `subject`（`tests/test_m2c_review_fixes.py:52-53、91-92、145-146、167`），没有一处 `mail.outbox[0].to == [...]`。把 `notify_user` 的 `user_id` 换成任意同租户用户，用例仍然全绿——这正是上轮要求"收件人 email 正确、租户/机构正确"的原因。本轮我靠独立探针才验证了收件人，测试本身钉不住。

---

### I-1 —— 已关闭

`apps/procure/api.py:803-823` 的 `_my_supplier` 现在要求：机构存在且 `status="APPROVED"`、`GS upplier.status="IN_LIBRARY"`、`blacklist=False`、`qualification_expire_date` 未过期。实测：

| 情形 | 列表 | 应价 |
|---|---|---|
| 合规（IN_LIBRARY/未黑/未过期/机构 APPROVED） | 200 `[bid]` | 200，报价落库 |
| `blacklist=True` | 200 `[]` | 403 |
| 资质过期 1 天 | 200 `[]` | 403 |
| 供应商 `status=PENDING` | 200 `[]` | 403 |
| 所属机构 `status=PENDING` | 200 `[]` | 403 |
| 用户无 `org_id` | 200 `[]` | 403 |

边界：`qualification_expire_date == today` 仍放行（判定是 `< today`）。资质"到期当天仍有效"是常见口径，可接受，不算缺陷。

---

### I-2 —— 已关闭（角色层），但 P 域语义未跟上（见 N-4）

- 院内 `user_source=INTERNAL` staff（id=2）授 R-EXPERT、R-MANAGER audit 通过后，真实 `POST /auth/login` 返回 JWT `roles=['R-STAFF','R-EXPERT']`；`GET /api/v1/project/mine` **200**。说明 `core/org_scope.py:27-44` 的规则 3（院内专家保留）和 `core/auth/api.py:58-65` 的调用点生效。
- 外部账号持 `R-PARTNER + R-STAFF` 真实登录后仍被剥成仅外部集，`GET /project/mine` **403**，规则 1 生效。
- 规则 2（EXTERNAL + 仅 R-EXPERT）由 `test_i2_external_account_still_stripped` 覆盖。

上轮 I-2 的具体验收句"院内 staff 授予 R-EXPERT 后真实登录仍持 R-STAFF+R-EXPERT 且能访问内部端点"已经满足，故记已关闭。但同一个院内专家在 P 域仍被当外部（N-4），这是本轮修复**暴露出的语义不一致**，不是 I-2 未修。

---

### I-3 —— 已关闭

`apps/expertreview/api.py:395` 在 `submit_score` 后调用 `_refresh_expert_stats(expert.id, t.tenant_id)`；`:404-415` 用 `NReviewScore.objects.filter(expert_id, tenant_id)` 取 count 与 `order_by("-submitted_at","-id").first()` 更新 `NExpert.review_count/last_review_at`。`NReviewScore.submitted_at` 字段存在（`apps/expertreview/models.py:125`），不是假字段。

实测：属性专家 ACTIVE、任务 STARTED，POST 打分 → 200，随后 `NExpert.review_count=1`、`last_review_at` 非空。回退 `apps/expertreview/api.py` 到 `b825029^` 后 `test_i3` 真红（`0 != 1`）。

小注：统计只按 `tenant_id` 聚合，专家档案本身也是租户内对象，口径自洽；跨租户评分不会混算。

---

### I-4 —— 部分关闭（新问题 N-1）

`apps/expertreview/portal.py:73` 只把 `CANDIDATE/ACTIVE` 挡成 409，其余状态一律走 `:83` 的 `existing.status = "CANDIDATE"` 并复用档案。实测：

- `SUSPENDED`（被驳回）→ 200，档案不新增，状态回 CANDIDATE，符合修复目标。
- `CANDIDATE` → 409，符合"待审不可重复提交"。
- **`BLACKLIST`（remark="学术不端"）→ 200，状态被复位 CANDIDATE**。这不是"复查"，是把惩罚状态直接抹掉；且 `:91` 的 `existing.reject_reason = None` 是**死赋值**——`NExpert` 没有 `reject_reason` 字段（`apps/expertreview/models.py:21` 只有 `remark`），该行只在实例上挂了个临时属性，`remark` 里的"学术不端"原样保留。

覆盖面：新测试只测了 SUSPENDED 与 CANDIDATE 两种（`tests/test_m2c_review_fixes.py:313、330`），BLACKLIST 没有被钉住，所以这个越界没有被 CI 发现。

---

### I-5 —— 已关闭

`apps/expertreview/portal.py:202-221` 的 `_grant_expert_role` 先 `SysUser.objects.filter(id=user_id, tenant_id=tenant_id, deleted=0).first()`，不存在即 `ApiError(400)`；调用点在 `audit_expert_application` 的 `@transaction.atomic` 内（`:179`），异常使 `e.status/remark` 整体回滚。

实测：把 tenant2 用户的 id 写进 tenant1 的 CANDIDATE 档案 `user_id`，audit APPROVE → **400**；随后查档案仍 `CANDIDATE`、无 `SysUserRole` 新增。`create_expert` 管理端不调用 `_grant_expert_role`，不存在第二条绕过路径（全仓仅 `:179` 一个调用点）。

---

### I-6 —— 已关闭

本轮新增 `tests/test_m2c_review_fixes.py`（16 例）确实钉住了多数缺陷。抽样真红（临时回退源码，跑完恢复）：

| 回退对象 | 用例 | 结果 |
|---|---|---|
| `apps/expertreview/portal.py` → `b825029^` | `test_i5_audit_rejects_cross_tenant_user_binding` | **1 failed**（200 ≠ 400） |
| `apps/procure/api.py` → `b825029^` | `test_i1_portal_admission_rejects_unusable_supplier` | **3 failed, 1 passed**（blacklist/过期/机构 PENDING 红；`status=PENDING` 因 `2079f9c` 已有过滤仍绿） |
| `apps/procure/portal.py` → `b825029^` | `test_m1_inquiry_list_tolerates_legacy_bid_entries` | **1 failed**（`KeyError: 'totalAmount'`，500） |
| `apps/expertreview/api.py` → `b825029^` | `test_i3_expert_stats_refreshed_after_scoring` | **1 failed**（`review_count 0 != 1`） |
| `apps/p/api.py` → `b825029^` | `test_c1_decide_application_notifies_pi_by_email` | **1 failed**（`mail.outbox` 空） |
| 仅删 `apps/procure/api.py:816` 的 `status="IN_LIBRARY",` | `test_i1[kwargs2]` | **1 failed** → 证明 I-6 的 status 过滤确被回归测试钉住 |

恢复方式：`git show b825029^:<file> > <file>`，跑完 `git checkout -- <file>`；每轮 `cmp` 校验恢复内容与 `b825029` 一致（`restored=OK`），`git status backend-django/apps` 干净，最后全量 **465 passed**。

不足（不改变 I-6 结论、但降低回归网强度）：C-1 不收件人（见上）；I-4 缺 BLACKLIST 负例；`notify_user` 跨租户无负例；`test_c1_bid_invite` 允许 `>=1`，无法发现"多发了别的机构"。

---

### M-1 —— 已关闭

`apps/procure/portal.py:91`（列表装配处）改为 `my_amount = mine[-1].get("totalAmount") if mine else None`；`:133-153` 的应价路径同样走 `.get`。实测历史脏数据 `bids_json=[{"supplierId": s.id}]`：`GET /portal/supplier/inquiries` → **200**，`myAmount` 为 `null`；回退后同一请求 **500 `KeyError: 'totalAmount'`**，`test_m1` 真红。

---

### M-2 —— 已关闭

`apps/notify/email.py:76-119` 的 `notify_user` 现在把 `notify_inapp` 包进 try（`:100-108`），异常只 `logger.warning`；邮件发送在 try 之外单独尽力而为。实测 monkeypatch `notify_inapp` 抛 `RuntimeError`：`notify_user` **不抛**，调用方业务不中断，且邮件仍发出（`to=[['m2@example.com']]`）。修复语义正确——站内信失败不应吞掉邮件。

---

### M-3 —— 部分关闭

- `frontend/src/router/index.ts:60`：`portal-expert-apply` 的 `roles` 已去掉 `R-STAFF`，只剩 `['R-PARTNER','R-EXPERT']`，与 `config/casbin/policy.csv:910-917` 的两条 `POST /api/v1/portal/expert-apply` 对齐。
- **`frontend/src/App.vue:216` 侧栏菜单仍是 `roles: ['R-PARTNER','R-EXPERT','R-STAFF']`**：院内 R-STAFF 会在侧栏看到"专家申请"入口，点进去被路由守卫拦下（死链）。这正是上轮 M-3 指出的"前端口径不一致"，只修了路由、没修菜单。
- `frontend/src/api/mock/overrides/auth.ts:31-121`：M2-c 相关的四条（R-EXPERT 的 `portal/expert-apply`、`portal/expert/credit|reviews|activities`，R-LEADER 的 `experts/*/credit`，R-MANAGER 的 `portal/supplier/inquiries`）确实按 policy 补上了；但整套 mock 仍以 `...W(['GET'])` 之类的通配为主（如 R-STAFF/R-EXPERT 的 GET 全通），并不是"逐行对齐"。mock 只服务演示，属 Minor，不构成真实越权。

---

### M-8 —— 已关闭

`seed_demo.py:1193-1214` 创建 `expert_ext`（EXTERNAL）并授予 R-EXPERT，把已生效专家档案 `e_demo.user_id` 指过去；`put()` 用 `get_or_create`（`:235-240`），重复执行不新增。

实测临时 sqlite 连跑两遍：第一遍有增量，第二遍全 0；库内 `expert_ext` = user id=6、`user_source=EXTERNAL`、`status=ACTIVE`、机构 `PTN-2026-000001`、角色 `['R-EXPERT']`，绑定的 `NExpert id=1` 为 `ACTIVE`。M-8 的验收点（外部专家账号存在、角色正确、绑到生效档案、seed 幂等）全部满足。

小注：该绑定档案 `code=None`（种子既有数据形态），不影响 M-8；若前端把 `code` 当非空渲染，会在演示里显示空编号，属既有 seed 数据问题。

---

## 3. 新发现的问题

本轮修复**未引入新的 Critical**。以下 Important 若不修，我不建议合并。

### Important

#### N-1 黑名单专家可自助洗白（I-4 复位口过宽）

- 文件：`backend-django/apps/expertreview/portal.py:73-96`
- 证据：`NExpert(status="BLACKLIST", remark="学术不端")` 本人 `POST /api/v1/portal/expert-apply` → **200**，重新查库 `status="CANDIDATE"`，`remark` 仍是"学术不端"。
- 影响：`BLACKLIST` 是对学术不端等行为的惩罚状态，与"被驳回待补充材料"（`SUSPENDED`）不是一回事。当前实现让任何被拉黑的专家都能用一次自助申请把状态复位，随后审核台一次 APPROVE 即可恢复 R-EXPERT，惩罚链路形同虚设。上轮 I-4 的原话是"`SUSPENDED/REJECTED` 复查"，不包含 BLACKLIST。
- 附带：`:91` 的 `existing.reject_reason = None` 是死代码（模型无此字段），真正该清的 `remark` 没清；应改为 `existing.remark = None`（或在 `CANDIDATE` 状态隐藏历史理由时明确保留策略）。
- 建议：复位条件收窄为 `existing.status in ("SUSPENDED",)`（模型没有 REJECTED，驳回即 SUSPENDED）；BLACKLIST 仍返回 409 并给"请走申诉/管理员解除"的提示；补一条 BLACKLIST 负例。

#### N-2 外部 PI 的机构邮箱副本仍未发（C-1 残留）

- 文件：`backend-django/apps/p/api.py:1022-1030`
- 证据：外部 PI `pi4@example.com` 收到决议邮件；机构联系人 `org4@example.com`（`SysPartnerOrg.contact_email`）**0 封**。
- 影响：计划书 `:561` 与上轮修复清单第 3 条都要求"外部则同时给机构邮箱"。外部 PI 若个人邮箱失效/离职，机构侧完全不知情，C5 的"外部用户能收到邮件"只覆盖了个人。
- 建议：`decide_application` 里在 `is_external_only(d)`/PI 为 EXTERNAL 且 `current_org_id` 非空时，再对 `SysPartnerOrg.contact_email` 调一次 `send_mail_best_effort`（不要重复写站内信）；补测试断言两封 `to`。

#### N-3 应价回执发给了采购发起人，供应商侧无回执（C-1 残留）

- 文件：`backend-django/apps/procure/portal.py:145-153`
- 证据：`POST /portal/supplier/inquiries/{bid}:quote` → 200，outbox 唯一收件人是 `buyer3@example.com`（`b.creator_id`），供应商机构用户 0 封。
- 影响：上轮修复建议第 4 条要求"给应价供应商机构联系人发'报价已收到'回执"。现在供应商提交报价后没有任何确认（页面之外无凭证），而采购方反而多一封。若产品上确实只想通知采购方，应在计划/报告里明确改口径，不能默默把上轮要求替换掉——新增用例名 `test_c1_quote_receipt_notifies_purchaser` 就是把偏差写死了。
- 建议：保留采购方通知的同时，对 `s.org_id` 下的 ACTIVE 用户补一封"报价已收到"；或由上轮评审人确认降级为 Minor 并改计划书。

#### N-4 院内专家在 P 域仍被当外部，申报入口被锁死（I-2 语义残留）

- 文件：`backend-django/core/org_scope.py:11、23、59-70`；消费点 `backend-django/apps/p/api.py:261-266、289-294`
- 证据：院内 staff（INTERNAL）授 R-EXPERT 后真实登录 roles=`['R-STAFF','R-EXPERT']`，`/project/mine` 200；但 `GET /apply/applications` 返回 `[]`（按 `current_org_id=None` 空集短路），`POST /apply/applications` 403"外部账号未绑定机构，无法申报"。
- 根因：`is_external_only` 的实现是 `has_external_role(roles)`，而 `EXTERNAL_ROLES=("R-PARTNER","R-EXPERT")`；它的 docstring 却写"**只要持有 R-PARTNER** 即按外部口径"，与 `normalize_roles_for_account` 规则 3"院内专家保留"直接矛盾。I-2 修复把"院内 R-EXPERT"确立为合法形态，但没有同步 `is_external_only`。
- 影响：院内科研人员兼任评审专家是常见形态；现在这类账号能看到内部项目，却不能申报/查看自己的申报。不是提权（更严），但是功能回归面，且与计划书的角色规则不一致。
- 建议二选一，并写进计划：(a) `is_external_only` 改为"`R-PARTNER` 恒外部；`R-EXPERT` 仅当账号 `user_source=EXTERNAL` 时外部"（需把 `d.user_source` 带进 Domain，或查 `SysUser`）；(b) 明确"院内账号不得持 R-EXPERT"，在 `normalize_roles_for_account` 里把院内 R-EXPERT 也剥掉，并同步 `_grant_expert_role` 的校验。无论哪种，都补一条"院内 R-EXPERT 走 P 域"的测试。

### 既有遗留（上轮 E-1，本轮复现，按上轮口径不计门槛）

#### N-5 N 域列表/抽专家跨租户 + 邀请通知静默丢失

- 文件：`backend-django/apps/expertreview/api.py:92-104`（`list_experts` 无 tenant）、`:225-235`（`list_reviews` 无 tenant）、`:273`（draw 池无 tenant）、`:318`（邀请取专家无 tenant）
- 证据：tenant1 R-MANAGER `GET /experts` 返回 tenant2 专家名；`GET /reviews` 返回 tenant2 任务标题；tenant1 任务 draw 返回 tenant2 专家 id。`git blame` 确认：`list_experts`/`list_reviews`/draw 池三处均为基线 `6e8c32e`（`9f087e9` 的祖先）；`:318` 是 `b825029` 新 helper 里的取数，沿用了同一段旧代码的无 tenant 写法（旧 `:302` 即如此）。`ad6960d` 的"按租户收口"只给 `draw_experts` 补了 `_get_task_or_404(tenant, id)`，没有补池子与列表。
- 与 C-1 的交互（本轮新观察）：`b825029` 的 `_notify_invitees` 用 `NExpert.objects.filter(id=iv.expert_id, deleted=0)`（无 tenant）取专家，再以 `t.tenant_id` 调 `notify_user`。当被抽中的是 tenant2 专家时：邮件查 `SysUser(id, tenant_id=t.tenant_id)` 落空 → **不发邮件**；站内信却以 `tenant_id=1 + tenant2 用户 id` 落库（孤儿信）。即"跨租户抽专家"场景下 C-1 的"每位被邀专家都收到邮件"仍不成立，且没有任何告警。
- 上轮已把 E-1 列为"既有 Critical、不计本期门槛"，故不作为本轮 verdict 依据；但 M2-c 若对外上线，建议与 E-2/E-3/E-4 一起先修 list/draw 的 tenant 过滤，并在 `_notify_invitees` 取专家时补 `tenant_id=t.tenant_id`（顺带把静默丢失变成可见告警）。

### Minor

| # | 位置 | 问题 |
|---|---|---|
| m-1 | `backend-django/apps/notify/email.py:96-99` | `row is None` 且用户"全局存在"就继续写站内信；跨租户调用会落一条 `tenant_id=A / user_id=B 租户用户` 的孤儿信。读路径按 tenant+user 过滤，不会泄给该用户，但污染 A 租户通知表。建议改为"同租户不存在直接 return None"，与发邮件的判定一致。 |
| m-2 | `backend-django/apps/expertreview/api.py:318` | `_notify_invitees` 取专家无 tenant（同 N-5）；即使不修列表，也应在此补租户过滤，避免孤儿信。 |
| m-3 | `backend-django/tests/test_m2c_review_fixes.py:52、91、145、167` | C-1 四例都不校验 `to`，无法发现"发错人/多发别机构"。建议至少各加一条 `to == [...]`，并对 bid 用例断言 `c3@example.com not in recipients`。 |
| m-4 | `frontend/src/App.vue:216` | 侧栏 `portal-expert-apply` 仍带 `R-STAFF`，与 `router/index.ts:60` 不一致（死链）。 |
| m-5 | `frontend/src/api/mock/overrides/auth.ts:31-121` | `W(['GET'])` 等通配使 mock 权限比 policy 宽，"逐行对齐"的说法过头；仅演示模式，建议注释标明"演示口径，非 policy 镜像"。 |
| m-6 | `backend-django/apps/notify/email.py:76-84` | 签名与计划 `:522-572` 不一致：没有 `channel` 形参，返回值是 `SysNotification`/`None` 而非 `int`。当前无调用方依赖返回值/传 channel，属契约漂移；建议要么补 `channel="BOTH"` 关键字（当前固定 BOTH），要么改计划书。 |
| m-7 | `backend-django/apps/procure/api.py:343`、`apps/procure/portal.py:149` | 发标/应价通知用 `typ="TODO"`（`SysNotification.typ` 的默认值），语义上应是 `PROCURE`/`QUOTE`；前端按 typ 过滤时会落到"其他"。不影响投递。 |
| m-8 | `backend-django/apps/procure/api.py:328-345` | 发标只找 `SysUser`（机构下的账号）邮箱；若机构只有 `SysPartnerOrg.contact_email`、没有账号，则 0 封邮件。建议 `uids` 为空时兜底 `contact_email`。 |
| m-9 | `backend-django/tests/test_m2c_review_fixes.py:313-345` | I-4 只覆盖 SUSPENDED/CANDIDATE，缺 BLACKLIST 负例，正是 N-1 未被发现的原因。 |
| m-10 | `backend-django/apps/expertreview/portal.py:91` | `existing.reject_reason = None` 死赋值（模型无该字段），应改 `remark`；见 N-1。 |

---

## 4. 契约与 policy

- 本轮没有新增/改路径端点：`_notify_invitees`、`_notify_bid_invite`、`_notify_quote`、`_notify_user` 都挂在既有端点上，请求/响应 schema 不变，**不需要补契约**。`09-采购与合同管理-G`、`15-专家与评审管理-N` 双份 `cmp` 均 SAME。
- `config/casbin/policy.csv:910-919` 已含本轮所需的 `POST /api/v1/portal/expert-apply`（R-PARTNER、R-EXPERT）与 `GET /portal/expert/{credit,reviews,activities}`（R-EXPERT），没有遗漏；同时 **没有**给 R-STAFF 授 `portal/expert-apply`，所以 `App.vue:216` 的菜单项是纯前端残留，不是 policy 缺口。
- mock `auth.ts` 的 M2-c 四条已补；整体通配属演示偏差（m-5）。
- 建议在计划书侧补一句 `_notify_quote` 的收件人口径（采购方回执 vs 供应商回执），避免下一轮再对不上（N-3）。

---

## 5. 合并门槛与修复顺序

1. **I-4 收窄**（N-1）：`apply_expert` 只允许 `SUSPENDED` 复位；BLACKLIST 返回 409；清 `remark` 用真实字段；补 BLACKLIST 负例。约 5 行 + 1 例。
2. **C-1 补两封**（N-2/N-3）：外部 PI 决议补机构 `contact_email`；应价回执补供应商机构用户。各约 8 行 + 断言 `to` 的用例。
3. **I-2 语义对齐**（N-4）：`is_external_only` 区分"R-PARTNER 恒外部 / R-EXPERT 看 `user_source`"，或明确取消院内 R-EXPERT 合法形态（二选一，写进计划）；补一条院内 R-EXPERT 走 `/apply` 的测试。
4. 顺手清 Minor：`App.vue:216` 去 R-STAFF、`notify_user` 跨租户早退、C-1 用例断言 `to`。

以上 1–3 做完即可给 **APPROVED**；只做 1、2 而把 N-4 作为已知限制写进计划，也可接受为 **APPROVED_WITH_MINOR**（需计划书明确"院内 R-EXPERT 在 P 域按外部处理"）。当前状态三项都在，故 **REQUEST_CHANGES**。

---

## 6. 附：探针与恢复说明

- 探针文件 `/tmp/m2cprobe/test_r2_probe.py`：10 个用例，覆盖 C-1 五链路、I-1 五情形、I-2 登录/端点、I-3、I-4、I-5、notify_user 跨租户、M-2 兜底、N 域跨租户复现；只 `print` 不断言，结果见 `/tmp/probe_out2.txt`。
- 运行方式：`cd backend-django && .venv/bin/python -m pytest -q /tmp/m2cprobe/test_r2_probe.py --ds=config.settings.test -s`；`pytest_plugins=["tests.conftest"]` 复用 `seed_auth`/`bearer`/locmem email。
- 真红实验的源码回退全部用 `git show b825029^:<file>` 写入同名文件，跑完 `git checkout -- <file>`；每轮 `cmp <file> <(git show b825029:<file>)` 均 `restored=OK`；`git status backend-django/apps` 干净。全量重跑 **465 passed**。
- seed 实验用独立 sqlite 文件 `/tmp/m2c_seed.sqlite3`，不触碰开发库；`migrate` 后连跑两次 `seed_demo`。
- 本报告未修改任何源码、未 `git add`/`commit`；仓库中与本复审无关的 docs 删除/未跟踪文件保持原状。
