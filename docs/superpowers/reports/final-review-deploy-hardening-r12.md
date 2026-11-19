# E-8 终审 r12：`mode` 原样比较与 C 系列累计复审

- 仓库：`/Users/jacky/works/science-research-project`
- 分支：`develop`
- 范围：`a83c409..1b1b55f`（新增 `1b1b55f`）
- diff 包：`/tmp/review-deploy-hardening-r12.diff`
- 计划：`docs/superpowers/plans/2026-11-19-deploy-hardening.md`
- ledger：`.superpowers/sdd/2026-11-19-deploy-hardening/progress.md`
- 复审对象：r11 的 I-R11-1（大小写/空白键绕过）与 I-R11-2（覆盖）
- 结论：**APPROVED**（无 Critical、无 Important；3 条 Minor）
- 合并结论：**可推送 develop**

## 0. 结论

r12 把 `_is_ephemeral_test_db()` 的 URI 参数比较改成了**原样比较**：

```python
key, _, value = pair.partition("=")
if key == "mode":
    modes.append(value)
return len(modes) == 1 and modes[0] == "memory"
```

这正好修掉了 r11 的 `strip().lower()` 过度容错。我亲手复测了四种形态：

- `MODE=memory`
- `Mode=memory`
- `mode =memory`
- `mode= memory`

四种全部 `manage.py migrate` **EXIT=1**，stderr 含 `IS_TEST_SETTINGS`，且没有创建任何落盘文件。之前会生成 1,294,336 字节文件的 `MODE=memory` 路径已不再成立。

同时确认正常 URI 没有被误伤：

- `file:memdbV1?mode=memory&cache=shared` → EXIT=0，无文件
- `file:memdbV2?cache=shared&mode=memory` → EXIT=0，无文件
- `file:memdbV3?cache=shared&mode=memory&uri=true` → EXIT=0，无文件

全量 **555 passed**、`makemigrations` No changes、design/schema 零 diff、README 三处计数均为 555。r1→r12 的 C 系列（compose 默认口令、旧库默认口令闸门、`--settings`、`django-admin`、`python -m django`、runserver autoreload、test-settings alias）逐项复测均仍生效。

**可推送 develop。** 没有阻塞项；下列 Minor 可作为后续清理，不影响本轮合并。

## 1. 逐项结论

| # | 必查项 | 结论 | 证据 |
|---|---|---|---|
| 1 | `MODE=memory` | **通过** | 别名 migrate EXIT=1，`IS_TEST_SETTINGS`，无 `memdbU` |
| 2 | `Mode=memory` | **通过** | EXIT=1，无 `memdbC` |
| 3 | `mode =memory` | **通过** | EXIT=1，无文件 |
| 4 | `mode= memory` | **通过** | EXIT=1，无文件 |
| 5 | `mode=memory` 在前 | **通过** | `mode=memory&cache=shared` EXIT=0，无文件 |
| 6 | `cache=shared` 在前 | **通过** | `cache=shared&mode=memory` EXIT=0，无文件 |
| 7 | 多参数 `cache=shared&mode=memory&uri=true` | **通过** | EXIT=0，无文件 |
| 8 | `xmode=memory` | **通过** | EXIT=1，无文件 |
| 9 | `mode=memory_extra` | **通过（False）** | 14 参数单测 |
| 10 | 重复 `mode=memory&mode=disk` | **通过（False）** | 14 参数单测 |
| 11 | `file:memory:foo`（无 mode） | **通过** | EXIT=1，无 `memory:foo` |
| 12 | sqlite 相对路径 / 绝对路径 / postgres | **通过** | 相对路径、绝对路径、postgres 均 False；`:memory:`/空串 True |
| 13 | 旧库默认口令闸门 | **通过** | 旧库 `manage.py check` EXIT=1；rotate 后 EXIT=0 |
| 14 | `--settings=prod` | **通过** | 旧库 `manage.py check --settings=config.settings.prod` EXIT=1 |
| 15 | `django-admin` / `python -m django` | **通过** | 旧库均 EXIT=1，列出六个默认账号 |
| 16 | runserver autoreload | **通过** | 旧库 `runserver --noreload` EXIT=1 |
| 17 | compose 默认 seed/口令 | **通过** | `ARK_SEED_DEMO: "0"`、`ARK_SEED_PASSWORD: ""`、`ARK_API_DOCS: "0"`、prod settings |
| 18 | 555 全量 / migrations / design+schema / README | **通过** | 555 passed；No changes；diff 0；README `:5`/`:29`/`:99` 均 555 |

## 2. 实测数字

| 项目 | 结果 |
|---|---|
| 全量 pytest | `555 passed, 19 warnings in 45.50s` |
| 定向 r12 用例 | `15 passed, 540 deselected, 15 warnings in 5.04s` |
| `makemigrations --check --dry-run` | `No changes detected`（仅 PG 5432 警告） |
| 范围 diff | 29 files, +1568/−59 |
| r12-only diff | 3 files, +16/−5（README、startup.py、test_deploy_hardening.py） |
| design / frontend schema | 0 行 |
| 旧库闸门 | `manage.py check` EXIT=1；rotate EXIT=0；复查 EXIT=0 |
| 无效 URI | 4 种 key/value 变体全部 EXIT=1，0 文件 |

## 3. Critical

无。

## 4. Important

无。

## 5. Minor

1. **`file::memory:?cache=shared` 这类“没有 `mode=memory` 的内存 URI”被判 False**：SQLite 的 `file::memory:?cache=shared` / `file:memory:?cache=shared` 本质是内存库，但当前策略要求显式 `mode=memory`，因此会被保守拒绝。默认 `config.settings.test` 使用 `:memory:`，当前套件不受影响；这是“策略选择 + false negative”，不是安全绕过。若以后要支持 SQLAlchemy 风格，需在 `_is_ephemeral_test_db()` 里显式识别 `:memory:` 路径，而不是放宽 `mode` 比较。
2. **不做 URL 解码**：`mode=memory%20` 判 False，方向保守、不会落盘；`%6demory` 这类编码合法值会被误拒，属于可用性 false negative，不是安全 bypass。
3. **`tests/test_deploy_hardening.py:747` 直接给 `settings.DATABASES` 赋值**：pytest 报 `UserWarning: Overriding setting DATABASES can lead to unexpected behavior`；建议改 `monkeypatch`/`override_settings`，纯测试卫生。
4. **`test_manage_test_runner_passes_with_sqlite` 只跑 11 例**：足以证明 `manage.py test` 启动不被守卫误杀；不覆盖全量发现/`--keepdb`，属覆盖深度。
5. **重复 mode 保守拒绝**：`mode=memory&mode=memory` 返回 False；SQLite 对重复 mode 的行为本身不可依赖，保守拒绝合理，不构成误伤合法单 mode URI。

## 6. C 系列累计复核

| 历史项 | 本轮复核 |
|---|---|
| C-1 compose 默认演示口令 / seed 默认开 | 已修：`docker compose config` 解析为 `ARK_SEED_DEMO=0`、`ARK_SEED_PASSWORD=""`、`ARK_API_DOCS=0`、prod settings |
| C-2 旧数据卷默认 `admin/Admin@123456` 继续可用 | 已修：旧库 `manage.py check` EXIT=1，列出六个账号；rotate 后 EXIT=0 |
| C-3 `manage.py --settings=prod` 被降级为 dev | 已修：旧库 `manage.py check --settings=config.settings.prod` EXIT=1 |
| C-4 `django-admin` / `python -m django` 绕过 | 已修：旧库两者均 EXIT=1；`django-admin` 需 `PYTHONPATH=.`（容器内 CWD 即 app 根，正常） |
| C-5 `runserver` autoreload 吞异常 | 已修：旧库 `--noreload` EXIT=1；默认 autoreload 在 r8 已验证不再挂起 |
| C-6 test-settings alias（`pytest` import） | 已修：`IS_TEST_SETTINGS` 按 marker 判定；本轮四种大小写/空白变体全部 EXIT=1 |
| C-7 `file:memory:foo` 落盘 | 已修：无 mode 的 `file:memory:foo` EXIT=1，无文件 |
| C-8 `xmode=memory` 子串绕过 | 已修：EXIT=1，无文件 |
| C-9 `MODE=memory` 大小写/空白绕过 | 本轮修好：四种变体全部 EXIT=1，0 文件 |

本轮没有发现“声称已修但实际未修”的 C 系列项。

## 7. 复现命令摘要

```bash
# 全量
cd backend-django
.venv/bin/python -m pytest -q
# 555 passed, 19 warnings in 45.50s

# 定向
.venv/bin/python -m pytest -q \
  -k "ephemeral_test_db_detection or manage_test_runner_passes_with_sqlite"
# 15 passed, 540 deselected

# migrations
DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python \
  manage.py makemigrations --check --dry-run
# No changes detected

# 旧库闸门（示例）
T=$(mktemp -d /tmp/e8r12.XXXXXX)
export ARK_DB_ENGINE=sqlite ARK_DB_NAME="$T/old.sqlite3"
DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py migrate --noinput
DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python manage.py seed_demo
DJANGO_SETTINGS_MODULE=config.settings.prod ARK_JWT_SECRET='R12-Str0ng-JWT-Secret-000000000000' \
  .venv/bin/python manage.py check
# EXIT=1，列出 admin、manager、staff、finance、partner、expert_ext
```

`MODE=memory` 等四种变体的完整脚本见 r11 报告 I-R11-1；本轮复测四种均 EXIT=1、0 文件。合法顺序两种与 `uri=true` 多参数均 EXIT=0、0 文件。

## 8. 合并门槛与结论

- **APPROVED**：无 Critical、无 Important。
- **可推送 develop**。
- 后续可选清理（不阻塞）：支持/明确拒绝 `file::memory:?cache=shared`；`settings.DATABASES` 改 `monkeypatch`；`manage.py test` 增加 `--keepdb`/全量发现覆盖。

## 9. 通过项与边界

- 555 全量、15 定向、migrations、README 三处计数、design/schema 零 diff 均符合声明。
- C 系列逐项复测：旧库闸门、rotate、`--settings`、`django-admin`、`python -m django`、runserver、test-settings alias、`file:memory:foo`、`xmode`、`MODE` 均生效。
- 未执行完整 `docker compose up --build`；compose 以 `docker compose config` 验证默认值，旧库/rotate 以 sqlite + prod settings 验证。
- 未修改任何源码；唯一仓库写入是本报告。
