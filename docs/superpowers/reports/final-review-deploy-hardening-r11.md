# E-8 终审 r11：`mode` 精确解析与累计修复复审

- 仓库：`/Users/jacky/works/science-research-project`
- 分支：`develop`
- 范围：`a83c409..264e64b`（新增 `264e64b`）
- diff 包：`/tmp/review-deploy-hardening-r11.diff`（105074 bytes）
- 计划：`docs/superpowers/plans/2026-11-19-deploy-hardening.md`
- ledger：`.superpowers/sdd/2026-11-19-deploy-hardening/progress.md`
- 复审对象：r10 的 I-R10-1（`xmode=memory` 子串绕过）与 I-R10-2（参数覆盖）
- 结论：**REQUEST_CHANGES**（无 Critical；2 条 Important）

## 0. 结论

r11 修好了 r10 报告里的两个具体形态：

- `file:memdb1?xmode=memory` 现在被精确判为非内存库，别名 + `manage.py migrate` **EXIT=1**，报 `IS_TEST_SETTINGS`，`memdb1` 未创建。
- 参数单测从 6 个扩到 10 个，覆盖 `xmode`、`mode=memory_extra`、重复 mode、`cache=shared&mode=memory`。

但新的解析器把键名做了 `strip().lower()`：

```python
key, _, value = pair.partition("=")
if key.strip().lower() == "mode":
    modes.append(value.strip().lower())
```

SQLite 的 URI 参数名是区分大小写、且不忽略空白的。`MODE=memory`、`Mode=memory`、` mode=memory`、`mode =memory` 都会被 Django 判为内存库（`_is_ephemeral_test_db()` 返回 True），而 SQLite 实际忽略这些键，按普通文件 URI **落盘**。我亲手复现：

- 别名 `from config.settings.test import *` + `DATABASES.default.NAME = "file:memdbU?MODE=memory"`
- `manage.py migrate --noinput` → **EXIT=0**
- 生成 `$T/memdbU`，**1,294,336 bytes**

同一轮还复现 `Mode=memory`、` mode=memory`、`mode =memory` 三种写法，均 EXIT=0 并生成 1,294,336 字节文件；`mode= memory`（值前空格）被 SQLite 拒绝，EXIT=1、无文件。也就是说，r11 把“子串匹配绕过”换成了“大小写/空白键名绕过”，安全边界仍未闭合。

因此 verdict 仍是 **REQUEST_CHANGES**，但不升级为 Critical：它需要非默认的自定义 settings/URI；默认 compose、README、prod 路径不经过这个别名。它是同一“测试配置不得迁持久库”边界的**第三次不完整修复**，必须在合并前收口。

## 1. 逐项结论

| # | 必查项 | 结论 | 证据 |
|---|---|---|---|
| 1 | `file:memdb1?xmode=memory` | **通过** | 别名 migrate EXIT=1，`IS_TEST_SETTINGS`，无 `memdb1` |
| 2 | `mode=memory_extra` | **通过（False）** | 10 参数单测；别名 migrate 被拒（上轮实测 EXIT=1、无文件） |
| 3 | `mode=memory&mode=disk` | **通过（False）** | 10 参数单测；重复 mode 保守拒绝 |
| 4 | `cache=shared&mode=memory` | **通过（True）** | 10 参数单测；别名 migrate EXIT=0，无文件 |
| 5 | `mode=memory&cache=shared&uri=true` | **通过** | 多参数不被“只有一个 mode 键”误伤；migrate EXIT=0，无文件 |
| 6 | `MODE=memory` | **失败（Important）** | migrate EXIT=0，生成 `memdbU` 1,294,336 bytes；`core/startup.py:80-82` 小写化 |
| 7 | `Mode=memory` | **失败（Important）** | migrate EXIT=0，生成 `memdbC` 1,294,336 bytes |
| 8 | `" mode=memory"`（键前空格） | **失败（Important）** | migrate EXIT=0，生成 `memdbK` 1,294,336 bytes |
| 9 | `mode =memory`（键后空格） | **失败（Important）** | migrate EXIT=0，生成 `memdbK2` 1,294,336 bytes |
| 10 | `mode= memory`（值前空格） | **保守通过** | SQLite 拒绝 `memory` 前空格，EXIT=1、无文件 |
| 11 | 相对路径 sqlite 文件名 | **方向正确** | `_is_ephemeral_test_db()` 返回 False；相对 CWD 落盘必须挡 |
| 12 | 绝对路径 / postgres | **通过** | 均返回 False |
| 13 | `manage.py test` 不被误杀 | **通过** | 子进程跑 `tests.test_login_auth`，11 例通过，EXIT=0 |
| 14 | 551 全量 / migrations / design+schema | **通过** | 551 passed；No changes；diff 0 |
| 15 | README 测试数 | **部分失败（Minor）** | `:99` 已 551；`:5`、`:29` 仍 522 |

## 2. 实测数字

| 项目 | 结果 |
|---|---|
| 全量 pytest | `551 passed, 15 warnings in 43.60s` |
| 定向 r11 用例 | `11 passed, 540 deselected, 11 warnings in 4.75s` |
| `tests.test_login_auth` | `11 tests collected` |
| `makemigrations --check --dry-run` | `No changes detected`（仅 PG 5432 警告） |
| 范围 diff | 29 files, +1557/−59 |
| r11-only diff | 3 files, +26/−3（README、startup.py、test_deploy_hardening.py） |
| design / frontend schema | 0 行 |
| 持久化证据 | `memdbU`、`memdbC`、`memdbK`、`memdbK2` 均 1,294,336 bytes |

## 3. Critical

无。

## 4. Important

### I-R11-1：大小写/空白键名绕过 `mode` 判定

**位置**：`backend-django/core/startup.py:76-82`

```python
params = name.split("?", 1)[1] if "?" in name else ""
modes = []
for pair in params.split("&"):
    key, _, value = pair.partition("=")
    if key.strip().lower() == "mode":
        modes.append(value.strip().lower())
return len(modes) == 1 and modes[0] == "memory"
```

**复现**（`mktemp -d`，无删除命令）：

```bash
BD=/Users/jacky/works/science-research-project/backend-django
T=$(mktemp -d /tmp/e8r11.XXXXXX)
for spec in 'memdbU:MODE=memory' 'memdbC:Mode=memory' \
            'memdbK: mode=memory' 'memdbK2:mode =memory'; do
  f=${spec%%:*}; q=${spec#*:}
  cat >"$T/$f.py" <<PY
from config.settings.test import *
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3",
                         "NAME": "file:$f?$q"}}
PY
  ( cd "$T" && PYTHONPATH="$T:$BD" DJANGO_SETTINGS_MODULE="$f" \
      ARK_JWT_SECRET='R11-Str0ng-JWT-Secret-000000000000' \
      "$BD/.venv/bin/python" "$BD/manage.py" migrate --noinput >/dev/null 2>&1 )
  echo "$f EXIT=$?"
  ls -l "$T/$f" 2>/dev/null || true
done
```

实测输出：四个 `EXIT=0`，四个文件均 1,294,336 bytes；`memdbU`（`MODE=memory`）是其中最短复现。

**机制**：SQLite 只识别精确的小写参数名 `mode`；`MODE`/`Mode`/` mode`/`mode ` 都不被识别，默认 `mode=rwc` 落盘。解析器却把键 `strip().lower()` 成 `mode`，于是 `_is_ephemeral_test_db()` 返回 True，`_assert_settings_module_deployable(strict=False)` 直接放行。

**修复要求**：不要对键做大小写/空白归一化，按 SQLite 的实际语法精确比较：

```python
for pair in params.split("&"):
    key, sep, value = pair.partition("=")
    if sep and key == "mode":
        modes.append(value)
return len(modes) == 1 and modes[0] == "memory"
```

即：键必须**原样**等于 `mode`；值必须**原样**等于 `memory`；`MODE`、`Mode`、` mode`、`mode ` 一律 False。若担心 URL 编码，可显式 `unquote` 后再比较，但不要先 `lower()`/`strip()` 键。

### I-R11-2：10 参数单测仍未覆盖大小写/空白键

**位置**：`backend-django/tests/test_deploy_hardening.py:705-739`

新增的 10 个参数只有 `xmode`、`mode=memory_extra`、重复 mode、`cache=shared&mode=memory`；没有 `MODE=memory`、`Mode=memory`、键前后空格。因此 551 全绿不能证明 I-R11-1 关闭；上述四种绕过在套件中完全静默。

请补至少四组参数化用例（全部 expected False）：

- `file:memdb1?MODE=memory`
- `file:memdb1?Mode=memory`
- `file:memdb1? mode=memory`
- `file:memdb1?mode =memory`

并加一条真实子进程回归：别名 + `MODE=memory` + `manage.py migrate` 断言 EXIT≠0、stderr 含 `IS_TEST_SETTINGS`、文件不存在。只测 `_is_ephemeral_test_db()` 不够，因为“解析器返回 False”和“migrate 被拒绝”是两件事。

## 5. Minor

1. **README `:5`、`:29` 仍写 522**：`:99` 已 551；`grep -n "522" README.md` 可复现。r10 已提过，仍未统一。
2. **`tests/test_deploy_hardening.py:738`** 直接给 `settings.DATABASES` 赋值，pytest 报 `UserWarning: Overriding setting DATABASES can lead to unexpected behavior`；建议 `monkeypatch`/`override_settings`。
3. **URL 解码缺失**：`mode=memory%20` 当前返回 False，方向保守、可接受；`%6demory` 之类会被误拒（false negative），但不会造成落盘，属于可用性/严格性问题，不是本轮阻塞项。
4. **重复 mode 一律 False**：`mode=memory&mode=memory` 是非法/歧义 URI，保守拒绝合理；不会误伤 `cache=shared&mode=memory&uri=true` 这类“多个其他键、一个 mode”的合法形态（已实测 EXIT=0、无文件）。
5. **`test_manage_test_runner_passes_with_sqlite` 只跑 11 例**：足以证明 `manage.py test` 启动不被守卫误杀；不覆盖全量发现/`--keepdb`，属覆盖深度。
6. **`mode= memory`（值前空格）**：SQLite 报 `no such access mode:  memory`，EXIT=1、无文件；当前解析器因 `value.strip()` 判 True，但 SQLite 自己拒绝，暂不构成落盘绕过；精确比较后会变成 False，方向一致。

## 6. 对三个重点问题的回答

### ① “只有一个 mode 键”是否误伤合法 URI

不会。实测 `file:memdbM?cache=shared&mode=memory&uri=true`：解析器只收集到一个 `mode=memory`，`_is_ephemeral_test_db()` 为 True，`manage.py migrate` EXIT=0，无 `memdbM` 文件。多出来的 `cache`/`uri` 是其他键，不影响。重复 `mode` 保守拒绝是合理的（SQLite 对重复/冲突 mode 的行为本身不可依赖）。

### ② 不做 URL 解码，`mode=memory%20` 判 False 是否可接受

可接受，方向是保守的：`%20` 解码后是 `memory `（带空格），SQLite 也会报 `no such access mode:  memory`；判 False 不会放行落盘。代价是 `%6demory` 这类编码过的合法值会被误拒，属于可用性 false negative，不是安全 bypass。若未来要支持 URL 编码，应 `unquote` 后再做**精确**比较，且仍不要 `lower()` 键。

### ③ r1..r10 是否还有“以为修了、实际没修”

本轮抽查了历史关键项：

- r5 的 `manage.py` 进程守卫、r6 的 `--settings=prod`、`django-admin`/`python -m django`、r7 的 runserver autoreload、r8 的 alias 普通形态、r9 的 `file:memory` 无 mode、r10 的 `xmode`：均仍按预期拒绝/通过。
- 仍遗留：**README `:5`/`:29` 的 522**（Minor）；**`settings.DATABASES` 警告**（Minor）；**`manage.py test` 仅 11 例**（覆盖深度，非缺陷）。
- 新发现：**大小写/空白键名**（I-R11-1），这是 r11 解析器引入的回归，不是旧条目未修。

## 7. 复现命令摘要

```bash
cd /Users/jacky/works/science-research-project/backend-django
.venv/bin/python -m pytest -q
# 551 passed, 15 warnings in 43.60s

.venv/bin/python -m pytest -q \
  -k "ephemeral_test_db_detection or manage_test_runner_passes_with_sqlite"
# 11 passed, 540 deselected

DJANGO_SETTINGS_MODULE=config.settings.dev .venv/bin/python \
  manage.py makemigrations --check --dry-run
# No changes detected
```

`MODE=memory` 等四种键名绕过的完整命令见 I-R11-1；`xmode` 复测 EXIT=1、无文件；多参数合法 URI 复测 EXIT=0、无文件。

## 8. 合并门槛

1. **I-R11-1**：键名/值都精确比较，移除 `strip().lower()`；`MODE=memory`、`Mode=memory`、` mode=memory`、`mode =memory` 必须 `_is_ephemeral_test_db()` False 且 `manage.py migrate` EXIT≠0、无文件。
2. **I-R11-2**：补上述四种参数化单测 + 一条真实 `MODE=memory` 子进程迁移回归。
3. **Minor**：README `:5`、`:29` 统一 551；`settings.DATABASES` 赋值改 `monkeypatch`（可选）。
4. 重新跑全量 `pytest -q`（≥551）、`makemigrations --check` No changes、`git diff --stat a83c409..HEAD -- design frontend/src/api/schema` 为空。
5. 通过后可给 **APPROVED**；当前不满足。

## 9. 通过项与边界

- `xmode`、`mode=memory_extra`、重复 mode、`cache=shared&mode=memory` 已按 r11 实现工作。
- `manage.py test` 真实子进程 11 例通过，不是直接调用守卫的 false green。
- 551 全量、migrations、design/frontend schema 均符合声明。
- 未执行完整 `docker compose up --build`；本轮持久化证据来自 sqlite + 测试 settings 别名 + 真实 `manage.py migrate`。
- 未修改任何源码；唯一仓库写入是本报告。
