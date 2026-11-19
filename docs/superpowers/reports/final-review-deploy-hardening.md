# 独立终审（E-8）：部署收口

- 仓库：`/Users/jacky/works/science-research-project`（分支 `develop`，HEAD `d255652`）
- 范围：`a83c409..d255652`，2 个 commit（`6bf5044`、`d255652`），`10 files changed, 223 insertions(+), 14 deletions(-)`
- 计划：`docs/superpowers/plans/2026-11-19-deploy-hardening.md`（5 个任务）
- 账本：`.superpowers/sdd/2026-11-19-deploy-hardening/progress.md`
- diff 包：`/tmp/review-deploy-hardening.diff`（27287 bytes）
- 审查方式：只读审查；全量 diff 逐行 + HEAD 源码核对 + 独立行为探针（临时目录 `/tmp/e8rev`、`/tmp/e8fake`、`/tmp/e8*.sqlite3`，未改工作区源码）；本报告是本次唯一写入仓库的文件，未 commit / 未 stash / 未切换分支

---

## 0. 结论

**REQUEST_CHANGES —— 不能合并。**

三条核心场景在「受支持的默认路径」上确实被堵住了，我逐条复现通过：

- 无 `ARK_JWT_SECRET` 以 prod 形态启动 → `ImproperlyConfigured`，exit 1，不是告警；
- prod + `ARK_SEED_DEMO=1` 但无 `ARK_SEED_PASSWORD` → `CommandError`，exit 1；
- prod + 不设 `ARK_API_DOCS` → `/api/v1/docs`、`/api/v1/openapi.json` 实际 404；显式 `ARK_API_DOCS=1` 才 200。

但本期没有真正收口，存在 **2 条 Critical（凭据暴露）** 与 **4 条 Important（门禁绕过/文档不一致）**：

1. **C-1**：`docker-compose.yml` 默认 `ARK_SEED_DEMO=1` + `ARK_SEED_PASSWORD=Demo@123456`。按 README 的快速开始照抄，`docker compose up` 仍会创建 `admin`（R-ADMIN）且口令是仓库公开的 `Demo@123456`，端口 `8787/8080` 绑定所有网卡。这正是 E-8 要消灭的事故类；计划 Review Focus #5 明确写「compose 里不得再出现任何可用的默认密钥/口令字面量」。
2. **C-2**：`seed_demo` 对已存在的演示用户只 `get_or_create(defaults=...)`，**不会更新口令**。我用新 `ARK_SEED_PASSWORD` 重播后，旧的 `admin/Admin@123456` 仍然可登录；从 E-8 之前的镜像升级、保留 `pgdata` 卷的部署，公开口令继续有效。
3. **I-1**：prod 自检只在 `DJANGO_SETTINGS_MODULE` 字符串以 `config.settings.prod` 开头时执行。自定义 settings（如 `config.settings.staging`、`myproj.settings`）`from config.settings.prod import *` 时自检静默跳过；我实测 `DEBUG=False`、`SECRET_KEY` 仍为仓库缺省值、进程 exit 0。自检读的是 `os.environ["ARK_JWT_SECRET"]`，不是最终生效的 `settings.SECRET_KEY`，属于 fail-open 的残留风险。
4. **I-2**：README `:59` 与 `:84`、`frontend/src/App.vue:275`、`scripts/compose-smoke.sh:14`、`scripts/compose-smoke-auth.sh:19` 仍写 `admin/Admin@123456`，而 compose 实际播种 `Demo@123456`。按 README 起跑后登录 401，冒烟脚本必失败；且前端提示同时列出 `staff/Staff@123456`、`finance/Finance@123456`，而新 seed 是「一枚口令覆盖全部演示账号」，结构上不可能再匹配。
5. **I-3**：README 生产段与 spec §9.2 都没有要求 systemd 设置 `DJANGO_SETTINGS_MODULE=config.settings.prod`；`wsgi.py:6` / `manage.py:8` 缺省回落 `config.settings.dev`。我实测不设该变量 import `config.wsgi` → `DEBUG=True`、仓库缺省 `SECRET_KEY`、exit 0。
6. **I-4**：README `:177` 说生产「不要设 `ARK_SEED_DEMO`」，但 compose `:27` 默认就是 `1`；对 compose 而言「不设」等于「开」，该指令无效，张力没有被说清。

---

## 1. 必查项逐条结论

| # | 必查项 | 结论 | 关键证据（file:line） |
|---|---|---|---|
| 1a | 无 `ARK_JWT_SECRET` 以 prod 启动必须失败 | **通过** | `backend-django/config/settings/prod.py:38-56`；`:61-62` 自检；实测 `manage.py check` exit 1，`ImproperlyConfigured` |
| 1b | `ARK_SEED_DEMO=1` 无 `ARK_SEED_PASSWORD` 且非 dev 必须拒绝 | **通过（仅 prod 路径）** | `apps/sysadmin/management/commands/seed_demo.py:139-158`；实测 prod 下 `CommandError` exit 1；test/dev 因 `ALLOW_DEMO_SEED=True` 是刻意放行（`config/settings/test.py:16`、`dev.py:6`） |
| 1c | 未设 `ARK_API_DOCS` 且 `DEBUG=False` 时文档不存在 | **通过（但 URL 口径要按 `/api/v1/...`）** | `core/ninja.py:16-25`、`:30-31`；`config/urls.py:24` 挂载 `/api/v1/`；实测 `/api/v1/docs`、`/api/v1/openapi.json` 均 404；`/docs`、`/openapi.json` 本来就不是真实路由 |
| 2 | `validate_prod_secrets()` 判据可绕过面 | **不通过（残留风险）** | `prod.py:61-62` 按 env 前缀判定；自定义 settings 实测 exit 0 + 缺省密钥；`prod.py:44` 读 env 而非 `settings.SECRET_KEY`；`"a"*32` 仅长度校验可通过（`:34`、`:53-56`） |
| 3(i) | 依赖播种的既有测试仍绿 | **通过** | 全量 `pytest -q` → `506 passed`；`tests/test_contract.py:43`、`tests/test_procure_m2c.py:210`、`tests/test_sysadmin.py:342-343`、`tests/test_sysadmin_partner.py:275` 均包含在 506 内 |
| 3(ii) | dev 本地 `manage.py seed_demo` 照旧可用 | **通过** | `config/settings/dev.py:6` `ALLOW_DEMO_SEED=True`；sqlite 实测 migrate/seed 均 exit 0，`admin/Admin@123456` 可登录 |
| 3(iii) | 是否存在「只跑一半」的写入路径 | **存在（Minor）** | `seed_demo.py` 的 `handle` 无 `transaction.atomic`；monkeypatch 让 `_seed_domains` 抛错后，库中残留 `roles 9 / users 4 / grants 88` |
| 4 | compose 语法、默认值组合、Dockerfile CMD 语义 | **部分通过** | `docker-compose.yml:25` `${ARK_JWT_SECRET:?…}` 实测缺省即失败、有值可解析；`:27-28` 默认播种+公开口令是阻断项；`Dockerfile:22` 的 `fi && gunicorn` 是合法 POSIX，seed 失败会阻止 gunicorn（实测 exit 1），**这一处是正确的** |
| 5 | README 与实现一致 | **不通过** | README `:59`、`:84` 仍是 `Admin@123456`；`:167` 说 `ARK_SEED_PASSWORD` 默认空，但 compose `:28` 默认 `Demo@123456`；`:177` 的「不要设 `ARK_SEED_DEMO`」对 compose 无效 |
| 6 | 回归与卫生 | **通过** | `design/` + `frontend/` diff 为 0；`makemigrations --check --dry-run` → `No changes detected` exit 0；`git diff --stat a83c409..d255652` 仅 10 个相关文件，无夹带；README 计数 506 与实测一致 |

---

## 2. 实测数字（HEAD `d255652`）

| 项 | 命令 | 实测 |
|---|---|---|
| 全量测试 | `cd backend-django && .venv/bin/python -m pytest -q` | **506 passed, 5 warnings in 20.48s** |
| 定向测试 | `.venv/bin/python -m pytest -q -k "seed or deploy"` | **9 passed, 497 deselected, 1 warning in 8.35s** |
| 迁移一致性 | `DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py makemigrations --check --dry-run` | 仅 PG 5432 `RuntimeWarning`，末行 **`No changes detected`**，exit 0 |
| diff 规模 | `git diff --stat a83c409..d255652` | **10 files changed, 223 insertions(+), 14 deletions(-)** |
| 前后端零改动 | `git diff --stat a83c409..d255652 -- design frontend` | **空** |
| README 计数 | `README.md:80` 等 | **506**，与实测一致 |
| compose 缺密钥 | `env -u ARK_JWT_SECRET docker compose config` | **exit 1**，`required variable ARK_JWT_SECRET is missing a value: 必须设置 ARK_JWT_SECRET：openssl rand -base64 32` |
| compose 有密钥 | `ARK_JWT_SECRET=... docker compose config` | **exit 0**；解析出 `ARK_SEED_DEMO=1`、`ARK_SEED_PASSWORD=Demo@123456`、`ARK_API_DOCS=0`、`DJANGO_SETTINGS_MODULE=config.settings.prod` |
| prod 缺密钥 | `env -u ARK_JWT_SECRET DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py check` | **exit 1**，`ImproperlyConfigured: 生产环境必须显式设置 ARK_JWT_SECRET（当前未设置，用的是仓库缺省密钥）。生成方式：openssl rand -base64 32` |
| prod 强密钥 | 同上 + `ARK_JWT_SECRET='S3cure-...-x9Q'` | **exit 0**，`System check identified no issues` |
| 文档默认关 | prod + `ARK_API_DOCS` 未设，Django Client | `/api/v1/docs` = **404**，`/api/v1/openapi.json` = **404**，`/docs` = **404**，`/openapi.json` = **404** |
| 文档显式开 | prod + `ARK_API_DOCS=1` | `/api/v1/docs` = **200**，`/api/v1/openapi.json` = **200**，`/api/v1/docs/` = **404**（无尾斜杠路由） |
| compose seed 实际口令 | prod + sqlite + `ARK_SEED_DEMO=1 ARK_SEED_PASSWORD=Demo@123456` | `Demo@123456` **True**；`Admin@123456` **False**；seed 输出 `users +4` 等与既有数据一致 |
| 升级/重播口令 | 已有 dev sqlite，重播 `ARK_SEED_PASSWORD='New-Demo-Pass-2026!'` | `Admin@123456` **True**；`New-Demo-Pass-2026!` **False**（既有用户不更新） |
| 部分写入 | 让 `_seed_domains` 抛错 | seed 中止，残留 `roles: 9 users: 4 grants: 88` |

> 说明：未做完整 `docker compose up` 的镜像构建/容器启动（耗时且需拉镜像）；已用 `docker compose config` 验证插值，用 `sh -c` + 假 `python`/`gunicorn` 验证 CMD 分支，用 prod settings + sqlite 验证 seed 实际落库口令。这三个层面足以判定本报告的 C-1/C-2，但「容器全链路」不在实测范围内，特此标明。

---

## 3. Critical

### C-1（阻断）compose 默认重新引入公开演示口令，且默认播种

**证据**

- `docker-compose.yml:27`：`ARK_SEED_DEMO: ${ARK_SEED_DEMO:-1}` —— 不设也开。
- `docker-compose.yml:28`：`ARK_SEED_PASSWORD: ${ARK_SEED_PASSWORD:-Demo@123456}` —— 不设就用公开口令。
- `docker-compose.yml:36` / `:115`：`8787:8787`、`8080:80`，绑定所有网卡，不是仅 localhost。
- `docker-compose.yml:26` 注释写「口令必须由 `ARK_SEED_PASSWORD` 提供」，但 `:28` 自己提供了默认值，注释与实现自相矛盾。
- `README.md:42-47`：快速开始只要求 `export ARK_JWT_SECRET`，然后直接 `docker compose up -d --build`；没有要求设置 `ARK_SEED_PASSWORD`。
- `seed_demo.py:152-158` 返回 `ARK_SEED_PASSWORD`；`:177` `effective_pwd = override_pwd or pwd`；`:178-183` 用它建所有演示用户；`:44` `admin` 是 `R-ADMIN`。
- 计划 `docs/superpowers/plans/2026-11-19-deploy-hardening.md:23-27` Review Focus #5：「compose 里不得再出现任何可用的默认密钥/口令字面量」；同计划 `:8-9` 的验收也要求「默认演示口令时直接失败」。
- 账本 `.superpowers/sdd/2026-11-19-deploy-hardening/progress.md:37` 已自认「compose 演示默认 `ARK_SEED_PASSWORD=Demo@123456` → 演示环境仍是公开口令」。

**我亲手复现**

```bash
cd backend-django
DJANGO_SETTINGS_MODULE=config.settings.prod \
ARK_JWT_SECRET='S3cure-Random-Prod-Secret-Value-2026-x9Q' \
ARK_SEED_DEMO=1 ARK_SEED_PASSWORD='Demo@123456' \
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8compose.sqlite3 \
.venv/bin/python manage.py migrate --noinput
DJANGO_SETTINGS_MODULE=config.settings.prod ... .venv/bin/python manage.py seed_demo
```

结果：

```text
seed_demo 完成（幂等）：... users +4 ...
Demo@123456 True
Admin@123456 False
```

也就是说，**README 的默认起法 + compose 的默认值 = admin/Demo@123456 的 R-ADMIN 账号**。这比旧的 `admin/Admin@123456` 只是换了一个公开字面量，事故类没有改变；任何能访问 `http://<host>:8787` 或 `:8080` 的人都能以管理员登录。

**为什么判 Critical**：这是默认路径上的公开管理员凭据，属于「能造成凭据泄露」；同时直接违反计划自己写的 Review Focus #5。计划 Task 3 `:65` 又明确要求 `ARK_SEED_PASSWORD: ${ARK_SEED_PASSWORD:-Demo@123456}`，说明**计划内部自相矛盾**；执行者按 Task 3 做了，但终审必须以目标与验收为准，不能放行。

**修复建议（二选一，推荐第一种）**

1. 把口令改成必填：`ARK_SEED_PASSWORD: ${ARK_SEED_PASSWORD:?必须设置演示口令}`，`ARK_SEED_DEMO` 默认改为 `0`；README 快速开始显式 `export ARK_SEED_PASSWORD=...`。这样「演示一键起」需要用户给一个自己知道的口令，不再有仓库公开凭据。
2. 若坚持 compose 默认演示，则至少 `ARK_SEED_DEMO` 默认 `0`，README 把 `ARK_SEED_DEMO=1 ARK_SEED_PASSWORD=...` 写成显式演示命令；但 `Demo@123456` 字面量仍不应留在 compose 里。

### C-2（阻断）既有演示用户的口令不会被覆盖，升级后公开口令仍有效

**证据**

- `seed_demo.py:175-183`：对每个演示用户 `get_or_create(username=..., tenant_id=1, defaults={..., "password_hash": bcrypt.hashpw(effective_pwd...)})`。`defaults` 只在 **create** 时生效；已存在的用户不会被更新。
- `seed_demo.py:177` 的 `effective_pwd` 只进入 `defaults`，没有 `if not created: u.password_hash = ...; u.save()` 之类的更新分支。
- 账本 `progress.md:31-33` 声称「统一覆盖全部演示账号」，但代码只覆盖新建账号；这是声明与实现不一致。
- 旧镜像的 CMD 是无条件 `seed_demo`（E-8 之前），因此既有 `pgdata` 卷里通常已经有 `admin/Admin@123456`。

**我亲手复现**

在已有 dev sqlite（上一次 seed 已建 `admin/Admin@123456`）上重播：

```bash
ARK_DB_ENGINE=sqlite ARK_DB_NAME=/tmp/e8dev.sqlite3 \
DJANGO_SETTINGS_MODULE=config.settings.dev \
ARK_SEED_PASSWORD='New-Demo-Pass-2026!' \
.venv/bin/python manage.py seed_demo
```

校验：

```text
Admin@123456 works = True
New-Demo-Pass-2026! works = False
```

**影响**：从旧版本升级、保留数据库的部署，E-8 只改了「新库第一次播种」的行为；旧的公开管理员口令继续可登录。对「生产带 `admin/Admin@123456`」这个事故场景，升级路径没有关闭。

**为什么判 Critical**：这是既有部署上的公开凭据仍然有效，属于凭据泄露；不是单纯的兼容性问题。

**修复建议**

- 当 `ARK_SEED_PASSWORD` 被显式提供时，对内置演示用户名（`admin`、`staff`、`finance` 等白名单）执行 `update_or_create` 或显式更新 `password_hash`；不要无条件重置真实用户。
- 或者新增 `seed_demo --rotate-passwords`（仅作用于内置演示账号），并在 README 的升级段写明必须执行；同时提供 `docker compose down -v` 的取舍说明。
- 增加回归：先以默认口令建库，再带新 `ARK_SEED_PASSWORD` 重播，断言旧口令 401/`checkpw=False`、新口令可登录。

---

## 4. Important

### I-1（重要）prod 自检按环境变量字符串前缀触发，继承 prod 的自定义 settings 会静默跳过；且校验的不是最终 `SECRET_KEY`

**证据**

- `backend-django/config/settings/prod.py:61-62`：

  ```python
  if os.environ.get("DJANGO_SETTINGS_MODULE", "").startswith("config.settings.prod"):
      validate_prod_secrets()
  ```

  只有模块名以 `config.settings.prod` 开头才自检。`config.settings.production` 会被前缀命中；但 `config.settings.staging`、`config.settings.live`、`myproj.settings`、`from config.settings.prod import *` 的自定义模块都不会。
- `prod.py:44` `raw = os.environ.get("ARK_JWT_SECRET")`，校验的是环境变量，不是 `django.conf.settings.SECRET_KEY`。如果 `SECRET_KEY` 在导入后被别的配置覆盖，校验与实际使用的密钥可能不是同一个值。
- `base.py:7` 的缺省值仍是公开的 `dev-secret-change-me-please-use-32-bytes-min!`。

**我亲手复现**

```bash
mkdir -p /tmp/e8rev
cat > /tmp/e8rev/custom_settings.py <<'PY'
from config.settings.prod import *
PY

cd backend-django
env -u ARK_JWT_SECRET PYTHONPATH=/tmp/e8rev \
DJANGO_SETTINGS_MODULE=custom_settings \
.venv/bin/python -c 'import django; django.setup(); from django.conf import settings; print(settings.DEBUG, settings.SECRET_KEY)'
```

结果：

```text
DEBUG= False
SECRET_KEY= dev-secret-change-me-please-use-32-bytes-min!
EXIT=0
```

同样，`/tmp/e8rev/myproj/settings.py` 里 `from config.settings.prod import *` 并覆盖 `SECRET_KEY`，也是 exit 0、`DEBUG=False`、缺省密钥。

**判定**：**是残留风险，且是 fail-open**。默认 compose/Dockerfile 路径把模块名精确设成 `config.settings.prod`，所以默认部署是安全的；但只要部署者用「继承 prod 的自定义 settings」这条常见路径（多环境 staging/live、按站点拆分），自检就静默不执行，生产会带着公开 `SECRET_KEY` 以 `DEBUG=False` 跑起来，JWT 可被伪造。按「生产门禁必须 fail-closed」的标准，这条不能只留作已知边界。

**修复建议**

- 把校验移到「生效配置」层：在 `AppConfig.ready()` 或 Django system check 中，当 `settings.DEBUG is False` 且不是 test 时，校验 `settings.SECRET_KEY` 不是缺省/弱值；这样任何继承 prod 的 settings 都会触发。
- 或者在 `wsgi.py` / `asgi.py` / `manage.py` 启动入口做一次显式断言：`settings.SECRET_KEY != base default`，且 `settings.DEBUG is False` 时 `ARK_JWT_SECRET` 必须存在。
- 若短期不改代码，至少把 README/部署文档写成「只支持 `DJANGO_SETTINGS_MODULE=config.settings.prod`，自定义 settings 必须自行调用 `validate_prod_secrets()`」，并加一条测试：自定义模块导入 prod 且无密钥时必须失败。

### I-2（重要）README、前端提示、冒烟脚本仍是 `Admin@123456`，与 compose 的 `Demo@123456` 不一致，按文档起跑登录失败

**证据**

- `README.md:59`：「演示账号……`admin / Admin@123456`」。
- `README.md:84`：「生产/CI 请用种子账号（如 `admin/Admin@123456`）登录，`scripts/compose-smoke.sh` 已改用种子账号」。
- `frontend/src/App.vue:275`：登录页提示 `admin/Admin@123456`、`staff/Staff@123456`、`finance/Finance@123456`。
- `scripts/compose-smoke.sh:14`：`-d '{"username":"admin","password":"Admin@123456"}'`。
- `scripts/compose-smoke-auth.sh:19`：`login admin 'Admin@123456'`。
- 实测 compose 默认路径：`Demo@123456 True`、`Admin@123456 False`（见 C-1）。
- 计划 Task 5 `:85-89` 的 Self-Review 明确问「演示一键跑是否仍成立（README 步骤可照抄执行）？」——答案是否定的。

**影响**：按 README 快速开始起容器后，用文档给的口令登录会 401；`scripts/compose-smoke.sh`、`compose-smoke-auth.sh` 也必失败。前端登录页的提示同样误导。更麻烦的是，seed 现在是「一枚口令覆盖全部演示账号」，而前端提示列了三个不同口令（admin/staff/finance），即便把 admin 改成 `Demo@123456`，另外两个仍然是错的。

**约束冲突**：计划 Global Constraints 要求「不动 `frontend/`」。这条要么允许改 `frontend/src/App.vue:275` 一行提示（推荐），要么在 README 明确「登录页提示已过期，请用 `ARK_SEED_PASSWORD` 的值」，但那仍然是一个坏的演示体验。最低限度必须修 README 与两个 smoke 脚本；否则「演示一键起」不成立。

### I-3（重要）生产 systemd 文档没有要求 `DJANGO_SETTINGS_MODULE=config.settings.prod`，按文档起 gunicorn 会落回 dev

**证据**

- `README.md:177` 的生产段只说了「设置强 JWT 密钥」「不要设 `ARK_SEED_DEMO`」「非容器化 systemd」，没有给出 `DJANGO_SETTINGS_MODULE`。
- `docs/superpowers/specs/2026-10-17-backend-django-rewrite-spec.md:207` 的环境变量表默认值仍是 `config.settings.dev`；§9.2 `:224-230` 的 systemd 清单也没有该变量。
- `backend-django/config/wsgi.py:6`、`backend-django/manage.py:8`：`os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")`。

**我亲手复现**

```bash
cd backend-django
env -u DJANGO_SETTINGS_MODULE -u ARK_JWT_SECRET \
.venv/bin/python -c 'import config.wsgi; from django.conf import settings; print(settings.SETTINGS_MODULE, settings.DEBUG, settings.SECRET_KEY)'
```

结果：

```text
config.settings.dev True dev-secret-change-me-please-use-32-bytes-min!
EXIT=0
```

**影响**：按 README/spec 的 systemd 步骤启动，若部署者没有额外设置该变量，gunicorn 会以 `DEBUG=True`、公开 `SECRET_KEY`、文档默认开、`ark/ark` 后门仅差 `ARK_DEV_LOGIN` 的形态运行。README `:89` 有一句「生产务必不复用 dev 配置」，但没有给出可照抄的 `Environment=` 行，实际可操作性不足。

**修复建议**：在 README 生产段与 spec §9.2 明确写出：

```ini
Environment=DJANGO_SETTINGS_MODULE=config.settings.prod
Environment=ARK_JWT_SECRET=...
```

并加一条部署后自检：`manage.py shell -c "from django.conf import settings; assert settings.DEBUG is False"`。

### I-4（重要）「生产不设 `ARK_SEED_DEMO`」对 compose 不成立，文档没有说清张力

**证据**

- `README.md:177`：「**不要**设 `ARK_SEED_DEMO`（否则会灌入演示账号）」。
- `docker-compose.yml:27`：`ARK_SEED_DEMO: ${ARK_SEED_DEMO:-1}`。即使宿主机完全不设，compose 也会注入 `1`。
- 账本 `progress.md:38`：「生产不设 `ARK_SEED_DEMO` 即可」——这句对 systemd 成立，对 compose 不成立。
- README `:46-48` 确实说了 compose 默认开会播种、干净库用 `ARK_SEED_DEMO=0`，但生产段没有把「compose 生产必须显式 0」写出来。

**影响**：一个用 compose 部署「生产/预发」的运维，按生产段「不要设」操作，结果反而播种了演示账号（叠加 C-1 的公开口令）。这不是文档小瑕疵，而是把安全指令写反了。

**修复建议**：生产段改成「compose 部署必须显式 `ARK_SEED_DEMO=0`；systemd 部署不要设置该变量」，或者直接把 compose 默认改成 `0`（与 C-1 一起修）。

---

## 5. Minor

| # | 项 | 证据 | 说明 |
|---|---|---|---|
| M-1 | 密钥只校验长度，不校验熵 | `prod.py:34` `_SECRET_MIN_LEN=32`；`:53-56` 仅 `len(raw)<32` | 实测 `ARK_JWT_SECRET='a'*32` 可通过；测试里甚至用 `"Z"*32` 当作强密钥（`tests/test_deploy_hardening.py:23-24`）。32 个重复字符不是强密钥。建议至少拒绝全同字符/明显重复，或改用 `secrets` 生成的示例并在文档强调。 |
| M-2 | seed 无事务，失败留半套数据 | `seed_demo.py:160-183` 无 `transaction.atomic` | 实测让 `_seed_domains` 抛错后残留 `roles 9 / users 4 / grants 88`。幂等重跑可补齐，但中途失败会留下半个演示库；建议 `with transaction.atomic():` 包住 `handle`，或至少包住用户/角色/授权写入。 |
| M-3 | 新测试只测单元函数，未测真实装配 | `tests/test_deploy_hardening.py:8-24` 直接调 `validate_prod_secrets()`；`:70-87` 只断言 `docs_enabled()`，未断言 `/api/v1/docs` 真实 404/200；无自定义 settings、无 compose/Dockerfile 文本断言 | 这正好漏掉了 I-1 与 I-4。建议补：自定义 settings 导入 prod 无密钥必须失败；prod `Client` 实际 URL 404；`docker-compose.yml` 不含 `Demo@123456` 之类默认口令。 |
| M-4 | README 环境变量表路径/默认值与实现有偏差 | `README.md:167-168` | 表里写文档路径 `/docs`、`/openapi.json`，实际是 `/api/v1/docs`、`/api/v1/openapi.json`；`ARK_SEED_PASSWORD` 默认写「空」，但 compose 默认 `Demo@123456`；`ARK_SEED_DEMO` 写 `0`，compose 是 `1`（表里补了「compose 演示为 1」，但生产段没接上）。 |
| M-5 | spec 未随 E-8 更新 | `docs/superpowers/specs/2026-10-17-backend-django-rewrite-spec.md:206-207` | spec 仍写 `ARK_JWT_SECRET` 默认 `dev-secret`、`ARK_SEED_DEMO` 默认 `1`、`DJANGO_SETTINGS_MODULE` 默认 `config.settings.dev`，与 README 的新口径冲突。spec 是「唯一真源」，至少应加一句「E-8 后以 README/部署段为准」。 |
| M-6 | 提交纪律与计划不一致 | `git log a83c409..d255652` | 计划要求 5 个任务各一 commit、消息前缀 `hardening(deploy):`；实际 2 个 commit（`fix(config)`、`chore(deploy)`），Task 1/2/4 与 3/5 合并。无夹带、无越界文件，属流程偏差，不影响功能。 |
| M-7 | compose 仍有其他默认凭据与全接口端口（范围外） | `docker-compose.yml:125`（postgres `POSTGRES_PASSWORD: ark`）、`:160-161`（minio `minioadmin`）、`:128`/`:145`/`:163-164` 端口 | E-8 声明范围只覆盖 JWT/seed/docs，这些是既有问题；但若按 Review Focus #5 的字面「任何可用的默认密钥/口令字面量」读，compose 仍不合格。建议至少记录为后续部署收口项，不要把本期结论说成「compose 已无默认凭据」。 |
| M-8 | Dockerfile 头注释与镜像默认形态不一致 | `backend-django/Dockerfile:1` 写「开发镜像（生产部署走 systemd 裸机）」，`:6` 却 `ENV DJANGO_SETTINGS_MODULE=config.settings.prod` | 注释漂移，易误导；建议改成「默认生产形态镜像」。 |

---

## 6. 我实际跑过的关键命令与输出（可复核）

### 6.1 场景 a：prod 缺密钥

```bash
cd backend-django
env -u ARK_JWT_SECRET DJANGO_SETTINGS_MODULE=config.settings.prod \
  .venv/bin/python manage.py check
```

```text
django.core.exceptions.ImproperlyConfigured: 生产环境必须显式设置 ARK_JWT_SECRET（当前未设置，用的是仓库缺省密钥）。生成方式：openssl rand -base64 32
EXIT=1
```

补充变体：`ARK_JWT_SECRET=""` / `" "` / 仓库缺省值 → 均 `ImproperlyConfigured`；`"short"` → 长度不足；`"a"*32` 与 44 字符 base64 → 通过（长度口径，见 M-1）。

### 6.2 场景 b：prod 下 seed 门禁

```bash
# 无 ARK_SEED_DEMO
DJANGO_SETTINGS_MODULE=config.settings.prod ARK_JWT_SECRET='...' \
  .venv/bin/python manage.py seed_demo
# -> CommandError: 演示数据默认不播种...  EXIT=1

# 有 ARK_SEED_DEMO=1，无 ARK_SEED_PASSWORD
ARK_SEED_DEMO=1 ... .venv/bin/python manage.py seed_demo
# -> CommandError: 非开发形态播种演示数据必须设置 ARK_SEED_PASSWORD...  EXIT=1

# --force 但无口令
ARK_SEED_DEMO=1 ... .venv/bin/python manage.py seed_demo --force
# -> 同上，EXIT=1

# 有口令：门禁通过，继续到 DB（本机无 PG）
ARK_SEED_DEMO=1 ARK_SEED_PASSWORD='...' ... .venv/bin/python manage.py seed_demo
# -> django.db.utils.OperationalError: connection ... 127.0.0.1:5432 ... Connection refused  EXIT=1
```

### 6.3 场景 c：prod 文档默认关/显式开

```bash
DJANGO_SETTINGS_MODULE=config.settings.prod ARK_JWT_SECRET='...' \
ARK_API_DOCS=1 .venv/bin/python - <<'PY'
import django; django.setup()
from django.test import Client
c = Client()
for p in ("/api/v1/docs", "/api/v1/openapi.json", "/docs", "/openapi.json"):
    print(p, c.get(p).status_code)
PY
```

```text
/api/v1/docs 200
/api/v1/openapi.json 200
/docs 404
/openapi.json 404
```

不设 `ARK_API_DOCS` 时四个路径全部 404。

### 6.4 自定义 settings 绕过（I-1）

```bash
cat > /tmp/e8rev/custom_settings.py <<'PY'
from config.settings.prod import *
PY
cd backend-django
env -u ARK_JWT_SECRET PYTHONPATH=/tmp/e8rev DJANGO_SETTINGS_MODULE=custom_settings \
  .venv/bin/python -c 'import django; django.setup(); from django.conf import settings; print(settings.DEBUG, settings.SECRET_KEY)'
```

```text
False dev-secret-change-me-please-use-32-bytes-min!
EXIT=0
```

### 6.5 wsgi 缺省回落（I-3）

```bash
env -u DJANGO_SETTINGS_MODULE -u ARK_JWT_SECRET \
  .venv/bin/python -c 'import config.wsgi; from django.conf import settings; print(settings.SETTINGS_MODULE, settings.DEBUG, settings.SECRET_KEY)'
```

```text
config.settings.dev True dev-secret-change-me-please-use-32-bytes-min!
EXIT=0
```

### 6.6 compose 插值与默认值

```bash
env -u ARK_JWT_SECRET docker compose config
# exit 1:
# error while interpolating services.backend.environment.ARK_JWT_SECRET:
# required variable ARK_JWT_SECRET is missing a value:
# 必须设置 ARK_JWT_SECRET：openssl rand -base64 32

ARK_JWT_SECRET='S3cure-Random-Prod-Secret-Value-2026-x9Q' docker compose config
# exit 0; 解析出：
# ARK_JWT_SECRET: S3cure-...
# ARK_SEED_DEMO: "1"
# ARK_SEED_PASSWORD: Demo@123456
# ARK_API_DOCS: "0"
# DJANGO_SETTINGS_MODULE: config.settings.prod
```

### 6.7 Dockerfile CMD 分支（`fi && gunicorn` 语义）

用 `/tmp/e8fake/bin` 的假 `python`/`gunicorn` 执行 `Dockerfile:22` 的 CMD：

```text
无 ARK_SEED_DEMO        -> migrate + gunicorn            EXIT=0
ARK_SEED_DEMO=1         -> migrate + seed_demo + gunicorn EXIT=0
ARK_SEED_DEMO=1 + seed 失败 -> migrate + seed_demo，gunicorn 不启动 EXIT=1
```

`sh -n` 语法检查通过。`if ...; then ...; fi && gunicorn` 在 `sh` 下是合法的，且 seed 失败会 fail-closed，**这一点比计划里的 `|| true` 更安全，应保留**。

### 6.8 全量回归与迁移

```bash
cd backend-django
.venv/bin/python -m pytest -q
# 506 passed, 5 warnings in 20.48s

.venv/bin/python -m pytest -q -k "seed or deploy"
# 9 passed, 497 deselected, 1 warning in 8.35s

DJANGO_SETTINGS_MODULE=config.settings.dev \
  .venv/bin/python manage.py makemigrations --check --dry-run
# RuntimeWarning: ... 127.0.0.1:5432 ... Connection refused
# No changes detected
# EXIT=0
```

---

## 7. 合并门槛

**阻断项（必须修完并复测，才可改判 APPROVED）**

1. **C-1**：`docker-compose.yml` 去掉可用的默认演示口令。推荐 `ARK_SEED_DEMO` 默认 `0` + `ARK_SEED_PASSWORD` 用 `${ARK_SEED_PASSWORD:?…}` 必填；同步 README 快速开始，给出显式 `export ARK_SEED_PASSWORD=...`。改完后 `docker compose config` 在未设口令时也必须失败或解析为 `ARK_SEED_DEMO=0`。
2. **C-2**：给既有演示用户提供口令轮换路径（显式 `ARK_SEED_PASSWORD` 时更新内置演示账号，或 `--rotate-passwords`），并在 README 升级段写明；回归必须证明「旧口令失效、新口令可登录」。
3. **I-1**：把 prod 密钥自检从「env 字符串前缀」改成「生效 settings / 启动入口」的 fail-closed 校验；至少覆盖 `from config.settings.prod import *` 的自定义 settings，并加回归测试。
4. **I-2**：README `:59` / `:84`、`scripts/compose-smoke.sh:14`、`scripts/compose-smoke-auth.sh:19` 与前端 `App.vue:275` 的演示口令必须统一到同一契约。若坚持「frontend 零 diff」，需在报告中明确接受登录页提示过期，并至少在 README 给出可用的登录口令；否则应允许改 `App.vue` 这一行。演示路径必须能按 README 照抄登录成功。

**发布前应完成（不单独阻断代码合并，但阻断「E-8 已收口」的结论）**

5. **I-3**：README/spec 的 systemd 段补 `DJANGO_SETTINGS_MODULE=config.settings.prod` 与 `Environment=ARK_JWT_SECRET=...`，并加 `settings.DEBUG is False` 的部署后断言。
6. **I-4**：明确「compose 生产必须 `ARK_SEED_DEMO=0`；systemd 不要设」；或直接把 compose 默认改 0，与 C-1 一起解决。
7. **M-3**：补三类回归：prod settings 被实际加载时缺密钥失败、真实 `/api/v1/docs` 404/200、自定义 settings 继承 prod 失败。
8. 复测：全量 `pytest -q` ≥ 506、`makemigrations --check` 仍 `No changes`、`design/`+`frontend/` diff 仍为 0（若允许改 App.vue，则只允许这一行，需在 PR 说明）、`docker compose config` 的缺省/有值两条路径都符合预期。

---

## 8. 通过项与残留边界

- **已通过**：1a（prod 缺密钥硬失败）、1b（prod seed 无口令拒绝）、1c（prod 文档默认 404/显式 200）、Dockerfile CMD 的 fail-closed 语义、compose 的 `:?` 必填插值、506 全量测试、迁移一致性、前后端零 diff、无夹带。
- **残留但范围外**：compose 的 postgres `ark/ark`、minio `minioadmin` 与 5432/6379/9000/9001 端口暴露（M-7）；`ALLOWED_HOSTS=["*"]`（prod.py:21）未动。这些不是本期引入，但若目标是「compose 无默认凭据」，它们仍是债务，建议另开小期次。
- **未实测**：完整镜像构建 + `docker compose up` 全链路（见第 2 节说明）；本报告用 compose 插值、CMD 分支、prod settings+sqlite 三层替代，足以支撑 C-1/C-2 的判定，但容器网络/健康检查未覆盖。
