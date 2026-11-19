# 独立终审 r3（最终）：安全收口（E-1 ~ E-5 + C-1/C-2/C-3）

- 仓库：`/Users/jacky/works/science-research-project`（分支 `develop`）
- 范围：`b908490..977de6d`，10 个 commit，`14 files changed, 750 insertions(+), 45 deletions(-)`
- 计划：`docs/superpowers/plans/2026-11-19-security-hardening.md`
- 账本：`.superpowers/sdd/2026-11-19-security-hardening/progress.md`
- diff 包：`/tmp/review-security-hardening-r3.diff`
- 审查方式：全量 diff 逐行 + HEAD 源码核对 + 独立行为探针（临时 worktree，不改工作区）+ 旧码红证
- 本报告是本次唯一写入的文件；未 commit / 未 stash / 未切换分支；探针 worktree 已清理

---

## 0. 结论

**APPROVED_WITH_MINOR —— 可合并推送（merge-ready）。**

r1 的 C-1/C-2、r2 的 C-3 出口守卫与测试空转、prod 配置，均已在 HEAD 落地并由我独立复现：

- **C-3 关闭**：`payment_callback` 与 `award_bid` 废标分支在预算写入前校验 `r.tenant_id == dom.tenant_id`，脏行 → **409/40901**，受害租户 `FBudgetLine.amount_frozen/amount_used`、`GRequisition.frozen_amount`、`payment.status` 全不变；同租户正常路径仍 **200** 并正确实扣。
- **C-3 的可运维性**：新增只读命令 `audit_cross_tenant_refs`，空库 exit 0，构造 1 条脏行后精确报出并 exit 1。
- **asset 测试不再空转**：改用真实路由 `/api/v1/asset/from-receipt` + `R-MANAGER`；旧码（c924247）上该测试 **200 != 404** 真红，正向对照通过。
- **prod 配置债关闭**：`config/settings/prod.py` + compose `DJANGO_SETTINGS_MODULE`，`DEBUG=False`，后门双门皆关；`manage.py check` 无问题。
- **回归**：`pytest -q` → **497 passed**；迁移 **No changes**；`design/` 与 `frontend/src/api/schema/` diff **为空**；README 三处 **497**。

遗留项均**不属于本期 5 条债**，且为基线已存在或域外：

- **E-7**：全仓 93 处 body-id 裸查（activity/confsec/funding/transform 等），已登记待排期，本期不阻断。
- **E-8（部署凭据债）**：`Dockerfile` 生产 CMD 恒跑 `seed_demo`（固定 `admin/Admin@123456`）、compose 默认 `ARK_JWT_SECRET` 为公开开发密钥、`ARK_API_DOCS=1`。这是**真实部署的硬门槛**，但不是本期引入，也不属于 5 条债；**代码可合并，上真实网络前必须先处理 E-8**。

---

## 1. r3 验收矩阵（对照 lead 四条）

| # | 项 | 结论 | 关键证据 |
|---|---|---|---|
| 1 | `payment_callback` 脏行守卫 | **通过** | `apps/procure/api.py:790` 在预算写前 409；探针脏付款 409 且受害预算/付款全不变；本租户 200 正常实扣 |
| 2 | `award_bid` 废标脏行守卫 + 预算行兜底 tenant | **通过** | `apps/procure/api.py:386` 409；`FBudgetLine` 兜底查询带 `tenant_id=r.tenant_id`；探针脏废标 409、本租户 200 |
| 3 | `audit_cross_tenant_refs` 只读命令 | **通过** | 空库 0 条、exit 0；造 1 条脏行后精确报出、exit 1；`--verbose` 可用 |
| 4 | asset 空转测试修复 | **通过** | `tests/test_security_hardening.py:360` 真实路由 + R-MANAGER + `converted_asset is False`；旧码 200 != 404；`:374` 正向 200 且转固 |
| 5 | prod settings + compose | **通过** | `config/settings/prod.py`、`docker-compose.yml:20`；prod 下 `DEBUG=False`；`manage.py check` 无问题；compose 未设 `ARK_DEV_LOGIN` |
| 6 | E-7 留档 | **按约定留档** | 93 处未修；ledger 已列 activity/confsec/funding/transform 具体 file:line |

---

## 2. 实测数字（HEAD = 977de6d）

| 项 | 命令 | 实测 |
|---|---|---|
| 全量测试 | `cd backend-django && .venv/bin/python -m pytest -q` | **497 passed, 5 warnings in 19.75s** |
| 迁移一致性 | `.venv/bin/python manage.py makemigrations --check --dry-run` | 仅 PG 5432 `RuntimeWarning`，末行 **`No changes detected`**，exit 0 |
| 契约 diff | `git diff --stat b908490..HEAD -- design/ frontend/src/api/schema/` | **空**（0 行） |
| README 计数 | `README.md:5` / `:29` / `:73` | 均为 **497**，与实测一致 |
| 提交纪律 | `git log --oneline b908490..HEAD` + 每 commit `--stat` | 10 个 commit；两新增 commit 仅改相关文件，无夹带 |
| 工作区 | `git status --porcelain` | 仅既有 docs 删除/未跟踪文件，**无源码改动** |
| 出口探针 | `/tmp/sec-r3-head` 的 `tests/test_probe_r3.py` | **4 passed**（脏付款 409 / 本租户付款 200 / 脏废标 409 / 本租户废标 200） |
| 审计命令 | sqlite `/tmp/audit-r3.sqlite3` | 空库 `0 条` exit 0；造脏行 `1 条` exit 1 |
| prod 配置 | `DJANGO_SETTINGS_MODULE=config.settings.prod` | `DEBUG=False`、`ALLOWED_HOSTS=['*']`、`check` 无问题 |
| compose 配置 | `docker compose config` | backend 含 `DJANGO_SETTINGS_MODULE: config.settings.prod`，无 `ARK_DEV_LOGIN` |

10 个 commit：

| commit | message | 文件 |
|---|---|---|
| `a83c274` | E-3 登录后门双门禁 + R-STAFF | `core/auth/api.py` + 测试 |
| `02c0c9c` | E-1 N 域列表/抽取池租户过滤 | `apps/expertreview/api.py` + 测试 |
| `49f085e` | E-2 G 域 helper/供应商查询租户过滤 | `apps/procure/api.py` + 测试 |
| `90aceee` | E-4 打分须已接受邀请且任务未终结 | `apps/expertreview/api.py` + 测试 |
| `22a2da4` | E-5 已付额按 paid_amount 聚合 | `apps/procure/api.py` + 测试 |
| `c924247` | README 487 | `README.md` |
| `a24776f` | C-1/C-2 + asset 补租户过滤（r1） | `apps/procure/api.py`、`apps/asset/api.py` + 测试 |
| `4ad7687` | dev 租户固定、compose 种子账号、DRAFT 拒绝（r1） | auth/expertreview/compose-smoke/contract 测试/README |
| `33e5311` | C-3 脏行出口守卫 + prod 配置 + asset 测试修复（r2） | `apps/procure/api.py`、`config/settings/prod.py`、`docker-compose.yml`、测试、README |
| `977de6d` | 跨租户引用审计命令 + 回归（r2） | `apps/procure/management/commands/audit_cross_tenant_refs.py`、测试、README |

---

## 3. Critical

**无。**

r1/r2 的三条阻断项均已关闭，且有「旧码红、新码绿」的双向证据：

1. **C-1 入口**：`payment_callback` 的 payment 查询已带 `tenant_id=dom.tenant_id`（`apps/procure/api.py:767`），跨租户 payment_id → 404。
2. **C-2 入口**：`create_contract` 的 `requisition_id` 走 `_get_req_or_404(dom.tenant_id, ...)`（`:580`），跨租户 → 404；`trace_contract` 三处子查询带 tenant（`:699/:702/:706`），脏合同 trace 只剩 `CONTRACT` 节点。
3. **C-3 出口**：`payment_callback` `:790`、`award_bid` `:386` 在预算写前做租户一致性校验，不一致 409；`FBudgetLine` 兜底查询带 `tenant_id=r.tenant_id`。

红证（独立 worktree，未动工作区）：

- `/tmp/sec-r3-mid`（4ad7687 + HEAD 测试）：C-3 用例 `assert 200 == 409`（响应体 `status PAID`）；prod/audit 用例因模块/命令不存在而失败 → **3 failed**。
- `/tmp/sec-r3-base`（c924247 + HEAD 测试）：asset 用例 `assert 200 == 404`（旧码成功转固），正向用例通过 → **1 failed 1 passed**。

---

## 4. Important（留档，不阻断本期代码合并）

### I-1 E-7：全仓仍有 93 处 body-id 裸查，跨域租户隔离未清零

- 现象：`grep -rn "objects\.filter(id=" apps/*/api.py | grep -v tenant_id` → **93 处**；典型如 `apps/activity/api.py:188 update_activity` / `:200 delete_activity`（helper 无 tenant 后直接 save）、`apps/confsec/api.py:434`、`apps/funding/api.py:1261/:1350`、`apps/transform/api.py:784`。
- 范围判定：**不属于本期 5 条债**（本期只含 E-1 N 域、E-2 G 域 + 终审点名的 asset 同族）；ledger 已登记 E-7 清单，lead 已确认「留档不阻断」。
- 验证：静态 grep + r2 对 activity/asset 的行为探针；未做全量逐域利用。
- 建议：单开「E-7 跨域 body-id 裸查」专项，每处配双租户回归；优先 activity/confsec/funding/transform。

### I-2 E-8：生产部署默认凭据与种子数据（pre-existing，真实部署硬门槛）

- 现象：
  - `backend-django/Dockerfile:19` CMD 恒跑 `seed_demo`；`apps/sysadmin/management/commands/seed_demo.py:35` 固定 `admin/Admin@123456`，`:151` 落 bcrypt 哈希；同时创建 manager/staff/finance 等已知口令账号与 R-ADMIN/TOP_SECRET 角色。
  - `docker-compose.yml:23` `ARK_JWT_SECRET: ${ARK_JWT_SECRET:-dev-secret-change-me-please-use-32-bytes-min!}`；`config/settings/base.py:7` 的 `SECRET_KEY` 同默认值。
  - `docker-compose.yml:25` `ARK_API_DOCS: "1"`（注释写「生产删除」但仍开）。
- 范围判定：**不属于 5 条债，基线已存在**，本期未改这些行；但本期把 compose 明确定位为 prod，风险更显性。
- 验证：`docker compose config` + `seed_demo.py` 源码 + `base.py` 默认值。
- 建议（部署前必须）：生产镜像不跑 `seed_demo`（或加 `SEED_DEMO=0` 开关 + 启动时随机初始密码）；强制显式提供 `ARK_JWT_SECRET`（缺失即启动失败）；生产关 `ARK_API_DOCS`。
- 定级：**部署 Critical、本期代码合并不阻断**；请勿把当前 compose 直接暴露到真实网络。

---

## 5. Minor

| # | 位置 | 现象 | 建议 |
|---|---|---|---|
| M-1 | `tests/test_security_hardening.py:435` 仅付款；`apps/procure/api.py:386` 无回归 | `award_bid` 脏行守卫只有我的探针覆盖，仓库测试未覆盖 | 补 `test_award_bid_blocks_dirty_cross_tenant_requisition`（409 + 预算/bid 不变） |
| M-2 | `apps/procure/management/commands/audit_cross_tenant_refs.py:32` | 只扫 `deleted=0`，软删脏行不报告（守卫仍会拦） | 审计改扫全量，或在输出中注明范围 |
| M-3 | `README.md`「部署形态」段；`progress.md` r2 条目 | 写「部署只有 ARK_DEV_LOGIN 一把锁」，与事实相反：prod `DEBUG=False` 后门**零门**，dev 才是双门 | 改为「部署 DEBUG=False，后门不可达；dev 需 DEBUG+ARK_DEV_LOGIN 双门」 |
| M-4 | `progress.md` r2 第二条 | 记 `4c0d6c0`，实际 HEAD 是 `977de6d` | 更正账本 hash |
| M-5 | `apps/expertreview/api.py:377/:391` | `_SCORE_UNSTARTED_STATUSES` 只含 DRAFT，注释却写「DRAFT/DRAWN」；DRAWN/INVITING+ACCEPT 仍可打分（探针 200） | 要么把 DRAWN/INVITING 纳入，要么改注释并登记口径 |
| M-6 | `apps/expertreview/api.py:74-85`；`NReviewInvitation` 模型 | `_my_expert_or_403` 取 `.first()`，同一用户多档案会误 403；邀请表无 `(task_id, expert_id)` 唯一约束 | 加唯一约束 + 按 task 关联取 expert |
| M-7 | `apps/procure/api.py:497` `create_order_from_bid` | 用 `bid.requisition` 无租户校验；当前 `config/api.py` 无路由，不可达 | 若将来接线路由，先补 `r.tenant_id` 校验 |
| M-8 | `README.md` / `progress.md` | 仍写「8 处调用点」，实际 9 处（258/272/303 + 610/637/656/674/690/724）；E-6 仍延后 | 更正计数；E-6 按计划 M3 |
| M-9 | `tests/test_security_hardening.py:501` | `capsys` 形参未使用；审计用例只断言文本，未断言 exit code | 顺手清理，或断言 `SystemExit.code == 1` |

---

## 6. 逐条必查结果（1–8）

### 1. C-3 `payment_callback`：脏行不得跨租户实扣

- 代码：`apps/procure/api.py:761` 函数；`:767` payment 查询已带 tenant；`:784 r = c.requisition`；`:790` 守卫 409；`:798-802` 预算写。
- 探针（`/tmp/sec-r3-head/tests/test_probe_r3.py`）：
  - tenant1 合同挂 tenant2 req（req/line 各 frozen 1000）→ tenant1 R-FINANCE POST `/api/v1/finance/expense` → **409**（40901）；line `frozen 1000/used 0`、req `frozen 1000`、payment `PLANNED` 全不变。
  - 本租户 own req/line → **200**；payment PAID 1000；line `frozen 0/used 1000`；req `frozen 0`。
- 回归：`tests/test_security_hardening.py:435 test_payment_callback_blocks_dirty_cross_tenant_requisition` 断言 409 + 三项预算/payment 不变，已通过。
- 红证：`/tmp/sec-r3-mid`（4ad7687 + HEAD 测试）→ `assert 200 == 409` 失败，响应体 `status PAID`。
- 结论：**关闭**。

### 2. C-3 `award_bid`：废标不得跨租户释放冻结

- 代码：`:356` 函数；`:383 r = bid.requisition`；`:386` 守卫 409；`:398` 扣减；`FBudgetLine` 兜底查询已带 `tenant_id=r.tenant_id`。
- 探针：tenant1 bid 挂 tenant2 req → `POST /api/v1/procurement/bids/{id}/award {"voided":true}` R-MANAGER → **409**（40901，「招标关联的采购申请不属于本租户，已阻断」）；line frozen 1000、req frozen 1000、bid 仍 `PUBLICIZING`。本租户 → **200**；line frozen 0、req frozen 0/status `SUBMITTED`、bid `CHALLENGE`。
- 回归缺口：仓库测试只覆盖 payment（M-1）；建议补 award 用例。
- 结论：**关闭（代码 + 探针）；测试覆盖 Minor 缺口**。

### 3. `audit_cross_tenant_refs`：只读、可退出码

- 命令：`apps/procure/management/commands/audit_cross_tenant_refs.py`；覆盖 `G_CONTRACT/G_BID/G_ORDER`，`deleted=0`，脏行 `SystemExit(1)`（`:53`）。
- 实测（sqlite `/tmp/audit-r3.sqlite3`，先 migrate）：空库 `G_CONTRACT/G_BID/G_ORDER: 0 条`、`合计 0 条脏行`、**exit 0**；shell 造 `GOrder(tenant1, requisition=tenant2)` 后 `G_ORDER: 1 条跨租户引用`、`合计 1 条脏行，需要修数`、**exit 1**。
- 回归：`tests/test_security_hardening.py:501` 通过。
- 结论：**通过**（deleted=1 盲区见 M-2）。

### 4. asset 回归不再空转

- 旧测试打 `/api/v1/asset/from-order`（全仓无此路由，404 来自路由未命中）→ 已改为真实 `/api/v1/asset/from-receipt`，角色 `R-MANAGER`，断言 `o2.converted_asset is False`（`tests/test_security_hardening.py:360`）；正向 `:374` 断言本租户 200 且 `converted_asset True`。
- 红证：`/tmp/sec-r3-base`（c924247 + HEAD 测试）→ `assert 200 == 404` 失败；正向通过。
- 结论：**通过**。

### 5. prod settings 与 compose

- `config/settings/prod.py`：`DEBUG=False`、`ALLOWED_HOSTS=["*"]`；`manage.py:8`/`wsgi.py:6` 的 `setdefault` 保留 dev 默认，compose 显式注入 prod。
- `docker-compose.yml:20` backend `DJANGO_SETTINGS_MODULE: config.settings.prod`；未设 `ARK_DEV_LOGIN`；`docker compose config` 已确认。
- 实测：`DJANGO_SETTINGS_MODULE=config.settings.prod` 下 `DEBUG=False`；`manage.py check` → `System check identified no issues`。
- 结论：**通过**；E-3 的 DEBUG 门在部署形态下不可达（比 r1 的「形同虚设」已实质修复）。

### 6. 回归、迁移、契约、纪律

- `pytest -q` → **497 passed, 5 warnings in 19.75s**。
- `makemigrations --check --dry-run` → **No changes detected**（PG 连接警告可忽略）。
- `git diff --stat b908490..HEAD -- design/ frontend/src/api/schema/` → **空**。
- README:5/:29/:73 → **497**，与实测一致。
- 10 commits 与文件一一对应，无夹带；工作区无源码改动。
- 结论：**通过**。

### 7. 测试真红（独立手法）

- C-3 用例：`/tmp/sec-r3-mid`（4ad7687）→ **3 failed**：`test_payment_callback_blocks_dirty...` `assert 200 == 409`；`test_prod_settings_have_debug_off`（prod 模块不存在）；`test_audit_command_detects_dirty_refs`（`CommandError: Unknown command`）。
- asset 用例：`/tmp/sec-r3-base`（c924247）→ **1 failed 1 passed**：拒绝用例 `assert 200 == 404`，正向通过。
- 结论：**新测试对修复有鉴别力**；C-3/award 守卫的旧码行为此前已由 r2 探针证明（200 + 受害预算归零）。

### 8. 是否漏债：E-1..E-6 + m-2/m-3/m-5/m-6/m-7/m-8

| 项 | 本期状态 | 证据/位置 |
|---|---|---|
| E-1 N 域 | **已修** | `apps/expertreview/api.py:94` list_experts、`:227` list_reviews、`:271-276` draw_experts 候选池均带 tenant；invite MID_CHECK 仍裸查（`m-2`，域内低风险遗留） |
| E-2 G 域 | **已修 + 加固** | helper `:82/:89`；9 个调用点；GSOrder 相关 GSupplier 查询全部带 tenant；C-3 出口守卫 |
| E-3 `ark/ark` | **已修** | `core/auth/api.py:31` 双门；`:36-42` `_dev_tenant_id`；`:72` 固定租户；`:58` 失败文案与真实账号一致；探针 DEBUG=False+env → 401、双 True → 200 且 roles `["R-STAFF"]`；body tenant 不再参与（`:395` 回归） |
| E-4 未受邀打分 | **已修（口径有残留）** | `:377-391`；DRAFT/DECLINED/EXPIRED/CONCLUDED 409；合法 accept→QUORUM→start→score 200；DRAWN/INVITING 仍可打分（M-5） |
| E-5 paid_sum | **已修** | `apps/procure/api.py:538 Sum("paid_amount")`；仅在 list_contracts；create_payment_plan 仍按 plan_amount 校验 |
| E-6 design 契约漂移 | **未修（计划延后 M3）** | 计划书:412；本期契约 diff 为空，说明未触碰但债仍在 |
| m-2 `_notify_invitees` / `set_mid_check_experts` 无 tenant | **仍未修** | `apps/expertreview/api.py:321`；`apps/project/api.py:1288-1294` |
| m-3 通知测试只断言 subject | **仍未修** | `tests/test_m2c_review_fixes.py:52-53/:91-92` |
| m-5 前端 mock 通配 | **仍未修** | `frontend/src/api/mock/overrides/auth.ts:33/35/50/68/117` |
| m-6 notify_user 无 channel | **仍未修** | `apps/notify/email.py:76` |
| m-7 5 处 TODO 通知 | **仍未修** | procure/portal:157/:175、procure/api:346、expertreview/api:325、expertreview/portal:122 |
| m-8 发标收件人范围 | **仍未修** | `apps/procure/api.py:326-356` |
| E-7 跨域 body-id | **新登记，未修** | 93 处；见 I-1 |
| E-8 部署凭据 | **新登记，未修** | 见 I-2 |

结论：本期 5 条债全部闭合；E-6 与 m-* 为明确的遗留，不属于本期承诺；E-7/E-8 已登记。

---

## 7. 合并门槛判定

| 门槛 | 结果 |
|---|---|
| 全量测试 | **497 passed** |
| 迁移一致性 | **No changes detected**（exit 0） |
| 契约零改动 | `design/` + `frontend/src/api/schema/` **0 行** |
| 五条债 + C-1/C-2/C-3 代码与回归 | **全部通过** |
| 新测试真红 | **通过**（C-3 3 failed、asset 1 failed 1 passed 于旧码） |
| 提交纪律 / README 计数 | **通过**（10 commits 无夹带；README 497） |
| 出口/脏行路径（本期范围） | G 域资金出口（payment/award）已闭环；`create_order_from_bid` 无路由（M-7） |
| 域外 | E-7 留档；E-8 部署前必须处理 |

**判定：可合并推送。** 合并后建议立即排期 E-8（部署凭据）与 E-7（跨域 body-id）；两者不影响本次代码正确性，但 E-8 是真实上线的硬门槛。

---

## 附录 A：r1 / r2 历史（已关闭）

- **r1（REQUEST_CHANGES）**：C-1 `payment_callback` 跨租户付款/预算写（`:762`）；C-2 `create_contract` `requisition_id` 注入（`:580`）；I-1 dev 登录 body tenant；I-2 `scripts/compose-smoke.sh` / `tests/test_contract.py` 仍 `ark/ark`；I-3 `apps/asset/api.py` GOrder 裸查。实测 487 passed；基线 b908490 跑新测试 13 failed 1 passed。
- **r2（REQUEST_CHANGES）**：C-1 入口已修但出口仍信任脏 FK（`:784`/`:383`）；asset 测试打不存在 URL（`:348`）；仓库无 prod settings（`DEBUG=True`）；93 处 body-id。实测 493 passed；基线 c924247 4 failed 1 passed。
- **r3 关闭方式**：`33e5311` 加 C-3 守卫 + prod + asset 真实路由测试；`977de6d` 加审计命令 + 回归；497 passed。

## 附录 B：本次探针与 worktree

- `/tmp/sec-r3-head`（HEAD 977de6d）：`tests/test_probe_r3.py`，4 passed。
- `/tmp/sec-r3-mid`（4ad7687 + HEAD 测试）：3 failed。
- `/tmp/sec-r3-base`（c924247 + HEAD 测试）：1 failed 1 passed。
- 审计库：`/tmp/audit-r3.sqlite3`（migrate 后空库 exit 0；造脏行 exit 1）。
- 三个 worktree 均已 `git worktree remove`；主工作区无源码改动。
