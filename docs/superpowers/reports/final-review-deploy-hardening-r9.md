# E-8 部署收口 · 第九轮终审（r9）

- 仓库：`/Users/jacky/works/science-research-project`
- 分支：`develop`
- 审查范围：`a83c409..806f600`（10 个 commit；本轮新增 `806f600`）
- 计划：`docs/superpowers/plans/2026-11-19-deploy-hardening.md`
- ledger：`.superpowers/sdd/2026-11-19-deploy-hardening/progress.md`
- diff 包：`/tmp/review-deploy-hardening-r9.diff`
- 审查方式：只读；本轮唯一写入是本报告
- 环境：`backend-django/.venv/bin/python`，Python 3.13，Django 5.x，pytest 9.x

## 0. 结论

**VERDICT: REQUEST_CHANGES**

r8 的两条 Important 主路径已实测修复：

- 别名 `from config.settings.test import *` + `DATABASES` 指向**绝对路径文件**：`manage.py migrate` 现在 **EXIT=1**，报 `IS_TEST_SETTINGS`，库文件不创建。
- 默认 `config.settings.test`（`:memory:`）下 `migrate` / `makemigrations` / `collectstatic` 仍 **EXIT=0**；`check` 仍拒绝。
- `python -m django` 与真实 `django-admin` 已拆成两条用例；`help` 改为不可连接库；两条直调 false-green 用例已删除；新增持久库回归。

但 `_is_ephemeral_test_db()` 的 `file:memory` 判据仍有一处**可复现的持久库绕过**：

```python
# core/startup.py:69
return name in ("", ":memory:") or name.startswith("file:memory")
```

`NAME="file:memory:e8r9_persist.sqlite3"` **没有** `?mode=memory` 时，SQLite URI 不是内存库，而是一个名为 `memory:e8r9_persist.sqlite3` 的持久文件；`manage.py migrate` 因此 **EXIT=0** 并写入 1,294,336 字节。r8-I1 的“只认内存库”在这一形态下没有真正成立。

**Critical：无。** 该绕过需要自定义 test-settings 别名（不是默认路径），也不泄露凭据；按本轮“Critical 只算凭据泄露/生产启动失败”的口径，列为 Important。如果该别名指向生产库，则实际后果是生产 schema 被迁移、随后服务被 `IS_TEST_SETTINGS` 拒绝，属于生产事故；报告在 I-R9-1 中明确标注。

## 1. 必查矩阵

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| 1 | 无 `ARK_JWT_SECRET` 的 prod 启动必须失败 | **通过（沿用 r7/r8）** | no-ARK `django.setup` / `manage.py` / `python -m django` / `django-admin` 均 EXIT=1 |
| 2 | 非 dev 下 `ARK_SEED_DEMO=1` 无口令必须拒绝 | **通过（沿用 r7）** | prod 无口令 / `--force` 无口令 / `Demo@123456` 均 CommandError |
| 3 | 未设 `ARK_API_DOCS` 且 `DEBUG=False` 时 docs 不存在 | **通过（沿用 r5）** | `docs_enabled()=False`；`/api/v1/docs`、`/api/v1/openapi.json` 404 |
| 4 | 绝对路径文件库 + test settings 的 `migrate` 必须拒绝 | **通过** | EXIT=1；`IS_TEST_SETTINGS`；文件未创建 |
| 5 | 默认 `:memory:` test settings 的 migrate/makemigrations/collectstatic | **通过** | 三者 EXIT=0；`check` EXIT=1 |
| 6 | `file:memory` URI 是否真的内存库 | **不完全通过（Important）** | 无 `mode=memory` 时是持久文件；migrate EXIT=0 并写 1.29 MB |
| 7 | 真实 `django-admin` / `python -m django` | **通过** | 旧库上两者均 EXIT=1；用例已拆分 |
| 8 | `help` 在坏库上仍可用 | **通过** | `tmp_path/no_such_dir/x.sqlite3`；EXIT=0 且 stdout 有子命令 |
| 9 | 删除两条直调 false-green 后无残留引用 | **通过** | 两条 `test_manage_command_gate_*` 已删；无同名引用 |
| 10 | `manage.py test` 运行器 | **手工通过，无自动回归** | 默认 test settings 与 `--keepdb` 均 EXIT=0；套件无该子进程用例 |
| 11 | 全量测试 / 迁移 / 零 diff | **通过** | `540 passed, 5 warnings in 43.28s`；dev `makemigrations` No changes；design/schema 零 diff |
| 12 | 真实 `django-admin` console script 存在时执行 | **通过（当前 venv）** | `.venv/bin/django-admin` 存在；定向用例未 skip |
| 13 | `file:memory` 无 `mode=memory` 的回归覆盖 | **缺失（Important）** | 新用例只测绝对路径；`grep` 无 `_is_ephemeral_test_db` / `file:memory` 测试 |

## 2. 实测数字

| 项目 | 结果 |
|---|---|
| 全量 `pytest -q` | `540 passed, 5 warnings in 43.28s` |
| 定向 4 个匹配用例（`test_test_settings_cannot_migrate_persistent_db`、`test_django_admin_console_script_blocks_legacy_db`、`test_alias_settings_with_pytest_import_still_refused`、`test_guard_scans_credentials_once_per_process`） | `4 passed, 536 deselected, 1 warning in 5.84s` |
| `makemigrations --check --dry-run`（dev） | `No changes detected`，EXIT=0（PG 5432 警告仅告警） |
| 默认 test settings `migrate` | EXIT=0，全量迁移 OK |
| 默认 test settings `makemigrations` | EXIT=0，`No changes detected` |
| 默认 test settings `collectstatic` | EXIT=0，`0 static files copied` |
| 默认 test settings `check` | EXIT=1，`IS_TEST_SETTINGS` |
| 绝对路径文件别名 `migrate` | EXIT=1，`IS_TEST_SETTINGS`；文件不存在 |
| `file:memory:e8r9_persist.sqlite3` 别名 `migrate` | **EXIT=0**；生成 `memory:e8r9_persist.sqlite3`，1,294,336 字节 |
| `file:memory:e8r9_mem?mode=memory&cache=shared` 别名 `migrate` | EXIT=0；**无文件** |
| `ARK_DB_NAME=/tmp/e8r9/ci_file.sqlite3` + `config.settings.test` | `DATABASES['default']['NAME'] = ':memory:'`（env 被 test.py 硬编码覆盖） |
| `manage.py test test_r9_smoke`（test settings） | EXIT=0，1 test OK |
| 同上 `--keepdb` | EXIT=0，1 test OK |
| 真实 `django-admin` console script | `.venv/bin/django-admin` 存在；旧库 check 用例通过 |
| `git diff --stat a83c409..806f600` | 29 files，+1497/−59；r9-only 2 files，+63/−37 |
| design / `frontend/src/api/schema` | 零 diff |

## 3. Critical

**无。**

按本轮口径，只有“能造成凭据泄露或生产启动失败”的缺陷才算 Critical。以下两点均已复核：

- 旧库 + 服务：`manage.py check`、真实 `django-admin`、`python -m django` 在旧库上全部 EXIT=1；`runserver` 默认/`--noreload` 仍 EXIT=1。没有默认路径的公开凭据服务启动。
- 测试配置别名 + `import pytest`：`django.setup()` / `config.wsgi` 仍 EXIT=1；未因 r9 改动回退。

`file:memory` 绕过不满足“默认路径”和“凭据泄露”，且需要自定义 settings 别名，故不列 Critical；但它在 I-R9-1 中作为 **发布阻塞 Important** 处理。

## 4. Important

### I-R9-1 `file:memory` 前缀被误判为内存库，实际是持久文件；migrate EXIT=0

**位置**：
- `backend-django/core/startup.py:57-69` — `_is_ephemeral_test_db()`；关键行 `:69` `name.startswith("file:memory")`
- `backend-django/core/startup.py:72-88` — `_assert_settings_module_deployable(*, strict)`；`:87` `if not strict and _is_ephemeral_test_db(): return`
- `backend-django/core/startup.py:107-127` — `validate_runtime_secrets(*, check_deployable)`；`:127` 调用
- `backend-django/core/startup.py:318-333` — `enforce_process_guard()`；豁免命令传 `check_deployable=False`

**机制**：
Django sqlite 后端以 `uri=True` 连接（`.venv/.../django/db/backends/sqlite3/base.py:181`）。SQLite URI 中：

- `file:memory:foo?mode=memory&cache=shared` → **内存库**（`PRAGMA database_list` 的 `main` 为 `''`）
- `file:memory:foo` **没有 `mode=memory`** → **持久文件**（实际文件名 `memory:foo`，相对 CWD 落盘）

当前判断只看字符串前缀，因而把第二种也当成临时库。

**复现**（在 `/tmp/e8r9` 执行，避免动仓库）：

```bash
BD=/Users/jacky/works/science-research-project/backend-django
T=/tmp/e8r9
cat >"$T/myfile.py" <<'PY'
from config.settings.test import *
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3",
                         "NAME": "file:memory:e8r9_persist.sqlite3"}}
PY
cd "$T"
PYTHONPATH="$T:$BD" DJANGO_SETTINGS_MODULE=myfile \
  "$BD/.venv/bin/python" "$BD/manage.py" migrate --noinput
# EXIT=0
# Applying sysadmin.0017_resync_permissions... OK
# Applying transform.0001_initial... OK

ls -l "$T"
# -rw-r--r--  1 jacky  wheel  1294336 ... memory:e8r9_persist.sqlite3
```

同一别名把 `NAME` 改为绝对路径 `/tmp/e8r9/persist_abs.sqlite3` 时：

```bash
PYTHONPATH="$T:$BD" DJANGO_SETTINGS_MODULE=myabs \
  "$BD/.venv/bin/python" "$BD/manage.py" migrate --noinput
# EXIT=1
# [启动自检] 拒绝启动：这份 settings 是测试配置（IS_TEST_SETTINGS）...
# ls: /tmp/e8r9/persist_abs.sqlite3: No such file or directory
```

`mode=memory` 的 URI 则确实不落盘：

```bash
NAME='file:memory:e8r9_mem?mode=memory&cache=shared'
# migrate EXIT=0；find -name '*e8r9_mem*' 为空
```

**判断**：
- 这是对 r8-I1 修复的直接绕过；新用例 `test_test_settings_cannot_migrate_persistent_db` 只覆盖“绝对路径文件”，没有覆盖 `file:memory` 无 `mode=memory` 的形态。
- 若该别名指向生产库（例如 DAST/CI 为了复用生产 schema 把 test settings 的 `DATABASES` 指到生产文件），会静默执行整库迁移；随后服务因 `IS_TEST_SETTINGS` 起不来，属于生产启动/数据完整性事故。
- 因需要自定义 settings 别名且不泄露凭据，按约定不标 Critical；但**建议阻塞合并**。

### I-R9-2 `file:memory`/`manage.py test` 的回归覆盖仍不完整

**位置**：
- `backend-django/tests/test_deploy_hardening.py:682-702` — `test_test_settings_cannot_migrate_persistent_db` 只构造绝对路径 `NAME`，断言文件不存在；没有 `file:memory`、`file:memory:...?...`、`mode=memory` 的用例。
- `backend-django/tests/test_deploy_hardening.py:588-600` — `test_django_admin_console_script_blocks_legacy_db` 在找不到 console script 时 `pytest.skip`；当前 venv 有 `.venv/bin/django-admin`，已执行，但 skip 分支会让缺 entry point 的环境静默少一条覆盖。
- `backend-django/tests/test_deploy_hardening.py:412-423` — 删除两条 `test_manage_command_gate_*` 后，`test_process_guard_blocks_non_exempt_command` / `test_process_guard_exempts_remediation_commands` 仍是**直调** `enforce_process_guard()` + monkeypatch 命令名，不是进程入口回归；它们不是新增的 false-green，但仍不能替代子进程。
- `backend-django/tests/test_deploy_hardening.py:598-603` — `help` 用例现在用坏库，已修复 r8 缺口。

**手工验证但未进套件**：

```bash
cd backend-django
PYTHONPATH=/tmp/e8r9/tests_pkg DJANGO_SETTINGS_MODULE=config.settings.test \
  .venv/bin/python manage.py test test_r9_smoke --noinput
# EXIT=0；Ran 1 test；OK

# 同上 --keepdb
# EXIT=0；Ran 1 test；OK
```

**判断**：
- `manage.py test` 运行器本身没有被 r9 新增用例覆盖；我在默认 test settings 下验证了 `--noinput` 与 `--keepdb` 都 EXIT=0。
- 由于 `running_under_tests()` 在 `test` 命令下提前返回，`manage.py test` 即使把 `DATABASES` 指向文件库也不会被 `_is_ephemeral_test_db` 拦截。这是“测试运行器”的合法通道，但它意味着 `test` 命令不适用于“持久库 + test settings”的防护；若要彻底防，需限制 `TEST.NAME` 或对 `test` 命令单独校验。
- 建议至少补：`file:memory` 无 mode → migrate 非零且不创建文件；`file:memory...?mode=memory` → 允许；`manage.py test` 默认/keepdb 子进程；`_is_ephemeral_test_db()` 直接单测（避免仅靠 migrate 间接覆盖）。

## 5. Minor

- **M-R9-1**：`README.md:5`、`:29` 仍写 522，`:99` 已是 540；r9 只改代码/测试，未同步头部计数。
- **M-R9-2**：`core/startup.py:58-61` docstring 说“只认内存 sqlite”，但 `:69` 接受所有 `file:memory*`；注释与实现不一致，正是 I-R9-1 的来源。
- **M-R9-3**：`_is_ephemeral_test_db()` 只接受 sqlite；若 CI 用 `config.settings.test` 的别名覆盖成 Postgres 测试库，`migrate` 会被拒绝（`manage.py test` 因 `running_under_tests` 提前返回仍可用）。默认 `test.py` 硬编码 sqlite `:memory:`，所以标准路径不受影响。
- **M-R9-4**：`ARK_DB_NAME` 对 `config.settings.test` 无效（`test.py:5-9` 硬编码 `:memory:`）；用户提到的“CI 里 ARK_DB_NAME 指向文件 + config.settings.test”在当前实现中实际仍是 `:memory:`，不会误伤，但也会让该 env 的预期落空。
- **M-R9-5**：`test_django_admin_console_script...` 的 skip 条件合理，但建议在 skip 时显式 `pytest.skip` 理由包含路径，CI 日志才能看出是“环境缺 entry point”而非“已通过”。
- **M-R9-6**：`test_manage_help_still_works_when_db_is_broken` 使用 `tmp_path/no_such_dir/x.sqlite3`，已正确覆盖“连库必失败”；但 `help` 仍会先做 JWT 校验，prod 无 `ARK_JWT_SECRET` 时 `help` 失败，纯信息命令是否应完全免密钥可再讨论。
- **M-R9-7**：`test_process_guard_*` 两条直调用例保留；它们现在只是单元测试，不能证明 `manage.py` 入口，建议注释明确“入口由子进程用例覆盖”，避免再次被当成回归证据。
- **M-R9-8**：`file:memory` 无 mode 的 URI 在 CWD 落盘（相对路径）；测试/文档若使用该形态，清理责任在调用方。建议修复时直接要求 `?mode=memory`，而不是解析目录。

## 6. 关键复现命令与输出

### 6.1 `file:memory` 无 mode（阻塞项）

```bash
BD=/Users/jacky/works/science-research-project/backend-django
T=/tmp/e8r9
cat >"$T/myfile.py" <<'PY'
from config.settings.test import *
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3",
                         "NAME": "file:memory:e8r9_persist.sqlite3"}}
PY
cd "$T"
PYTHONPATH="$T:$BD" DJANGO_SETTINGS_MODULE=myfile \
  "$BD/.venv/bin/python" "$BD/manage.py" migrate --noinput
# EXIT=0
ls -l "$T/memory:e8r9_persist.sqlite3"
# 1294336 bytes
```

### 6.2 绝对路径文件别名（已修复）

```bash
cat >"$T/myabs.py" <<'PY'
from config.settings.test import *
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3",
                         "NAME": "/tmp/e8r9/persist_abs.sqlite3"}}
PY
PYTHONPATH="$T:$BD" DJANGO_SETTINGS_MODULE=myabs \
  "$BD/.venv/bin/python" "$BD/manage.py" migrate --noinput
# EXIT=1  IS_TEST_SETTINGS
test ! -e /tmp/e8r9/persist_abs.sqlite3 && echo NO_FILE
# NO_FILE
```

### 6.3 `mode=memory`（正确形态）

```bash
cat >"$T/mymem.py" <<'PY'
from config.settings.test import *
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3",
                         "NAME": "file:memory:e8r9_mem?mode=memory&cache=shared"}}
PY
PYTHONPATH="$T:$BD" DJANGO_SETTINGS_MODULE=mymem \
  "$BD/.venv/bin/python" "$BD/manage.py" migrate --noinput
# EXIT=0
find "$T" -maxdepth 1 -name '*e8r9_mem*' -print
# （空）
```

### 6.4 默认 test settings

```bash
cd backend-django
DJANGO_SETTINGS_MODULE=config.settings.test .venv/bin/python manage.py migrate --noinput
# EXIT=0
DJANGO_SETTINGS_MODULE=config.settings.test .venv/bin/python manage.py makemigrations --check --dry-run
# EXIT=0  No changes detected
DJANGO_SETTINGS_MODULE=config.settings.test .venv/bin/python manage.py collectstatic --noinput
# EXIT=0  0 static files copied
DJANGO_SETTINGS_MODULE=config.settings.test .venv/bin/python manage.py check
# EXIT=1  IS_TEST_SETTINGS
```

### 6.5 `ARK_DB_NAME` + `config.settings.test`

```bash
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r9/ci_file.sqlite3 \
  DJANGO_SETTINGS_MODULE=config.settings.test \
  .venv/bin/python manage.py shell -c \
  "from django.conf import settings; print('NAME=', settings.DATABASES['default']['NAME'])"
# NAME= :memory:
```

### 6.6 `manage.py test` 运行器

```bash
mkdir -p /tmp/e8r9/tests_pkg
cat >/tmp/e8r9/tests_pkg/test_r9_smoke.py <<'PY'
import unittest
class R9Smoke(unittest.TestCase):
    def test_ok(self):
        self.assertTrue(True)
PY
PYTHONPATH=/tmp/e8r9/tests_pkg DJANGO_SETTINGS_MODULE=config.settings.test \
  .venv/bin/python manage.py test test_r9_smoke --noinput
# EXIT=0；Ran 1 test；OK

# --keepdb 同样 EXIT=0
```

### 6.7 全量/迁移/diff

```bash
cd backend-django
.venv/bin/python -m pytest -q
# 540 passed, 5 warnings in 43.28s
DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py \
  makemigrations --check --dry-run
# No changes detected
cd ..
git diff --stat a83c409..806f600
# 29 files changed, 1497 insertions(+), 59 deletions(-)
git diff --stat a83c409..806f600 -- design frontend/src/api/schema
# （空）
```

## 7. 合并门槛

1. **修 I-R9-1**：`_is_ephemeral_test_db()` 只接受：
   - `NAME in ("", ":memory:")`，或
   - SQLite URI 且查询参数显式 `mode=memory`（例如解析 `urllib.parse.urlsplit` 的 query，确认 `mode=memory`；不要用 `file:memory` 前缀）。
   拒绝 `file:memory:foo`（无 mode）、`file:memory:foo?mode=ro` 等会落盘/非内存的形态。
2. **补回归**：`test_test_settings_cannot_migrate_persistent_db` 增加 `file:memory:...` 无 mode → 非零且不创建文件；`file:memory...?mode=memory` → 允许；`_is_ephemeral_test_db()` 直接单测；`manage.py test` 默认/keepdb 子进程。
3. **清 Minor**：README `:5/:29` 统一 540；`core/startup.py:58-61` 注释与实现一致；`test_django_admin` skip 理由；`test_process_guard_*` 注释。
4. **复跑**：全量 pytest ≥540；dev `makemigrations` No changes；design/schema 零 diff；旧库 `manage.py check` / `django-admin` / `python -m django` 均 EXIT=1；默认 test settings 三命令 EXIT=0；`file:memory` 无 mode 拒绝且不落盘。

## 8. 通过项与未测项

**通过**：
- 绝对路径文件 + test settings 的 `migrate` 拒绝，文件未创建。
- 默认 `:memory:` 的 migrate/makemigrations/collectstatic 与 `check` 的差异符合设计。
- 真实 `django-admin`、`python -m django` 旧库检查；`help` 坏库仍可用。
- 删除两条直调 false-green；新增持久库回归存在。
- 全量 `540 passed`、dev makemigrations No changes、design/schema 零 diff。
- 旧库服务门禁、`--settings`、autoreload、单次扫描（r7/r8 修复）未回退。

**未测 / 边界**：
- 未安装/运行 gunicorn，`--preload`/`--reload` 未实测。
- 未跑真实 Postgres/Redis/MinIO/nginx 端到端；未跑完整 `docker compose up --build`。
- 未在 Windows 实机跑 `python -m pytest` 的入口判定。
- `file:memory` 只在 sqlite3 URI 上验证；`file:memorydb_default?mode=memory&cache=shared` 逻辑上同 `mode=memory`，未单独跑全量迁移（仅验证 `mode=memory` 形态）。
