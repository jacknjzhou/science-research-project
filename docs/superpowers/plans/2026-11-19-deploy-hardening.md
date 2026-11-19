# 部署收口（E-8）实施计划

> **面向执行者**：本计划清「安全收口」终审遗留的上线硬门槛。逐任务 TDD、每任务一 commit；
> 不改业务语义、不改契约；所有硬化必须**可关闭**（保留本地/演示路径），但**默认必须是安全的**。

**目标**：让「默认启动」的部署形态不携带任何人造凭据、不暴露排障面、不自动灌演示账号。

**验收**：`docker compose` 缺 `ARK_JWT_SECRET` 时**拒绝启动并给出生成命令**；镜像 CMD 不再无条件
跑 `seed_demo`；生产形态（`DEBUG=False`）用弱默认密钥或默认演示口令时**直接失败**；`/docs` 在
生产默认关闭。pytest 基线 500 → 目标 ≥504 全绿。

## Global Constraints

- 不新增依赖；只用 stdlib `os`/`secrets` 与 Django `ImproperlyConfigured`/`CommandError`。
- 环境变量命名沿用 `ARK_*`；新增变量必须在 README 说明（含生成命令）。
- 演示路径仍要能一键跑通：`compose` 显式注入 `ARK_SEED_DEMO=1` + `ARK_SEED_PASSWORD`。
- 生产形态校验放在 `config/settings/prod.py`（`DEBUG=False` 的唯一样板），不污染 `base.py` 的 dev 便利。
- 每处硬化配一条回归：证明「不安全输入 → 失败」，且「安全输入 → 通过」。
- 提交信息 `hardening(deploy): ...`；只 stage 明确文件；不动 `design/`、不动 `frontend/`。

## Review Focus（终审必查五条）

1. `ARK_JWT_SECRET` 缺省/等于旧默认值时，prod 形态必须抛错且信息可操作（不能只在日志 warn）。
2. `seed_demo` 三条路径：未开 `ARK_SEED_DEMO` → 拒绝；开启但未给 `ARK_SEED_PASSWORD` 且 `DEBUG=False` → 拒绝；开启+给口令 → 用该口令播种。
3. Dockerfile CMD 不再无条件 seed；`migrate` 仍无条件执行。
4. `/docs`、`/openapi.json` 在 prod 默认 404；显式 `ARK_API_DOCS=1` 才开。
5. compose 里不得再出现任何可用的默认密钥/口令字面量。

## Task 1 生产形态强制密钥

**Files**：`backend-django/config/settings/prod.py`、`backend-django/tests/test_deploy_hardening.py`（新建）

**Step 1（RED）**：测试
```python
def test_prod_requires_strong_jwt_secret(monkeypatch):
    monkeypatch.delenv("ARK_JWT_SECRET", raising=False)
    with pytest.raises(ImproperlyConfigured):
        prod.validate_prod_secrets()
    monkeypatch.setenv("ARK_JWT_SECRET", "dev-secret-change-me-please-use-32-bytes-min!")
    with pytest.raises(ImproperlyConfigured):
        prod.validate_prod_secrets()
    monkeypatch.setenv("ARK_JWT_SECRET", "x" * 32)
    prod.validate_prod_secrets()          # 通过，不抛
```
**Step 2**：`prod.py` 增 `WEAK_SECRETS = {...}`、`validate_prod_secrets()`（缺省/弱/长度<32 → `ImproperlyConfigured`，消息含 `openssl rand -base64 32`），并在模块底部调用一次。
**Step 3（GREEN）**：`pytest tests/test_deploy_hardening.py -q`。
**Step 4**：commit `hardening(deploy): 生产形态强制 ARK_JWT_SECRET 并拒绝弱默认值`

## Task 2 seed_demo 三重门禁

**Files**：`apps/sysadmin/management/commands/seed_demo.py`、`tests/test_deploy_hardening.py`

- `add_arguments`：`--force`（跳过开关，人工确认用）。
- `handle` 开头：`if not options.get("force") and os.environ.get("ARK_SEED_DEMO") != "1": raise CommandError(...)`（信息含 `ARK_SEED_DEMO=1 python manage.py seed_demo`）。
- 口令来源：`_seed_password()` = `os.environ.get("ARK_SEED_PASSWORD")`；当 `settings.DEBUG is False` 且为空 → `CommandError("生产形态必须设置 ARK_SEED_PASSWORD")`；有值时用它播种全部演示账号。
- 回归 3 例（未开开关拒绝 / prod 无口令拒绝 / 口令生效：admin 能用新口令登录 200 且旧口令 401）。
- RED 先行（当前三例全失败）。
- commit `hardening(deploy): seed_demo 加开关/强口令门禁，演示口令不再隐式入库`

## Task 3 镜像启动不再自动播种

**Files**：`backend-django/Dockerfile`、`docker-compose.yml`、`tests/test_deploy_hardening.py`

- CMD 改为：`python manage.py migrate --noinput && ( [ "$ARK_SEED_DEMO" = "1" ] && python manage.py seed_demo || true ) && gunicorn ...`（放在 `sh -c` 里，注意 `set -e` 语义：用 `if` 更稳）。
- compose backend 增 `ARK_SEED_DEMO: "1"`、`ARK_SEED_PASSWORD: ${ARK_SEED_PASSWORD:-Demo@123456}`（演示口令**仅** compose 注入），`ARK_API_DOCS: ${ARK_API_DOCS:-0}`，`ARK_JWT_SECRET: ${ARK_JWT_SECRET:?必须设置：openssl rand -base64 32}`。
- 回归：读 `Dockerfile` 文本断言 `seed_demo` 不出现在 CMD 的无条件位置（断言 CMD 行含 `ARK_SEED_DEMO`）；读 `docker-compose.yml` 断言不含 `dev-secret-change-me` 字面量、含 `:?`。
- commit `hardening(deploy): 镜像启动按开关播种，compose 去除默认密钥与默认文档面`

## Task 4 生产关闭在线文档

**Files**：`core/ninja.py`、`tests/test_deploy_hardening.py`

- 抽 `docs_enabled() -> bool`（`DEBUG` 为真 → True；否则 `ARK_API_DOCS == "1"`），`_DOCS = docs_enabled()`。
- 回归：`docs_enabled()` 在 `DEBUG=False` 且无 env → False；有 env → True；`DEBUG=True` → True。
- commit `hardening(deploy): 在线文档开关抽函数并默认关闭`

## Task 5 文档与全量验收

**Files**：`README.md`

- 快速起跑段改：先 `export ARK_JWT_SECRET=$(openssl rand -base64 32)`，再 `docker compose up`；说明 `ARK_SEED_DEMO=1` 只给演示、`ARK_SEED_PASSWORD` 覆盖口令、`ARK_API_DOCS=1` 内网排障。
- 跑全量 `pytest -q`（≥504 passed）、`makemigrations --check`、契约 diff 空、README 三处计数同步。
- commit `docs(deploy): 起跑前置密钥与演示开关说明`

## Self-Review 清单

- 每条硬化是否「默认安全、显式可开」？
- 是否存在第二处仍硬编码的凭据/口令（`grep -rn "Admin@123456\|dev-secret-change-me" --include=*.py --include=*.yml --include=*.sh`）？
- 演示一键跑是否仍成立（README 步骤可照抄执行）？
- 新变量是否都在 README 出现？
