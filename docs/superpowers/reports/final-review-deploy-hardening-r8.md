# E-8 部署收口 · 第八轮终审（r8）

- 仓库：`/Users/jacky/works/science-research-project`
- 分支：`develop`
- 审查范围：`a83c409..f869c72`（7 个 commit；本轮新增 `f869c72`）
- 计划：`docs/superpowers/plans/2026-11-19-deploy-hardening.md`
- ledger：`.superpowers/sdd/2026-11-19-deploy-hardening/progress.md`
- diff 包：`/tmp/review-deploy-hardening-r8.diff`
- 审查方式：只读；本轮唯一写入是本报告
- 环境：`backend-django/.venv/bin/python`，Python 3.13，Django 5.x，pytest 9.x

## 0. 结论

**VERDICT: REQUEST_CHANGES**

本轮 C-R7-1 与 I1–I4 的主路径都已实测修复：

- `import pytest` 不再短路 `IS_TEST_SETTINGS`；`mydeploy.py: from config.settings.test import *` + `import pytest` + 已知 `ARK_JWT_SECRET` 现在 **EXIT=1**。
- 默认 `runserver`（autoreload）在旧库上 **EXIT=1**，不再 124 挂住。
- `enforce_process_guard` 每进程 **1 次**，`config.wsgi` 不再重复扫描。
- `config.settings.test` 下 `migrate` / `makemigrations` / `collectstatic` 均 **EXIT=0**；`check` 仍拒绝。
- `django-admin check`（真实命令）与 `python -m django check` 在旧库上均 **EXIT=1**；`--settings=config.settings.prod` 不再降级为 dev。

但仍有 **2 条 Important，建议本轮阻塞**：`migrate` 等豁免命令绕过了 `IS_TEST_SETTINGS`，自定义 test-settings 别名可以把迁移应用到持久库且无任何提示；以及新增回归里仍有一条“名为 django-admin、实际跑 python -m django”的覆盖缺口，旧 false-green 直调用例也仍在。

**没有发现新的 Critical**：默认 `docker compose` 路径、空库首次启动、旧库 `manage.py`/`django-admin` 门禁、`--settings` 解析、JWT 密钥校验均未复现凭据泄露或生产启动失败。

## 1. 必查矩阵

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| 1 | 无 `ARK_JWT_SECRET` 的 prod 启动必须失败 | **通过（沿用 r7）** | no-ARK `django.setup`/`manage.py`/`python -m django`/`django-admin` 均 EXIT=1 |
| 2 | 非 dev 下 `ARK_SEED_DEMO=1` 无口令必须拒绝 | **通过（沿用 r7）** | prod 无口令/`--force` 无口令/`Demo@123456` 均 CommandError |
| 3 | 未设 `ARK_API_DOCS` 且 `DEBUG=False` 时 docs 不存在 | **通过（沿用 r5）** | `docs_enabled()=False`，`/api/v1/docs`、`/api/v1/openapi.json` 404 |
| 4 | `--settings=config.settings.prod` 不得降级 | **通过** | `manage.py check --settings=...` 旧库 EXIT=1；`shell --settings` 打印 prod、`DEBUG=False` |
| 5 | 真实 `django-admin` / `python -m django` 都过门禁 | **通过** | 旧库上两者均 EXIT=1；`django-admin` 需 `PYTHONPATH=.` |
| 6 | 测试配置别名 + `import pytest` 不可部署 | **通过** | `mydeploy` + `import pytest` + 已知 ARK：`django.setup()` 与 `config.wsgi` 均 EXIT=1，报 `IS_TEST_SETTINGS` |
| 7 | `runserver` 默认 autoreload 不挂住 | **通过** | 旧库默认 `runserver` EXIT=1；`--noreload` EXIT=1 |
| 8 | 每进程只扫描一次 | **通过** | 实测 `GUARD_CALLS=1`；wsgi 不再调用 guard |
| 9 | test settings 下 migrate/makemigrations/collectstatic | **通过** | 三者 EXIT=0；`check` 仍 EXIT=1 |
| 10 | 旧库 `manage.py check` / rotate / 空库 migrate | **通过** | 旧库 EXIT=1；rotate 6 个；rotate 后 EXIT=0；空库 migrate EXIT=0 |
| 11 | 全量测试 / 迁移 / 零 diff | **通过** | `540 passed, 5 warnings in 42.30s`；dev `makemigrations` No changes；design/schema 零 diff |
| 12 | 豁免命令 + test settings 的自定义持久库 | **不完全通过（Important）** | 自定义 alias 的 `migrate` EXIT=0 并写入 1,294,336 字节持久 sqlite；无警告 |
| 13 | 回归覆盖 | **部分通过（Important）** | `test_django_admin_check...` 实际执行 `python -m django`；旧直调 false-green 仍在；`help` 用可连接旧库而非坏库 |

## 2. 实测数字

| 项目 | 结果 |
|---|---|
| 全量 `pytest -q` | `540 passed, 5 warnings in 42.30s` |
| 定向 7 个 r8 用例 | `7 passed, 533 deselected` |
| `makemigrations --check --dry-run`（dev） | `No changes detected`，EXIT=0（PG 5432 警告仅告警） |
| `config.settings.test` `migrate` | EXIT=0（sqlite `:memory:`） |
| `config.settings.test` `makemigrations` | EXIT=0，`No changes detected` |
| `config.settings.test` `collectstatic` | EXIT=0，`0 static files copied` |
| `config.settings.test` `check` | EXIT=1，`IS_TEST_SETTINGS` |
| 旧库 `manage.py check --settings=prod` | EXIT=1，列出六账号 |
| 旧库 `manage.py check`（env prod） | EXIT=1，同上 |
| rotate 后 `manage.py check` | EXIT=0，`System check identified no issues` |
| 空库 `migrate --noinput` | EXIT=0 |
| 真实 `django-admin check` 旧库 | EXIT=1 |
| `python -m django check` 旧库 | EXIT=1 |
| `manage.py shell --settings=prod` | `MODULE=config.settings.prod`，`DEBUG=False` |
| `manage.py help` + 不可用 DB | EXIT=0 |
| 别名 + `import pytest` + 已知 ARK | EXIT=1（`IS_TEST_SETTINGS`） |
| 别名 + `config.wsgi` + `import pytest` | EXIT=1（`IS_TEST_SETTINGS`） |
| `runserver` 默认（旧库） | EXIT=1 |
| `runserver --noreload`（旧库） | EXIT=1 |
| `GUARD_CALLS` | **1** |
| `python -m pytest` 的 `sys.argv[0]` | `.../site-packages/pytest/__main__.py`，`CONTAINS=True` |
| `python -m unittest` + test settings | EXIT=1，无 traceback |
| 自定义 `from .prod import *; DEBUG=True` | EXIT=0，`DEBUG=True`，JWT `dev-secret-change-me...` |
| 自定义 test-settings alias + 持久 sqlite `migrate` | EXIT=0，生成 1,294,336 字节 DB；随后 `check` EXIT=1 |
| 真实 gunicorn `--preload`/`--reload` | **未测**（venv 未安装 gunicorn） |
| README 计数 | `:99` 540；`:5`、`:29` 仍是 522 |
| `DEPLOY.md:3` | 已改为 `ARK_SEED_PASSWORD` 指定，旧口令句已删 |

## 3. Critical

**无。**

C-R7-1 已关闭。我重点复核了三种可能重新变成 Critical 的路径：

1. **别名 + `import pytest`**：`running_under_tests()` 改为 `argv[0]` 入口判定后，`python -c "import pytest; ..."` 的 `argv[0]` 是 `-c`，不再被误判；实际 EXIT=1。真实 `python -m pytest` 的 `argv[0]` 是 `.../pytest/__main__.py`，被正确识别（实测 `CONTAINS=True`），测试套件本身 540 passed。
2. **`--settings` 降级**：`manage.py shell --settings=config.settings.prod` 打印 `MODULE=config.settings.prod`、`DEBUG=False`；旧库 `check --settings` EXIT=1。`CoreConfig.ready()` 在 settings 解析后执行，r6-C1 的机制已消除。
3. **旧库默认口令 + 服务**：`manage.py check`、`django-admin check`、`python -m django check` 全部 EXIT=1；`runserver` 默认/`--noreload` 都 EXIT=1。`os._exit(1)` 让 autoreload 父进程退出，没有留下可服务的进程。

## 4. Important

### I-R8-1 豁免命令绕过 `IS_TEST_SETTINGS`，自定义 test-settings 别名可迁移持久库且无提示

**位置**：
- `core/startup.py:298-314` — 先算 `exempt`，再 `validate_runtime_secrets(check_deployable=not exempt)`；`migrate` 等命中豁免时跳过 `_assert_settings_module_deployable()`
- `core/startup.py:88-114`（`:106`） — `check_deployable` 为 False 时不做测试配置拒绝
- `config/settings/test.py:5-9` — 默认 `DATABASES` 是 sqlite `:memory:`，所以**默认 test settings 的 migrate 不会碰持久库**；但 `from config.settings.test import *` 后覆盖 `DATABASES` 的别名不受保护

**复现**（`/tmp/e8r8/test_alias_db.py`）：

```python
from config.settings.test import *
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "/tmp/e8r8/alias-prod.sqlite3",
    }
}
```

```bash
env -u ARK_JWT_SECRET PYTHONPATH=/tmp/e8r8:. \
  DJANGO_SETTINGS_MODULE=test_alias_db \
  .venv/bin/python manage.py migrate --noinput
# EXIT=0
# Applying sysadmin.0017_resync_permissions... OK
# Applying transform.0001_initial... OK

ls -l /tmp/e8r8/alias-prod.sqlite3
# -rw-r--r-- 1 jacky wheel 1294336 ...

env -u ARK_JWT_SECRET PYTHONPATH=/tmp/e8r8:. \
  DJANGO_SETTINGS_MODULE=test_alias_db \
  .venv/bin/python manage.py check
# EXIT=1
# [启动自检] 拒绝启动：这份 settings 是测试配置（IS_TEST_SETTINGS）...
```

**判断**：
- 这不是默认路径：`config.settings.test` 本身固定 `:memory:`，默认 `migrate` 只在内存库执行，不会写入生产。
- 但“test settings 别名”正是前几轮反复出现的绕过形态；只要别名同时覆盖 `DATABASES`（例如为了复用测试 JWT/缓存配置而指向真实库），`migrate` 会以 EXIT=0 成功、**没有任何提示**，随后服务又被 `IS_TEST_SETTINGS` 拒绝。这是可造成“迁移了库但服务起不来”的运维事故，不需要凭据即可触发，因此列为 Important，而非 Critical。
- 用户问“是否需要额外提示”：需要。建议在 `enforce_process_guard` 的 exempt 分支对 `IS_TEST_SETTINGS` 打一行 stderr 警告，至少包含 settings 模块名和 `DATABASES["default"]["NAME"]`；或者只允许 `migrate` 豁免当 `DATABASES` 是 `:memory:`/测试库，否则拒绝。

### I-R8-2 回归覆盖仍有缺口：真实 `django-admin`、坏库 `help`、旧 false-green 直调

**位置**：
- `tests/test_deploy_hardening.py:609-613` — 用例名 `test_django_admin_check_blocks_legacy_db`，实际执行 `[sys.executable, "-m", "django", "check"]`；这是 `python -m django`，不是 `django-admin`。真实 `django-admin` 是我手工跑出来的 EXIT=1，未进套件。
- `tests/test_deploy_hardening.py:616-620` — `test_manage_help_still_works_on_legacy_db` 用的是**可连接的旧库**，不是坏库；docstring 说“库不可用/带病时也必须能看出这是哪个版本”，实际没覆盖坏库。我手工用 `/tmp/e8r8/no-such-dir/db.sqlite3` 验证 `help` EXIT=0，但套件没有。
- `tests/test_deploy_hardening.py:475-500` — 两条旧的 `test_manage_command_gate_*` 仍然 monkeypatch `_current_management_command` 后直接调用 `enforce_process_guard()`；它们在 `099bd56` 上也绿，属于 false-green。r8 新增的 541 行后的子进程用例才是真回归，但旧的两条没删/没改。
- `tests/test_deploy_hardening.py:640-658` — 别名用例用 `python -c "import pytest; ..."`，覆盖了“import 不应成为开关”，但没有覆盖真实 `pytest` 入口；真实入口由 540 全量套件间接覆盖。

**判断**：生产行为已手工验证通过；缺口主要让未来回归可能再次“单测绿、入口坏”。建议把 `django-admin` 改成真实 `django-admin` 调用（`PYTHONPATH=.`），`help` 用不可连接 DB，删除/改写 475-500 的直调用例。

## 5. Minor

- **M-R8-1**：`README.md:5`、`:29` 仍写 522，`:99` 已是 540；用户称“README 计数 540”只改了示例行。
- **M-R8-2**：`core/startup.py:8-10` 模块 docstring 仍说调用点是 `config/wsgi.py`、`config/asgi.py`、`config/settings/prod.py`、`manage.py`；r8 已单点化到 `core/apps.ready()`，注释过期。
- **M-R8-3**：`core/startup.py:94-97` 仍说“必须由环境变量 `ARK_JWT_SECRET` 显式提供”，实现校验的是生效的 `settings.JWT_SECRET`；与 r7 相同。
- **M-R8-4**：`python -m unittest` + `config.settings.test` 现在被 `os._exit(1)` 直接杀掉，只有一行 stderr、没有 traceback。测试配置名义上“仅供 pytest”，但 `unittest`/程序化 `pytest.main()` 都是合法测试入口；这是 `ready()` 里 `os._exit` 的误伤面。
- **M-R8-5**：`running_under_tests()` 的 `"/pytest/" in argv[0]` 在 Windows 上经 `os.sep` 替换后可用（`C:\...\pytest\__main__.py` -> `C:/.../pytest/__main__.py`），venv 的 `pytest`/`py.test` 入口也可用；但任何恰好位于 `/pytest/` 目录下的 `__main__.py` 会被误判为测试进程，且 `python -c "pytest.main()"` 这类包装入口会被误判为“非测试”，触发 `os._exit`。入口判定比 `sys.modules` 可靠，但仍不是安全边界。
- **M-R8-6**：`os._exit(1)` 跳过 `atexit`、Django 连接关闭和 gunicorn worker 的异常处理。`gunicorn --preload` 会在 master 执行 `ready()`，`os._exit` 在 bind 前终止 master，行为合理；`gunicorn --reload` 下 worker 退出后 master 可能反复重启，只留一行日志，形成 crash loop。未安装 gunicorn，未实测，建议在部署文档明确“生产不要用 `--reload`”，并给 `--reload` 场景加 backoff/文档说明。
- **M-R8-7**：`manage.py help`/`version` 虽然豁免凭据扫描，但 `validate_runtime_secrets` 仍校验 JWT；`prod` 下没有 `ARK_JWT_SECRET` 时 `help` 也会失败。纯信息命令是否应完全不需要密钥，可再讨论。
- **M-R8-8**：`config/settings/prod.py:21` 注释说“密钥与默认口令实际校验放在 ready（enforce_process_guard）”，正确；`core/apps.py:44` 注释写“SIGTERM(124)”，实际 `timeout` 返回 124 是 timeout 的退出码，不是 SIGTERM 的数字，注释不精确。

## 6. 关键复现命令与输出

### 6.1 r7-C1 已关闭

```bash
cat >/tmp/e8r8/mydeploy.py <<'PY'
from config.settings.test import *
PY

env ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r8-alias.sqlite3 \
  ARK_JWT_SECRET='R8-Known-JWT-000000000000000000000000' \
  PYTHONPATH=/tmp/e8r8:. DJANGO_SETTINGS_MODULE=mydeploy \
  .venv/bin/python -c "import pytest; import django; django.setup(); print('SETUP_OK')"
# EXIT=1
# [启动自检] 拒绝启动：这份 settings 是测试配置（IS_TEST_SETTINGS）...

env ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r8-alias.sqlite3 \
  ARK_JWT_SECRET='R8-Known-JWT-000000000000000000000000' \
  PYTHONPATH=/tmp/e8r8:. DJANGO_SETTINGS_MODULE=mydeploy \
  .venv/bin/python -c "import pytest; from config.wsgi import application; print('WSGI_OK')"
# EXIT=1
# 同上
```

真实 `python -m pytest` 入口：

```text
ARGV0= '/Users/.../.venv/lib/python3.13/site-packages/pytest/__main__.py'
BASENAME= __main__.py
CONTAINS= True
```

### 6.2 runserver 不再挂住

```bash
export ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r8-old2.sqlite3
export ARK_JWT_SECRET='R8-Str0ng-JWT-Secret-000000000000'
DJANGO_SETTINGS_MODULE=config.settings.prod timeout 15 \
  .venv/bin/python manage.py runserver 127.0.0.1:8992
# EXIT=1（不是 124）
# [启动自检] 拒绝启动：检测到仍在使用仓库默认口令的账号...
```

### 6.3 单点扫描

```bash
env ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r8-empty.sqlite3 \
  ARK_JWT_SECRET='R8-Str0ng-JWT-Secret-000000000000' \
  DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/python - <<'PY'
import core.startup as s
calls = []
orig = s.enforce_process_guard
def wrapped(*a, **k):
    calls.append(1)
    return orig(*a, **k)
s.enforce_process_guard = wrapped
import django
django.setup()
import config.wsgi
print("GUARD_CALLS", len(calls))
PY
# GUARD_CALLS 1
```

### 6.4 test settings 命令

```bash
DJANGO_SETTINGS_MODULE=config.settings.test \
  .venv/bin/python manage.py migrate --noinput
# EXIT=0（sqlite :memory:）

DJANGO_SETTINGS_MODULE=config.settings.test \
  .venv/bin/python manage.py makemigrations --check --dry-run
# EXIT=0  No changes detected

DJANGO_SETTINGS_MODULE=config.settings.test \
  .venv/bin/python manage.py collectstatic --noinput
# EXIT=0  0 static files copied

DJANGO_SETTINGS_MODULE=config.settings.test \
  .venv/bin/python manage.py check
# EXIT=1  IS_TEST_SETTINGS
```

### 6.5 `--settings` / 真实 `django-admin`

```bash
export ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r8-old2.sqlite3
export ARK_JWT_SECRET='R8-Str0ng-JWT-Secret-000000000000'

.venv/bin/python manage.py shell -c "from django.conf import settings; \
  print('MODULE=', __import__('os').environ.get('DJANGO_SETTINGS_MODULE')); \
  print('DEBUG=', settings.DEBUG)" --settings=config.settings.prod
# MODULE= config.settings.prod
# DEBUG= False

PYTHONPATH=. DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/django-admin check
# EXIT=1

PYTHONPATH=. DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/python -m django check
# EXIT=1
```

### 6.6 坏库 help

```bash
ARK_DB_NAME=/tmp/e8r8/no-such-dir/db.sqlite3 \
  DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/python manage.py help
# EXIT=0
```

### 6.7 自定义 test alias 迁移持久库（Important）

见 I-R8-1；`/tmp/e8r8/alias-prod.sqlite3` 生成 1,294,336 字节，随后 `manage.py check` 被 `IS_TEST_SETTINGS` 拒绝。

### 6.8 非 pytest 测试运行器

```bash
cat >/tmp/e8r8/unittest/test_smoke.py <<'PY'
import unittest, django
django.setup()
from django.conf import settings
class T(unittest.TestCase):
    def test_settings(self):
        self.assertFalse(settings.DEBUG)
PY

cd backend-django
DJANGO_SETTINGS_MODULE=config.settings.test \
  PYTHONPATH=/tmp/e8r8/unittest:. \
  .venv/bin/python -m unittest -q test_smoke
# EXIT=1
# [启动自检] 拒绝启动：这份 settings 是测试配置（IS_TEST_SETTINGS）...
# （没有 unittest 的 traceback）
```

## 7. 回归与卫生

- `540 passed, 5 warnings in 42.30s`；定向 7 个 r8 用例 `7 passed`。
- `makemigrations --check --dry-run`（dev）`No changes detected`，EXIT=0。
- `git diff --stat a83c409..f869c72`：29 files，+1471/−59；r8-only 7 files，+117/−40。
- `git diff --stat a83c409..f869c72 -- design frontend/src/api/schema`：空，零 diff。
- `git show --name-only f869c72`：`DEPLOY.md`、`README.md`、`config/asgi.py`、`config/wsgi.py`、`core/apps.py`、`core/startup.py`、`tests/test_deploy_hardening.py`；无夹带。
- 前端 10 个冒烟脚本 `node --check` 全 OK；`DEMO_PASSWORDS` 已删除，`ARK_SMOKE_PASSWORD` 必填。
- `README:5/29` 仍 522；`README:99` 540；`DEPLOY:3` 已改为 `ARK_SEED_PASSWORD` 指定。

## 8. 合并门槛（§8）

1. **修 I-R8-1**：对 `IS_TEST_SETTINGS` + 豁免命令（尤其 `migrate`）加显式警告并输出 `DATABASES` 目标；或仅允许 `:memory:` 测试库豁免，否则拒绝。补“test settings alias + 持久 sqlite migrate 不应静默成功”的回归。
2. **修 I-R8-2**：`test_django_admin_check_blocks_legacy_db` 改为真实 `django-admin`；`help` 用不可连接 DB；删除/改写 `tests/test_deploy_hardening.py:475-500` 的直调 false-green；补 `python -c "pytest.main()"` / `unittest` 的明确预期（支持或文档声明不支持）。
3. **Minor 清理**：`README.md:5/29` 统一 540；`core/startup.py:8-10` 与 `:94-97` 注释更新；`core/apps.py:44` 的 “SIGTERM(124)” 修正；部署文档写明 `os._exit` 与 `gunicorn --reload` 的边界。
4. 复跑：旧库 `manage.py check` / `--settings` / 真实 `django-admin` / `python -m django` 均 EXIT=1；别名 + `import pytest` 的 `django.setup`/wsgi 均 EXIT=1；默认 `runserver` 旧库 EXIT=1；`GUARD_CALLS=1`；test settings `migrate`/`makemigrations`/`collectstatic` EXIT=0；全量 pytest ≥540；dev `makemigrations` No changes；design/schema 零 diff；前端 `node --check` 全过。

## 9. 通过项与未测项

**通过**：
- 无 ARK 的 prod 启动失败（`django.setup` / `manage.py` / `python -m django` / `django-admin`）。
- 旧库 `manage.py check`、`--settings`、env、真实 `django-admin`、`python -m django` 全部 EXIT=1；rotate 后 EXIT=0；空库 migrate EXIT=0。
- `--settings=config.settings.prod` 不再被提前 setup 降级；`shell --settings` 打印 prod / `DEBUG=False`。
- 别名 + `import pytest` + 已知 ARK 的 `django.setup`/`config.wsgi` 均 EXIT=1。
- 默认 `runserver` 与 `--noreload` 旧库均 EXIT=1。
- `GUARD_CALLS=1`；`config.wsgi` 不再调用 guard。
- test settings `migrate`/`makemigrations`/`collectstatic` EXIT=0；`check` EXIT=1。
- 前端 10 个冒烟脚本 `node --check` 全过，旧口令表删除。
- `540 passed`、dev `makemigrations` No changes、design/schema 零 diff。

**未测 / 边界**：
- 未装 gunicorn，未实测 `--preload` / `--reload`；`os._exit` 的 gunicorn 行为按代码推理，`--reload` 可能 crash-loop。
- 未在 Windows 实机跑 `python -m pytest`；按 `os.path.basename` + `os.sep` 替换推理，路径判定可用。
- 未跑完整 `docker compose up --build`；C-1 仍用 compose config + prod/sqlite 等价验证。
- 未跑真实 PG/Redis/MinIO/nginx 端到端。
