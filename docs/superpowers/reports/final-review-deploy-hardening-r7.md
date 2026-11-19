# E-8 部署收口 · 第七轮终审（r7）

- 仓库：`/Users/jacky/works/science-research-project`
- 分支：`develop`
- 审查范围：`a83c409..a459b4c`（6 个 commit，本轮新增 `a459b4c`）
- 计划：`docs/superpowers/plans/2026-11-19-deploy-hardening.md`
- ledger：`.superpowers/sdd/2026-11-19-deploy-hardening/progress.md`
- diff 包：`/tmp/review-deploy-hardening-r7.diff`
- 审查方式：只读；本轮唯一写入是本报告
- 环境：`backend-django/.venv/bin/python`，Python 3.13，Django 5.x，pytest 9.x

## 0. 结论

**VERDICT: REQUEST_CHANGES**

C1（`--settings` 被提前 `django.setup()` 降级）已实测修复：`manage.py check --settings=config.settings.prod` 在旧库上 exit 1，`DJANGO_SETTINGS_MODULE` 同结果；`manage.py shell --settings=...` 打印的是 prod / `DEBUG=False`；rotate 后 exit 0，空库 migrate exit 0。

C2（`import *` 别名）在“普通进程”下已修复：别名模块被 `IS_TEST_SETTINGS` 拦住；测试配置的 JWT 已改为随机值。

但仍有 **1 条 Critical**：`running_under_tests()` 只要进程里出现 `pytest` 就短路 `IS_TEST_SETTINGS` 检查。实测 `mydeploy.py: from config.settings.test import *` + `import pytest` + 已知 `ARK_JWT_SECRET` 时，`django.setup()` 和 `config.wsgi` 都能成功启动（`SETUP_OK` / `WSGI_OK`），而该配置是 `DEBUG=False`、`ALLOW_DEMO_SEED=True`。这不是默认启动路径，但它使“测试配置不可部署”在一种可出现的生产/预发镜像里失效，属于上一轮 C2 的残留绕过。

另外有 4 条 Important：默认 autoreload 的 `runserver` 在守卫失败时**不退出**（8 秒超时仍存活）；`ready()` 与 `wsgi/asgi` 重复执行凭据扫描（实测 `ASSERT_CALLS=2`）；`config.settings.test` 下 `migrate` / `makemigrations` / `collectstatic` 全部被 `IS_TEST_SETTINGS` 拒绝；本轮新增的“真子进程”测试里仍有一条把 `python -m django` 写成 `django-admin` 的覆盖缺口，且两条旧 false-green 直调用例还在。

## 1. 必查矩阵

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| 1 | 无 `ARK_JWT_SECRET` 时 prod 启动必须失败 | **通过** | no-ARK `django.setup()` / `manage.py check` / `python -m django check` / `django-admin check` 均 EXIT=1；`manage.py` 输出一行 `[启动自检] 拒绝启动：...` |
| 2 | `ARK_SEED_DEMO=1` 无 `ARK_SEED_PASSWORD` 且非 dev 必须拒绝 | **通过** | prod + `ARK_SEED_DEMO=1` 无口令 -> `CommandError`；`--force` 无口令同样拒绝；`--force` + `Demo@123456` 拒绝 |
| 3 | 未设 `ARK_API_DOCS` 且 `DEBUG=False` 时 docs 不存在 | **通过（沿用 r5 实测）** | `docs_enabled()=False`，`api.docs_url=None`，`/api/v1/docs`、`/api/v1/openapi.json` 均 404 |
| 4 | `--settings=config.settings.prod` 不得被降级 | **通过** | `manage.py check --settings=...` 旧库 EXIT=1；`shell --settings=...` 打印 `MODULE=config.settings.prod`、`DEBUG=False`；`runserver --settings=...` 被拦 |
| 5 | `django-admin` / `python -m django` 同样过凭据门禁 | **通过** | 旧库上两者均 EXIT=1；`django-admin` 需要 `PYTHONPATH=.` 才能找到 `config`（部署环境自然满足） |
| 6 | 测试配置别名不可部署 | **部分通过** | 无 `pytest` 时别名被 `IS_TEST_SETTINGS` 拒绝；但 `import pytest` 后绕过（见 C-R7-1） |
| 7 | 新增回归在旧代码上真红 | **部分通过** | 旧树 `099bd56` + 当前测试：`4 failed, 1 passed`；`test_manage_check[env-settings-module]` 旧代码本来就会拦，不能算新回归；两条旧直调用例仍 false-green |
| 8 | 全量测试 / 迁移 / 零 diff | **通过** | `537 passed, 5 warnings in 41.09s`；dev `makemigrations --check` -> `No changes detected`；`design` + `frontend/src/api/schema` 零 diff |

## 2. 实测数字

| 项目 | 结果 |
|---|---|
| 全量 `pytest -q` | `537 passed, 5 warnings in 41.09s` |
| 定向 `pytest -q -k "manage_check_blocks or django_admin_check or manage_help or alias_test_settings or deploy or seed"` | `40 passed, 497 deselected` |
| `makemigrations --check --dry-run`（dev） | `No changes detected`，EXIT=0（PG 5432 连接警告仅告警） |
| `makemigrations --check --dry-run`（test settings） | **EXIT=1**，`[启动自检] 拒绝启动：这份 settings 是测试配置（IS_TEST_SETTINGS）...` |
| 旧树 `099bd56` + 当前测试（5 个候选） | `4 failed, 1 passed`，7.25s |
| `config.wsgi` 启动时 `assert_no_default_credentials()` 调用次数 | **2**（`core.apps.ready()` + `config/wsgi.py:15`） |
| `runserver`（默认 autoreload）旧库 | `timeout 8` 后 EXIT=124；traceback 在 `django-main-thread`，父进程仍存活 |
| `runserver --noreload` 旧库 | EXIT=1，干净的一行拒绝信息 |
| 旧库 `manage.py check` / `--settings` / env | 均 EXIT=1，列出六个默认账号 |
| rotate 后 `manage.py check` | EXIT=0，`System check identified no issues (0 silenced).` |
| 空库 `migrate --noinput` | EXIT=0 |
| `django-admin check` 旧库 | EXIT=1（带 `PYTHONPATH=.`） |
| `python -m django check` 旧库 | EXIT=1 |
| `manage.py help` + 不可用 DB | EXIT=0（help 豁免） |
| `config.settings.test` 别名 + 无 pytest | EXIT=1，`IS_TEST_SETTINGS` |
| 别名 + `import pytest` + 已知 ARK | **EXIT=0，`SETUP_OK` / `WSGI_OK`**（C-R7-1） |
| `python -m unittest` + test settings | EXIT=1（`IS_TEST_SETTINGS`；非 pytest 测试运行器误伤） |
| `cdn`/前端冒烟脚本 `node --check` | 10 个脚本全部 OK；旧口令表已删除，`ARK_SMOKE_PASSWORD` 必填 |
| README 计数 | `:99` 已 537；`:5`、`:29` 仍是 522 |
| `DEPLOY.md:3` | 仍写演示账号 `admin / Admin@123456` |

## 3. Critical

### C-R7-1 `import pytest` 使 `IS_TEST_SETTINGS` 失效，测试配置仍可启动 WSGI

**位置**：
- `backend-django/core/startup.py:33-42` — `running_under_tests()` 用 `"pytest" in sys.modules` 判定“测试进程”
- `backend-django/core/startup.py:56-57` — `if running_under_tests(): return`，在检查 `IS_TEST_SETTINGS` 之前直接放行
- `backend-django/core/startup.py:92-99` — `validate_runtime_secrets()` 调用上述检查
- `backend-django/config/settings/test.py:17,24,28` — `ALLOW_DEMO_SEED=True`、JWT 随机/可被 ARK 覆盖、`IS_TEST_SETTINGS=True`

**复现**（`/tmp/e8r7/mydeploy.py` 内容 `from config.settings.test import *`）：

```bash
env ARK_JWT_SECRET='R7-Known-Test-JWT-Secret-000000000000' \
  PYTHONPATH=/tmp/e8r7:. \
  ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r7-alias.sqlite3 \
  DJANGO_SETTINGS_MODULE=mydeploy \
  .venv/bin/python -c "import pytest, django; django.setup(); \
    from django.conf import settings; \
    print('SETUP_OK', settings.DEBUG, settings.IS_TEST_SETTINGS)"
# EXIT=0
# SETUP_OK False True
```

```bash
env ARK_JWT_SECRET='R7-Known-Test-JWT-Secret-000000000000' \
  PYTHONPATH=/tmp/e8r7:. \
  ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r7-alias.sqlite3 \
  DJANGO_SETTINGS_MODULE=mydeploy \
  .venv/bin/python -c "import pytest; from config.wsgi import application; print('WSGI_OK')"
# EXIT=0
# WSGI_OK
```

无 `import pytest` 时同一别名被正确拒绝（`IS_TEST_SETTINGS`，EXIT=1）。差异完全来自 `sys.modules`。

**为什么算 Critical（有条件）**：
- 如果生产/预发镜像包含 pytest（或任何依赖在启动时 import pytest），而部署者选择了 `config.settings.test` 或其别名，`IS_TEST_SETTINGS` 这道“不可部署”标记被静默跳过；
- 该配置 `ALLOW_DEMO_SEED=True`，若再执行 `seed_demo`，会生成公开口令账号；若 `ARK_JWT_SECRET` 在该环境已知，JWT 可伪造；
- 这不是默认 `docker compose` 路径，因此我把触发条件写清楚；但在“测试配置不可部署”的承诺下，它是残留绕过，应阻断合并。

**修复建议**：
- `enforce_serving_guard()` 不应调用带 `running_under_tests()` 短路的 `validate_runtime_secrets()`；服务进程必须无条件拒绝 `IS_TEST_SETTINGS`（即使 pytest 已 import）。
- 或者把“是否测试进程”改为显式、不可由业务依赖触发的信号（例如 `PYTEST_CURRENT_TEST` + `--test` 子命令 + 启动入口白名单），不要把 `sys.modules` 当安全边界。
- 新增回归：别名 + `import pytest` + `config.wsgi` 必须 EXIT≠0；同时覆盖 `config.settings.test` 直用。

## 4. Important

### I-R7-1 `runserver` 默认 autoreload 在守卫失败时不退出；`--noreload` 才 exit 1

**位置**：`core/apps.py:8-32`（异常在 `ready()` 中抛出），Django autoreload 的 `django-main-thread` 捕获后只打印 traceback。

**实测**（旧库 `/tmp/e8r7-old2.sqlite3`，prod，强密钥）：

```text
manage.py runserver 127.0.0.1:8897 --noreload  -> EXIT=1，一行拒绝信息
manage.py runserver 127.0.0.1:8896              -> timeout 8 后 EXIT=124
  Exception in thread django-main-thread:
  ...
  ImproperlyConfigured: 检测到仍在使用仓库默认口令的账号...
```

父进程没有退出，也没有绑定端口，CI/本地脚本会**挂住**而不是快速失败。`runserver` 不是生产入口，但这是可观测的回归；且用户特别问了 autoreload 双进程行为。

### I-R7-2 `ready()` 与 `wsgi/asgi` 重复扫描，每个进程至少两次 bcrypt 检查

**位置**：
- `core/apps.py:8-32` — 每个 Django 进程在 `ready()` 调 `enforce_process_guard()`
- `config/wsgi.py:13-15`、`config/asgi.py:13-15` — 再次 `enforce_serving_guard()`
- `core/startup.py:299,305` — 两次都会走 `assert_no_default_credentials()`

**实测**（干净库、prod、强密钥，monkeypatch 计数）：

```text
ASSERT_CALLS= 2
APP= WSGIHandler
```

`gunicorn -w 4` 即 8 次扫描；每次对六个账号做 bcrypt。旧库命中时第一次就拒绝，所以不是“重复报错”，而是**干净库/每次重启的固定启动成本**。`runserver` autoreload 的父/子进程还会再乘 2。建议只保留 `ready()` 一处，或让 `wsgi/asgi` 只调用不查库的密钥检查。

### I-R7-3 `config.settings.test` 下 `migrate` / `makemigrations` / `collectstatic` 全部被拒绝

`IS_TEST_SETTINGS` 在 `enforce_process_guard()` 中先于 `GUARD_EXEMPT_COMMANDS` 判断；这些命令即使本应豁免，也会在 `ready()` 阶段被拒绝：

```bash
DJANGO_SETTINGS_MODULE=config.settings.test python manage.py makemigrations --check --dry-run
# EXIT=1  [启动自检] 拒绝启动：这份 settings 是测试配置（IS_TEST_SETTINGS）...

DJANGO_SETTINGS_MODULE=config.settings.test python manage.py migrate --noinput
# EXIT=1 同上

DJANGO_SETTINGS_MODULE=config.settings.test python manage.py collectstatic --noinput
# EXIT=1 同上
```

默认 dev 的 `makemigrations` 仍为 `No changes detected`，所以 README 的默认路径没坏；但任何用 test settings 做 CI 迁移/静态文件的流程会坏。需要明确“test settings 只允许 pytest”，还是让豁免命令先于 `IS_TEST_SETTINGS`。

### I-R7-4 自定义 settings `from .prod import *; DEBUG=True` 静默放宽全部检查

```bash
# /tmp/e8r7/custom_debug.py
from config.settings.prod import *
DEBUG = True

env -u ARK_JWT_SECRET PYTHONPATH=/tmp/e8r7:. \
  ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r7-old2.sqlite3 \
  DJANGO_SETTINGS_MODULE=custom_debug \
  .venv/bin/python -c "import django; django.setup(); \
    from django.conf import settings; print('DEBUG=', settings.DEBUG); print('JWT=', settings.JWT_SECRET)"
# EXIT=0
# DEBUG= True
# JWT= dev-secret-change-me-please-use-32-bytes-min!
```

`validate_runtime_secrets()` / `enforce_process_guard()` 都在 `DEBUG` 为真时直接 return；`config.wsgi` 也不会调用 serving guard。显式 `DEBUG=True` 是开发者选择，我不把它单独列为 Critical；但“继承 prod 再写回 DEBUG=True”是很自然的误配置，建议在 `ready()` 对 `IS_TEST_SETTINGS` 之外的 prod 派生配置给出显式警告，或在文档中把 `DEBUG=True` 定义为“仅本地 dev，永不部署”。

### I-R7-5 回归测试仍有覆盖缺口与 false-green

- `tests/test_deploy_hardening.py:608-612` 的测试名是 `test_django_admin_check_blocks_legacy_db`，实际执行的是 `python -m django check`，**没有真正跑 `django-admin`**；真实 `django-admin` 是我手工验证的（EXIT=1）。
- `tests/test_deploy_hardening.py:475-500` 两条旧的 `test_manage_command_gate_*` 仍然 monkeypatch `_current_management_command` 后直接调用 `enforce_process_guard()`；它们在旧代码上也绿，用户所说的“改写为真子进程”只新增了 541 行后的用例，没有删掉这两条 false-green。
- `tests/test_deploy_hardening.py:615-619` 的 `help` 用例用的是**可连接的旧库**，不是“DB 不可用”；docstring 说“库不可用/带病”，实际没覆盖坏库。
- `tests/test_deploy_hardening.py:519-532` 的 `test_demo_seed_switch` 没有 `django_db`；旧树失败是 `RuntimeError: Database access not allowed`，不是预期的 `CommandError`，测试通过原因不纯粹。

## 5. Minor

- **M-R7-1**：`README.md:5` 与 `:29` 仍是 `522`，`:99` 已是 `537`；用户声称“522→537”只改了一处。
- **M-R7-2**：`DEPLOY.md:3` 仍写演示账号 `admin / Admin@123456`；虽然文件自称“旧 Node 参考栈”，但开头是可直接照抄的 compose 说明，建议加显著“历史文档，口令已废弃”或删除该句。
- **M-R7-3**：`core/startup.py:82-85` docstring 仍说“必须由环境变量 `ARK_JWT_SECRET` 显式提供”，实现已改为校验生效的 `settings.JWT_SECRET`；注释与行为不一致。
- **M-R7-4**：`django-admin check` / `python -m django check` 失败时是整段 traceback，`manage.py` 才是干净的一行；不是功能错误，但运维体验不一致。
- **M-R7-5**：`core/startup.py:295` 的 `running_under_tests()` 在 `enforce_process_guard` 中还会跳过**凭据门禁**（不只是 settings 可部署性）；与 C-R7-1 同源，修复时应一并处理。
- **M-R7-6**：`config/settings/test.py:24` 的随机 JWT 每个进程不同；若未来引入 pytest-xdist 多 worker，跨 worker 令牌不通用，需要固定测试密钥或 worker 级共享。

## 6. 关键复现命令与输出

### 6.1 `--settings` 已修复

```bash
export ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r7-old.sqlite3
export ARK_JWT_SECRET='R7-Str0ng-JWT-Secret-000000000000'

.venv/bin/python manage.py check --settings=config.settings.prod
# EXIT=1
# [启动自检] 拒绝启动：检测到仍在使用仓库默认口令的账号：admin、manager、staff、finance、partner、expert_ext...

DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py check
# EXIT=1 同上

.venv/bin/python manage.py shell -c "from django.conf import settings; \
  print('MODULE=', __import__('os').environ.get('DJANGO_SETTINGS_MODULE')); \
  print('DEBUG=', settings.DEBUG); print('JWT=', settings.JWT_SECRET[:20])" \
  --settings=config.settings.prod
# EXIT=0
# MODULE= config.settings.prod
# DEBUG= False
# JWT= R7-Str0ng-JWT-Secret

.venv/bin/python manage.py rotate_demo_credentials \
  --password 'R7-Rotated-Passw0rd-2026!' --settings=config.settings.prod
# EXIT=0  已轮换 6 个账号...

.venv/bin/python manage.py check --settings=config.settings.prod
# EXIT=0  System check identified no issues (0 silenced).

ARK_DB_NAME=/tmp/e8r7-empty.sqlite3 .venv/bin/python manage.py migrate \
  --noinput --settings=config.settings.prod
# EXIT=0
```

### 6.2 `django-admin` / `python -m django` 已接门禁

```bash
PYTHONPATH=. DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/django-admin check
# EXIT=1  ImproperlyConfigured: 检测到仍在使用仓库默认口令的账号...

PYTHONPATH=. DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/python -m django check
# EXIT=1  同上
```

### 6.3 测试配置别名（无 pytest）已被拒绝

```bash
# /tmp/e8r7/mydeploy.py
from config.settings.test import *

env -u ARK_JWT_SECRET PYTHONPATH=/tmp/e8r7:. \
  DJANGO_SETTINGS_MODULE=mydeploy \
  .venv/bin/python -c "import django; django.setup()"
# EXIT=1
# ImproperlyConfigured: 这份 settings 是测试配置（IS_TEST_SETTINGS）...
```

### 6.4 `runserver` 两种行为

```text
runserver --noreload  -> EXIT=1（干净拒绝）
runserver（默认 reload）-> timeout 8 后 EXIT=124，traceback 在 django-main-thread，父进程不退出
```

### 6.5 重复扫描计数

```bash
env ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r7-old.sqlite3 \
  ARK_JWT_SECRET='R7-Str0ng-JWT-Secret-000000000000' \
  DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/python - <<'PY'
import core.startup as s
calls = {"n": 0}
orig = s.assert_no_default_credentials
def counted(*a, **k):
    calls["n"] += 1
    return orig(*a, **k)
s.assert_no_default_credentials = counted
from config.wsgi import application
print("ASSERT_CALLS=", calls["n"])
PY
# ASSERT_CALLS= 2
```

## 7. 回归与卫生

- `537 passed, 5 warnings in 41.09s`；定向 40 passed。
- `makemigrations --check --dry-run`（dev）`No changes detected`，EXIT=0。
- `git diff --stat a83c409..a459b4c`：28 files，+1391/−56；r7-only 14 files，+268/−78。
- `git diff --stat a83c409..a459b4c -- design frontend/src/api/schema`：空，零 diff。
- 前端 10 个冒烟脚本 `node --check` 全 OK；`DEMO_PASSWORDS` 已删除，`ARK_SMOKE_PASSWORD` 必填。
- 工作区仍有与本轮无关的未跟踪 `frontend/pnpm-lock.yaml`、`frontend/pnpm-workspace.yaml`、`backend-django/uv.lock`；未进入 `a459b4c`。

## 8. 合并门槛（§8）

1. **修 C-R7-1**：`config.wsgi` / `config.asgi` 的 serving guard 必须无条件拒绝 `IS_TEST_SETTINGS`；`running_under_tests()` 不能成为部署守卫的短路条件。新增“别名 + `import pytest` + WSGI”回归。
2. **修 I-R7-1 / I-R7-2**：`runserver` 默认 autoreload 失败应退出；去掉 `ready()` 与 `wsgi/asgi` 的重复扫描（只保留一处），并给出启动耗时。
3. **修 I-R7-3**：明确 test settings 的管理命令策略；若 `migrate` / `makemigrations` / `collectstatic` 仍应可用，豁免判断要放在 `IS_TEST_SETTINGS` 之前。
4. **修 I-R7-4**：对 `from .prod import *; DEBUG=True` 给出显式警告或拒绝；文档禁止将 DEBUG=True 作为部署配置。
5. **修 I-R7-5**：补真正的 `django-admin` 回归、坏库 `help` 回归；删除或改写 475-500 的 false-green；给 `test_demo_seed_switch` 加 `django_db`。
6. **文档**：`README.md:5/29` 统一 537；`DEPLOY.md:3` 删除旧口令或标注历史；`core/startup.py:82-85` 注释改为“校验生效的 settings.JWT_SECRET”。
7. 复跑：无 ARK 的 `django.setup`/`manage.py check` 必须 exit 1；旧库 `manage.py check`、`--settings`、`django-admin`、`python -m django` 必须 exit 1；rotate 后 exit 0；空库 migrate exit 0；全量 pytest ≥537；`makemigrations` No changes；`design`/schema 零 diff；前端脚本 `node --check` 全过。

## 9. 通过项与未测项

**通过**：
- 无 ARK 的 prod 启动失败（`django.setup` / `manage.py` / `python -m django` / `django-admin`）。
- 旧库 `manage.py check` / `--settings` / env 全部 exit 1；rotate 后 exit 0；空库 migrate exit 0。
- `manage.py shell --settings=prod` 不再降级（打印 prod、DEBUG=False）。
- `django-admin` / `python -m django` check 已走凭据门禁。
- `config.settings.test` 普通别名被 `IS_TEST_SETTINGS` 拒绝；随机 JWT 不再固定。
- prod seed 拒绝 `Demo@123456` / 无口令 / `--force` 无口令；强口令 rotate 六账号。
- `help` 在 prod 坏库上 exit 0。
- 前端 10 个冒烟脚本 `node --check` 全过，旧口令表删除。
- `537 passed`、`makemigrations`（dev）No changes、design/schema 零 diff。

**未测 / 边界**：
- 未跑完整 `docker compose up --build`；compose 只做了 `docker compose config` 与 prod/sqlite 等价验证。
- 未接真实 PG/Redis/MinIO/nginx 做端到端。
- 未跑 `gunicorn` 多 worker 启动计时；重复扫描是按 `config.wsgi` 计数与代码路径判定。
- `django-admin` 需要 `PYTHONPATH` 才能找到 `config`（容器/安装包环境自然满足；本地裸跑需注意）。
