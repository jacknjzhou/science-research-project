# M2-b 第五轮（收敛轮）终审报告 — final-review-m2b-r5

- 评审对象：`/Users/jacky/works/science-research-project`，HEAD `34cc06d`（`fix(p): change-pi 同步 DRAFT 任务书快照并在签署开始后拒绝改派（终审 r4 I-1/I-2）`）
- 评审范围：`9ed7ef7..34cc06d`，1 commit，`git diff --stat` = README.md 6 / backend-django/apps/p/api.py +22 / backend-django/apps/project/api.py +10 / backend-django/tests/test_p_m2b.py +92（121 insertions, 9 deletions）
- 前序：r1 `docs/superpowers/reports/final-review-m2b.md`（4 Critical + 4 Important）、r2 `final-review-m2b-r2.md`（1 Critical + 5 Important + 9 Minor）、r3 `final-review-m2b-r3.md`（2 Important + 5 Minor）、r4 `final-review-m2b-r4.md`（2 Important 新增 + 9 Minor）
- 本轮性质：只判"r4 遗留 2 条 Important + 同批 3 条 Minor 是否真关闭、是否引入新问题、能否合并"
- 只读约束：未修改任何源码/测试/契约，未提交。仅新增本报告。
  - 说明：评审结束时 `git status --porcelain` 显示 **8 处与本次 diff 无关的已跟踪改动**——`docs/.DS_Store`（二进制元数据）+ 7 个 `docs/` 图片资产被删除（`IMG_1355.jpeg`/`IMG_1357.jpeg`/`IMG_1358.jpeg`/`scienceResearch2.png`/`spm3.png`/`spm5.png`/`spm9.png`）。本会话全程只读（`git archive` 解到 `/tmp`、`pytest`、`sed`/`grep`），未执行任何 `rm`/`git rm`，也未写入 `docs/` 下除本报告外的文件；本会话启动时的勘查记录未覆盖这 7 个删除，故**无法确认其产生时点**，推测来自并行的其他会话。**不影响本判决**（不涉及 `backend-django/` 与 `frontend/src/` 源码），但合并前请 lead 确认这 7 个删除是否为有意提交。

---

## 1. Verdict

**APPROVED_WITH_MINOR — 可以合并（合并门槛 PASS）。**

- r4 的 2 条 Important（I-1 快照不同步、I-2 单签未拦）在本轮**实质关闭**，不是"表面关闭"：改派后 `PTaskBook.content_snapshot["pi_user_id"]` 已是新 PI，且该值经双签→立项后与 `EProject.pi_user_id` 一致（A4/A9）；单签后改派 409 且申报 pi、快照、签名记录三者均未变（B3/B3b/B3c/B3d）。
- 同批 M-1 / M-3 / M-4 达标（全部 400 + 不落库），实测含边界值。
- 未发现新的 Critical / Important。新增 4 条 Minor（N-r5-1..4），均为"同类面未扫干净"或"文档/锁序/产品出口"性质，不改变合并判定。
- 唯一"Important 但在 r4 已定性为既有、单独立项"的 I-3（停用账号存量 JWT 仍可签署）本轮**复现且仍未修**，按 r4 口径 carryover，不阻塞本次合并，但**必须在合并记录中登记 owner 与截止里程碑**（r3 §6 已提出同一要求）。

判决依据的不变式（本轮全部实测成立）：**任何时刻，"申报的 PI" = "最新活跃任务书快照的 PI" = "已签的 PI 名" = "立项后的项目 PI"；一旦有人签过字，这组值不再变。**

---

## 2. 逐条复核

### 2.1 I-1 `change_application_pi` 同步 DRAFT 任务书快照 — **PASS**

**实现**（`backend-django/apps/p/api.py:1082-1087`）：

```python
snap = dict(tb_now.content_snapshot or {})
snap["pi_user_id"] = new_pi
tb_now.content_snapshot = snap
tb_now.modifier_id = ...
tb_now.save(update_fields=["content_snapshot", "modifier_id", "updated_at"])
```

放在同一事务内、同一 DB 写（`apps/p/api.py:1046` 起在 `transaction.atomic()` 中），且 `_task_book_snapshot`（`:903-920`）的 13 个键里只有 `pi_user_id` 与负责人相关（无 `pi_name`），因此"只覆盖一个键"是完整正确的，不存在漏同步字段。

**实跑证据**（`/tmp/m2b_r5_probe.py`，真实 sqlite 迁移库 + `seed_demo` + 真 casbin；pi1=id 6，pi2=id 7，manager=id 2）：

| 断言 | 结果 | 实测值 |
|---|---|---|
| A1 建申报→submit→decide→生成任务书 | 200/200/200/200 | `tb=2`，`snapshot.pi_user_id=6` |
| A2 改派到 pi2 | 200 | `pi_user_id=7` |
| A3 申报行 | PASS | `pi_user_id=7`，`modifier_id=2` |
| **A4 任务书快照** | **PASS** | `content_snapshot.pi_user_id=7`（改派前为 6） |
| A5 快照其余 12 键 | PASS | 逐键比对全等，`frozen_at` 值未变 |
| A5b 任务书状态 | PASS | 仍 `DRAFT`，`sign_records=[]` |
| A6 新 PI 本人登录签 PI | 200 | 无"非申报负责人"类 400 |
| A7 MANAGER 签 MANAGER | 200 | `tb=SIGNED`，`app=EXECUTING` |
| A8 立项 | 200 | `EProject.id=5` |
| **A9 三方一致** | **PASS** | `EProject.pi_user_id=7 == snapshot.pi_user_id=7 == pi2.id` |
| A10 签名主体 | PASS | `signers=[('PI',7),('MANAGER',2)]` |

补充面：
- **无任务书时改派**（B1）：200，申报落 7，无快照可同步——正确（`tb_now is None` 分支）。
- **DRAFT 空签时改派**（B2）：200 且快照同步为 7——这正是 r4 I-1 的原始场景，已修复。
- **软删旧行后重建**（C1）：旧行 id=6（已 `deleted=1`）快照仍是 6，新行 id=7 快照=7；改派只触碰新行，旧行未被"顺手改活"。`order_by("-id").first()` + `deleted=0` 的取向正确。
- **同值改派**（C6）：200 幂等，不产生额外副作用。

> 语义说明（非问题）：I-1 让 `frozen_at` 与其余冻结字段保持原值、只覆盖 `pi_user_id`。负责人不是一个"申报内容冻结项"，这个取舍是对的；建议在快照字段说明里加一句"`pi_user_id` 随改派可变"，以免后人把它当冻结值。**不阻塞。**

### 2.2 I-2 任务书已开始签署 → 改派 409 — **PASS**

**实现**（`backend-django/apps/p/api.py:1058-1066`）：

```python
tb_now = (PTaskBook.objects.filter(application_id=a.id, deleted=0)
          .order_by("-id").first())
if tb_now is not None and (tb_now.status != "DRAFT" or (tb_now.sign_records or [])):
    raise ApiError(409, ..., "任务书已开始签署，不可改派负责人")
```

守卫位置在 `:1053`（申报已 SIGNED/EXECUTING → 409）与 `:1055`（`_assert_application_mutable`）**之后**、负责人解析/存在性校验（`:1067` 起）**之前**。这个顺序是对的：任务书一旦开始签署，改派就是"操作本身非法"，不该先因 `piUserId` 不存在而报 400（B5 已实测 409 优先）。

**五个边界逐条实测**（`/tmp/m2b_r5_probe.py` + `/tmp/m2b_r5_probe4.py`）：

| # | 场景 | 期望 | 实测 | 判定 |
|---|---|---|---|---|
| ① | 未生成任务书 | 200 | 200，申报落 7 | PASS |
| ② | 任务书 DRAFT 且 `sign_records=[]` | 200 且快照同步 | 200，`snapshot.pi=7` | PASS |
| ③ | PI 单签（`tb.status=DRAFT`，`sign_records=[('PI',6)]`） | **409** | 409 `code=40901`「任务书已开始签署，不可改派负责人」 | PASS |
| ③' | 被拒后副作用 | 全不变 | `a.pi_user_id=6`、`snapshot.pi=6`、`len(sign_records)=1` | PASS |
| ④ | 双签 `tb=SIGNED` / `app=EXECUTING` | 409 | 409「申报已立项，不可改派负责人」 | PASS |
| ④' | 被拒后副作用 | `a.pi_user_id` 不变 | 6 未变 | PASS |
| ⑤ | 已签 + `piUserId=999999` | 409（而非 400/500） | 409，守卫先于存在性校验 | PASS（附带收益） |
| ⑥ | R-LEADER 走同一端点 | 409 | 409（策略行含 R-LEADER，行为一致） | PASS |

关键点：③ 的 `tb.status` 仍是 `DRAFT`——**这正是 r4 指出的、旧实现唯一漏掉的形态**；新守卫用 `sign_records` 非空兜住了它，且不依赖 `status` 迁移是否及时。这是正确的判据选择（"已开始签署"= 有签名记录 ∨ 已离开 DRAFT）。

**用例覆盖度（观察，非问题）**：新增的 4 条 `-k r4` 用例里，I-2 只写了③一种形态（`tests/test_p_m2b.py:64 test_r4_change_pi_rejected_after_signing_started`），①②④⑤由本轮探针覆盖，未进 CI。建议后续补 3 条（未生成 / DRAFT 空签同步 / 双签）把语义钉住。**不阻塞。**

### 2.3 M-1 `piUserId` 拒绝 bool / 非整浮点 — **PASS**

**实现**（`apps/p/api.py:1042-1043`）：

```python
if isinstance(raw, bool) or (isinstance(raw, float) and not raw.is_integer()):
    raise ApiError(400, CODE_BAD_REQUEST, "piUserId 必须为整数")
```

**实测**（探针 1 的 D 组，12 个输入）：

| 输入 | 状态 | 落库/消息 |
|---|---|---|
| `true` / `false` | 400 / 400 | 「piUserId 必须为整数」——不再 `int(True)→1` |
| `1.5` / `-1.5` / `"1.5"` | 400 / 400 / 400 | 同上 |
| `"abc"` / `"   "` / `[]` / `{}` | 400 ×4 | 同上 |
| `0` | 400 | 「申报负责人不存在」（合法类型，走存在性） |
| `"7"` | 200 | 落 7（字符串数值接受，与全仓 `_pick + int()` 风格一致，可接受） |
| `7.0` | 200 | 落 7（整数值浮点，见 2.5 同款口径） |
| 全部非法输入后 | PASS | `a.pi_user_id` 未变（400 不产生半提交） |

`isinstance(raw, bool)` 必须排在数值判断前（`bool` 是 `int` 子类），实现顺序正确。

### 2.4 M-3 `period` 先 strip 再判空 — **PASS**

**实现**（`backend-django/apps/project/api.py:293-298`）：`period` / `report_type` 先 `.strip()`，空串按缺省处理。

**实测**（探针 1 的 E 组）：

| 输入 | 状态 | 落库 |
|---|---|---|
| `period="   "` | 400「请求参数错误」 | `count` 0→0，**未落库** |
| `period="\t \n"` | 400 | 未落库 |
| `reportType="  "` | 400 | 未落库（同一处一并修好） |
| `period="  2026Q1  "` | 200 | 落 `'2026Q1'`（trim 生效，不是只判空） |

"全空格不再落空串"与"带空格合法值被 trim"两个方向都验到了，符合 r4 的修法要求。

### 2.5 M-4 `progressPercent=55.7` → 400 — **PASS（含 1 条同类残留，见 N-r5-1）**

**实现**（`backend-django/apps/project/api.py:309-316`）：

```python
if isinstance(raw_pct, float) and not raw_pct.is_integer():
    raise ApiError(400, ..., "progressPercent 必须为整数")
progress_percent = int(raw_pct or 0)
```

**实测**：

| 输入 | 状态 | 落库 |
|---|---|---|
| `55.7` | 400「progressPercent 必须为整数」 | 未落库（count 不变） |
| `"55.7"` | 400 | 未落库 |
| `150` | 400（既有上限校验） | 未落库 |
| `55` | 200 | 落 55 |
| `55.0` | 200 | 落 55 —— **合理**：JSON/PG `numeric` 常见把整数写成 `55.0`，语义无损，接受可避免误伤 |
| `"55"` | 200 | 落 55（字符串数值沿用既有风格） |
| **`true`** | **200，落 1** | **不拦截** → N-r5-1 |

结论：r4 要求的"不静默截断"达成；`55.0` 的处置我明确认可（无损整数，允许）。残留的 bool 分支是同一函数里 M-1 的同构缺口，见 §3 N-r5-1。

---

## 3. 新问题

本轮修复**没有**引入 Critical / Important。以下 4 条 Minor，按严重度排序：

### N-r5-1（Minor，建议本轮顺手修，一行）`progressPercent=true/false` 静默转 1/0

- 位置：`backend-django/apps/project/api.py:309-316`
- 复现：`POST /api/v1/project/progress-reports`（或对应创建端点）body `{"progressPercent": true, ...}` + 合法 `reportType/period`
- 实测：**200**，`msg=ok`，落库 `progress_percent=1`（`false` → 0）
- 原因：M-4 只挡了 `isinstance(raw_pct, float)`，`bool` 是 `int` 子类，`int(True)=1` 直接通过；M-1 在 `piUserId` 上已经处理了同一形状，此函数未同步
- 修法（与 M-1 完全同构）：
  ```python
  if isinstance(raw_pct, bool) or (isinstance(raw_pct, float) and not raw_pct.is_integer()):
      raise ApiError(400, CODE_BAD_REQUEST, "progressPercent 必须为整数")
  ```
- 影响面：无安全含义，只是"脏数据不静默落库"的完整性；`true` 落成 1% 进度不会被误读成严重错误，故不阻塞

### N-r5-2（Minor，文档）契约文字与 handler docstring 未覆盖"已开始签署"

- 位置：`design/01-项目申报与立项-P.openapi.yaml:642-643`（对应副本 `frontend/src/api/schema/01-项目申报与立项-P.openapi.yaml`，两文件当前 `cmp` 一致）
- 现状：`409` 描述仍写"申报已立项（SIGNED/EXECUTING）或任务书已签订时返回"，未提"任务书已开始签署（`sign_records` 非空 / `status != DRAFT`）"
- 同源问题：`backend-django/apps/p/api.py:1031-1034` 的 handler docstring 仍写"任务书签订后（SIGNED/EXECUTING）不再允许改派"，与新守卫的实际语义（单签即拦）不一致；`:1056-1057` 的行内注释是准确的，建议把 docstring 改成"任务书开始签署后即不再允许改派"
- 影响：前端/联调方按文档只会处理"已立项"分支，遇到单签 409 时提示语落到兜底
- 修法：同一段补一句"或任务书已开始签署（存在签署记录或已离开 DRAFT）"；**改 design/ 后必须同步 `frontend/src/api/schema/` 并 `cmp` 复查**（本轮已确认两处仍 IDENTICAL，若只改一侧会破坏一致性门禁）
- 不阻塞：错误码 `409` 与 message 本身已自解释，行为正确，缺的只是描述

### N-r5-3（Minor，产品出口）单签后被停用 → 该申报永久不可立项，且无重置入口

- 位置：`backend-django/apps/p/api.py:1058-1066`（新守卫）+ `backend-django/config/api.py:101-103`（任务书只有 POST 生成 / POST :sign / GET 三个端点，无撤销/重置）
- 复现链（`/tmp/m2b_r5_probe4.py` B 组，全部实测）：
  1. PI 单签 → 200（`tb.status` 仍 `DRAFT`）
  2. 管理员停用该 PI（离职）→ 后续新登录被拦，存量 token 2h 内仍可签（I-3）
  3. 改派 → **409**（I-2 的设计，正确）
  4. 终止申报 → 200（`app=REJECTED`，`_assert_application_mutable` 不拦 DRAFT 任务书）
  5. 再次改派 → **仍 409**（签名记录还在，守卫不看申报状态）
  6. 重新生成任务书 → 200 但**幂等返回同一行** `tb=4`（`generate_task_book` 的 exist 分支），不可能换一张白纸
  7. MANAGER 补签 → 409「申报状态不允许立项」
  - 结论：该申报从此既不能改派、不能立项、不能重置；业务上只能作废另建申报（评审记录/编号全丢）
- 为什么算 Minor：触发需要"PI 已签字后离职"这种窄序列，且**不会产生错误数据**（比"允许改派导致签名与负责人不一致"好得多）；r4 也明确否决了"改派时自动撤销 PI 签名"的方案（会摧毁签名不可否认性）
- 修法（择一，均为小改动，建议 follow-up 单独立项）：
  a. 新增 `POST /api/v1/apply/task-books/{id}:reset`：仅 `R-MANAGER`、仅 `status=DRAFT`、清空 `sign_records`/`remark` 并记审计 + 通知——最小且语义清晰；
  b. 或允许 `:terminate` 在"仅 PI 单签且 DRAFT"时把任务书一并置为 `VOID`，并在 `generate_task_book` 的 exist 分支排除 `VOID`，使重建拿到新行
- 注意：无论选哪个，**都不要**放开 I-2 的守卫

### N-r5-4（Minor，PG-only 并发）改派与签署的加锁顺序相反，窄窗口下 PG 死锁 → 500

- 位置：`backend-django/apps/p/api.py:1052`（`_locked_scoped_app_or_404` → `:941` `PApplication.select_for_update()`）→ `:1058-1062` 读 tb → `:1087` 写 tb，顺序 **app → tb**；`apps/p/api.py:1123`（`PTaskBook.select_for_update()`）→ `:1132`（`PApplication.select_for_update()`），顺序 **tb → app**
- 交错：T1=签署 持 tb 锁等 app；T2=改派 持 app 锁等 tb → PG 检测死锁，中止一方，HTTP 500
- 严重度：**数据一致性不受影响**（死锁一方整体回滚，不会出现"签名了但快照是旧 PI"），只丢可用性；SQLite 单写者模型下测试环境不复现
- 实测状态：本机 PG 5432 未启动，**未实跑**，以上为代码静态推断（`select_for_update` 行序可直接读出）；本轮所有并发相关结论均以 sqlite 串行探针为限
- 修法：`change_application_pi` 的 `tb_now` 查询改成 `select_for_update()` 且**放在 app 锁之前**（先 tb 后 app），或统一"先 tb 后 app"的全局顺序；顺带把 `:1058` 的查询补 `tenant_id=a.tenant_id`（与 `_assert_application_mutable` `:1212-1217` 的过滤口径对齐，当前靠 `application_id` 已足够，属防御性）

### 3.1 遗留项（非本轮新增，不重复计）

| 项 | 类型 | 状态 | 说明 |
|---|---|---|---|
| I-3 停用账号存量 JWT 仍可签 | **Important（既有）** | **未修，本轮复现** | 停用后旧 token 签 PI → 200（`/tmp/m2b_r5_probe4.py`），TTL=7200s；根因 `core/auth/deps.py:40-70` 只 parse+casbin 不查 `SysUser.status`。r4 已定性"既有、建议单独立项"，本轮沿用：**不阻塞 M2-b 合并，但须登记 owner 与里程碑** |
| M-2 改派到无角色账号仍 200 | Minor | 未修 | 新 PI 无 `R-STAFF` 也能被指派；签署时会 403，故不致命 |
| M-5 `assign_role` 不重算 `user_source` | Minor | 未修 | 与 r3-N2 的签发/鉴权裁剪叠加后无可利用面 |
| M-6 防御分支 / M-7 mock `report_type` / M-8 REJECTED 改派 200 / M-9 出参 snake_case | Minor | 未修 | M-8 本轮实测 C5：REJECTED + DRAFT 空签改派 200，**未扩大拦截面**（r4 已认可保留） |

---

## 4. Review Focus 五项复判

| # | 焦点 | 判定 | 本轮依据 |
|---|---|---|---|
| ① | 任务书生成是否走机构作用域 | **PASS** | `_locked_scoped_app_or_404`（`apps/p/api.py:935-951`）统一租户+机构；跨机构读任务书 404（`probe4` r2-C1）、跨租户改派 400「申报负责人不存在」（`probe2`）；本轮 diff 未触及该函数 |
| ② | 一申报一项目 / 一任务书 | **PASS** | `generate_task_book`（`:954-987`）先查 `exist` 幂等返回（本轮 B5/C5 二次生成拿到同一行 `tb=4`）；全仓无 `p_task_book` 唯一约束（sqlite schema 仅 `idx_p_tb_tenant_st` / `idx_p_tb_project`），1:1 由"app 行锁 + exist 检查"在应用层保证；软删重建探针 C1 未产生两条活跃行 |
| ③ | P 域 body 的 pi/org 覆盖 | **PASS** | 本轮 diff 未改 `create_application`（`:281-313`）；外部身份 `pi=self`、`applicant_org_id=current_org_id` 强制覆盖；院内新增"存在/ACTIVE/非外部"三重校验仍在，且改派路径已同口径（停用 400、外部 400、跨租户 400 实测） |
| ④ | 签署后不可再变更 | **PASS（保留解除）** | r4 的"有保留"针对"PI 单签、status 仍 DRAFT"未覆盖 → 本轮 I-2 已覆盖（409 + 无副作用）；叠加"已立项/已双签 409"（B4）、"改派同步快照"（I-1）、"立项 PI 取自申报 PI"（A9），签署后四条改派路径全部闭合。`_assert_application_mutable` 仍覆盖 SIGNED/EXECUTING 与多处非改派写入口（withdraw/terminate/sections），职责未被削弱 |
| ⑤ | 混合角色并集权限 | **PASS** | 签发裁剪（`core/auth/api.py:62-63`）+ 鉴权裁剪（`core/auth/deps.py:47-48`）双处生效；本轮复跑"伪造未裁剪混合 token 打 `/staff` → 403"、"混合角色 token 签发侧角色被裁为 `["R-PARTNER"]`"；改派端点策略仅 R-MANAGER + R-LEADER（`SysPermission id=368`，obj `/api/v1/apply/applications/*:change-pi`，act POST），R-STAFF → 403 实测 |

---

## 5. 修复未引入新回归（针对本轮 diff 的三项定点检查）

**a) `_assert_application_mutable` 与新守卫是否重复/冲突** — 冗余，但**不冲突，且互补**。
- `:1053` 判申报 `SIGNED/EXECUTING`；`:1055` 判存在 `SIGNED/EXECUTING` 任务书；`:1063` 判最新活跃任务书 `!= DRAFT` ∨ 有签名。对改派而言 `:1063` 是 `:1055` 在任务书维度的超集，故 `:1055` 在本 handler 内已成冗余（仍被其他写入口使用，不能删全局函数）。
- **互补的证据**：漂移场景"旧行 SIGNED 活跃 + 新行 DRAFT 空签"（ORM 直接造，`probe5`）下，`:1063` 只看最新行会误判放行，`:1055` 兜住 → 409 且未落库。两条守卫叠加反而比单条更稳。
- 建议：在 `:1055` 上方留一行注释"任务书维度已由 :1063 覆盖，此处保留为多任务书漂移兜底"，避免后人误删。**不阻塞。**

**b) `tb_now` 在多任务书场景是否误判** — 1:1 在应用层成立，软删重建路径正确，仅"数据漂移"下有一处残留。
- 正常路径：`deleted=0` + `order_by("-id")` + `generate_task_book` 幂等 → 每申报只有一条活跃任务书（C1/C2/B5 实测）。软删旧行后重建会拿到**新行**（C1：`new.snap=7`，`old.snap=6` 未被触碰），不会"复活旧行"或改错行。
- 残留（需 DB 直接写入才能制造，产品路径不可达）：漂移2"旧行 DRAFT 单签 + 新行 DRAFT 空签"→ 改派 200，`new.snap=7` / `old.snap=6` / `old.signs=1`，即旧行的签名与快照仍指向旧 PI。因为旧行不是活跃 1:1 行、签署端点按 id 定位且该行已不可能推进立项，**无可利用面**；若要彻底防，可在 I-2 守卫处改成"任一条 `deleted=0` 行 `!= DRAFT` ∨ 有签名 → 409"（一次 `exists()` 查询，2 行）。**不阻塞。**

**c) 无其他回归**：diff 仅 3 个源文件，`apps/p/api.py` 的 +22 行全部落在 `change_application_pi` 与 `_assert_application_mutable` 邻近区域，未触碰签署、立项、生成、列表、权限相关代码；`apps/project/api.py` +10 行只改 `period/report_type/progressPercent` 三处类型与空值处理。全量 417 passed 与 r4 的 417 一致，无测试被改写为"迁就实现"。

---

## 6. 实跑数字（全部本机独立复现，非引用上轮）

| 项 | 命令 | 结果 |
|---|---|---|
| 后端全量 | `.venv/bin/python -m pytest -q` | **417 passed**, 7 warnings in **15.74s**（7 warnings 为既有 `PytestReturnNotNoneWarning`） |
| 新用例（HEAD） | `pytest tests/test_p_m2b.py -k r4 -q` | **4 passed**, 29 deselected in **1.97s** |
| **真红复现** | `git archive 9ed7ef7 \| tar -x -C /tmp/m2b_r5_old` + 覆盖 HEAD 的 `tests/test_p_m2b.py` → `pytest -k r4 -q` | **4 failed, 29 deselected, 1.97s**；失败点与声称缺陷一一对应：`test_r4_change_pi_syncs_draft_snapshot` `assert 4 == 5`（快照未同步）、`test_r4_change_pi_rejected_after_signing_started` `assert 200 == 409`（单签未拦）、`test_r4_change_pi_input_edges` `assert 200 == 400`（`piUserId=true`）、`test_r4_progress_report_rejects_blank_and_fractional` `assert 200 == 400`（`period="   "`）。**用例确为真红，非空转** |
| 迁移一致性 | `.venv/bin/python manage.py makemigrations --check --dry-run` | `No changes detected`，exit 0（stderr 仅 PG 5432 连接警告，无迁移差异） |
| 前端类型 | `cd frontend && ./node_modules/.bin/vue-tsc --noEmit` | exit 0，无输出 |
| 契约一致 ×3 | `cmp design/01-…yaml frontend/src/api/schema/01-…yaml`（01/02/12 各一次） | 三对全部 **IDENTICAL** |
| 契约 paths 计数 | `yaml.safe_load` 两侧各取 `len(paths)` | design / frontend 均 **01=41, 02=26, 12=27** |
| 空库 migrate | 全新 sqlite → `migrate` | exit 0 |
| seed 幂等 ×2 | 连续两次 `seed_demo`，逐表比行数（141 张表） | 第二次 `diff={}`，完全幂等；核心表 `p_application=2 / p_task_book=1 / e_project=4 / sys_user=5` |
| 探针 1（全流程 + I-1/I-2/M-1/M-3/M-4） | `/tmp/m2b_r5_probe.py` | 62 断言，**61 PASS / 1 FAIL**（唯一 FAIL = N-r5-1 `progressPercent=true`），4.5s |
| 探针 2（租户/机构/账号状态/通知/幂等） | `/tmp/m2b_r5_probe2.py` | 13/13 PASS |
| 探针 4（历史 C/I 回归扫 + N-r5-3 链） | `/tmp/m2b_r5_probe4.py` | 14/14 PASS（其中 r4-I3 以"未修"为预期命中 200） |
| 探针 5（多任务书漂移） | 内联 ORM 脚本 | 3/3 PASS（漂移1 → 409、未落库；漂移2 → 200 且仅新行同步） |

环境：macOS + Python 3.13 + sqlite 临时库（每个探针独立 `rm` 后 `migrate` + `seed_demo`），真 JWT + 真 casbin 策略表，无 mock 业务层。PG 5432 未启动，涉及 PG 的结论已显式标注为静态推断。

---

## 7. 合并门槛结论

**PASS — 可合并。**

逐项对照合并门槛：
1. 无未关闭的 Critical：**满足**（r1 的 4 条、r2 的 1 条、r3 的 N-1/N-2 均在 r3/r4 关闭，本轮回归扫 r1-C2/C3、r2-C1、r3-N2 复测仍为 403/409/404/403）。
2. 无未关闭的 Important（除已登记延期项）：**满足**——r4 的 I-1、I-2 本轮实质关闭（§2.1/§2.2），无新增 Important。
3. 测试全绿且新用例真红：**满足**（417 passed；旧码 4 failed / 新码 4 passed）。
4. 迁移/类型/契约/seed 无漂移：**满足**（§6 六项）。
5. 修复未引入回归：**满足**（§5；唯一残留为 DB 漂移才可达的旧行不同步，无可利用面）。

**合并记录必须同时登记（非阻塞，但不可省）：**
- **I-3**（停用账号存量 JWT 仍可签，TTL 2h）：既有 Important，owner + 截止里程碑；建议修法是 `ark_auth` 在 `parse_token` 后查 `SysUser.status`（缓存 60s 即可），并让停用动作写入吊销集。
- **N-r5-1**（`progressPercent` bool 静默转 1）：一行修复，建议随下个 PR 带入。
- **N-r5-2**（契约 409 文字）、**N-r5-3**（单签后无重置出口，建议 `:reset` 端点）、**N-r5-4**（PG 锁序统一为先 tb 后 app）：作为 M2-b 的技术债清单落在同一份合并记录里，各自估计工作量均 ≤ 半天。
- 存量 Minor M-2 / M-5 / M-6 / M-7 / M-8 / M-9：维持 r4 的"接受"结论，随技术债清单流转。

**最小必要条件（若产品/评审会要求"修完再合"）**：仅需 N-r5-1 的一行 bool 守卫（`apps/project/api.py:309` 前加 `isinstance(raw_pct, bool)` 分支），其余均不影响正确性。除此之外**不建议**再扩大范围——I-2 的守卫不要为了 N-r5-3 而放开，N-r5-4 的锁序调整需要 PG 环境验证，应独立 PR。

---

## 附录 A：证据可复现性

- 探针脚本：`/tmp/m2b_r5_probe.py`、`/tmp/m2b_r5_probe2.py`、`/tmp/m2b_r5_probe4.py`（均为一次性脚本，各自 `rm` 独立 sqlite 后 `migrate`+`seed_demo`，不触碰仓库）
- 旧码树：`/tmp/m2b_r5_old`（`git archive 9ed7ef7` 解出，含 HEAD 的测试文件覆盖）
- 本轮唯一产出文件：本报告 `docs/superpowers/reports/final-review-m2b-r5.md`
- 复核命令（可直接重跑）：
  ```bash
  cd /Users/jacky/works/science-research-project/backend-django
  .venv/bin/python -m pytest -q
  .venv/bin/python -m pytest tests/test_p_m2b.py -k r4 -q
  .venv/bin/python manage.py makemigrations --check --dry-run
  cd ../frontend && ./node_modules/.bin/vue-tsc --noEmit
  ```

## 附录 B：判定一览

| 项 | 判定 |
|---|---|
| I-1 快照同步（含立项后一致性） | **PASS** |
| I-2 已开始签署 → 409（五边界） | **PASS** |
| M-1 `piUserId` bool/非整浮点 | **PASS** |
| M-3 `period` strip 后判空 | **PASS** |
| M-4 `progressPercent` 小数 | **PASS**（bool 残留 → N-r5-1） |
| 新 Critical / Important | **0** |
| 新 Minor | 4（N-r5-1..4） |
| 延期 Important | 1（I-3，r4 定性） |
| 合并门槛 | **PASS** |
| **Verdict** | **APPROVED_WITH_MINOR** |
