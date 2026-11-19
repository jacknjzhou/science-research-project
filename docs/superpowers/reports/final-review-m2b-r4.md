# M2-b 第四轮终审报告（r4）

- 评审对象：`231c6a5..9ed7ef7`（2 commits：`5cbb44b` 修复、`9ed7ef7` 新增 4 条 r3 回归用例）
- 工作区 HEAD：`9ed7ef7`；仓库 `/Users/jacky/works/science-research-project`
- 方式：只读复核 + 独立实跑（真实 sqlite 迁移库 + `seed_demo` + 真实 `POST /api/v1/auth/login` 取 token + 真 casbin 策略），全程未改源码、未提交
- 探针：`/tmp/m2b_r4_probe.py`，125 条断言，**117 PASS / 8 flag**，`elapsed 6.5s`
- 前序：r1 REQUEST_CHANGES → r2 REQUEST_CHANGES → r3 REQUEST_CHANGES（N-1 PI 死锁、N-2 存量混合角色并集越权）

---

## 1. Verdict

**REQUEST_CHANGES**

r3 的 6 项待复核项（N-1..N-5、N-7）**全部实质关闭**，4 条新增用例在旧提交上真红、在新提交上真绿，院内既有链路零回归。判 REQUEST_CHANGES 的唯一原因是本轮新增的 `:change-pi` 端点自身留下 2 条 Important：

1. 改派后不同步 `PTaskBook.content_snapshot["pi_user_id"]`，任务书正文/签署页仍写旧 PI（r3 修法明确要求"同步更新 content_snapshot.pi_user_id"，本轮遗漏），而这条恰好是 N-1 死锁修复的**主路径**（先建任务书、再停用 PI、再改派）。
2. 任务书 PI 已单签（任务书仍 `DRAFT`）时仍允许改派，随后可补签立项，产出「签名人＝旧 PI、项目负责人＝新 PI」的已签任务书。契约 `design/01-项目申报与立项-P.openapi.yaml:642-643` 明确写"申报已立项（SIGNED/EXECUTING）**或任务书已签订时 409**"，实测 200。

两条都可在 30 行内收口，不影响其他结论；I-1 与 I-2 建议同批修（同一函数、同一事务）。

---

## 2. 逐条复核表（N-1..N-5、N-7）

| 编号 | 要求 | 判定 | 证据 |
|---|---|---|---|
| N-1 | PI 死锁修复全链 + 400/403/409/404 边界 | **PASS**（核心链） | 见 2.1；`apps/p/api.py:1030-1080`、`:299-313` |
| N-2 | 存量混合角色并集越权关闭 | **PASS** | 见 2.2；`core/auth/api.py:62-63`、`core/auth/deps.py:47-48`、`apps/p/api.py:599-606` |
| N-3 | progress-report 字段校验（非法全 400，合法落库） | **PASS** | 见 2.3；`apps/project/api.py:286-306` |
| N-4 | EXTERNAL 角色独占 / 外部账号禁追加内部角色 | **PASS** | 见 2.4；`apps/sysadmin/api.py:144-162`、`:187-208`、`:314-334` |
| N-5 | 院内账号只能绑已审核机构 | **PASS** | 见 2.5；`apps/sysadmin/api.py:131-141`、`:191` |
| N-7 | `_pick` 空串回落 snake 键 | **PASS** | 见 2.6；`apps/project/api.py:286-292` |

### 2.1 N-1 PI 死锁：PASS（主链贯通），但引出 I-1/I-2

真实登录驱动的主链（探针断言，非 mock）：

```
建 r4pi1(id=6)/r4pi2(id=7)（R-STAFF，真实密码）→ 两者真实登录 200
pi1 建申报 → id=3, pi_user_id=6
submit 200 → decide 200 → 生成任务书 200（tb=2, status=DRAFT）
PUT /api/v1/admin/users/6 {"status":"DISABLED"} → 200
pi1 真实登录 → 403（code=40302）            ← 死锁复现成立
R-MANAGER POST /api/v1/apply/applications/3:change-pi {"piUserId":7}
  → 200，落库 pi_user_id=7 / modifier_id=2，出参 pi_user_id=7
pi2 以 PI 身份签任务书 → 200，sign_records 落库含 ("PI",7)
MANAGER 签 → 200
最终 app=EXECUTING tb=SIGNED EProject.id=5 pi_user_id=7   ← 双签立项完成
```

边界逐项（全部实测）：

| 场景 | 实测 |
|---|---|
| 改派 999999（不存在） | 400「申报负责人不存在」 |
| 改派停用账号 | 400「申报负责人账号非启用状态」 |
| 改派外部账号（partner） | 400「申报负责人不得为外部机构账号」 |
| 新 PI 跨租户（tenant2 用户） | 400 |
| 申报 id 不存在 | 404 |
| tenant2 的申报 id | 404 且未落库（跨租户收口，`_locked_scoped_app_or_404`，`apps/p/api.py:935-951`） |
| R-STAFF / R-ADMIN / R-FINANCE / 纯 R-PARTNER | 403（R-ADMIN 无策略，与 `:decide` 同口径） |
| R-LEADER | 200（另测 `app5`） |
| 缺 `piUserId` / `"abc"` / `"  "` | 400 |
| 已立项（SIGNED/EXECUTING）再改派 | 409 |
| 任务书已签（tb SIGNED）后改派 | 409（此时申报必为 EXECUTING，由状态判定命中） |
| `:decide` 对 DRAFT 申报 | 409（动作路由未被 `{id}` 遮蔽的对照） |
| 同值改派、DRAFT 申报 | 200 |
| REJECTED 申报改派 | 200（契约未描述，见 M-8） |
| 建单 PI＝999999 / `"abc"` / 停用 / 外部 | 全 400（`apps/p/api.py:299-313`） |

**跨机构 404 分支**：`:change-pi` 对 `is_external_only(d)` 先行 403（`apps/p/api.py:1046-1047`），而外部账号不可能持 R-MANAGER/R-LEADER（N-2 裁剪 + N-4 禁追加），因此"外部跨机构改派→404"在现行策略下结构性不可达；跨租户 404 已实测。不是漏项，是防御性分支被策略层前置拦截。

**但主链暴露两处 Important**（详见第 3 节 I-1/I-2）：
- 改派后 `PTaskBook.content_snapshot["pi_user_id"]` 仍为 6（期望 7），任务书正文停留在旧 PI；
- 任务书 PI 已单签（tb 仍 DRAFT）后再改派返回 200，补签后 `signers=[("PI",3),("MANAGER",2)]` 而 `proj_pi=7`。

### 2.2 N-2 存量混合角色并集：PASS

用 ORM 直接写入存量脏账号 `r4mixed`（org_b，`user_source=EXTERNAL`，roles=`[R-PARTNER, R-STAFF]`），再经 `PUT /api/v1/admin/users/{id}` 重设密码后走**真实登录**：

- 登录 200，`parse_token` 结果 `roles=['R-PARTNER']` —— 签发处裁剪（`core/auth/api.py:62-63`）。
- 真实 token 打 `/api/v1/expenses`、`/staff`、`/output`、`/budgets` → **全 403**。
- 另用 `gen_token` 伪造**未裁剪**双角色 token（绕过签发裁剪）打同样四端点 → **仍全 403** —— 鉴权入口第二道裁剪（`core/auth/deps.py:47-48`）独立生效，双处防线都成立。
- 混合账号（登录裁剪后按外部口径）建申报 200，`/apply/task-books` POST 403（`/apply/*` POST 策略只给 R-STAFF），跨机构任务书签署 404、本机构任务书签署 200，`/apply/ai/draft` 403。
- references 机构过滤（`apps/p/api.py:599-606`）在当前策略下不可达（见 M-6），属防御性代码。
- **内部账号零影响**：`r4pi2` 真实登录 `roles=['R-STAFF']`，四端点全 200；`manager` `['R-MANAGER','R-LEADER']` 未裁剪；`admin` `['R-ADMIN']` 且 `/staff` 200；`ark/ark` 回退 `['R-STAFF','R-MANAGER']`，`/staff`、`/expenses` 均 200。

### 2.3 N-3 汇报字段：PASS

| 入参 | 期望 | 实测 |
|---|---|---|
| `reportType=WHATEVER` / 小写 `self` / 缺失 | 400 | 400 |
| `progressPercent="abc"` | 400 | 400（非 500） |
| `progressPercent=150` / `-5` | 400 | 400 |
| period 33 字符 / 缺失 | 400 | 400 |
| 合法 camel（`2026Q1/SELF/55`） | 200 + 落库 | 200，DB `('2026Q1','SELF',55,'进展')` |
| period 32 字符边界 | 200 | 200 |
| snake + `progress_percent=0` | 200 且为 0 | 200，DB 0 |

无任何 5xx。瑕疵：纯空格 period 200 落库空串、55.7 截断（M-3/M-4）。

### 2.4 N-4 外部角色独占：PASS

`user_source=EXTERNAL` + 空角色 → **400** 且不落库；`EXTERNAL+R-STAFF` → 400；`EXTERNAL+R-PARTNER` 无机构 → 400；`EXTERNAL+R-PARTNER+PENDING 机构` → 400；`EXTERNAL+R-PARTNER+APPROVED` → 200 且 `user_source=EXTERNAL`；`user_source=BOGUS` → 400；`""+R-STAFF` → 推导 `INTERNAL`；`""+R-PARTNER` → 推导 `EXTERNAL`；外部账号再 `assign_role` 内部角色 → **400 且角色未污染**；重复授 R-PARTNER → 200（幂等）。

观察项：INTERNAL + 空角色建号 200（uid=17），随后可补授 R-PARTNER 再补授内部角色（M-5，无提权）。

### 2.5 N-5 机构绑定：PASS

院内账号（R-STAFF）绑 PENDING 机构 → 400「机构尚未通过资质审核」；绑 99999 → 400「机构不存在或跨租户」；绑 tenant2 机构 → 400；绑 APPROVED → 200；`org_id="abc"` → 400。无机构时授 R-PARTNER → 400（`_assert_role_consistency`）。

### 2.6 N-7 `_pick`：PASS

`reportType="" + report_type="SELF"`、`progressPercent="" + progress_percent=42` → 200 且落库 `('SELF',42)`；`progressPercent=None` 回落 snake 7 → 落库 7；`period=""` 回落 snake → 正常 400/200 分支（`apps/project/api.py:286-292`）。

### 2.7 N-6（r3 Minor，非本轮门槛）

- M-9（period 自由文本 vs 契约 enum）**已由设计解决**：契约改为 `{type:string,maxLength:32}`，与既有前端一致（见 5.4）。
- M-8（staff 全量 `/apply/*` POST）与 M-3（REJECTED 孤儿任务书）本轮未处理，维持 r3 的 Minor 评级，不阻塞。

---

## 3. 新问题

### Important（阻塞合并）

#### I-1 `:change-pi` 未同步任务书快照，改派后任务书正文仍是旧 PI

- 位置：`backend-django/apps/p/api.py:1065`
  `a.save(update_fields=["pi_user_id", "modifier_id", "updated_at"])` —— 只更新申报，未触碰 `PTaskBook.content_snapshot`。
- 复现：pi1 建申报 → decide → 生成任务书（tb DRAFT）→ 停用 pi1 → `POST /apply/applications/3:change-pi {"piUserId":7}` → 200 → 读 `PTaskBook.content_snapshot`
- 实测：`snapshot.pi_user_id=6 expect=7 tb_status=DRAFT`
- 影响：签署页/打印件展示旧 PI，新 PI 签名落库，同一份任务书里"负责人姓名"与"签名人"不一致；审计不可解释。这正是 N-1 死锁修复的主路径（先有任务书才能签署）。
- 修法：在 `transaction.atomic()` 内，对 `PTaskBook.objects.filter(application_id=a.id, status="DRAFT")` 逐个读改写 `content_snapshot["pi_user_id"] = new_pi`（含 `pi_name` 若快照有）并 `save(update_fields=["content_snapshot","updated_at"])`；已签订/执行中由 409 兜住不会污染。r3 的修法建议原文即要求此步。

#### I-2 任务书 PI 已单签（tb 仍 DRAFT）时仍可改派，产出签名人与负责人不一致的已签任务书

- 位置：`apps/p/api.py:1050`（只判 `a.status in ("SIGNED","EXECUTING")`）；`apps/p/api.py:1190-1196` `_assert_application_mutable` 只判任务书 `status in ("SIGNED","EXECUTING")`，不看 `sign_records`。
- 复现：pi1 建单 → decide → 生成任务书 → pi1 以 PI 身份签（tb 仍 DRAFT，`sign_records=[("PI",3)]`）→ R-MANAGER change-pi → 200 → pi2 签 PI → **409**（同角色已签）→ MANAGER 签 → 200 → 立项。
- 实测：`tb=SIGNED app=EXECUTING proj_pi=7 signers=[('PI', 3), ('MANAGER', 2)]`
- 契约对照：`design/01-项目申报与立项-P.openapi.yaml:642-643`"申报已立项（SIGNED/EXECUTING）或任务书已签订时 409"；实测 200，实现与契约冲突。
- 影响：已签任务书的 PI 签名归属离职/停用旧 PI，而项目负责人是新 PI；签署链路此后无法自愈（新 PI 永远 409），只能由 MANAGER 单方补签，等于绕过 PI 双签。
- 修法（建议 a）：
  a) change-pi 增加前置：`tb = PTaskBook.objects.filter(application_id=a.id).first()`；若 `tb` 存在且（`tb.status != "DRAFT"` 或 `tb.sign_records`）→ 409「任务书已开始签署，不可改派」。这样契约的 409 语义才真正闭合。
  b) 允许改派但作废旧签名（`sign_records` 记 voided 并留痕、通知、UI 重签），需同步改契约与前端；本轮不建议。

### Important（既有，非本轮引入，建议单独立项）

#### I-3 停用账号的存量 JWT 仍可签署（无状态 token 不吊销）

- 复现：pi1 真实登录取 token → `PUT /admin/users/6 {"status":"DISABLED"}` → 用停用前 token `POST /api/v1/apply/task-books/2:sign {"role":"PI"}`。
- 实测：**200**（新登录则 403 code=40302）。`ark_auth`（`core/auth/deps.py`）只验签不查 `SysUser.status`。
- 影响：N-1 的"死锁"仅对新登录成立；持有 token 的停用/离职账号在 TTL 内仍能签署。这是 r1 以来既有的设计缺口，不是本轮回归。
- 修法：签署/立项等高风险端点入口复核 `SysUser.status=="ACTIVE"`（或在 `ark_auth` 每请求查一次，成本可接受）；中长期加 token 版本号/黑名单。

### Minor

| 编号 | 位置 | 复现 → 实测 | 修法 |
|---|---|---|---|
| M-1 | `apps/p/api.py:1042` `new_pi = int(raw)` | `{"piUserId": true}` → **200 且 pi=1**（`int(True)==1` 可指派给 uid=1 的 admin） | `isinstance(raw,int) and not isinstance(raw,bool)` 才接受，否则 400 |
| M-2 | `apps/p/api.py:1046-1078` | 改派到无任何角色账号 → 200，该账号签 PI **403**（无 `/apply/*` 策略），再次死锁 | 改派时校验新 PI 至少持一个可签角色（R-STAFF/R-MANAGER/R-LEADER） |
| M-3 | `apps/project/api.py:292-294` 先判空、`:297` 后 strip | `period="   "` → **200 且落库 `''`** | 先 `str(period or "").strip()` 再判空 |
| M-4 | `apps/project/api.py:306` `int(...)` | `progressPercent=55.7` → **200 落库 55**；`"55"` 亦 200 | 先判整型（数字字符串可宽松），非整数 400 |
| M-5 | `apps/sysadmin/api.py:208`、`:329` | INTERNAL+空角色建号 200（uid=17）→ 补授 R-PARTNER（需已审核机构）→ `user_source` 仍 INTERNAL → 再补授 R-STAFF ⇒ 重新造出混合数据；登录/鉴权双裁剪使其无提权 | `assign_role`/`revoke_role` 后按角色重算 `u.user_source`，以角色为单一真源 |
| M-6 | `apps/p/api.py:599-606` | `is_external_only` 分支在当前策略下不可达（外部账号先被 403） | 保留；注释说明"由策略层前置拦截，此处为纵深防御" |
| M-7 | `frontend/src/api/mock/overrides/portal.ts:330` | mock 默认 `report_type:'QUARTERLY'`，不在新枚举内（mock 不经后端，无运行时影响） | 改 `'SELF'` |
| M-8 | `apps/p/api.py:1050` | REJECTED 申报改派 200 | 契约 409 描述补一句"REJECTED/WITHDRAWN 允许改派以支持恢复" |
| M-9 | `apps/p/api.py:1080` | 200 出参 `pi_user_id`（snake_case） | 契约 200 为泛型 `ApiResponse`，不违约；与 `:decide` 等既有端点同口径，可忽略 |

---

## 4. Review Focus 五项判定

| # | 焦点 | 判定 | 依据 |
|---|---|---|---|
| ① | 任务书生成是否走机构作用域 | **PASS** | `_locked_scoped_app_or_404`（`apps/p/api.py:935-951`）统一租户+机构；混合账号跨机构签署 404 且不落库；院内正常 200。 |
| ② | 一申报一项目/一任务书 | **PASS** | 本轮未改立项/建项目路径；`generate_task_book`（`apps/p/api.py:954-987`）先查 exist 幂等返回；探针同参二次生成未产生第二条任务书。 |
| ③ | P 域 body 的 pi/org 覆盖 | **PASS** | 外部身份 `pi=self`、`applicant_org_id=current_org_id` 仍强制覆盖（`apps/p/api.py:274-280`）；院内新增存在/ACTIVE/非外部三重校验（`:299-313`），r3 的 N-1 保留项关闭。 |
| ④ | 签署后不可再变更 | **PASS（有保留）** | 已立项/任务书 SIGNED 后改派 409、签署非法状态 409 均实测成立；但"任务书 PI 已单签、状态仍 DRAFT"未被覆盖 → I-2，故保留。 |
| ⑤ | 混合角色并集权限 | **PASS** | 签发裁剪（`core/auth/api.py:62-63`）+ 鉴权裁剪（`core/auth/deps.py:47-48`）双处生效；存量混合账号真实登录后四端点全 403，伪造未裁剪 token 亦 403；内部账号与 `ark` 回退零影响。 |

---

## 5. 独立实跑数字

| 检查 | 命令（工作目录） | 结果 |
|---|---|---|
| 全量测试 | `backend-django $ .venv/bin/python -m pytest -q` | **413 passed, 7 warnings in 15.95s**，exit 0（7 条为既有 `PytestReturnNotNoneWarning` / naive datetime） |
| 迁移漂移 | `backend-django $ .venv/bin/python manage.py makemigrations --check --dry-run` | **No changes detected**，exit 0（stderr 仅既有 PG 5432 连接警告） |
| 前端类型 | `frontend $ ./node_modules/.bin/vue-tsc --noEmit` | **exit 0**，无输出 |
| 契约副本 | `cmp -s design/<f> frontend/src/api/schema/<f>` ×3 | `01-项目申报与立项-P.openapi.yaml`、`02-项目过程管理-E.openapi.yaml`、`12-用户与权限-U.openapi.yaml` 全部 **IDENTICAL** |
| 契约解析 | `yaml.safe_load` | paths：01=**41**、02=**26**、12=**27**（两侧一致；01 由 r3 的 40 → 41，正是新端点） |
| 空库建库+种子 | 删 `/tmp/r4_empty.sqlite3` → `migrate` → `seed_demo` ×2 | migrate 含 `Applying sysadmin.0014_resync_permissions... OK`；第 1 遍 legal +2、staff +11、p +6、project +17、funding +23、output +7、expert +6、activity +4、archive +6、performance +6、transform +13、ethics +5、procure +8、asset +9、confsec +7、notify +5、partner +5、users +4、dicts +5、items +26、grants +78；第 2 遍 `seed_demo 完成（幂等）：`（全 0），两次 exit 0 |
| 0014 权限落库 | 新库查询 | `SysPermission`：`obj=/api/v1/apply/applications/*:change-pi, act=POST, code=apply.applications.x:change-pi.post, domain=apply`；`SysRolePermission` 绑定 **R-MANAGER + R-LEADER**；perms 368、links 705 |
| 0014 回放幂等 | `migrate sysadmin 0013` → 删权限行（367）→ `migrate sysadmin` | Applying 0014 OK；change-pi 权限 **count=1**、roles `['R-LEADER','R-MANAGER']`、perms 368、links 705；`sync_permissions_from_csv` 连跑两次仍 (368,705)，幂等 |
| 新 4 条用例真红 | `git archive 231c6a5` → `/tmp/old-m2b`，覆盖 HEAD `tests/test_p_m2b.py`，`pytest -k "r3n1 or r3n3 or r3n4n5"` | 旧码 **4 failed, 25 deselected in 2.44s**（failure：`:change-pi` 404、EXTERNAL 空角色 200≠400 等）；HEAD **4 passed, 25 deselected in 2.28s** |
| 自建攻击探针 | `/tmp/m2b_r4_probe.py`（125 断言） | **117 PASS / 8 flag**，elapsed 6.5s；8 条 flag 全部落入 I-1/I-2/I-3 与 M-1/M-2/M-3/M-4 |
| 院内回归 | 探针 `建单/提交/立项/生成任务书/PI 签/MANAGER 签/汇报` | `[200,200,200,200,200,200]`；`/staff` 200 |

### 5.4 契约 period 改动与既有前端

- `design/02-项目过程管理-E.openapi.yaml:1098-1100`：`required:[period,reportType,progressPercent]`，`period: {type:string, maxLength:32}`（不再是 enum）。
- `frontend/src/views/portal/ProjectReportView.vue:10` `period?: string`；`:37` 表单 `report_type:'SELF'`；`:38` 仅校验 `trim().length>0`；`:65` 提交 `period: form.period.trim()`；`:143` 自由文本 input（placeholder「如 2026Q1」）；report_type 为 `<select>`，选项 **SELF/MID_CHECK/ANNUAL**。
- 结论：**无冲突**。契约由枚举改自由字符串与既有前端实现一致；`reportType` 枚举与前端选项一致。唯一残留是 mock 默认值 `QUARTERLY`（M-7，mock-only）。

### 5.5 工作区

本轮未改任何源码（`git diff -- backend-django frontend/src design` 为空）。`git status --porcelain` 24 项全部为评审前既存：`docs/` 二进制删改、`docs/superpowers/plans/*`、未跟踪的 `docs/superpowers/reports/`、`backend-django/uv.lock`、`frontend/pnpm-lock.yaml`、`frontend/pnpm-workspace.yaml`、`dump.rdb`、`scripts/ocr_*`。仅写 `/tmp/m2b_r4_probe.py` 与本报告。

---

## 6. 合并门槛结论

**不满足合并门槛（NOT MERGEABLE）**，但只差两处小修。

关闭情况：
- r3 **N-1 关闭**（主链贯通，400/403/409/404 全部符合预期）；
- r3 **N-2 关闭**（双处裁剪，存量混合账号四端点 403，内部账号零影响）；
- r3 **N-3 关闭**（非法入参全 400，合法落库正确）；
- r3 **N-4 关闭**、**N-5 关闭**、**N-7 关闭**；
- r3 **N-6** 中 M-9 已由契约变更解决，M-8/M-3 维持 Minor 不阻塞。

合并前必须完成（均在 `change_application_pi` 内，可同一 commit）：
1. **I-1**：改派时同步 `PTaskBook.content_snapshot["pi_user_id"]`（DRAFT 任务书）。
2. **I-2**：任务书已开始签署（`sign_records` 非空或 status≠DRAFT）时改派返回 409，与契约描述对齐。
3. 建议同批带上 **M-1/M-3/M-4**（各 1–5 行，避免下一轮再开 r5）。
4. **I-3**（停用不吊销 token）单独立项跟踪，不阻塞本次合并，但需在发布说明标注该窗口期风险。

修完 I-1/I-2 后，本轮全部 N 项与 Review Focus 五项即全部 PASS，可判 **APPROVED**。
