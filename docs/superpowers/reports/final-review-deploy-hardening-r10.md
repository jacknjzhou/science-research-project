# E-8 终审 r10：`file:` URI 内存库判定与 `manage.py test` 复审

- 仓库：`/Users/jacky/works/science-research-project`
- 分支：`develop`
- 范围：`a83c409..aef797d`（新增 `aef797d`）
- diff 包：`/tmp/review-deploy-hardening-r10.diff`（104076 bytes）
- 计划：`docs/superpowers/plans/2026-11-19-deploy-hardening.md`
- ledger：`.superpowers/sdd/2026-11-19-deploy-hardening/progress.md`
- 复审对象：r9 的 I-R9-1（`file:memory` 不落盘判错）与 I-R9-2（覆盖不足）
- 结论：**REQUEST_CHANGES**（无 Critical；2 条 Important）

## 0. 结论

r10 修好了 r9 暴露的**默认复现形态**：`file:memory:foo` 不带 `?mode=memory` 时不再被当成内存库，别名 + `manage.py migrate` 现在被 `IS_TEST_SETTINGS` 拒绝，且没有生成 `memory:foo`。`manage.py test` 也新增了真实子进程用例，11 个登录测试通过，证明测试运行器没有被启动守卫挡死。

但 `_is_ephemeral_test_db()` 的 URI 判定仍是**子串匹配**，不是参数解析：

```python
params = name.split("?", 1)[1] if "?" in name else ""
return "mode=memory" in params
```

因此 `file:memdb1?xmode=memory` 会被判为内存库（因为 `xmode=memory` 包含子串 `mode=memory`），而 SQLite 实际把 `xmode` 当未知参数忽略，按普通文件 URI 落盘。我亲手复现：

- 别名 `from config.settings.test import *` + `DATABASES.default.NAME = "file:memdb1?xmode=memory"`
- `manage.py migrate --noinput` → **EXIT=0**
- 生成 `$T/memdb1`，**1,294,336 bytes**

这正是 I-R9-1 要堵的“测试配置迁到持久库”，只是换了一个畸形 URI。r10 新增的 6 参数单测没有覆盖它，所以测试全绿但绕过仍在。结论：**REQUEST_CHANGES**，但不把这次问题升级为 Critical，因为它需要非默认的自定义 settings/URI，尚不构成默认部署路径的凭据泄露或必然启动失败；它是同一安全边界的**不完整修复**，必须在合并前收口。

## 1. 逐项结论

| # | 必查项 | 结论 | 证据 |
|---|---|---|---|
| 1 | `file:memory:foo`（无 mode）不再被判内存 | **通过** | 别名 + `manage.py migrate` EXIT=1，报 `IS_TEST_SETTINGS`；无 `memory:foo` 文件 |
| 2 | `file:…?mode=memory` 正常内存库 | **通过** | `file:memdb4?mode=memory&cache=shared` migrate EXIT=0，无 `memdb4` 文件 |
| 3 | 畸形 URI `xmode=memory` | **失败（Important）** | migrate EXIT=0，生成 `memdb1` 1,294,336 bytes；`core/startup.py:73-75` 子串匹配 |
| 4 | `mode=memory_extra` | **误判但不落盘** | `_is_ephemeral` 返回 True；SQLite 报 `no such access mode: memory_extra`，EXIT=1，无文件 |
| 5 | 重复 `mode=memory&mode=rw` | **误判但不落盘** | `_is_ephemeral` 返回 True；SQLite 报 `unable to open database file`，EXIT=1，无文件 |
| 6 | sqlite 相对路径文件名 | **方向正确** | `_is_ephemeral_test_db()` 返回 False；Django/SQLite 相对 CWD 落盘，必须挡住 |
| 7 | 绝对路径文件库 | **通过** | `_is_ephemeral_test_db()` 返回 False；别名 migrate EXIT=1 |
| 8 | 非 sqlite（postgres） | **通过** | `_is_ephemeral_test_db()` 返回 False |
| 9 | `manage.py test` 不被守卫误杀 | **通过（覆盖深度可接受）** | 新用例子进程运行 `manage.py test tests.test_login_auth`，11 例通过，EXIT=0 |
| 10 | 547 全量测试 / migrations / design+frontend schema | **通过** | 547 passed；No changes detected；diff 0 |
| 11 | README 测试数 | **部分失败（Minor）** | `README.md:99` 已 547；`:5`、`:29` 仍 522 |

## 2. 实测数字

| 项目 | 结果 |
|---|---|
| 全量 pytest | `547 passed, 11 warnings in 42.93s` |
| 定向 r10 用例 | `7 passed, 540 deselected, 7 warnings in 4.67s` |
| `tests.test_login_auth` 收集 | `11 tests collected` |
| `makemigrations --check --dry-run` | `No changes detected`（仅 PG 5432 连接警告） |
| 范围 diff | 29 files, +1534/−59 |
| r10-only diff | 3 files, +39/−2（README、startup.py、test_deploy_hardening.py） |
| design / frontend schema | 0 行 |
| 持久化证据 | `$T/memdb1` = 1,294,336 bytes |

## 3. Critical

无。

## 4. Important

### I-R10-1：`xmode=memory` 仍可让测试配置迁移持久库

**位置**：`backend-django/core/startup.py:73-75`

```python
if name.startswith("file:"):
    params = name.split("?", 1)[1] if "?" in name else ""
    return "mode=memory" in params
```

**复现**（本次使用 `mktemp -d`，未使用任何删除命令）：

```bash
T=$(mktemp -d /tmp/e8r10.XXXXXX)
cat >"$T/myxmode.py" <<'PY'
from config.settings.test import *
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3",
                         "NAME": "file:memdb1?xmode=memory"}}
PY
cd "$T"
PYTHONPATH="$T:/Users/jacky/works/science-research-project/backend-django" \
DJANGO_SETTINGS_MODULE=myxmode \
ARK_JWT_SECRET='R10-Str0ng-JWT-Secret-000000000000' \
/Users/jacky/works/science-research-project/backend-django/.venv/bin/python \
/Users/jacky/works/science-research-project/backend-django/manage.py migrate --noinput
# EXIT=0
ls -l "$T/memdb1"
# -rw-r--r-- 1 jacky wheel 1294336 ... memdb1
```

**机制**：`"mode=memory" in "xmode=memory"` 为真；SQLite URI 只认参数名 `mode`，`xmode` 被忽略，默认 `mode=rwc` 落盘。`_assert_settings_module_deployable(strict=False)` 看到 `_is_ephemeral_test_db()` 为 True 就直接放行，导致测试配置迁移到持久库。

**同类误判**（本次实测）：

- `file:memdb2?mode=memory_extra`：`_is_ephemeral` 为 True，但 SQLite 报 `no such access mode: memory_extra`，EXIT=1，无文件。
- `file:memdb3?mode=memory&mode=rw`：`_is_ephemeral` 为 True，SQLite 报 `unable to open database file`，EXIT=1，无文件。
- 这两个当前不落盘，但判定为“内存库”本身是错的；一旦 SQLite 版本/驱动行为变化，或 `mode=memoryfoo` 被接受，就会变成新的持久化绕过。

**修复要求**：按 URI 查询参数精确解析，禁止子串匹配。建议：

```python
from urllib.parse import parse_qs

if name.startswith("file:"):
    query = name.split("?", 1)[1] if "?" in name else ""
    modes = parse_qs(query, keep_blank_values=True).get("mode", [])
    return len(modes) == 1 and modes[0] == "memory"
```

要求 `xmode=memory`、`mode=memory_extra`、`mode=memory&mode=rw`、`mode=memoryfoo`、大小写变体都返回 False；`mode=memory`（可带 `cache=shared`）返回 True。

### I-R10-2：6 参数单测没有覆盖真正的绕过面

**位置**：`backend-django/tests/test_deploy_hardening.py:705-723`

现有参数只有：

- `:memory:` → True
- `""` → True
- `file:memdb1?mode=memory&cache=shared` → True
- `file:memory:foo` → False
- `/tmp/whatever.sqlite3` → False
- postgres → False

没有 `xmode=memory`、`mode=memory_extra`、重复 `mode`、`mode=memoryfoo`、查询串顺序/编码变体。因此 r10 的 547 全绿不能证明 I-R9-1 真正关闭；我实测的 `xmode` 绕过在套件中完全静默。请至少补：

1. `_is_ephemeral_test_db()` 对上述畸形串全部 False；
2. 别名 + `file:memdb1?xmode=memory` + `manage.py migrate` 断言 EXIT≠0、stderr 含 `IS_TEST_SETTINGS`、`$T/memdb1` 不存在；
3. 保留现有 `file:memory:foo` 与 `mode=memory` 正反例。

这属于**回归覆盖不足**，不是新代码路径缺失；但它是当前唯一能证明修复有效的证据，必须补。

## 5. Minor

1. **README 计数仍不一致**：`README.md:99` 已改为 547，但 `:5` 与 `:29` 仍写 522。`grep -n "522" README.md` 可复现。
2. **`tests/test_deploy_hardening.py:722`** 直接给 `settings.DATABASES` 赋值，pytest 报 `UserWarning: Overriding setting DATABASES can lead to unexpected behavior`；功能上可接受，建议 `monkeypatch.setattr(settings, "DATABASES", ...)` 或 `override_settings`。
3. **`test_manage_test_runner_passes_with_sqlite` 只跑 11 例**：足以证明 `manage.py test` 启动不被守卫误杀，但不覆盖全量发现/`--keepdb`；这是覆盖深度，不是当前阻塞项。
4. **`mode=memory_extra` / 重复 `mode`** 目前只是误判、SQLite 自身报错，没有落盘；修 I-R10-1 时一并覆盖即可。
5. **`file:` URI 的参数名大小写**：SQLite 参数名大小写敏感，`MODE=memory` 当前返回 False（保守方向正确）；精确解析后保持 False 即可。
6. **查询串在 `file:` 之前**：例如 `mode=memory?file:foo` 不满足 `startswith("file:")`，返回 False，方向保守，不构成绕过；真正的问题是 `file:` 之后的参数名子串匹配。

## 6. 已复核的 r9 修复

| r9 项 | r10 结果 |
|---|---|
| I-R9-1 默认 `file:memory:foo` | 已修：别名 migrate EXIT=1，`IS_TEST_SETTINGS`，无 `memory:foo` |
| I-R9-1 绝对路径文件 | 仍正确：EXIT=1，无文件 |
| I-R9-1 `file:…?mode=memory` | 仍正确：EXIT=0，无文件 |
| I-R9-2 6 参数单测 | 已加，但缺畸形串（见 I-R10-2） |
| I-R9-2 `manage.py test` 真实运行 | 已加；11 例通过，证明运行器可用 |
| r9 的 `django-admin`/`python -m django`/`--settings`/autoreload | 本次未回归；r8/r9 已覆盖 |

## 7. 复现命令摘要

```bash
# 全量
cd backend-django
.venv/bin/python -m pytest -q
# 547 passed, 11 warnings in 42.93s

# 定向
.venv/bin/python -m pytest -q \
  -k "ephemeral_test_db_detection or manage_test_runner_passes_with_sqlite"
# 7 passed, 540 deselected

# migrations
DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python \
  manage.py makemigrations --check --dry-run
# No changes detected

# 运行器用例本身
.venv/bin/python -m pytest -q tests/test_deploy_hardening.py::test_manage_test_runner_passes_with_sqlite
# 1 passed
```

`xmode` 绕过的完整命令见 I-R10-1；`mode=memory_extra`、重复 `mode`、合法 `mode=memory`、`file:memory:foo` 的实测结果见 §1 表。

## 8. 合并门槛

1. **I-R10-1**：`_is_ephemeral_test_db()` 改为精确解析 `mode` 参数，拒绝 `xmode=memory`、`mode=memory_extra`、重复 `mode`、`mode=memoryfoo` 等；`file:memdb1?xmode=memory` 必须 EXIT≠0 且不生成 `memdb1`。
2. **I-R10-2**：补上述畸形串的 `_is_ephemeral_test_db()` 参数化用例与一个真实 `manage.py migrate` 子进程回归；保留 `file:memory:foo`/`mode=memory` 正反例。
3. **Minor**：README `:5`、`:29` 统一为 547；测试里的 `settings.DATABASES` 赋值改 `monkeypatch`（可选）。
4. 重新跑全量 `pytest -q`（≥547）、`makemigrations --check` No changes、`git diff --stat a83c409..HEAD -- design frontend/src/api/schema` 为空。
5. 通过后可给 **APPROVED**；当前不满足。

## 9. 通过项与边界

- 默认 `file:memory:foo` 路径已堵住；这是 r9 报告的主复现，已不再成立。
- `manage.py test` 子进程用例真实执行，11 例通过；不是直接调用守卫的 false green。
- 547 全量、migrations、design/frontend schema 均符合声明。
- 未执行完整 `docker compose up --build`；本轮的持久化证据来自 sqlite + 测试 settings 别名 + 真实 `manage.py migrate`，足以证明 URI 判定问题。
- 未修改任何源码；唯一仓库写入是本报告。
