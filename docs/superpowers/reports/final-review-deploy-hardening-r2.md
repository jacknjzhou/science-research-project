# E-8 部署收口 · 终审报告（r2）

- **仓库**：`/Users/jacky/works/science-research-project`
- **分支**：`develop`
- **审查范围**：`a83c409..43b5688`（3 commits：`6bf5044`、`d255652`、`43b5688`）
- **计划**：`docs/superpowers/plans/2026-11-19-deploy-hardening.md`（5 任务）
- **Ledger**：`.superpowers/sdd/2026-11-19-deploy-hardening/progress.md`
- **Diff 包**：`/tmp/review-deploy-hardening-r2.diff`（43260 bytes）
- **审查方式**：只读代码审查 + 独立复现；唯一写入是本报告。

---

## 0. 结论

**REQUEST_CHANGES**

r1 的三条意见里，C-1（compose 默认公开口令）已实测关闭，C-2（既有账号轮换）在**显式复种**路径上已生效，I-1 的“自定义 settings 继承 prod 时按模块名漏检”已修复。

但仍有必须阻断合并的问题：

1. **C-2 的默认升级路径未关闭**：已有旧数据卷执行文档里的默认 `docker compose up` 时，`ARK_SEED_DEMO=0` 不触发 `seed_demo`，`_rotate_password()` 永远不会执行；旧的 `admin/Admin@123456`（R-ADMIN）继续有效。r2 只修了“显式 `ARK_SEED_DEMO=1` + `ARK_SEED_PASSWORD` 复种”这一条路，没有修默认升级路径。
2. **I-1 仍有旁路**：`validate_runtime_secrets()` 检查的是环境变量 `ARK_JWT_SECRET`，而 JWT 实际使用 `settings.JWT_SECRET`。自定义 settings 在 `from config.settings.prod import *` 之后覆盖 `JWT_SECRET="short"`，只要环境变量是强值，自检就通过，进程仍用弱密钥签发/校验令牌。
3. 文档/脚本/前端仍有旧口令与错误路径，默认干净库没有 README 宣称的演示账号；生产 systemd 文档仍漏 `DJANGO_SETTINGS_MODULE`。

---

## 1. 必查矩阵

| # | 检查项 | 结论 | 证据 / 说明 |
|---|--------|------|-------------|
| 1a | 无 `ARK_JWT_SECRET` 以 prod 启动必须失败 | ✅ PASS | `manage.py check` 在 `config.settings.prod` 下 `EXIT=1`，`ImproperlyConfigured`；空串、纯空白、仓库默认值、短于 32 均拒绝 |
| 1b | `ARK_SEED_DEMO=1` 但无 `ARK_SEED_PASSWORD`、非 dev 必须拒绝 | ✅ PASS | prod + sqlite：`CommandError: 非开发形态播种演示数据必须设置 ARK_SEED_PASSWORD...`，`EXIT=1`；空串按未给处理（`seed_demo.py:152` 的 `or None`） |
| 1c | 未设 `ARK_API_DOCS` 且 `DEBUG=False` 时自省文档不存在 | ✅ PASS（路径需注意） | `docs_enabled()=False`，`api.docs_url=None`、`api.openapi_url=None`；`/docs`、`/openapi.json`、`/api/v1/docs` 均 404。实际挂载点是 `/api/v1/docs`、`/api/v1/openapi.json`（`config/urls.py:24`），README `:175` 写成了 `/docs` |
| 2 | 自检判据/绕过面 | ⚠️ PARTIAL | 自定义 settings 的**触发**已修（`core/startup.py:46` 按运行期 `DEBUG`）；但判据读 env 而非 effective `settings.JWT_SECRET`，可被覆盖绕过；32 字符低熵值可通过；空白串已拒绝 |
| 3 | seed 门禁副作用 | ⚠️ PARTIAL | 全量 `pytest` 511 绿；dev `manage.py seed_demo` 仍可用；但 seed 无事务，失败会留下部分角色/用户/授权；`manage.py test` 被误伤（见 I-4） |
| 4 | 编排/Dockerfile 正确性 | ✅ PASS | `${ARK_JWT_SECRET:?...}` 缺值直接失败；默认 `ARK_SEED_DEMO=0`、`ARK_SEED_PASSWORD=`；CMD 的 `fi && gunicorn` 在 `sh` 下语义正确，seed 失败会阻止 gunicorn |
| 5 | 文档一致性 | ❌ FAIL | README `:66`、`:91` 仍宣称 `admin/Admin@123456`；默认干净库实际无账号；smoke 脚本硬编码旧口令；生产段漏 settings module |
| 6 | 回归与卫生 | ✅ PASS（有 stale 注释） | `design/`、`frontend/` 零改动；`makemigrations --check` = `No changes detected`；README 的 511 与实测一致；两批 commit 无夹带无关源码 |

---

## 2. 实测数字

| 项目 | 结果 |
|------|------|
| 全量测试 | `511 passed, 5 warnings in 28.75s` |
| 目标测试 | `pytest -q -k "seed or deploy"` → `14 passed, 497 deselected` |
| `makemigrations --check --dry-run` | `No changes detected`，`EXIT=0`（仅有 PG 5432 连接 warning） |
| compose 默认解析 | `ARK_SEED_DEMO="0"`、`ARK_SEED_PASSWORD=""`、`DJANGO_SETTINGS_MODULE=config.settings.prod` |
| 无 `ARK_JWT_SECRET` 的 compose | `docker compose config` 直接报 `required variable ARK_JWT_SECRET is missing a value`，`EXIT=1` |
| C-2 显式复种 | 六个账号新口令全 `True`，六个旧默认口令全 `False` |
| C-2 默认升级 | 旧库 6 个账号；只跑 prod `migrate` 后 `admin/Admin@123456` 仍 `True` |
| 自省文档 | 默认 `/api/v1/docs` 404；`ARK_API_DOCS=1` 时 200 |
| 设计/前端 diff | `0` 行 |
| 总 diff | 15 files, `+402/-19`（43b5688 本身 10 files, `+238/-64`） |

---

## 3. Critical

### C-2 默认升级仍保留旧公开口令（r1 C-2 未真正关闭）

**结论**：显式复种能轮换，但文档里的默认升级命令不会复种，旧 `admin/Admin@123456` 继续有效。这是可被外部登录的 R-ADMIN 公开凭据，属于凭据泄露类缺陷。

**证据**：

- `docker-compose.yml:29-30`：`ARK_SEED_DEMO` 默认 `0`、`ARK_SEED_PASSWORD` 默认空。
- `backend-django/Dockerfile:22`：只有 `ARK_SEED_DEMO=1` 才执行 `python manage.py seed_demo`。
- `backend-django/apps/sysadmin/management/commands/seed_demo.py:160-178`：`_rotate_password()` 只在 `seed_demo` 被调用且传入了 `override_pwd` 时执行。
- 调用点：`seed_demo.py:207`（admin/manager/staff/finance）、`:1140`（partner）、`:1260`（expert_ext）。
- `README.md:54-55` 只说“已存在库重播种时”会轮换，没有把“默认升级必须显式复种”写成强制步骤，也没有警告默认 `docker compose up` 不会轮换。

**复现**（旧库用 dev 形态播种旧默认口令，再用新版本默认 compose 方式升级）：

```bash
cd backend-django

# 1) 模拟升级前的旧库：dev 形态会播种全部六個旧默认口令
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r2-upgrade.sqlite3 \
  DJANGO_SETTINGS_MODULE=config.settings.dev \
  .venv/bin/python manage.py migrate
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r2-upgrade.sqlite3 \
  DJANGO_SETTINGS_MODULE=config.settings.dev \
  .venv/bin/python manage.py seed_demo

# 2) 新版本默认升级：只 migrate（对应 compose 默认 ARK_SEED_DEMO=0）
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r2-upgrade.sqlite3 \
  ARK_JWT_SECRET='R2-Str0ng-JWT-Secret-For-Test-000000000' \
  DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/python manage.py migrate --noinput

# 3) 检查旧口令是否仍有效
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r2-upgrade.sqlite3 \
  ARK_JWT_SECRET='R2-Str0ng-JWT-Secret-For-Test-000000000' \
  DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/python -c "
import bcrypt
from apps.sysadmin.models import SysUser
u = SysUser.objects.get(tenant_id=1, username='admin')
print('users=', SysUser.objects.count())
print('old_admin=', bcrypt.checkpw(b'Admin@123456', u.password_hash.encode()))
"
```

关键输出：

```text
users= 6
old_admin= True
```

**影响**：任何从 E-8 之前版本升级、且按 README 默认方式 `docker compose up -d --build` 的部署，都会保留公开的 R-ADMIN 口令；攻击者可直接登录后台。该缺陷不是“未来可能”，而是默认升级路径的确定行为。

**修复要求（阻断）**：

1. 在升级路径上主动检测六个演示账号的已知默认 `password_hash`；若存在且没有提供新口令，则**拒绝启动并给出明确操作指令**（例如要求一次性执行 `ARK_SEED_DEMO=1 ARK_SEED_PASSWORD=... manage.py seed_demo`），或自动轮换到显式提供的新口令。
2. 不能把“操作者记得手动复种”作为唯一防线；默认 `docker compose up` 必须要么安全，要么可诊断地失败。
3. 增加回归测试：旧默认口令库 + 默认升级路径 → 旧口令必须失效，或启动必须失败并提示；不能只测“显式 `ARK_SEED_DEMO=1` + 新口令”这一条。

---

## 4. Important

### I-1 自检校验 env，而非 effective `settings.JWT_SECRET`，可被自定义 settings 绕过

**结论**：按运行期 `DEBUG` 触发已修好；但真正的密钥来源没对齐，仍可用自定义 settings 在 import 后覆盖弱值，同时让自检通过。

**证据**：

- `backend-django/core/startup.py:49`：`raw = os.environ.get("ARK_JWT_SECRET")`；`:54-61` 只校验这个 env 值。
- `backend-django/config/settings/base.py:107`：`JWT_SECRET = os.environ.get("ARK_JWT_SECRET", ...)`。
- `backend-django/core/auth/jwt_util.py:34,42`：签发和校验都用 `settings.JWT_SECRET`。
- `backend-django/config/settings/prod.py:21-23` 在 import 期调用自检；自定义 settings 可以随后覆盖。

**复现**：

```bash
cd backend-django
cat >/tmp/e8r2/custom_override.py <<'PY'
from config.settings.prod import *
JWT_SECRET = "short"
SECRET_KEY = "short"
DEBUG = False
PY

env ARK_JWT_SECRET='Kkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkk' \
  PYTHONPATH=/tmp/e8r2 DJANGO_SETTINGS_MODULE=custom_override \
  .venv/bin/python -c "
import django; django.setup()
from django.conf import settings
from core.startup import validate_runtime_secrets
validate_runtime_secrets()
print('DEBUG=', settings.DEBUG)
print('JWT_SECRET=', repr(settings.JWT_SECRET))
print('LEN=', len(settings.JWT_SECRET))
"
```

关键输出：

```text
DEBUG= False
JWT_SECRET= 'short'
LEN= 5
EXIT=0
```

**影响**：生产形态（`DEBUG=False`）下，只要部署方的自定义 settings 覆盖 `JWT_SECRET`（例如多租户/多站点配置里从另一个变量回退到 `"short"`），自检仍然通过，进程用 5 字符密钥签发 JWT，令牌可被伪造。这不是默认 prod 路径，但正是 r1 I-1 想覆盖的“自定义 settings 继承 prod”场景的第二半。

**修复要求（阻断）**：

1. 自检应校验 effective `settings.JWT_SECRET`（以及 `settings.SECRET_KEY`，如仍用于会话签名），或同时校验 env 与 effective 值并拒绝不一致。
2. `wsgi.py`/`asgi.py`/`manage.py` 在 settings 加载完成后调用自检，才能看到自定义覆盖；仅在 `prod.py` import 期检查 env 不够。
3. 增加回归测试：自定义 settings 继承 prod 后覆盖 `JWT_SECRET="short"`，必须 `ImproperlyConfigured`。

### I-2 README / 冒烟脚本 / 前端仍使用旧口令，默认干净库没有它们宣称的账号

**结论**：实现已改为“默认不播种、演示口令由环境决定”，但文档和客户端仍停留在旧世界；按 README 快速开始会登录失败。

**证据**：

- `README.md:66`：“演示账号（启动时 `seed_demo` 幂等播种）：`admin / Admin@123456`。”默认 `ARK_SEED_DEMO=0` 时没有账号，这句是假的。
- `README.md:91`：仍让生产/CI 用 `admin/Admin@123456`，并称 `scripts/compose-smoke.sh` 已改用种子账号；实际脚本仍硬编码旧口令。
- `scripts/compose-smoke.sh:14`：`-d '{"username":"admin","password":"Admin@123456"}'`。
- `scripts/compose-smoke-auth.sh:19`：`login admin 'Admin@123456'`；`:45`：`login staff 'Staff@123456'`。
- `frontend/src/App.vue:275`：登录页仍展示 `admin/Admin@123456 · staff/Staff@123456 · finance/Finance@123456`。
- `README.md:46-52` 的显式演示起法要求 `ARK_SEED_PASSWORD` 自定义；因此上述固定口令在按新文档启动后必然失败。

**影响**：默认路径没有账号，显式演示路径的密码由用户自定，但 README 和 smoke 仍让操作者用 `Admin@123456`；首次启动/CI 冒烟会直接失败，前端提示也会误导用户。不是新的凭据泄露，但属于部署可用性与文档一致性的实质缺陷。

**修复要求**：

1. README `:66` 改为“显式 `ARK_SEED_DEMO=1` + `ARK_SEED_PASSWORD` 才有演示账号，账号口令由该变量决定”；`:91` 改为“用 `ARK_SEED_PASSWORD` 对应的口令”。
2. smoke 脚本从 `ARK_SEED_PASSWORD`/`SMOKE_PASSWORD` 读取，不得硬编码 `Admin@123456`、`Staff@123456`。
3. `frontend/src/App.vue:275` 的固定口令提示必须处理；但本计划要求 `frontend/` 零改动，需明确例外或单开前端修复任务，不能继续把公开口令写在登录页。

### I-3 生产 systemd 文档漏 `DJANGO_SETTINGS_MODULE`，wsgi 默认回落到 dev

**结论**：新自检只在 `DEBUG=False` 时生效；按 README 生产段和 spec §9.2 部署 systemd 时，未显式设置 settings module，`wsgi.py` 会回落到 `config.settings.dev`，`DEBUG=True`，自检被跳过。

**证据**：

- `backend-django/config/wsgi.py:6`：`os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")`。
- `backend-django/manage.py:18`：同样默认 dev。
- `README.md:184`：生产段只说设置强 JWT、不要设 `ARK_SEED_DEMO`、systemd 多实例；没有 `DJANGO_SETTINGS_MODULE=config.settings.prod`。
- `docs/superpowers/specs/2026-10-17-backend-django-rewrite-spec.md:223-230`：systemd 单元清单同样没有 settings 环境变量。
- `docs/superpowers/specs/2026-10-17-backend-django-rewrite-spec.md:207` 甚至把默认写成 `config.settings.dev`。

**影响**：部署者即使设置了强 `ARK_JWT_SECRET`，只要漏了 settings module，进程仍以 DEBUG=True 运行，自省文档默认打开、调试页暴露，且新增的弱密钥自检完全不执行。不是“启动失败”，但属于部署形态错误和暴露面残留。

**修复要求**：

1. README 生产段和 spec §9.2 的 systemd 示例显式加入 `Environment=DJANGO_SETTINGS_MODULE=config.settings.prod`（或等价 `EnvironmentFile`）。
2. 在部署检查清单里加一条“确认 `settings.DEBUG is False`”；仅靠“设置强 JWT”不足以证明选中 prod。
3. 可选：生产启动脚本对 `DEBUG=True` 给出显式警告，避免 systemd 漏配时静默进入 dev。

### I-4 `manage.py test` 被自检误伤

**结论**：`config.settings.test` 继承 base 的 `DEBUG=False`，`manage.py` 在 `execute_from_command_line` 之前就把测试 settings 当生产，没设 `ARK_JWT_SECRET` 时直接失败。

**证据**：

- `backend-django/manage.py:7-14`：`_validate_if_prod()` 在命令解析前调用；`if not settings.DEBUG` 即校验。
- `backend-django/config/settings/test.py:16`：`ALLOW_DEMO_SEED = True`，但 `DEBUG` 继承 `False`（base `:8`）。
- 复现：`env -u ARK_JWT_SECRET DJANGO_SETTINGS_MODULE=config.settings.test .venv/bin/python manage.py test --keepdb` → `ImproperlyConfigured`，`EXIT=1`（`manage.py:14`）。
- 对比：pytest 全量 511 绿；dev `manage.py check`、dev `migrate`/`seed_demo` 正常。

**影响**：项目文档主用 pytest，因此 CI 不受影响；但 Django 标准 `manage.py test` 不可用，且未来若有人用 `manage.py test` 做本地验证会得到“生产密钥缺失”的误导错误。这是 r2 引入的回归。

**修复要求**：

1. 给 test settings 增加显式 `TESTING=True`，自检在 `settings.TESTING` 时跳过；或在 `manage.py` 对 `test` 子命令跳过（不要用 `ALLOW_DEMO_SEED` 作为判据，因为生产也可能误设）。
2. 增加一个 `manage.py test` 的回归用例，确保测试 settings 不需要生产密钥。

---

## 5. Minor

### M-1 32 字符低熵值可通过

`core/startup.py:58-61` 只检查 `len(raw) >= 32`；`"a"*32` 可通过，测试自己也用 `"Z"*32`（`tests/test_deploy_hardening.py:25`）。这不是新增泄露（部署方本来可以选坏密钥），但“强密钥”措辞过强。建议拒绝全同/明显重复串，或在文档里明确 32 字符只是下限、不是熵评估。

### M-2 seed 无事务，失败会留下半套数据

`seed_demo.py:180` 的 `handle` 没有 `transaction.atomic()`；实测把 `_seed_domains` 打成异常后，库中留下 `roles: 9 users: 4 grants: 88`。这不造成凭据泄露，但会让失败重试处于不一致状态；建议用事务包住整个 seed，或至少按 domain 分段并回滚。

### M-3 README 文档路径写错

`README.md:175` 写 `/docs`、`/openapi.json`；实际 NinjaAPI 挂在 `api/v1/`（`config/urls.py:24`），正确路径是 `/api/v1/docs`、`/api/v1/openapi.json`。README `:144` 自己写对了，前后不一致；测试只测 `docs_enabled()`，没有断言真实 URL。

### M-4 注释/ledger/spec 仍描述旧行为

- `docker-compose.yml:5` 仍说“启动时幂等播种演示数据”（默认已不播种）。
- `backend-django/Dockerfile:1` 仍自称“开发镜像”，但 `:6` 已 `ENV ... prod`。
- `backend-django/config/settings/base.py:136-137` 说“容器启动脚本据此决定是否跑 seed_demo”，实际 CMD 用的是 `ARK_SEED_DEMO`。
- `.superpowers/sdd/2026-11-19-deploy-hardening/progress.md:37-38` 仍写 compose 默认 `Demo@123456`（r2 已改空）。
- `docs/superpowers/specs/2026-10-17-backend-django-rewrite-spec.md:206-207` 仍写 `ARK_SEED_DEMO` 默认 1、`DJANGO_SETTINGS_MODULE` 默认 dev。

这些不改变运行结果，但会误导下一轮部署/评审。

### M-5 测试覆盖缺口

`tests/test_deploy_hardening.py` 覆盖了空串、模块名、显式轮换、docs 开关，但没有覆盖：默认升级路径（C-2）、effective `settings.JWT_SECRET` 覆盖（I-1）、compose 文件默认值文本、真实 `/api/v1/docs` 路由。建议至少补 C-2 和 I-1 的回归用例，否则同类问题可再次“测试全绿但线上仍开门”。

### M-6 提交粒度与计划不完全一致

计划 5 个任务，实际 3 个 commit（`6bf5044`、`d255652`、`43b5688`），commit message 也不是计划里的 `hardening(deploy)`。这不影响正确性，但降低了按任务回滚/追溯的精度；不阻断。

### M-7 compose 仍把 postgres/minio 默认凭据和端口暴露到宿主机（范围外残留）

`docker-compose.yml:125` `POSTGRES_PASSWORD: ark`、`:160-161` `minioadmin`、`:128`/`:145`/`:163-164` 发布 5432/6379/9000/9001；`:36`/`:115` 发布 8787/8080。E-8 本期只承诺 JWT/seed/docs 三类，这些是既有残留；若 compose 用于公网主机，应关闭端口发布或改强口令。建议单开部署收口任务，不与本期混在一起。

---

## 6. 复现命令与关键输出

### 6.1 C-1：默认不播种、空口令拒绝

```bash
cd backend-django
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r2-clean.sqlite3 \
  ARK_JWT_SECRET='R2-Str0ng-JWT-Secret-For-Test-000000000' \
  DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/python manage.py migrate --noinput

ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r2-clean.sqlite3 \
  ARK_JWT_SECRET='R2-Str0ng-JWT-Secret-For-Test-000000000' \
  DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/python -c "
from apps.sysadmin.models import SysUser
print('users=', SysUser.objects.count())
"
# users= 0

ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8r2-clean.sqlite3 \
  ARK_JWT_SECRET='R2-Str0ng-JWT-Secret-For-Test-000000000' \
  DJANGO_SETTINGS_MODULE=config.settings.prod \
  ARK_SEED_DEMO=1 ARK_SEED_PASSWORD='' \
  .venv/bin/python manage.py seed_demo
# CommandError: 非开发形态播种演示数据必须设置 ARK_SEED_PASSWORD...
# EXIT=1
```

compose 默认解析：

```bash
cd /Users/jacky/works/science-research-project
ARK_JWT_SECRET='R2-Str0ng-JWT-Secret-For-Test-000000000' docker compose config | \
  grep -E 'ARK_SEED_DEMO|ARK_SEED_PASSWORD|DJANGO_SETTINGS_MODULE'
# ARK_SEED_DEMO: "0"
# ARK_SEED_PASSWORD: ""
# DJANGO_SETTINGS_MODULE: config.settings.prod
```

Dockerfile CMD 用 `/tmp/e8fake/bin` 的 `python`/`gunicorn` stub 复现：

```text
# 不设 ARK_SEED_DEMO：
FAKE python manage.py migrate --noinput
FAKE gunicorn config.wsgi:application ...
EXIT=0

# ARK_SEED_DEMO=1 且 seed 失败：
FAKE python manage.py migrate --noinput
FAKE python manage.py seed_demo
EXIT=1        # gunicorn 未执行
```

### 6.2 C-2：显式复种能轮换，但默认升级不轮换

显式复种（六账号）：

```text
old: admin/Admin@123456 manager/Manager@123456 staff/Staff@123456
     finance/Finance@123456 partner/Partner@123456 expert_ext/Expert@123456
new: R2-Rotated-Passw0rd-2026!
结果：六个新口令 True；六个旧默认口令 False
```

默认升级（同一旧库，只 migrate，不 seed）：

```text
users= 6
old_admin= True
```

即：r2 的 `_rotate_password()` 代码正确，但默认 `docker compose up` 根本不会调用它。

### 6.3 I-1：effective `JWT_SECRET` 覆盖绕过

```text
DEBUG= False
JWT_SECRET= 'short'
LEN= 5
EXIT=0
```

同时 `validate_runtime_secrets()` 没有抛异常；`core/auth/jwt_util.py:34,42` 后续会用这个 5 字符值签发/校验令牌。

### 6.4 I-4：`manage.py test` 误伤

```bash
cd backend-django
env -u ARK_JWT_SECRET DJANGO_SETTINGS_MODULE=config.settings.test \
  .venv/bin/python manage.py test --keepdb
# django.core.exceptions.ImproperlyConfigured:
#   生产环境必须显式设置 ARK_JWT_SECRET...
#   at manage.py:14
# EXIT=1
```

### 6.5 全量回归与卫生

```text
$ .venv/bin/python -m pytest -q
511 passed, 5 warnings in 28.75s

$ .venv/bin/python -m pytest -q -k "seed or deploy"
14 passed, 497 deselected, 1 warning

$ DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py \
    makemigrations --check --dry-run
No changes detected
EXIT=0

$ git diff --stat a83c409..43b5688 -- design frontend
（空）
```

---

## 7. 合并门槛

**必须全部满足才可 APPROVED：**

1. **关闭 C-2 默认升级路径**：旧默认口令库执行默认 `docker compose up` 时，要么自动轮换到显式提供的新口令，要么在启动时明确失败并给出一次性复种指令；不能静默保留 `admin/Admin@123456`。
2. **关闭 I-1 effective 密钥旁路**：自检必须校验 `settings.JWT_SECRET`（及必要的 `SECRET_KEY`），不能只看 env；自定义 settings 覆盖弱值必须被拒绝。
3. **修正 I-2 文档/脚本**：README `:66`、`:91`、`README` 环境变量表、smoke 脚本与实现一致；`frontend/src/App.vue:275` 的固定口令提示给出明确处置（例外改动或独立前端任务），不能继续公开旧口令。
4. **修正 I-3 生产部署文档**：systemd/README/spec 明确 `DJANGO_SETTINGS_MODULE=config.settings.prod`，并加入“确认 DEBUG=False”的部署检查项。
5. **修正 I-4 误伤**：`config.settings.test` 下 `manage.py test` 不再要求生产密钥；加回归用例。
6. **补回归测试**：C-2 默认升级、I-1 自定义覆盖、compose 默认值文本、真实 docs URL；测试必须能复现修复前的失败。
7. **复跑**：`pytest -q` ≥ 511 全绿；`makemigrations --check` = No changes；`design/`+`frontend/` 仍零改动（除非对 frontend 提示单独授权）；`docker compose config` 默认不产生任何演示凭据。

**建议但不阻断**：M-1 低熵拒绝、M-2 seed 事务、M-3 路径修正、M-4 注释/ledger/spec 更新、M-6 提交粒度、M-7 生产 compose 关闭 postgres/minio 端口发布。

---

## 8. 通过项、边界与未覆盖

**已独立确认通过：**

- C-1：默认 compose 不再注入 `ARK_SEED_DEMO=1`/`Demo@123456`；干净库默认 0 用户；空 `ARK_SEED_PASSWORD` 在非 dev 形态被拒绝。
- C-2 显式路径：`_rotate_password()` 覆盖 admin/manager/staff/finance/partner/expert_ext 六个账号，旧默认口令失效；重复 seed 幂等。
- I-1 触发：自定义 settings `from config.settings.prod import *` 且无密钥时，`django.setup()` / `import config.wsgi` 均失败；自检不再依赖 `DJANGO_SETTINGS_MODULE` 字符串。
- 1c：`docs_enabled()` 默认 False，真实 `/api/v1/docs`、`/api/v1/openapi.json` 404；显式 `ARK_API_DOCS=1` 可开。
- 编排：`${ARK_JWT_SECRET:?...}` 缺值失败；`ARK_SEED_DEMO=1` 且 seed 失败时 gunicorn 不启动。
- 回归：511 passed；`makemigrations --check` No changes；`design/`、`frontend/` 零改动；无无关源码夹带。

**未执行/边界：**

- 未执行完整 `docker compose up --build`（需要构建镜像与启动 PG/Redis/MinIO，超出只读审查时间盒）；C-1/C-2 用 compose 配置解析、prod+sqlite 的 migrate/seed、以及 Dockerfile CMD 的 `sh` stub 复现。该边界不影响 C-2 的结论：默认 CMD 在 `ARK_SEED_DEMO=0` 时不会调用 seed。
- 未对真实公网环境做渗透测试；`ALLOWED_HOSTS=["*"]`、postgres/minio 端口发布属于既有范围外残留（M-7）。

---

**最终 verdict：REQUEST_CHANGES**。C-2 默认升级路径是阻断项；I-1 的 effective 密钥旁路、I-2/I-3 文档与生产配置、I-4 测试误伤应在合并前处理。
