# E-8 部署收口 · 终审报告（r5）

- **仓库**：`/Users/jacky/works/science-research-project`
- **分支**：`develop`
- **审查范围**：`a83c409..0c5c487`（6 commits；本轮新增 `0c5c487`）
- **计划**：`docs/superpowers/plans/2026-11-19-deploy-hardening.md`（5 任务）
- **Ledger**：`.superpowers/sdd/2026-11-19-deploy-hardening/progress.md`
- **Diff 包**：`/tmp/review-deploy-hardening-r5.diff`（82215 bytes）
- **审查方式**：只读代码审查 + 独立复现；唯一写入是本报告。

---

## 0. 结论

**REQUEST_CHANGES**

r4 的四个 Critical 中，三个已在代码层真正关闭：

1. **弱密钥自检已覆盖所有 Django 进程**：`core/apps.py::CoreConfig.ready()` 调用 `validate_runtime_secrets()`，`django.setup()`、`python -m django check`、`django-admin check` 无 `ARK_JWT_SECRET` 均实测 `EXIT=1`；自定义 settings 覆盖 `JWT_SECRET` 也会按**生效值**拦截。
2. **旧库默认口令现在会阻断服务启动**：`wsgi/asgi` 的 `enforce_serving_guard()` 在旧 sqlite 库上实测拒绝 `gunicorn`/`runserver`，提示六个默认账号并给出 `rotate_demo_credentials`。
3. **播种默认口令已被拒绝**：prod 下 `ARK_SEED_DEMO=1` + `Demo@123456`、`--force` 无口令、`--force` + `Demo@123456` 均 `CommandError`；强口令播种会把六个账号全部轮换。

但仍有一个必须阻断合并的**安全控制未接线**，以及一个会把测试配置变成生产后门的配置问题：

1. **C-R5-1**：`enforce_process_guard()` 在生产代码里只被 `wsgi/asgi` 直接调用；`manage.py`、`django-admin`、worker/management command 都没有调用它。实测旧库上 `manage.py check` 和 `django-admin check` 都返回 `EXIT=0`，`manage.py shell` 仍能用 `Admin@123456` 登录。所谓「所有 Django 进程」的默认口令门禁并不存在。
2. **I-R5-1**：为它写的回归测试 `test_process_guard_blocks_non_exempt_command` 是直接调用函数，不经过 `manage.py`，因此正好在接线缺失时仍然绿——这是本轮最关键的错误绿色测试。
3. **I-R5-2**：`config.settings.test` 是 `DEBUG=False` 的生产形态，却内置公开的 `JWT_SECRET`，同时 `ALLOW_DEMO_SEED=True`；临时测试已证明它在无 env 时会种出 `admin/Admin@123456`。误把 test settings 用于任何可服务进程，等于公开 JWT 签名密钥。

---

## 1. 必查矩阵

| # | 检查项 | 结论 | 证据 / 说明 |
|---|--------|------|-------------|
| 1a | 无 `ARK_JWT_SECRET` 以 prod 启动必须失败 | ✅ PASS | `django.setup()` / `python -m django check` / `django-admin check` 三条路径均 `ImproperlyConfigured`、`EXIT=1`；`" "*40`、仓库默认值、短于 32 均拒绝；`"a"*32` 通过（见 Minor M-5） |
| 1b | `ARK_SEED_DEMO=1` 无 `ARK_SEED_PASSWORD`、非 dev 必须拒绝 | ✅ PASS | prod + sqlite：`CommandError: 非开发形态播种演示数据必须设置 ARK_SEED_PASSWORD...`；`--force` 同；空串按未给处理；`Demo@123456` 被显式拒绝 |
| 1c | 未设 `ARK_API_DOCS` 且 `DEBUG=False` 时 `/docs`、`/openapi.json` 不存在 | ✅ PASS | `docs_enabled()=False`、`api.docs_url=None`、`api.openapi_url=None`；实际挂载点 `/api/v1/docs`、`/api/v1/openapi.json`（`config/urls.py:24`） |
| 2 | 自检口径 / 绕过面 | ⚠️ **FAIL（非服务进程）** | 自定义 settings 的生效值已修（`core/startup.py:33-54`）；但 `manage.py`/`django-admin` 不调用 `enforce_process_guard()`（C-R5-1）；test settings 有公开 JWT（I-R5-2）；长度判据低熵可通过（M-5） |
| 3 | seed 门禁副作用 | ⚠️ PARTIAL | 全量 528 绿；dev `manage.py seed_demo` 仍可用；但 seed 无事务（M-6）；test settings 无 env 仍可种默认口令（I-R5-2） |
| 4 | 编排 / Dockerfile 正确性 | ✅ PASS（未跑完整镜像） | `docker compose config`：`ARK_SEED_DEMO="0"`、`ARK_SEED_PASSWORD=""`、`DJANGO_SETTINGS_MODULE=config.settings.prod`；`${ARK_JWT_SECRET:?}` 缺值失败；`Dockerfile:23` 的 `fi && gunicorn` 保持 fail-closed |
| 5 | 文档一致性 | ⚠️ PARTIAL | README 快速开始/生产段/环境变量表已与实现对齐（`:188`、`:198`）；但 README `:99` 仍写 522，实测 528；`DEPLOY.md:3` 仍写 `admin / Admin@123456`；8 个前端 smoke 仍有 `DEMO_PASSWORDS` 回落 |
| 6 | 回归与卫生 | ✅ PASS（有残留） | 全量 528、`makemigrations --check` = `No changes detected`；`design/`、`frontend/src/api/schema` 零改动；`pnpm-lock.yaml`/`pnpm-workspace.yaml` 仍是未跟踪文件，但未进 commit |

---

## 2. 实测数字

| 项目 | 结果 |
|------|------|
| 全量测试 | `528 passed, 5 warnings in 33.28s` |
| 目标测试 | `pytest -q -k "seed or deploy or credential or secret or guard"` → `40 passed, 488 deselected` |
| `makemigrations --check --dry-run` | `No changes detected`，`EXIT=0`（仅 PG 5432 连接 warning） |
| README 测试数 | `README.md:99` 写 `522 passed`；实测 **528**（stale） |
| compose 默认解析 | `ARK_SEED_DEMO="0"`、`ARK_SEED_PASSWORD=""`、`DJANGO_SETTINGS_MODULE=config.settings.prod` |
| 干净库默认启动 | prod + sqlite：`migrate` `EXIT=0`，`SysUser.objects.count() == 0` |
| 旧库服务门禁 | `runserver` 被 `config/wsgi.py:15` 拒绝，列出 `admin、manager、staff、finance、partner、expert_ext` |
| 旧库管理命令 | `manage.py check` / `django-admin check` 均 `EXIT=0`；`manage.py shell` 的 `Admin@123456` 校验为 `True` |
| 密钥自检 | 无 ARK 的 `django.setup` / `python -m django check` / `django-admin check` 均 `EXIT=1` |
| 播种默认口令 | prod + `Demo@123456`、`--force` 无口令、`--force` + `Demo@123456` 均 `EXIT=1` |
| 强口令复种 | 六个账号新口令全 `True`、旧默认全 `False`；`find_default_credential_accounts()` 返回 `[]` |
| test settings 播种 | 临时测试 1 passed：`DEBUG=False`、`ALLOW_DEMO_SEED=True`、无 env → `admin/Admin@123456` 为 `True` |
| 旧 commit 红测 | 22609c1 上跑 8 个候选新用例：`5 failed, 3 passed`（见 §6.8） |
| 前端语法 | 8 个 smoke mjs `node --check` 全部 `OK` |
| 设计/前端 schema diff | `git diff --name-only a83c409..0c5c487 -- design frontend/src/api/schema` → 0 行 |
| 总 diff | 28 files, `+1085/-53`；r5 本身 18 files, `+272/-70` |

---

## 3. Critical

### C-R5-1 `enforce_process_guard()` 未接入 `manage.py` / `django-admin`，非服务进程仍可使用公开默认口令

**结论**：服务入口（`wsgi/asgi`）确实被 `enforce_serving_guard()` 守住了；但「所有 Django 进程」的默认口令门禁只存在于函数定义里，生产上没有任何入口调用它。旧库上 `manage.py check`（非豁免命令）和 `django-admin check` 均成功，`manage.py shell` 仍能校验通过 `admin/Admin@123456`。

**证据**：

- `backend-django/core/startup.py:225-239` 定义了 `enforce_process_guard()`：先 `validate_runtime_secrets()`，再按 `_current_management_command()` 判断豁免，最后 `assert_no_default_credentials()`。
- `backend-django/core/apps.py:9-19` 的 `CoreConfig.ready()` 只调用 `validate_runtime_secrets()`；docstring `:15` 却声称默认口令扫描在 `manage.py` 非豁免命令里。
- `backend-django/manage.py:7-14` 的 `_validate_if_prod()` 只调用 `validate_runtime_secrets()`；`main()` `:19` 调用它后直接 `execute_from_command_line()`，**没有** `enforce_process_guard()`。
- `backend-django/config/wsgi.py:11,15`、`config/asgi.py:11,15` 只调用 `enforce_serving_guard()`。
- 全仓 grep `enforce_process_guard`：生产代码只有定义处；调用点仅 `tests/test_deploy_hardening.py:424,437`。`manage.py`、`django-admin`、worker 均未接线。
- `backend-django/core/startup.py:204-211` 的 `GUARD_EXEMPT_COMMANDS` 包含 `shell`、`test`、`collectstatic`、`createsuperuser` 等；`check` 不在豁免集，本应被拦，实际通过，正好证明门禁没有执行。

**复现**（旧库由 dev `migrate` + `seed_demo` 建出六个默认账号）：

```bash
cd backend-django
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r5-old.sqlite3 \
ARK_JWT_SECRET='R5-Str0ng-JWT-Secret-000000000000' \
DJANGO_SETTINGS_MODULE=config.settings.prod \
.venv/bin/python manage.py check
# System check identified no issues (0 silenced).   EXIT=0

ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r5-old.sqlite3 \
ARK_JWT_SECRET='R5-Str0ng-JWT-Secret-000000000000' \
PYTHONPATH=. DJANGO_SETTINGS_MODULE=config.settings.prod \
.venv/bin/django-admin check
# System check identified no issues (0 silenced).   EXIT=0

ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r5-old.sqlite3 \
ARK_JWT_SECRET='R5-Str0ng-JWT-Secret-000000000000' \
DJANGO_SETTINGS_MODULE=config.settings.prod \
.venv/bin/python manage.py shell -c \
"from apps.sysadmin.models import SysUser; import bcrypt; \
 u=SysUser.objects.get(tenant_id=1, username='admin'); \
 print('ADMIN_DEFAULT_LOGIN=', bcrypt.checkpw(b'Admin@123456', u.password_hash.encode()))"
# ADMIN_DEFAULT_LOGIN= True   EXIT=0
```

同一旧库上，服务入口是拒绝的（对照组，证明不是 DB 本身不可用）：

```bash
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r5-old.sqlite3 \
ARK_JWT_SECRET='R5-Str0ng-JWT-Secret-000000000000' \
DJANGO_SETTINGS_MODULE=config.settings.prod \
.venv/bin/python manage.py runserver 127.0.0.1:8899 --noreload
# config/wsgi.py:15 enforce_serving_guard()
# ImproperlyConfigured: 检测到仍在使用仓库默认口令的账号：admin、manager、staff、finance、partner、expert_ext
# EXIT=1
```

**影响**：远程 HTTP 入口仍被 `wsgi/asgi` 拦住，这一点必须说清楚；但 `manage.py` / `django-admin` / 生产 systemd 里提到的 `django-worker`/`django-beat` 之类非服务进程不受默认口令门禁保护。只要这些进程执行认证/令牌签发/数据访问，旧库里的公开 R-ADMIN 就仍然可用；README 的「所有 Django 进程」承诺不成立。

**建议修复**：

1. 在 `manage.py` 的 `_validate_if_prod()` 中改为调用 `enforce_process_guard()`（或在其后、`execute_from_command_line()` 前调用）；确保 `_current_management_command()` 在 `python manage.py migrate` 下正确识别 `migrate` 并豁免。
2. 为 `django-admin`/worker 提供同样的入口包装，或把默认口令门禁放进一个能安全访问 DB 的启动钩子（不要直接在 `AppConfig.ready()` 里查库，避免 app init 期 DB 警告）。
3. 用**子进程**回归测试 `python manage.py check` 在旧库上必须 `EXIT=1`，不要只测函数。
4. 明确 `shell` 是否继续豁免：本地修库合理，但应在文档中写明「shell 可读旧库，不等同服务可用」。

---

## 4. Important

### I-R5-1 进程门禁回归是「直接调用函数」的错误绿色测试

**结论**：`test_process_guard_blocks_non_exempt_command` 通过 monkeypatch 把 `_current_management_command` 设为 `runserver`，然后直接 `startup.enforce_process_guard()`；它从未经过 `manage.py`，因此在 C-R5-1 的接线缺失下仍然绿。

**证据**：

- `backend-django/tests/test_deploy_hardening.py:412-424`：测试体直接调用 `startup.enforce_process_guard()`，没有 `subprocess`、没有 `manage.py`。
- 同一文件的 `test_process_guard_exempts_remediation_commands` 也是直接调用。
- 因此 `pytest -q -k guard` 的 40 passed 不能证明「所有 Django 进程」被守住；它只证明函数本身逻辑正确。

**建议**：增加 `subprocess.run([sys.executable, "manage.py", "check"], env=...)` 的旧库测试，断言 `returncode != 0` 且 stderr 含默认账号名；同时保留函数级单测。

### I-R5-2 `config.settings.test` 是 production-shaped，却内置公开 JWT 且允许播默认口令

**结论**：test settings 不是默认部署路径，因此当前不构成默认生产泄露；但它 `DEBUG=False`、`ALLOW_DEMO_SEED=True`，并硬编码公开 `JWT_SECRET`。任何把 `DJANGO_SETTINGS_MODULE` 指向 `config.settings.test` 的可服务进程，都会通过 `CoreConfig.ready()` 的强密钥检查（因为测试密钥长度足够），同时可被仓库读者伪造 JWT；无 env 播种还会生成 `admin/Admin@123456`。

**证据**：

- `backend-django/config/settings/test.py:16` `ALLOW_DEMO_SEED = True`；`:20` `JWT_SECRET = "test-only-secret-please-do-not-use-in-production-0123456789"`。
- `backend-django/config/settings/base.py:8` `DEBUG=False`；test.py 未覆盖 DEBUG，所以测试进程也是 production-shaped。
- `backend-django/core/apps.py:17-19` 只校验密钥强度，无法区分 test/prod；该公开密钥长度 >32，直接通过。
- `backend-django/apps/sysadmin/management/commands/seed_demo.py:145-167`：`demo_mode=True` 时无 env 也返回 `None`，后续用 `USERS` 固定口令（`:37-40`）播种。

**复现**（临时测试，不写仓库）：

```bash
cat >/tmp/e8r5/test_test_settings_seed.py <<'PY'
import bcrypt
import pytest

@pytest.mark.django_db
def test_test_settings_seed_defaults(monkeypatch, settings):
    from django.core.management import call_command
    from apps.sysadmin.models import SysUser

    assert settings.DEBUG is False
    assert settings.ALLOW_DEMO_SEED is True
    monkeypatch.delenv("ARK_SEED_DEMO", raising=False)
    monkeypatch.delenv("ARK_SEED_PASSWORD", raising=False)
    call_command("seed_demo", verbosity=0)
    admin = SysUser.objects.get(tenant_id=1, username="admin")
    assert bcrypt.checkpw(b"Admin@123456", admin.password_hash.encode())
PY
cd backend-django
DJANGO_SETTINGS_MODULE=config.settings.test .venv/bin/python -m pytest \
  -q /tmp/e8r5/test_test_settings_seed.py -p tests.conftest \
  --no-header -p no:cacheprovider
# 1 passed
```

**建议**：测试密钥改为 `secrets.token_urlsafe(48)` 之类的**每进程随机值**（或从 CI secret 注入），不要提交固定值；`ALLOW_DEMO_SEED` 与测试专用标志绑定，并在 `config.settings.test` 文档/命令中禁止用于任何 served 进程。若必须保留固定测试密钥，应在 `CoreConfig.ready()` 明确拒绝 `config.settings.test` 作为生产进程配置（但不要让正常 pytest 变红）。

### I-R5-3 8 个前端 smoke 仍有 `DEMO_PASSWORDS` 公开默认口令回落

**结论**：`scripts/compose-smoke.sh`、`compose-smoke-auth.sh`、`App.vue` 已改为 env/部署方口令；但 8 个 `frontend/**/smoke-*.mjs` 仍保留 `DEMO_PASSWORDS`，`smokePwd(who)` 在未设 `ARK_SMOKE_PASSWORD` 时回落到 `Admin@123456` 等。它们是 dev smoke，但一旦指向旧库/旧环境，等于用公开 R-ADMIN 登录。

**证据**：

- `frontend/scripts/task-m1b-smoke.mjs:10-11`、`frontend/scripts/task11-smoke.mjs:6-7`、`frontend/smoke-admin-allprojects.mjs:5-7`、`frontend/smoke-expense-subject.mjs:4-5`、`frontend/smoke-fundingconfig.mjs:4-5`、`frontend/smoke-mocktoasts.mjs:7-8`、`frontend/smoke-pagegrant.mjs:8-9`、`frontend/smoke-projects-views.mjs:4-5` 均为 `DEMO_PASSWORDS` 常量 + `process.env.ARK_SMOKE_PASSWORD || DEMO_PASSWORDS[who]`。
- `node --check` 全部通过；语法没问题，问题是回落值。
- `frontend/src/App.vue:275` 已改为「口令由部署方通过 ARK_SEED_PASSWORD 指定」，这一处已修。

**建议**：删掉 `DEMO_PASSWORDS`，改为 `const pwd = process.env.ARK_SMOKE_PASSWORD; if (!pwd) throw new Error(...)`；或者把 fallback 限制在 `ARK_DEV_LOGIN=1` 且显式 `ARK_SMOKE_ALLOW_DEMO=1`。

### I-R5-4 `DEPLOY.md:3` 仍把公开 admin 口令写成当前一键部署的现状

**结论**：`DEPLOY.md` 顶部「现状速览」是当前口吻，写着「一键 `docker compose up -d --build`，演示账号 `admin / Admin@123456`」，但默认 compose 现在是干净库、不播种。后面虽声明正文是旧 Node 历史参考，顶部仍会误导。

**证据**：`DEPLOY.md:3` 原文含 `演示账号 admin / Admin@123456`；`docker-compose.yml:29-30` 默认 seed 0/空口令；默认干净库 `SysUser.objects.count() == 0`（实测）。

**建议**：把 `DEPLOY.md:3` 改为「默认干净库，演示账号需显式设置 `ARK_SEED_DEMO=1` 与 `ARK_SEED_PASSWORD`」，或明确标注该句仅适用于旧 Node 栈。

---

## 5. Minor

### M-1 README 测试数仍是 522

`README.md:99` 写 `python -m pytest tests -q # 当前 522 passed`；本轮实测 `528 passed`。文档数字应与 HEAD 一致，改为 528。

### M-2 `makemigrations` / `collectstatic` 在 prod settings 且无 ARK 时失败

实测：

```bash
env -u ARK_JWT_SECRET DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/python manage.py makemigrations --check --dry-run
# ImproperlyConfigured: settings.JWT_SECRET 是仓库内置的演示默认值... EXIT=1

env -u ARK_JWT_SECRET DJANGO_SETTINGS_MODULE=config.settings.test \
  .venv/bin/python manage.py makemigrations --check --dry-run
# No changes detected   EXIT=0
```

`collectstatic` 同样：test settings `0 static files copied`、`EXIT=0`；prod 无 ARK `EXIT=1`。这是 `ready()` 的 fail-closed 预期行为，不是 CI 回归（CI 用 test settings）；但生产部署流水线若用 prod settings 跑 `collectstatic`，需要显式提供 `ARK_JWT_SECRET`，建议写进部署文档。

### M-3 seed 仍无事务，失败会留下部分写入

`seed_demo.py:185-241` 的 `handle()` 没有 `transaction.atomic()`；`_seed_domains()` 在 roles/users/dicts/grants 已写入后才执行。r1 的复现是中断后留下 `roles: 9 users: 4 grants: 88`；当前代码结构未变。建议包一层事务，或明确接受「可重跑、最终一致」。

### M-4 密钥/口令判据仍是长度优先，低熵值可通过

`core/startup.py:57-69` 只拒绝空、默认值、`len < 32`；`"a"*32` 通过（r4 已有此结论）。`seed_demo.py:145-167` 只要求 `len >= 10`，`"aaaaaaaaaa"` 可通过。不是公开默认值，但「强口令」承诺偏弱；建议至少加常见弱口令/重复字符检查，或在文档中明确这是最低门槛。

### M-5 `rotate_demo_credentials --password` 仍可把口令放进 argv/ps

命令支持 `ARK_ROTATE_PASSWORD`/stdin（`rotate_demo_credentials.py:30-33`），但 `--password` 仍然接受；README 也用 `--password` 示例。建议把 `--password` 标为 deprecated 或只保留 env/stdin，避免 shell history/ps 泄露。

### M-6 注释与构建产物残留

- `core/apps.py:15` 与 `config/settings/prod.py:21` 仍声称 `enforce_process_guard` 由 `manage.py`/ready 调用，与 C-R5-1 不符。
- `frontend/dist/assets/index-*.js` 是已构建产物，仍含旧登录口令文案；下次构建会覆盖，但当前仓库里可被 grep 到。建议把 `dist` 排除出版本库或在报告中标注生成物。
- `docs/superpowers/plans/2026-11-19-deploy-hardening.md:65` 仍把 `Demo@123456` 写进计划（历史计划，不必改代码；若作为验收依据需注明已被 r5 取代）。

### M-7 pnpm 文件仍未跟踪

`frontend/pnpm-lock.yaml`、`frontend/pnpm-workspace.yaml` 在 `git status` 中仍是 `??`，未进 commit（`git ls-files` 为空）。不是本轮源码夹带，但工作区不干净；若计划要求「移除」，应在 commit 中删除或加入 `.gitignore` 并说明。

---

## 6. 复现命令与输出

### 6.1 无密钥的三种进程入口

```bash
cd backend-django
env -u ARK_JWT_SECRET DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/python -c 'import django;django.setup()'
# ImproperlyConfigured: settings.JWT_SECRET 是仓库内置的演示默认值...
# EXIT=1

env -u ARK_JWT_SECRET PYTHONPATH=. DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/python -m django check
# 同上，EXIT=1

env -u ARK_JWT_SECRET PYTHONPATH=. DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/django-admin check
# 同上，EXIT=1
```

### 6.2 自定义 settings（生效值）

```bash
cat >/tmp/e8r5/custom_alias.py <<'PY'
from config.settings.prod import *
PY
env -u ARK_JWT_SECRET PYTHONPATH=/tmp/e8r5:. DJANGO_SETTINGS_MODULE=custom_alias \
  .venv/bin/python -c 'import django;django.setup()'
# ImproperlyConfigured（默认密钥），EXIT=1

ARK_JWT_SECRET='R5-Str0ng-JWT-Secret-000000000000' \
PYTHONPATH=/tmp/e8r5:. DJANGO_SETTINGS_MODULE=custom_alias \
  .venv/bin/python -c 'import django;django.setup();print("SETUP_OK")'
# SETUP_OK，EXIT=0

cat >/tmp/e8r5/custom_alias_override.py <<'PY'
from config.settings.prod import *
JWT_SECRET = "short"
PY
ARK_JWT_SECRET='R5-Str0ng-JWT-Secret-000000000000' \
PYTHONPATH=/tmp/e8r5:. DJANGO_SETTINGS_MODULE=custom_alias_override \
  .venv/bin/python -c 'import django;django.setup()'
# ImproperlyConfigured: settings.JWT_SECRET 长度 5 不足 32 字符... EXIT=1
```

### 6.3 自省文档

```bash
env -u ARK_API_DOCS ARK_JWT_SECRET='R5-Str0ng-JWT-Secret-000000000000' \
DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python -c \
"import django;django.setup();from core.ninja import docs_enabled,api; \
 print('docs_enabled=',docs_enabled());print('docs_url=',api.docs_url);print('openapi_url=',api.openapi_url)"
# docs_enabled= False
# docs_url= None
# openapi_url= None
# EXIT=0
```

### 6.4 播种门禁

```bash
# prod + Demo 口令
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r5-old.sqlite3 \
ARK_JWT_SECRET='R5-Str0ng-JWT-Secret-000000000000' \
DJANGO_SETTINGS_MODULE=config.settings.prod \
ARK_SEED_DEMO=1 ARK_SEED_PASSWORD='Demo@123456' \
.venv/bin/python manage.py seed_demo
# CommandError: ARK_SEED_PASSWORD 不得是仓库内置的默认口令（含 Demo@123456）。 EXIT=1

# prod + --force 无口令
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r5-old.sqlite3 \
ARK_JWT_SECRET='R5-Str0ng-JWT-Secret-000000000000' \
DJANGO_SETTINGS_MODULE=config.settings.prod \
.venv/bin/python manage.py seed_demo --force
# CommandError: 非开发形态播种演示数据必须设置 ARK_SEED_PASSWORD... EXIT=1
```

### 6.5 旧库门禁（服务 vs 管理命令）

```bash
# 建旧库
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r5-old.sqlite3 \
DJANGO_SETTINGS_MODULE=config.settings.dev \
.venv/bin/python manage.py migrate --noinput
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r5-old.sqlite3 \
DJANGO_SETTINGS_MODULE=config.settings.dev \
.venv/bin/python manage.py seed_demo
# MIGRATE=0 / SEED=0

# 服务入口：拒绝
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r5-old.sqlite3 \
ARK_JWT_SECRET='R5-Str0ng-JWT-Secret-000000000000' \
DJANGO_SETTINGS_MODULE=config.settings.prod \
.venv/bin/python manage.py runserver 127.0.0.1:8899 --noreload
# ImproperlyConfigured ... admin、manager、staff、finance、partner、expert_ext ... EXIT=1

# 管理命令：放行（C-R5-1）
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r5-old.sqlite3 \
ARK_JWT_SECRET='R5-Str0ng-JWT-Secret-000000000000' \
DJANGO_SETTINGS_MODULE=config.settings.prod \
.venv/bin/python manage.py check
# System check identified no issues (0 silenced). EXIT=0
```

### 6.6 强口令复种轮换

```bash
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r5-old.sqlite3 \
ARK_JWT_SECRET='R5-Str0ng-JWT-Secret-000000000000' \
DJANGO_SETTINGS_MODULE=config.settings.prod \
ARK_SEED_DEMO=1 ARK_SEED_PASSWORD='R5-Rotated-Passw0rd!' \
.venv/bin/python manage.py seed_demo
# seed_demo 完成（幂等）： EXIT=0

.venv/bin/python - <<'PY'
import django; django.setup()
from apps.sysadmin.models import SysUser
import bcrypt
old = {"admin":"Admin@123456","manager":"Manager@123456","staff":"Staff@123456",
       "finance":"Finance@123456","partner":"Partner@123456","expert_ext":"Expert@123456"}
for u, p in old.items():
    x = SysUser.objects.get(tenant_id=1, username=u)
    print(u, "new=", bcrypt.checkpw(b"R5-Rotated-Passw0rd!", x.password_hash.encode()),
          "old=", bcrypt.checkpw(p.encode(), x.password_hash.encode()))
from core.startup import find_default_credential_accounts
print("hits=", find_default_credential_accounts(active_only=False))
PY
# admin new=True old=False
# ... 六个均同
# hits= []
```

### 6.7 默认干净库

```bash
rm -f /tmp/e8r5-clean.sqlite3
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r5-clean.sqlite3 \
ARK_JWT_SECRET='R5-Str0ng-JWT-Secret-000000000000' \
DJANGO_SETTINGS_MODULE=config.settings.prod \
.venv/bin/python manage.py migrate --noinput
# MIGRATE=0
# 查询：USERS= 0
```

### 6.8 新回归的「红」验证

在 `/tmp/e8old` 用 `git archive 22609c1` 解出 r4 代码，再把当前 `tests/test_deploy_hardening.py` 复制进去运行（不改仓库）：

```bash
rm -rf /tmp/e8old && mkdir -p /tmp/e8old
git archive 22609c1 | tar -x -C /tmp/e8old
cp backend-django/tests/test_deploy_hardening.py \
   /tmp/e8old/backend-django/tests/test_deploy_hardening.py
cd /tmp/e8old/backend-django
/Users/jacky/works/science-research-project/backend-django/.venv/bin/python -m pytest \
  -q tests/test_deploy_hardening.py \
  -k "prod_settings_defers or process_guard or seed_demo_rejects or gate_fails_closed or account_table_ready" \
  --no-header -p no:cacheprovider
# 5 failed, 3 passed, 20 deselected
# failed: process_guard_blocks_non_exempt_command / process_guard_exempts_remediation_commands /
#         seed_demo_rejects_builtin_default_password / seed_demo_rejects_short_password /
#         account_table_ready_treats_partial_schema_as_unknown
```

说明：`5 failed` 证明这些新用例确实能捕获旧行为；`3 passed` 是保留行为的守卫用例（如 `_account_table_ready` 的 fail-closed 部分、prod 延迟校验）。但 `process_guard` 的失败只证明函数缺失，**不证明接线存在**；当前 HEAD 上该测试仍然是直接调用函数（I-R5-1）。

### 6.9 全量 / 静态检查

```bash
cd backend-django
.venv/bin/python -m pytest -q
# 528 passed, 5 warnings in 33.28s

.venv/bin/python -m pytest -q -k "seed or deploy or credential or secret or guard"
# 40 passed, 488 deselected

DJANGO_SETTINGS_MODULE=config.settings.dev \
.venv/bin/python manage.py makemigrations --check --dry-run
# No changes detected, EXIT=0

cd ..
for f in frontend/scripts/task-m1b-smoke.mjs frontend/scripts/task11-smoke.mjs \
         frontend/smoke-admin-allprojects.mjs frontend/smoke-expense-subject.mjs \
         frontend/smoke-fundingconfig.mjs frontend/smoke-mocktoasts.mjs \
         frontend/smoke-pagegrant.mjs frontend/smoke-projects-views.mjs; do
  node --check "$f" || exit 1
done
# 8 个全部 OK
```

---

## 7. 合并门槛

以下任一项未完成，不应合并：

1. **C-R5-1**：把 `enforce_process_guard()` 接入 `manage.py` 和 `django-admin`/worker 入口；用旧库跑 `python manage.py check` 必须是 `EXIT=1`，并用子进程回归锁定。
2. **I-R5-1**：删除/替换「直接调用函数」的假绿测试；新增 `manage.py` 子进程测试，断言旧库被拒、豁免命令（`migrate`、`rotate_demo_credentials`）仍可运行。
3. **I-R5-2**：test settings 的固定公开 `JWT_SECRET` 改为随机/CI 注入；`ALLOW_DEMO_SEED=True` 与测试专用标志绑定；明确禁止 test settings 用于 served 进程。
4. **I-R5-3**：8 个前端 smoke 删除 `DEMO_PASSWORDS` 回落，未设 `ARK_SMOKE_PASSWORD` 直接报错。
5. **I-R5-4**：修正 `DEPLOY.md:3` 的当前口径；把 README `:99` 的 522 改为 528。
6. 回归复跑：全量 `pytest` ≥ 528 绿；`makemigrations --check` 仍 `No changes`；`design/` 与 `frontend/src/api/schema` 仍零 diff。

---

## 8. 通过项、残留与未测边界

**已通过**：

- 无密钥的 `django.setup` / `python -m django check` / `django-admin check` 全部失败（r4 C-2 的密钥部分真正关闭）。
- 自定义 settings 的生效 `JWT_SECRET` 被校验；强别名通过、短覆盖被拒。
- 旧库在 `wsgi/asgi` 服务入口被默认口令门禁拒绝。
- prod 播种拒绝 `Demo@123456`、无口令、`--force` 无口令；强口令复种轮换六个账号（含 partner/expert）。
- 默认 compose `ARK_SEED_DEMO=0`、空口令、prod settings；干净库 `USERS=0`。
- 自省文档默认关（`docs_url=None`、`openapi_url=None`）。
- 全量 528 绿；`makemigrations` No changes；`design/` 与 `frontend/src/api/schema` 零 diff。

**残留**：

- C-R5-1 / I-R5-1 / I-R5-2 / I-R5-3 见上；`manage.py shell` 仍可读旧库（即使接线，`shell` 仍在豁免集，需要产品决策）。
- `README.md:99` 522、`DEPLOY.md:3` 旧口令、`frontend/dist` 旧文案。
- seed 无事务；低熵口令可通过；`rotate --password` 仍在 argv。

**未测边界**：

- 未跑完整 `docker compose up --build`（无 Docker 镜像构建/容器启动）；C-1 用 `docker compose config` + prod/sqlite `migrate` + 干净库计数验证；服务门禁用 `runserver`/`wsgi` 验证。
- 未在当前 HEAD 重跑 Dockerfile CMD 的 shell stub（r4 已验证过 `fi && gunicorn` 语义，本轮 Dockerfile 未改）；`Dockerfile:23` 仍是 exec-form `sh -c`，语义为 seed 失败则 gunicorn 不启动。
- 未对 `frontend/dist` 做重建；它是生成物，不作为源码结论。
- 未跑真实 PostgreSQL/Redis/MinIO/前端浏览器链路；本轮只审部署凭据/启动门禁。

---

**一句话**：r5 把「弱密钥」和「旧库服务启动」两条主路真正堵住了，但默认口令的**进程级**门禁没有接线，测试又用直接调用函数把这一缺口测绿；在修好 C-R5-1 与 I-R5-2 之前，不能给 APPROVED。
