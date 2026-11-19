# E-8 部署收口 · 第六轮终审（r6）

- **仓库**：`/Users/jacky/works/science-research-project`
- **分支**：`develop`
- **审查范围**：`a83c409..099bd56`（6 commits；本轮新增 `099bd56`）
- **本轮提交**：`099bd56 fix(config): 管理命令走完整守卫 + 测试配置不可部署（E-8 终审 r5）`
- **计划**：`docs/superpowers/plans/2026-11-19-deploy-hardening.md`
- **Ledger**：`.superpowers/sdd/2026-11-19-deploy-hardening/progress.md`
- **diff 包**：`/tmp/review-deploy-hardening-r6.diff`（87115 bytes）
- **审查方式**：只读代码审查 + 独立复现；除本报告外未修改仓库任何文件
- **日期**：2026-11-19

## 0. 结论

**VERDICT: REQUEST_CHANGES**

r6 修好了 r5 的主路径：`manage.py check` 在旧库上不再假绿，`rotate_demo_credentials` 能自愈，空库 `migrate` 正常，生产播种继续拒绝内置口令。这些是本轮的真实进步，已逐条复现。

但本轮引入了两个仍可造成**公开凭据被使用 / 生产配置被静默降级**的缺陷，且都不是理论问题：

1. **`manage.py --settings=config.settings.prod` 被静默忽略**：`_validate_if_prod()` 在 Django 解析 `--settings` 之前就实例化了 `settings`，实际运行的是 `config.settings.dev`（`DEBUG=True`、仓库 dev 密钥）。我实测用该参数对旧库启动 `runserver`，`admin/Admin@123456` 直接拿到 `R-ADMIN` token（HTTP 200）。
2. **`config.settings.test` 的别名配置仍可部署**：`from config.settings.test import *` 这类自定义 settings 绕过了 `_assert_settings_module_deployable()` 的精确模块名判断；`django.setup()` 与 `config.wsgi` 都能启动，且使用仓库公开的固定测试 JWT 密钥。

因此本轮不能合并。下面给出可复现证据、严重级别与合并门槛。

## 1. 必查项矩阵

| # | 检查项 | 结论 | 关键证据 |
|---|---|---|---|
| 1 | 旧库上 `manage.py check` 必须失败 | **通过** | 旧库 + 强密钥：`ImproperlyConfigured`，EXIT=1；`rotate` 后 EXIT=0 |
| 2 | 空库 `migrate` 必须正常 | **通过** | 空 sqlite + 强密钥：EXIT=0 |
| 3 | `manage.py` 非豁免命令应走完整守卫 | **部分通过** | `manage.py check` 已拦；但 `--settings` 路径降级为 dev（见 C-R6-1） |
| 4 | `django-admin` / `python -m django` 也应过守卫 | **未完全通过** | 旧库 `django-admin check` / `python -m django check` 均 EXIT=0（见 I-R6-1）；`runserver` 因加载 `config.wsgi` 会被拦 |
| 5 | 生产不得能启动 `config.settings.test` 或其别名 | **失败** | `from config.settings.test import *` 别名 `SETUP_OK`、`WSGI_OK`（见 C-R6-2） |
| 6 | 生产播种拒绝内置/空口令 | **通过** | `Demo@123456`、空口令、无口令 `--force` 均 CommandError；强口令轮换 6 账号 |
| 7 | `ALLOW_DEMO_SEED` 只在 dev/test 生效 | **通过（进程内）** | `settings.DEBUG=False` + `running_under_tests=False` 时拒绝；但测试配置本身仍带 `ALLOW_DEMO_SEED=True` |
| 8 | 新增回归必须真红，且覆盖入口 | **部分失败** | 旧树 4 条中 2 红 2 绿；两条 manage 回归直接调函数，仍是 false green（见 I-R6-2） |
| 9 | 全量测试 / 迁移 / 目录卫生 | **通过** | `532 passed`；`No changes detected`；`design/`、`frontend/src/api/schema/` 零 diff |

## 2. 实测数字

| 项目 | 实测 |
|---|---|
| 全量 pytest | `532 passed, 5 warnings in 32.95s` |
| 定向 pytest | `-k "manage_command or test_settings or demo_seed_switch"` → `4 passed, 528 deselected` |
| 旧树回归 | `2 failed, 2 passed`（失败的正是测试配置/播种开关；通过的两条是 false green 的 manage 测试） |
| `makemigrations --check --dry-run` | `No changes detected`，EXIT=0（仅有 PG 5432 连接 warning） |
| 目录 diff | `design/` 与 `frontend/src/api/schema/` 均为 0 行 |
| r6 commit | 4 files，+118/−5 |
| 全范围 | 28 files，+1198/−53 |
| 旧库 `manage.py check` | EXIT=1（6 个默认账号被列出） |
| 旧库 `rotate_demo_credentials` | 6 个账号轮换，之后 `check` EXIT=0 |
| README 测试数 | `README.md:5,29,99` 仍写 `522`，与实测 `532` 不一致 |

## 3. Critical（合并阻断）

### C-R6-1 `manage.py --settings=config.settings.prod` 静默降级为 dev，旧库公开口令可直接登录

**位置**：
- `backend-django/manage.py:7-26`（`_validate_if_prod()` 在 `django.setup()` 前读取 `settings.DEBUG`）
- `backend-django/manage.py:30-38`（`os.environ.setdefault(...dev)`，然后 `execute_from_command_line()` 才解析 `--settings`）

**机制**：`main()` 先 `os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")`，`_validate_if_prod()` 第 15 行 `from django.conf import settings` 触发 settings 实例化；此时 `--settings=config.settings.prod` 还没被 Django 解析，LazySettings 已经绑定 `config.settings.dev`。第 23 行 `django.setup()` 进一步固化。最后第 38 行 `execute_from_command_line()` 虽然把环境变量改成 `config.settings.prod`，但 settings 对象已经是 dev，无法回头。

**复现（无 `DJANGO_SETTINGS_MODULE`，只传标准 `--settings`）**：

```bash
env -u DJANGO_SETTINGS_MODULE -u ARK_JWT_SECRET \
  .venv/bin/python manage.py shell \
  -c "from django.conf import settings; import os; print('MODULE=', os.environ.get('DJANGO_SETTINGS_MODULE')); print('DEBUG=', settings.DEBUG); print('JWT=', settings.JWT_SECRET)" \
  --settings=config.settings.prod
```

实测输出：

```text
EXIT=0
MODULE= config.settings.prod
DEBUG= True
JWT= dev-secret-change-me-please-use-32-bytes-min!
```

`--settings` 明明写的是 prod，实际 `DEBUG=True`、JWT 是仓库公开 dev 默认值。

**更严重的利用**：对仍带 `admin/Admin@123456` 的旧库，用该参数启动 `runserver`，登录直接成功：

```bash
env -u DJANGO_SETTINGS_MODULE -u ARK_JWT_SECRET \
  ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r6-old2.sqlite3 \
  .venv/bin/python manage.py runserver 127.0.0.1:8897 --noreload \
  --settings=config.settings.prod
```

```text
POST /api/v1/auth/login  ->  HTTP 200
{"code":0,"message":"ok","data":{"token_type":"Bearer","access_token":"eyJ...","...":"..."}}
账号：admin / Admin@123456（旧库默认口令）
角色：R-ADMIN
```

这不是“帮助命令的小问题”：它让标准 Django 的 `--settings` 变成“看起来是 prod、实际是 dev”，`runserver` 因此绕过 `enforce_serving_guard()`（`config/wsgi.py` 看到 `DEBUG=True` 直接返回）。生产部署者如果按 Django 习惯用 `--settings` 指定配置，会得到一个带公开密钥、公开演示口令的进程。

**修复方向**：
- 在触碰 `settings` 之前解析 `--settings`（同时支持 `--settings=value` 与 `--settings value`），先设置 `os.environ["DJANGO_SETTINGS_MODULE"]`，再 `settings`/`django.setup()`。
- 或者把守卫移到 `execute_from_command_line()` 之后仍能拿到正确 settings 的入口（自定义 `ManagementUtility` / `BaseCommand` 包装），不要用 `setdefault` + 提前 `settings.DEBUG` 的写法。
- 加一条 subprocess 回归：`manage.py check --settings=config.settings.prod` 在旧库上必须 EXIT=1，且不得打印 dev 密钥。

### C-R6-2 `config.settings.test` 的自定义别名仍可部署，公开测试 JWT 可被用来伪造任意用户

**位置**：
- `backend-django/core/startup.py:45-61`：只比较 `os.environ.get("DJANGO_SETTINGS_MODULE") in ("config.settings.test",)`
- `backend-django/config/settings/test.py:15-20`：`ALLOW_DEMO_SEED=True`，`JWT_SECRET="test-only-secret-please-do-not-use-in-production-0123456789"`
- `backend-django/core/startup.py:33-42`：`running_under_tests()` 用 `"pytest" in sys.modules` 判断测试进程

**复现 1：别名 settings 可以 `django.setup()`**：

```bash
cat >/tmp/e8r6/test_alias.py <<'EOF'
from config.settings.test import *
EOF

env -u ARK_JWT_SECRET PYTHONPATH=/tmp/e8r6:. \
  ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r6-alias.sqlite3 \
  DJANGO_SETTINGS_MODULE=test_alias \
  .venv/bin/python -c "import django; django.setup(); print('SETUP_OK')"
```

实测：

```text
SETUP_OK
EXIT=0
DEBUG=False
ALLOW_DEMO_SEED=True
JWT_SECRET=test-only-secret-please-do-not-use-in-production-0123456789
```

**复现 2：别名 settings 可以启动 WSGI**：

```bash
env -u ARK_JWT_SECRET PYTHONPATH=/tmp/e8r6:. \
  ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r6-alias.sqlite3 \
  DJANGO_SETTINGS_MODULE=test_alias \
  .venv/bin/python -c "from config.wsgi import application; print('WSGI_OK')"
```

实测：

```text
WSGI_OK
EXIT=0
```

`WSGI_OK` 说明 `enforce_serving_guard()` 没有拦截：`DEBUG=False` 进入守卫，`_assert_settings_module_deployable()` 只看环境变量是否等于精确的 `config.settings.test`，别名直接跳过；JWT 校验只检查“长度 ≥32、不是仓库 dev 默认值”，这个固定测试串恰好通过。

**复现 3：`pytest` 模块即可放宽测试配置判断**：

```bash
env -u ARK_JWT_SECRET DJANGO_SETTINGS_MODULE=config.settings.test \
  .venv/bin/python -c "import pytest, django; django.setup(); print('SETUP_OK')"
```

实测 `SETUP_OK`，EXIT=0。任何进程只要 `import pytest`，就会被 `running_under_tests()` 判成测试进程，绕过精确模块名限制。它不是默认生产路径，但和别名叠加后，测试配置具备了完整的“可部署”能力：公开 JWT 密钥 + `ALLOW_DEMO_SEED=True`。

**影响**：读到仓库的人可以用公开测试密钥签出任意 `uid/roles` 的 JWT；如果该配置被当成生产 settings（别名、模板复制、CI 误用），就是完整的 R-ADMIN 伪造面。`ALLOW_DEMO_SEED=True` 还让“测试配置”保留演示账号播种能力。

**修复方向**：
- 不要用 `sys.modules` 判断测试进程；用显式的 `ARK_TESTING=1` 或 `pytest` 注入的专用标记，并且只允许在测试入口设置。
- 在 test settings 加显式 `TESTING = True`，`_assert_settings_module_deployable()` 拒绝 `TESTING=True` 的非测试进程；同时按 `settings.JWT_SECRET == TEST_JWT_SECRET` 或 `settings.ALLOW_DEMO_SEED` 做 fail-closed 检查。
- 测试 JWT 改为每次测试进程随机生成（或从测试 fixture 注入），不要用仓库里的固定公开串。
- 移除 `config.settings.test` 的 `ALLOW_DEMO_SEED=True`；需要播种的测试用显式 fixture / `--force` + 强环境口令。
- 增加“别名 settings 不得启动”的回归，而不只是测精确模块名。

## 4. Important（应修，但不单独阻断合并）

### I-R6-1 `django-admin` / `python -m django` 的 check 不走凭据门禁；`runserver` 虽被 `config.wsgi` 拦住

**位置**：
- `backend-django/core/apps.py:9-19`（`ready()` 只调 `validate_runtime_secrets()`）
- `backend-django/core/startup.py:237-244` 的注释声称“所有 Django 进程（wsgi/asgi/celery/manage/django-admin）”都过关，但 `enforce_process_guard()` 只被 `manage.py` 调用
- `backend-django/manage.py:24-26` 是唯一的 `enforce_process_guard()` 生产调用点

**实测（旧库 + 强密钥）**：

```text
django-admin check          -> EXIT=0  "System check identified no issues (0 silenced)."
python -m django check      -> EXIT=0  同上
django-admin runserver ...  -> 启动即 ImproperlyConfigured（因为 runserver 加载 config.wsgi，走 serving guard）
```

所以这不是“远程 HTTP 仍可登录”的 Critical，但它让 `django-admin check` 在坏库上继续绿，运维会误判；`django-admin shell` / 自定义 management command 也不会被拦。注释与实现不一致，且“所有 Django 进程”这一安全承诺目前不成立。

**建议**：要么给 `django-admin` 也接上入口守卫（例如把凭据检查放到 `BaseCommand.execute()` 的统一包装/自定义 `ManagementUtility`），要么明确文档只保证 `manage.py` + `config.wsgi`/`asgi`，并修正 `core/apps.py:10` 与 `core/startup.py:237` 的注释。不要继续声称“所有进程”。

### I-R6-2 两条新增 manage 回归是 false green，未覆盖真正的入口

**位置**：`backend-django/tests/test_deploy_hardening.py:471-495`
- `test_manage_command_gate_blocks_check_on_default_credentials`
- `test_manage_command_gate_still_allows_remediation`

两条都 `monkeypatch.setattr(startup, "_current_management_command", ...)` 后直接调用 `startup.enforce_process_guard()`，**从未启动 `manage.py`**。因此在 r5 代码（`manage.py` 根本没接 `enforce_process_guard`）上它们也通过。

**实测旧树**（`git archive 0c5c487` + 当前测试文件）：

```text
tests/test_deploy_hardening.py::test_manage_command_gate_blocks_check_on_default_credentials PASSED
tests/test_deploy_hardening.py::test_manage_command_gate_still_allows_remediation PASSED
tests/test_deploy_hardening.py::test_test_settings_module_is_not_deployable FAILED
tests/test_deploy_hardening.py::test_demo_seed_switch_ignored_outside_debug_and_tests FAILED
2 failed, 2 passed
```

结论：4 条新回归只有 2 条真红；两条“管理命令门禁”是假绿。r5 的 C-R5-1 能修好，不是因为这两条测试能证明接线，而是因为实际代码碰巧接了。

`test_demo_seed_switch_ignored_outside_debug_and_tests` 在旧树上的失败还是 `RuntimeError: Database access not allowed`，不是 `CommandError`——它没有 `django_db` 标记，旧树红得也不是正确原因；当前代码只是刚好在 DB 前抛错。

**建议**：用 subprocess 跑 `manage.py check`（旧库断言 EXIT=1，rotate 后断言 EXIT=0），而不是直接调函数；别名 settings 和 `--settings` 也要有独立回归。

### I-R6-3 `manage.py help` 现在依赖数据库，DB 不可达要等约 10 秒才失败

**复现**：

```bash
env ARK_DB_ENGINE=postgresql ARK_DB_HOST=127.0.0.1 ARK_DB_PORT=59999 \
  ARK_DB_NAME=nope ARK_DB_USER=nope ARK_DB_PASSWORD=nope \
  ARK_JWT_SECRET='R6-Str0ng-JWT-Secret-000000000000' \
  DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/python manage.py help
```

实测 EXIT=1，约 10 秒，报：

```text
ImproperlyConfigured: 启动自检无法确认数据库中的默认口令状态（不会在未知状态下启动）：
无法读取数据库表清单. 请先确保数据库可用并执行 migrate，然后重试启动。
```

`help` 不访问业务数据，却因为 `enforce_process_guard()` 对所有非豁免命令生效而卡在 DB 重试。建议把 `help` 加入 `GUARD_EXEMPT_COMMANDS`（仍保留密钥校验），或只对需要 DB 的命令做凭据扫描。

顺带确认：`manage.py test` 未因提前 `django.setup()` 破坏。用一个临时 `SimpleTestCase` 实测：

```text
Ran 1 test in 0.000s
OK
```

`manage.py makemigrations --check --dry-run`、`collectstatic --noinput` 在旧库上也 EXIT=0；它们作为 CI 步骤豁免是合理的，不需要改。

### I-R6-4 文档/脚本仍有旧口令与错误测试数

- `README.md:5`、`:29`、`:99` 仍写 `522`，实测 `532 passed`。
- `DEPLOY.md:3` 仍写一键演示账号 `admin / Admin@123456`；默认 compose 现在是干净库，这句会直接误导用户去用旧公开口令。
- 8 个前端 smoke `*.mjs` 仍保留 `DEMO_PASSWORDS` 回落（例如 `frontend/scripts/task-m1b-smoke.mjs:10-12`、`frontend/smoke-admin-allprojects.mjs:5-7`）；`scripts/compose-smoke*.sh` 和 `App.vue` 已改为必须显式环境变量。`node --check` 全部通过，语法没问题，但缺省仍会静默使用 `Admin@123456`。
- `README.md:57` 的旧口令只出现在“旧数据卷升级”说明里，语境正确，可保留；它和 `DEPLOY.md:3` 的“演示账号”不是一回事。

### I-R6-5 `shell` / `dbshell` 豁免没有提示；本地全权限可接受，但应显式告知

**实测**：旧库 + 强密钥 `manage.py shell -c 'checkpw(Admin@123456)'` → `SHELL_DEFAULT_LOGIN= True`，EXIT=0。

`shell` 是本地全权限入口，不构成新的远程攻击面；但在“库仍是公开口令”的状态下静默进入，会让人误以为状态正常。建议对这些豁免命令在 stderr 打一行警告，说明“当前库仍含默认口令，仅修复用途”。

## 5. Minor

- `core/apps.py:10` 与 `core/startup.py:237` 的“所有 Django 进程（含 django-admin）”注释与实现不符；随 I-R6-1 一起改。
- `config/settings/prod.py:19-23` 注释说“密钥与默认口令的实际校验放在 core/apps.ready()”，但 `ready()` 只校验密钥；默认口令在 serving/manage 入口。注释需修正。
- `test_demo_seed_switch_ignored_outside_debug_and_tests` 缺 `@pytest.mark.django_db`；旧树红因 DB 访问限制而非 `CommandError`，测试意图不纯。
- `seed_demo.handle()` 仍无 `transaction.atomic()`；中途 `CommandError`/异常会留下部分 roles/users/grants（r1 已记录，非本轮新增）。
- `rotate_demo_credentials --password` 仍进 `argv`/shell history；已有 `ARK_ROTATE_PASSWORD`/stdin，但默认示例仍可能诱导使用 `--password`。
- `frontend/dist` 构建产物仍含旧登录提示；生成物可重建，不作为源码阻断。
- `frontend/pnpm-lock.yaml`、`frontend/pnpm-workspace.yaml`、`backend-django/uv.lock`、`dump.rdb` 等为未跟踪工作区文件，未进入 commit；不影响本次 diff。
- `README` 文档路径表仍写 `/docs`、`/openapi.json`；实际 NinjaAPI 挂在 `/api/v1/`，应为 `/api/v1/docs`、`/api/v1/openapi.json`（r1 已提，仍未改）。

## 6. 我亲手跑的命令与结果（摘要）

### 6.1 旧库 `manage.py` 守卫 / 修复

```bash
# 旧库：dev migrate + seed_demo
env ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r6-old.sqlite3 \
  DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py migrate --noinput
env ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r6-old.sqlite3 \
  DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py seed_demo

# 生产 check：必须失败
env ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r6-old.sqlite3 \
  ARK_JWT_SECRET='R6-Str0ng-JWT-Secret-000000000000' \
  DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py check
# EXIT=1
# ImproperlyConfigured: 检测到仍在使用仓库默认口令的账号：admin、manager、staff、finance、partner、expert_ext...

# 旋转：自愈
env ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r6-old.sqlite3 \
  ARK_JWT_SECRET='R6-Str0ng-JWT-Secret-000000000000' \
  DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py \
  rotate_demo_credentials --password 'R6-Rotated-Passw0rd-2026!'
# 已轮换 6 个账号...
# 自检通过：已无默认口令账号。

# 再 check：通过
# System check identified no issues (0 silenced).
```

空库 `migrate`：

```bash
env ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r6-empty.sqlite3 \
  ARK_JWT_SECRET='R6-Str0ng-JWT-Secret-000000000000' \
  DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py migrate --noinput
# EXIT=0
```

### 6.2 `django-admin` / `python -m django` 的残余绿

以下用**未轮换的新旧库** `/tmp/e8r6-old2.sqlite3`（`admin/Admin@123456` 仍有效，先验证 `ADMIN_DEFAULT= True`）：

```bash
env ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r6-old2.sqlite3 \
  ARK_JWT_SECRET='R6-Str0ng-JWT-Secret-000000000000' \
  PYTHONPATH=. DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/django-admin check
# EXIT=0  System check identified no issues (0 silenced).

env ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r6-old2.sqlite3 \
  ARK_JWT_SECRET='R6-Str0ng-JWT-Secret-000000000000' \
  PYTHONPATH=. DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/python -m django check
# EXIT=0  同上
```

同一库上 `manage.py check` 会 EXIT=1 并列出六个账号，说明这不是“库已干净”造成的假象。

`django-admin runserver` 反而会被 `config.wsgi` 的 serving guard 拦住（`LOGIN_HTTP=000`，`ImproperlyConfigured` 六个账号），所以远程 HTTP 面没有因此新开；问题在“非 serving 管理命令的绿”和“所有进程”的承诺。

### 6.3 `--settings` 降级

```bash
env -u DJANGO_SETTINGS_MODULE -u ARK_JWT_SECRET \
  .venv/bin/python manage.py shell \
  -c "from django.conf import settings; import os; print('MODULE=', os.environ.get('DJANGO_SETTINGS_MODULE')); print('DEBUG=', settings.DEBUG); print('JWT=', settings.JWT_SECRET)" \
  --settings=config.settings.prod
```

```text
MODULE= config.settings.prod
DEBUG= True
JWT= dev-secret-change-me-please-use-32-bytes-min!
```

```bash
env -u DJANGO_SETTINGS_MODULE -u ARK_JWT_SECRET \
  ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r6-old2.sqlite3 \
  .venv/bin/python manage.py runserver 127.0.0.1:8897 --noreload \
  --settings=config.settings.prod
# POST /api/v1/auth/login  ->  HTTP 200
# {"code":0,...,"token_type":"Bearer","access_token":"eyJ..."}
# 凭据：admin / Admin@123456；角色：R-ADMIN
```

### 6.4 测试配置别名

```bash
cat >/tmp/e8r6/test_alias.py <<'EOF'
from config.settings.test import *
EOF

env -u ARK_JWT_SECRET PYTHONPATH=/tmp/e8r6:. \
  ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r6-alias.sqlite3 \
  DJANGO_SETTINGS_MODULE=test_alias \
  .venv/bin/python -c "import django; django.setup(); print('SETUP_OK')"
# SETUP_OK

env -u ARK_JWT_SECRET PYTHONPATH=/tmp/e8r6:. \
  ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r6-alias.sqlite3 \
  DJANGO_SETTINGS_MODULE=test_alias \
  .venv/bin/python -c "from config.wsgi import application; print('WSGI_OK')"
# WSGI_OK
```

```bash
env -u ARK_JWT_SECRET DJANGO_SETTINGS_MODULE=config.settings.test \
  .venv/bin/python -c "import pytest, django; django.setup(); print('SETUP_OK')"
# SETUP_OK（import pytest 即可触发 running_under_tests）
```

### 6.5 全量测试 / 迁移 / 卫生

```bash
.venv/bin/python -m pytest -q
# 532 passed, 5 warnings in 32.95s

.venv/bin/python -m pytest -q -k "manage_command or test_settings or demo_seed_switch"
# 4 passed, 528 deselected

DJANGO_SETTINGS_MODULE=config.settings.dev \
  .venv/bin/python manage.py makemigrations --check --dry-run
# No changes detected

git diff --stat a83c409..099bd56 -- design frontend/src/api/schema
# (empty)
```

旧树回归：

```bash
# /tmp/e8old6 = git archive 0c5c487 + 当前 tests/test_deploy_hardening.py
.venv/bin/python -m pytest tests/test_deploy_hardening.py \
  -k "manage_command or test_settings or demo_seed_switch" -v
# 2 failed, 2 passed
# PASSED: test_manage_command_gate_blocks_check_on_default_credentials
# PASSED: test_manage_command_gate_still_allows_remediation
# FAILED: test_test_settings_module_is_not_deployable
# FAILED: test_demo_seed_switch_ignored_outside_debug_and_tests
```

## 7. 合并门槛

在以下条件全部满足前，E-8 不应合并：

1. **修 C-R6-1**：`manage.py --settings` 必须在 `settings` 实例化前生效；subprocess 回归覆盖 `--settings=config.settings.prod`（旧库 EXIT=1、不得打印 dev 密钥），并覆盖 `runserver` 不得以 dev 配置启动。
2. **修 C-R6-2**：别名 settings 不得部署；`running_under_tests` 不得由 `import pytest` 单独触发；测试 JWT 随机化；test settings 移除 `ALLOW_DEMO_SEED=True`；增加别名回归。
3. **修 I-R6-1**：要么把 `django-admin` 也接入凭据门禁，要么把“所有 Django 进程”的声明收窄并修正 `core/apps.py:10` / `core/startup.py:237` 注释；`django-admin check` 不应在旧库上绿。
4. **修 I-R6-2**：用 subprocess 替换两条 false green 回归；`test_demo_seed_switch` 加 `django_db` 并断言 `CommandError` 文本。
5. **修 I-R6-3**：`help` 不应因 DB 不可达而阻塞（加入豁免或仅对 DB 命令扫描）。
6. **文档/脚本**：`README` 测试数改 532；`DEPLOY.md:3` 删除/标注旧口令；8 个 mjs 去掉 `DEMO_PASSWORDS` 回落或显式失败；`README` 文档路径改为 `/api/v1/docs`。
7. **复跑**：`pytest -q` ≥532 通过；`makemigrations --check` No changes；`design/` 与 `frontend/src/api/schema/` 零 diff；`docker compose config` 默认仍为 seed 0/空口令/必填 JWT。

## 8. 已确认通过 / 残余风险 / 未测试

**通过**：
- 无 `ARK_JWT_SECRET` 时 `django.setup()`、`python -m django check`、`django-admin check` 均失败（检查的是有效 `settings.JWT_SECRET`）。
- 旧库 `manage.py check` 被拦；`rotate_demo_credentials` 轮换 6 账号后放行；空库 `migrate` 正常。
- 生产播种拒绝 `Demo@123456`、空口令、无口令 `--force`；强口令轮换 6 账号。
- 默认 compose 干净库：seed 0、password 空、JWT 必填。
- 生产 `docs_enabled()` 默认关闭。
- 全量 532 通过；迁移 No changes；design/schema 零 diff；`node --check` 8 个 mjs 通过。
- `manage.py test` 的提前 setup 没有破坏一个最小 `SimpleTestCase`（`Ran 1 test ... OK`）。
- `manage.py makemigrations` / `collectstatic` 在旧库上作为 CI 豁免可正常退出。

**残余风险**：
- `ALLOWED_HOSTS=["*"]`（`backend-django/config/settings/prod.py:17`）仍未收窄；不是本轮新增，但生产暴露面仍大。
- `rotate_demo_credentials --password` 进 argv/history（有 env/stdin 替代）。
- test settings 固定公开 JWT（C-R6-2 的一部分）。
- `frontend/dist` 旧构建产物含旧登录提示。

**未测试 / 边界**：
- 未跑完整 `docker compose up --build`（需要真实 PG/Redis/MinIO 与镜像构建）；compose 用 `docker compose config` 验证解析，C-1 用 prod + sqlite migrate/seed 验证。
- 未做真实浏览器登录；HTTP 复现用 Django runserver + curl。
- 未重跑 PG 端到端 30 项冒烟；结论只覆盖本报告列出的命令。
