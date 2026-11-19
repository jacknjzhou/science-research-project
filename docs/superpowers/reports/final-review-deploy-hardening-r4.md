# E-8 部署收口 · 终审 r4（22609c1）

- **仓库**：`/Users/jacky/works/science-research-project`
- **分支**：`develop`
- **审查范围**：`a83c409..22609c1`（5 commits：`6bf5044`、`d255652`、`43b5688`、`1e6af75`、`22609c1`）
- **本轮新增**：`22609c1 fix(config): 启动自检改为 fail-closed + 跨租户，文档与冒烟脚本去默认口令（E-8 终审 r3）`
- **计划**：`docs/superpowers/plans/2026-11-19-deploy-hardening.md`
- **Ledger**：`.superpowers/sdd/2026-11-19-deploy-hardening/progress.md`
- **Diff 包**：`/tmp/review-deploy-hardening-r4.diff`（54539 bytes）
- **审查方式**：只读；唯一写入为本文件。源码、测试、编排均未修改。

## 0. 结论

**REQUEST_CHANGES。**

r3 的两个 Critical（旧库默认口令、文档修复命令不可执行）在**标准 compose/gunicorn 路径**上已基本关闭：

- 默认 compose 不再播种（`ARK_SEED_DEMO=0`、`ARK_SEED_PASSWORD` 为空），干净库用户数为 0；
- 旧库 gate 能跨租户命中原六个账号并拒绝启动；
- `rotate_demo_credentials` 能轮换六个账号，旧口令登录 401、新口令 200；
- `docker compose run --rm --no-deps` 替代 `exec`，方向正确；
- 全量 `pytest` **522 passed**，`makemigrations --check` 为 `No changes detected`，`design/` 与 `frontend/src/api/schema/` 零 diff。

但本轮仍有两个可造成**凭据泄露/生产带默认密钥**的 Critical，以及数个 Important：

1. **C-R4-1**：`seed_demo` 只检查“有没有给 `ARK_SEED_PASSWORD`”，不拒绝已知默认口令；我用 `Demo@123456` 在 prod 形态播种成功，库里出现六个公开口令账号。gate 会拦住 gunicorn，但 DB 已经被写成公开凭据，且不是所有 Django 进程都会执行 gate。
2. **C-R4-2**：`config.settings.prod` 在缺少 `ARK_JWT_SECRET` 时不再 import 期失败，只由 `wsgi.py`/`asgi.py`/`manage.py` 三个入口在运行期检查；直接 `django.setup()`、`django-admin` 管理命令、Celery worker/beat（spec §9.2 的计划形态）会以 `DEBUG=False` + 仓库默认 JWT 密钥继续运行。实测 `django.setup()` 与 `django-admin check` 均 exit 0。
3. **I-R4-1**：`core/startup.py:142-149` 把 `table_names()` 不含 `sys_user` 一律当作“表还没建”放行；一个可连接、已有其他表但没有 `sys_user` 的库实测 `GATE=PASS`。空 schema/partial schema/权限只暴露部分表时，这是静默放行路径。
4. **I-R4-2**：README `:79`、`:104` 和 `scripts/compose-smoke-auth.sh:47` 仍写死 `Admin@123456`/`Staff@123456`；按当前默认/显式演示路径起容器后，文档给的账号和 auth smoke 的第 5 步都会失败。
5. **I-R4-3**：自定义 settings 用 `MY_JWT_SECRET` 提供强密钥、完全不设 `ARK_JWT_SECRET` 时，import 期不再误杀（符合本轮目标），但运行期仍强制要求 `ARK_JWT_SECRET`，所以该自定义部署**无法真正启动**；`prod.py:25-29` 的注释说“允许自己的密钥来源”，与实现矛盾。

## 1. 验收矩阵（逐条对应本轮要求）

| # | 要求 | 结果 | 关键证据 |
|---|---|---|---|
| 1 | C-R3-1：连不上库必须 fail-closed，不能静默放行 | **部分通过** | 不存在的 sqlite 路径：5 次尝试后 exit 1，8.02s，消息“启动自检无法确认数据库中的默认口令状态”；但 `table_names()` 不含 `sys_user` 的可连接库仍 PASS（见 I-R4-1） |
| 2 | C-R3-2：旧卷升级路径可执行 | **通过（有边界）** | README `:61-68` 已改 `docker compose run --rm --no-deps`；prod+sqlite 旧库轮换 6 账号后 gate PASS。未起真实 `docker compose up --build`，见 §8 |
| 3 | I-R3-1：跨租户扫描 | **通过** | 仅 tenant 2 的 `admin/Admin@123456`：`hits=['admin']`，`GATE=BLOCKED` |
| 4 | I-R3-2：rotate 拒绝 `Demo@123456` 并自检 | **通过** | `rotate_demo_credentials --password 'Demo@123456'` → `CommandError: 新口令不得是仓库内置的默认口令（含 Demo@123456）。` exit 1 |
| 5 | I-R3-3：gate 只看 ACTIVE，rotate 轮换所有状态 | **通过（产品取舍）** | 单个 DISABLED + 默认口令：`find` 返回 `[]`，gate PASS；rotate 仍会轮换该账号 |
| 6 | I-R3-4：README/脚本/UI/注释去默认口令，systemd 补 settings module | **不通过** | `README.md:79`、`:104` 仍写 `admin/Admin@123456`；`scripts/compose-smoke-auth.sh:47` 仍 `login staff 'Staff@123456'`；`frontend/smoke-*.mjs` 多处旧口令（见 I-R4-2） |
| 7 | I-R3-5：自定义 settings 不再 import 误杀，运行期仍拦 | **部分通过/设计矛盾** | `MY_JWT_SECRET` 强密钥、无 ARK：import 成功（DEBUG=False，JWT 36 字符），运行期仍 `BLOCKED 必须显式设置 ARK_JWT_SECRET`；设置 ARK 后才 PASS。见 I-R4-3 |
| 8 | 新增回归是否真红 | **7/8 红，1 绿** | 对 `1e6af75` 逐个跑新测试：7 failed，1 passed；`test_gate_allows_when_table_missing` 红是因为旧代码没有 `_account_table_ready`（结构性红），`test_prod_settings_module_refuses_weak_secret_at_import` 旧代码本来就会绿 |
| 9 | 启动期 bcrypt 成本 | **通过但线性增长** | 6 行 ~2.28s；24 个跨租户 `admin` 行 **3.836s**；每个 gunicorn worker 各跑一次 |
| 10 | 回归与卫生 | **通过** | 522 passed；makemigrations No changes；`design/`+`frontend/src/api/schema/` 零 diff；22609c1 11 files +266/-69，无夹带；App.vue 仅 1 行 |

## 2. 实测数字

| 项目 | 命令/环境 | 结果 |
|---|---|---|
| 全量测试 | `backend-django/.venv/bin/python -m pytest -q` | `522 passed, 5 warnings in 32.83s` |
| 定向测试 | `-k "seed or deploy or credential or secret"` | `27 passed, 495 deselected, 1 warning in 21.21s` |
| 新测试在旧代码 | 1e6af75 归档 + 新 `tests/test_deploy_hardening.py` | 7 failed，1 passed（见 §6.9） |
| 迁移 | `manage.py makemigrations --check --dry-run`（dev/sqlite） | `No changes detected`，exit 0 |
| diff | `git diff --stat a83c409..22609c1` | 19 files，+855/-25 |
| 本轮 commit | `git show --stat 22609c1` | 11 files，+266/-69 |
| 设计/契约 | `git diff --stat a83c409..22609c1 -- design frontend/src/api/schema` | 0 行 |
| gate 不可达 | `ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r4-missing/no/such/db.sqlite3` | `GATE=FAIL_CLOSED 8.02s`（attempts=5，实际 4 次 sleep） |
| 跨租户 | tenant 2 仅一个 `admin/Admin@123456` | `hits=['admin']`，`GATE=BLOCKED` |
| 空/部分 schema | sqlite 只有 `other` 表，无 `sys_user` | `ready=False`，`GATE=PASS` |
| seed 用公开口令 | prod + `ARK_SEED_DEMO=1 ARK_SEED_PASSWORD=Demo@123456` | seed exit 0，创建 6 个账号；随后 gate `BLOCKED` |
| rotate 用公开口令 | `--password Demo@123456` | CommandError，exit 1 |
| rotate 用 env | `ARK_ROTATE_PASSWORD='Env-R0tated-Pass!'` | `已轮换 1 个账号：admin@1`；`自检通过`，exit 0 |
| 自定义密钥源 | `MY_JWT_SECRET` 强、无 ARK | import 成功；`RUNTIME=BLOCKED`；加 ARK 后 `PASS_WITH_ARK` |
| compose 必填 | `env -u ARK_JWT_SECRET docker compose config` | exit 1，`required variable ARK_JWT_SECRET is missing a value` |
| compose 默认 | `ARK_JWT_SECRET=... docker compose config` | `ARK_SEED_DEMO: "0"`、`ARK_SEED_PASSWORD: ""`、`DJANGO_SETTINGS_MODULE: config.settings.prod` |
| 启动扫描成本 | 24 个 tenant 的 `admin` 同名行，均为默认口令 | `3.836s`（每次 `find_default_credential_accounts()`） |

## 3. Critical

### C-R4-1：`seed_demo` 接受已知默认口令，仍然能把公开 R-ADMIN 写进库

- `backend-django/apps/sysadmin/management/commands/seed_demo.py:152-157` 的 `_guard` 只做：

```python
env_pwd = os.environ.get("ARK_SEED_PASSWORD") or None
if not demo_mode and not env_pwd:
    raise CommandError("非开发形态播种演示数据必须设置 ARK_SEED_PASSWORD，"
                       "不接受仓库内置的默认口令（admin/Admin@123456 等公开凭据）。")
return env_pwd
```

它没有把 `env_pwd` 与 `core.startup.DEFAULT_SEED_PASSWORDS` 比较。`seed_demo.py:37-40` 的 `USERS` 仍然把 `Admin@123456`、`Manager@123456`、`Staff@123456`、`Finance@123456` 作为默认值；`:1134`、`:1256` 还有 partner/expert 的默认值。

**复现**：

```bash
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r4-seed-default.sqlite3 \
ARK_JWT_SECRET='R4-...' DJANGO_SETTINGS_MODULE=config.settings.prod \
python manage.py migrate --noinput

ARK_SEED_DEMO=1 ARK_SEED_PASSWORD='Demo@123456' \
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r4-seed-default.sqlite3 \
ARK_JWT_SECRET='R4-...' DJANGO_SETTINGS_MODULE=config.settings.prod \
python manage.py seed_demo
```

输出 `seed_demo 完成`，exit 0；随后 `assert_no_default_credentials()` 报：

```
检测到仍在使用仓库默认口令的账号：admin、manager、staff、finance、partner、expert_ext。
```

**为什么仍判 Critical**：`seed_demo` 是文档化的部署命令，它在 gate 之前执行；它已经把公开口令写进数据库。标准 gunicorn 会被 gate 拦住，但：

- `manage.py` 本身只调用 `validate_runtime_secrets()`，不调用 `assert_no_default_credentials()`（`manage.py:7-14`）；
- `django-admin` 管理命令完全绕过 `manage.py`；
- spec §9.2 计划的 Celery worker/beat 不经过 `wsgi.py`/`asgi.py`；
- 只要有一个进程/脚本使用该 DB，公开 R-ADMIN 就是实际凭据。

**修复**：`_guard` 应复用 `DEFAULT_SEED_PASSWORDS` 拒绝已知默认值，和 `rotate_demo_credentials.py:42` 保持同一判据；并补一条 `ARK_SEED_PASSWORD=Demo@123456` 的回归。

### C-R4-2：prod 的 import 期密钥检查被移除，非三入口的 Django 进程会带默认 JWT 启动

- `backend-django/config/settings/prod.py:25-31`：

```python
if os.environ.get("ARK_JWT_SECRET"):
    validate_secret_value(str(JWT_SECRET or ""), origin="config.settings.prod.JWT_SECRET")
```

缺 `ARK_JWT_SECRET` 时 import 直接成功。
- 运行期检查只在 `config/wsgi.py:16-19`、`config/asgi.py:16-19`、`manage.py:7-14`。
- `django.setup()`、`django-admin` 管理命令、Celery worker/beat 等不经过这三处。

**复现**：

```bash
cd backend-django
env -u ARK_JWT_SECRET DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/python -c "import django;django.setup();from django.conf import settings;print(settings.DEBUG, settings.JWT_SECRET)"
# DEBUG= False
# JWT_SECRET= dev-secret-change-me-please-use-32-bytes-min!
# exit 0

env -u ARK_JWT_SECRET PYTHONPATH=. DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/django-admin check
# System check identified no issues (0 silenced).
# exit 0
```

标准 `django-admin runserver` 因为 `WSGI_APPLICATION = "config.wsgi.application"`（`base.py:51`）会 import `config.wsgi`，被运行期检查拦住；这一点不能夸大。但 `django.setup()`、`django-admin check/migrate/shell`、Celery worker/beat、任何自定义 `gunicorn myapp:app` 只要不 import `config.wsgi`/`asgi`，就会带着仓库公开的 `dev-secret-change-me-please-use-32-bytes-min!` 运行。对签名密钥来说，这等同“任何读过仓库的人都能伪造 JWT”。

**修复**：把密钥检查放回 `prod.py` import 期，或放到所有 Django 进程都会 import 的 `config/__init__.py`；为 `rotate_demo_credentials` 提供显式 bypass（例如 `ARK_ALLOW_ROTATE_WITHOUT_SECRET=1`），而不是全局移除。若要支持 Vault/自定义密钥源，应允许“最终 `settings.JWT_SECRET` 强”即通过，不能要求 `ARK_JWT_SECRET` 必须存在。

**测试覆盖**：`tests/test_deploy_hardening.py:78-98` 的 `test_prod_settings_defers_missing_env_to_runtime` 把“缺 env 时 prod 可以 import”固化为正确行为；旧测试 `test_prod_settings_module_refuses_to_import_without_secret` 被替换。这正好把本 Critical 的回归保护删掉了。

## 4. Important

### I-R4-1：`table_names()` 不含 `sys_user` 就放行，不是严格 fail-closed

`backend-django/core/startup.py:142-149`：

```python
return "sys_user" in connection.introspection.table_names()
```

`assert_no_default_credentials()` 在返回 `False` 时直接 `return`（`:171-172`）。但 `False` 同时覆盖：

- 真正的首次 migrate 前空库（预期放行）；
- 已有其他表、但 `sys_user` 尚未/未能迁移的 partial schema；
- 当前 DB 角色对 `sys_user` 没有目录可见性、但应用另有查询路径；
- search_path 指向错误 schema、DB proxy 只暴露部分表。

**复现**（可连接、已有 `other` 表、没有 `sys_user`）：

```bash
ready= False
GATE=PASS
```

**影响**：这是 gate 的静默放行分支。当前复现库里没有 `sys_user`，登录本身也不可用，所以不等同于已可利用的凭据泄露；但它违背了报告宣称的“只有表尚未创建才放行”，在权限/搜索路径不一致的部署里可能变成真正的绕过。建议改为直接 `SELECT 1 FROM sys_user LIMIT 1`，只在明确的“表不存在”（PostgreSQL `42P01`/sqlite `no such table`）时放行；权限、连接、超时一律 fail-closed。

### I-R4-2：README 和 auth smoke 仍残留旧口令，I-R3-4 未收口

全仓 grep 仍能在**当前运维路径**找到：

- `README.md:79`：`演示账号（启动时 seed_demo 幂等播种）：admin / Admin@123456。`
  - 默认 `ARK_SEED_DEMO=0` 时没有账号；显式演示时口令由 `ARK_SEED_PASSWORD` 决定。这句是假的。
- `README.md:104`：`生产/CI 请用种子账号（如 admin/Admin@123456）登录，scripts/compose-smoke.sh 已改用种子账号。`
  - 生产默认不播种；且 `Admin@123456` 已不是有效口令。
- `scripts/compose-smoke-auth.sh:47`：`STAFF_TOKEN=$(login staff 'Staff@123456')`
  - 第 2 步已改为 `ARK_SMOKE_USER`/`ARK_SMOKE_PASSWORD`，第 5 步仍写死；用 `ARK_SEED_PASSWORD='...'` 播种后，staff 的口令是同一枚自定义口令，`Staff@123456` 必失败。
- `frontend/smoke-*.mjs`、`frontend/scripts/task11-smoke.mjs` 等仍有多处 `Admin@123456`/`Staff@123456`/`Manager@123456`；`DEPLOY.md:3` 也仍写旧账号。
- `frontend/src/App.vue:275` 已正确改为“部署方通过 `ARK_SEED_PASSWORD` 指定”，这一点通过。

**判断**：这不是新的凭据泄露（gate 会拦住标准启动），但 I-R3-4 明确要求“README/脚本/UI 去默认口令”，现在未完成；按 README 起容器后登录会 401，`compose-smoke-auth.sh` 第 5 步必失败。合并前应全仓清理当前路径，历史计划/测试 fixture 可保留。

### I-R4-3：自定义 settings 的“自己的密钥来源”仍无法启动

- `prod.py:25-29` 注释说：缺 ARK 时不拦，允许 `from .prod import *` 的自定义 settings 用自己的密钥来源（例如 Vault 注入后覆盖 `JWT_SECRET`）。
- 实测自定义 `MY_JWT_SECRET`：

```python
import os
from config.settings.prod import *
JWT_SECRET = os.environ["MY_JWT_SECRET"]
```

```bash
env -u ARK_JWT_SECRET MY_JWT_SECRET='Alias-Str0ng-JWT-Secret-000000000000' \
PYTHONPATH=/tmp/e8r4 DJANGO_SETTINGS_MODULE=custom_alias \
python -c "import django;django.setup();from core.startup import validate_runtime_secrets;validate_runtime_secrets()"
# DEBUG= False JWT_LEN= 36
# RUNTIME=BLOCKED 生产环境必须显式设置 ARK_JWT_SECRET
```

加 `ARK_JWT_SECRET` 后才 `PASS_WITH_ARK`。也就是说 import 期不再误杀，但运行期仍强制 ARK，所谓“自定义密钥源”不能独立工作。

**判断**：如果产品要求 `ARK_JWT_SECRET` 永远必填，应删掉 `prod.py:25-29` 的“允许自定义来源”表述，并让 README 明确；如果确实支持 Vault/别名 env，运行期应校验最终 `settings.JWT_SECRET`，不应先要求 `ARK_JWT_SECRET` 存在。

### I-R4-4：`manage.py` 只做密钥检查，不做默认口令 gate

`manage.py:7-14` 只调用 `validate_runtime_secrets()`；`assert_no_default_credentials()` 只在 `wsgi.py`/`asgi.py`。

- 标准 `manage.py runserver` 因为 `WSGI_APPLICATION` 仍会 import `config.wsgi`，被 gate 拦住（实测启动失败）；
- 但其他 `manage.py` 命令、`django-admin`、Celery worker/beat 不跑 gate；它们可以使用带公开口令的 DB。
- 这是 C-R4-1 的放大器，也是 C-R4-2 的同类问题：安全 gate 依赖入口，而不是依赖“Django 已启动”。

**修复**：给 `manage.py` 加 `--skip-credential-gate` 白名单（只允许 `rotate_demo_credentials`/`migrate`），或在 `config/__init__.py` 统一做一次 gate；不要让“为了 rotate 能跑”变成所有命令都不跑。

### I-R4-5：跨租户扫描的成本随同名账号线性增长

`find_default_credential_accounts()` 现在 `username__in` 六个名字、跨全部租户，逐行 `bcrypt.checkpw`。实测：

- 6 行（tenant 1）≈ 2.28s；
- 24 行（tenant 2..25 的同名 admin）≈ **3.836s**；
- Dockerfile `-w 4`：4 个 worker 各跑一次，启动阶段约 15s CPU；
- `docker-compose.yml:49-54` healthcheck `start_period: 60s`，100+ 同名账号时可能超过，容器进入 crash-loop。

**修复**：启动时只做一次预检（例如 gunicorn `--preload` 或独立 init），或缓存扫描结果；至少给 healthcheck 留出与账号规模相关的余量。

## 5. Minor

- **M-R4-1**：`find_default_credential_accounts()` 只查 `deleted=0`；软删除的默认口令账号被跳过。若后台可恢复，仍是潜在暴露。
- **M-R4-2**：`rotate_demo_credentials` 逐行 `save`，无事务；中途失败会部分轮换。gate 仍会拦截，不会“半通过”，但重试需幂等。
- **M-R4-3**：README `:64` 的 `docker compose run` 命令没有提醒先 `export ARK_JWT_SECRET`。缺该 env 时 compose 在插值阶段就报 `required variable`，错误清楚但修复命令本身跑不到容器；`--no-deps` 下 DB 未起时也只是 Django traceback，不是友好提示。
- **M-R4-4**：`tests/test_security_hardening.py:501-515` 的 `test_prod_settings_have_debug_off` 仍 monkeypatch `config.settings.base`，docstring 却说“prod 在 import 期校验密钥”；该行为已在 r4 改变，测试注释过期，且没有覆盖真实 env 路径。
- **M-R4-5**：`test_gate_fails_closed_when_db_unreachable` 只 monkeypatch `_account_table_ready=None`，没有覆盖“introspection 成功但 `find` 查询抛 DatabaseError”的重试分支。
- **M-R4-6**：`test_gate_allows_when_table_missing` 在旧代码上红是因为 `_account_table_ready` 不存在（AttributeError），不是行为回归；新增 8 个测试中 `test_prod_settings_module_refuses_weak_secret_at_import` 在旧代码上也绿。所谓“7 条真红”基本成立，但有一条是结构性红、有一条不是回归。
- **M-R4-7**：`docker-compose.yml:5` 已改对；`Dockerfile` 注释已改；spec `docs/superpowers/specs/2026-10-17-backend-django-rewrite-spec.md:206-207` 仍写 `ARK_SEED_DEMO` 默认 1、settings 默认 dev；`DEPLOY.md:3` 仍写旧演示账号。历史文档可保留，但需标注“历史”。
- **M-R4-8**：`ALLOWED_HOSTS=["*"]`（`prod.py:17`）仍是公开暴露面；不属于本轮范围，但生产收口应至少给出显式配置项。
- **M-R4-9**：`seed_demo` 无 `transaction.atomic`，部分写入仍可能；与 r1/r2 相同，本轮未处理。

## 6. 我亲手跑的命令与结果

> 全部在 `/Users/jacky/works/science-research-project/backend-django`，使用 `.venv/bin/python`（Python 3.13.12，Django 5.2.19，pytest 9.2.0）。未修改源码；旧代码实验用 `/tmp/e8r4-old.*` 的 `git archive 1e6af75` 副本。

### 6.1 全量/定向测试

```bash
.venv/bin/python -m pytest -q
# 522 passed, 5 warnings in 32.83s

.venv/bin/python -m pytest -q -k "seed or deploy or credential or secret"
# 27 passed, 495 deselected, 1 warning in 21.21s
```

### 6.2 prod 缺密钥的 import/入口行为

```bash
env -u ARK_JWT_SECRET DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/python -c "import django;django.setup();from django.conf import settings;print(settings.DEBUG, settings.JWT_SECRET)"
# DEBUG= False
# JWT_SECRET= dev-secret-change-me-please-use-32-bytes-min!
# exit 0

env -u ARK_JWT_SECRET PYTHONPATH=. DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/django-admin check
# System check identified no issues (0 silenced).
# exit 0
```

对照：`manage.py check` 会因 `_validate_if_prod()` 拒绝；`django-admin runserver` 因 `WSGI_APPLICATION` import `config.wsgi` 被运行期检查拦住。说明“三入口覆盖”而不是“所有 Django 进程覆盖”。

### 6.3 gate 不可达库

```bash
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r4-missing/no/such/db.sqlite3 \
ARK_JWT_SECRET='R4-...' DJANGO_SETTINGS_MODULE=config.settings.prod \
.venv/bin/python -c "import django;django.setup();from core.startup import assert_no_default_credentials;assert_no_default_credentials()"
# GATE=FAIL_CLOSED 8.02 启动自检无法确认数据库中的默认口令状态（不会在未知状态下启动）
# exit 1
```

代码是 `attempts=5, delay=2.0`，实际 4 次 sleep，共 8s；不是用户描述的“5×2s=10s”。

### 6.4 跨租户

```bash
# tenant 2 仅一个 admin/Admin@123456
hits= ['admin']
GATE=BLOCKED 检测到仍在使用仓库默认口令的账号：admin。
```

### 6.5 可连接但无 `sys_user`

```bash
# sqlite 文件里只有 other 表
ready= False
GATE=PASS
```

### 6.6 seed 用公开默认口令

```bash
ARK_SEED_DEMO=1 ARK_SEED_PASSWORD='Demo@123456' ... manage.py seed_demo
# seed_demo 完成（幂等）... users +4 ...
# exit 0
# 随后 gate:
# GATE=BLOCKED 检测到仍在使用仓库默认口令的账号：admin、manager、staff、finance、partner、expert_ext。
```

### 6.7 rotate

```bash
manage.py rotate_demo_credentials --password 'Demo@123456'
# CommandError: 新口令不得是仓库内置的默认口令（含 Demo@123456）。
# exit 1

ARK_ROTATE_PASSWORD='Env-R0tated-Pass!' manage.py rotate_demo_credentials
# 已轮换 1 个账号：admin@1
# 自检通过：已无默认口令账号。
# exit 0
```

### 6.8 自定义 settings 别名 env

```bash
env -u ARK_JWT_SECRET MY_JWT_SECRET='Alias-Str0ng-JWT-Secret-000000000000' \
PYTHONPATH=/tmp/e8r4 DJANGO_SETTINGS_MODULE=custom_alias \
python -c "import django;django.setup();from core.startup import validate_runtime_secrets;validate_runtime_secrets()"
# DEBUG= False JWT_LEN= 36
# RUNTIME=BLOCKED 生产环境必须显式设置 ARK_JWT_SECRET
```

### 6.9 新测试对旧代码（1e6af75）

```bash
git archive 1e6af75 backend-django | tar -x -C /tmp/e8r4-old...
cp backend-django/tests/test_deploy_hardening.py /tmp/e8r4-old.../tests/
# 逐个跑新测试
# 7 failed, 1 passed
```

红的 7 个：`test_gate_is_cross_tenant`、`test_gate_ignores_non_active_accounts`、`test_gate_fails_closed_when_db_unreachable`、`test_gate_allows_when_table_missing`（AttributeError：旧代码没有 `_account_table_ready`）、`test_rotate_rejects_fallback_default_password`、`test_rotate_reports_remaining_accounts`、`test_prod_settings_defers_missing_env_to_runtime`。
绿的 1 个：`test_prod_settings_module_refuses_weak_secret_at_import`（旧代码本来就拒绝弱 env，属于非回归）。

### 6.10 编排/卫生

```bash
env -u ARK_JWT_SECRET docker compose config
# exit 1: required variable ARK_JWT_SECRET is missing a value

ARK_JWT_SECRET='R4-...' docker compose config
# ARK_SEED_DEMO: "0"
# ARK_SEED_PASSWORD: ""
# DJANGO_SETTINGS_MODULE: config.settings.prod

git diff --stat a83c409..22609c1
# 19 files changed, 855 insertions(+), 25 deletions(-)

git diff --stat a83c409..22609c1 -- design frontend/src/api/schema
# 0 lines

python manage.py makemigrations --check --dry-run
# No changes detected
```

## 7. 合并门槛

在以下条件全部满足前，不建议合并/发布：

1. **C-R4-1**：`seed_demo._guard` 拒绝 `DEFAULT_SEED_PASSWORDS`（至少 `Demo@123456` 与四个 USERS 默认值），与 `rotate_demo_credentials` 共用判据；增加回归测试。
2. **C-R4-2**：恢复“所有 Django 进程”都能触发的密钥检查（`prod.py` import 期或 `config/__init__.py`），或明确把 `ARK_JWT_SECRET` 设为所有 worker/beat/管理命令的硬前提；为 `rotate` 提供显式 bypass，而不是全局移除。补 `django.setup()`/`django-admin`/worker 的回归。
3. **I-R4-1**：`table_names()` 不含 `sys_user` 不能直接放行；只允许明确的“表不存在”，权限/连接/超时 fail-closed；补 partial schema/权限测试。
4. **I-R4-2**：清掉 `README.md:79`、`:104`、`scripts/compose-smoke-auth.sh:47` 和当前 frontend smoke 里的旧口令；auth smoke 的 staff 也必须从 env 读，或复用 `ARK_SMOKE_USER/PASSWORD`。
5. **I-R4-3**：要么在文档/代码中明确 `ARK_JWT_SECRET` 必填（删除“自定义密钥源”表述），要么允许强 `settings.JWT_SECRET` 在无 ARK 时通过；二者选一并测试。
6. **I-R4-5**：评估 100+ 同名账号的启动成本，避免 healthcheck `start_period` 超时；至少做一次预检/缓存。
7. 重跑：全量 `pytest -q` ≥522、`makemigrations --check` No changes、`design/`+`frontend/src/api/schema/` 零 diff；新增 Critical 回归必须真红。

## 8. 已通过项与边界

**已通过（有证据）**：

- 默认 compose：`ARK_SEED_DEMO=0`、`ARK_SEED_PASSWORD=""`，干净库不建演示账号。
- `ARK_JWT_SECRET` 必填插值：无 env 时 `docker compose config` 直接 exit 1，不会起容器。
- Dockerfile CMD 仍是 `migrate && if seed; fi && gunicorn`；seed 失败不会启动 gunicorn（fail-closed）。
- 旧库六个默认口令：跨租户 gate 命中；`rotate_demo_credentials` 可轮换；旧口令 401、新口令 200。
- `rotate --password Demo@123456` 已拒绝；`ARK_ROTATE_PASSWORD` 可用。
- 禁用账号不再阻断启动（产品取舍已明确）。
- 文档默认关闭：`core/ninja.py:16-22` 逻辑未变；实际路径仍是 `/api/v1/docs`、`/api/v1/openapi.json`。
- `frontend/src/App.vue:275` 已去掉默认口令提示。
- 全量 522、定向 27、makemigrations No changes、design/schema 零 diff、commit 无夹带。

**未执行/边界**：

- 未跑完整 `docker compose up --build`，也未用真实 PostgreSQL 跑旧卷升级；C-R3-2 用 prod+sqlite 模拟了 `run` 的代码路径，compose 只做 `config` 解析。
- 未跑 `docker compose run --rm --no-deps backend ...` 的真实容器（DB 未起时预期 Django traceback；`ARK_JWT_SECRET` 缺失时 compose 插值先失败）。
- 未跑 read-only replica、真实权限隔离、Celery worker/beat（仓库目前没有 `config/celery.py`，spec §9.2 只是计划）。
- 未做 100+ 租户规模压测；24 行数据给出线性趋势。
- 未修改源码；工作区原有的 `docs/` 删除/未跟踪文件不在本次范围。
