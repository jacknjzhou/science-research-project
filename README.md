# 科研管理系统（science-research-project）

面向科研院所的一体化科研管理平台：项目申报立项 → 过程管理 → 经费 → 成果 → 转化 → 诚信伦理 → 人员团队 → 决策大屏 → 采购合同 → 资产耗材 → 涉密多法人治理，共 11 个业务模块，契约驱动、前后端分离、多法人多租户。

> **当前状态**：后端 Django 重写 **Phase 0–4 全部完成**（11 模块全量落地 + svc-ai AI 微服务），全量 154 pytest 通过，PG 端到端冒烟 30 项全过，`develop` 已推送。

## 技术栈（方案 C）

| 层 | 选型 |
|----|------|
| 后端主体 | **Django 5.x LTS + django-ninja**（单服务 `backend-django`，端口 8787） |
| AI 微服务 | **FastAPI**（`backend-django/svc_ai`，端口 8900，无状态、不连业务库） |
| 数据库 / 缓存 / 对象存储 | PostgreSQL 15 / Redis 7 / MinIO |
| 前端 | Vue 3.4 + Vite + TypeScript（`frontend/`，契约 mock 驱动，见 [frontend/README.md](frontend/README.md)） |
| LLM 网关 | NewAPI OpenAI 兼容（`ARK_LLM_BASE_URL`，未配置自动降级） |
| 鉴权 | PyJWT Bearer + casbin（RBAC 8 角色，`config/casbin/policy.csv`） |

## 仓库结构

```
├── design/                  # 11 模块 OpenAPI 3.0.3 契约 + DDL + detail（唯一真源）
├── PRD/                     # 产品需求文档（通用规约 README 2.1–2.15）
├── backend-django/          # Django 主体 + svc_ai FastAPI（本仓库后端）
│   ├── apps/                # 18 个域 app（sysadmin/notify/p/project/funding/output/…）
│   ├── core/                # 信封/鉴权/幂等/契约 stub/dataio/llm/storage
│   ├── svc_ai/              # FastAPI AI 微服务（/ai/*）
│   ├── config/              # settings(dev/test/base) + 集中路由 + casbin policy
│   ├── scripts/             # PG 冒烟脚本 smoke_p3.py / smoke_p4.py
│   └── tests/               # pytest 套件（154 个）
├── frontend/                # Vue3 SPA（契约 mock，13 屏）
├── prototype/               # 静态高保真原型
├── docs/superpowers/        # 重写 plan 与 spec（backend-django-rewrite-*）
├── docker-compose.yml       # 一键编排（backend/frontend/svc-ai/postgres/redis/minio）
├── TECH_ARCHITECTURE.md     # 架构文档（顶部横幅标注 v2 选型变更）
└── DEPLOY.md / PRODUCT_PLAN.md / PRODUCTION_GAP_ROADMAP.md
```

## 快速开始（Docker Compose）

```bash
docker compose up -d --build
```

启动后（全部容器 healthcheck 通过约 1 分钟）：

| 服务 | 地址 | 说明 |
|------|------|------|
| 前端入口 | http://localhost:8080 | nginx 托管 SPA；`?autologin=1#/project` 可跳过登录 |
| 后端 API | http://localhost:8787/api/v1 | 健康检查 `/healthz` |
| svc-ai | http://localhost:8900/healthz | AI 微服务；`llmConfigured:false` 即降级态 |
| 接口在线文档 | http://localhost:8081 | Swagger UI 浏览 design/ 全部 16 份 OpenAPI 契约（下拉切模块） |

演示账号（启动时 `seed_demo` 幂等播种）：`admin / Admin@123456`。

常用运维：

```bash
docker compose ps                    # 服务与健康状态
docker compose logs -f backend       # 后端日志
docker compose restart backend       # 只重启后端
docker compose down -v               # 连数据卷一起清空（重新初始化）
```

## 本地开发与测试

```bash
cd backend-django
# 依赖：Python ≥3.12（建议 3.13），安装依赖后：
python manage.py migrate                                    # 默认连 localhost:5432 PG
python manage.py seed_demo                                  # 幂等播种

# 全量测试（sqlite 内存库，不依赖 PG）
python -m pytest tests -q                                   # 当前 154 passed

# PG 端到端冒烟（直连 live PG，幂等可重跑）
python scripts/smoke_p3.py                                  # Phase 3 域 18 项
python scripts/smoke_p4.py                                  # Phase 4 域 + svc-ai 12 项

# svc-ai 本地起服务
uvicorn svc_ai.main:app --port 8900
```

测试配置见 `pyproject.toml`（`DJANGO_SETTINGS_MODULE=config.settings.test`）；冒烟脚本走 `config.settings.dev`。

## API 约定（对齐 design/README.md）

- **统一信封**：`{code, message, data, traceId, timestamp}`；`code=0` 成功，非 0 业务错误
- **主要错误码**：40001 参数 / 40102 凭证 / 40301 casbin 拒绝 / 40401 不存在 / 40901 状态机冲突 / 40902 余额或引用 / 40909 幂等锁 / 40910 预算冻结失败 / 40911 付款超合同额 / 40913 供应商黑名单 / 40916 重复转资产 / 50003/50010 转化分配校验 / 50301 依赖不可用
- **认证**：`Authorization: Bearer <JWT>`；写接口支持 `Idempotency-Key` 幂等头
- **AI 端点降级契约**：LLM 未配置或上游不可达 → HTTP 200 `{verdict:"REVIEW", confidence:0, reasons:["llm-unavailable"]}`，不阻塞业务；AI 永不自动定密（X 域）
- **多法人/密级**：业务表携带 `legal_entity_id / security_level`；涉密对象在非 SECRET_NET 网络域不可见（`X-Network-Zone` 头），关键涉密操作须 `X-MFA-Assert` 二次鉴别

### 接口在线文档（三处入口）

| 入口 | 地址 | 内容 |
|------|------|------|
| 契约文档（推荐） | `http://localhost:8081`（compose 的 `api-docs` 服务） | design/ 全部 16 份 OpenAPI 3.0.3 原文，Swagger UI 下拉切换；这是接口的唯一真源 |
| Django 主体自省 | `http://localhost:8787/api/v1/docs`（dev 默认开；生产设 `ARK_API_DOCS=1`） | django-ninja 自动生成的 Swagger UI（运行时路由） |
| svc-ai 自省 | `http://localhost:8900/docs`（另有 `/redoc`、`/openapi.json`） | FastAPI 原生文档 |

## 实现进度

| Phase | 内容 | 提交 |
|-------|------|------|
| 0 | 脚手架 + 信封/TraceID/登录鉴权/幂等 + sysadmin/notify + 契约 stub | ✅ |
| 1 | P 申报立项 / E 过程 / F-income 全链路 | `67596d5` |
| 2 | F 经费域全模块（40 路由） | `4a9db4a` |
| 3 | R 成果 / N 专家评审 / V 学术活动 / O 档案 / M 绩效 / D 大屏（~95 路由） | `6e8c32e` |
| 4 | T 转化 / C 诚信伦理 / S 人员 / G 采购合同 / A 资产耗材 / X 涉密治理（~126 端点）+ svc-ai | `0b64232` |
| 4.x | compose 编装修复 + svc-ai 服务编排 | `f7a715b` |

## 环境变量（`ARK_*` 前缀，对齐 Go 版命名）

| 变量 | 用途 | 默认 |
|------|------|------|
| `ARK_DATABASE_URL` | PostgreSQL DSN | `postgres://ark:ark@localhost:5432/ark` |
| `ARK_REDIS_ADDR` | Redis | `127.0.0.1:6379` |
| `ARK_JWT_SECRET` / `ARK_JWT_TTL_SEC` | JWT | dev-secret / 7200 |
| `ARK_LLM_BASE_URL` / `API_KEY` / `MODEL` / `TIMEOUT_SEC` | LLM 网关（NewAPI OpenAI 兼容） | 空（降级）/ `gpt-4o-mini` / 30 |
| `ARK_DB_ENGINE=sqlite` | 测试切 sqlite 内存库 | — |
| `ARK_S3_*` | MinIO 对象存储 | minioadmin…/ark-docs |

## 部署

- **开发/演示**：`docker compose up -d --build`（见上文）。
- **生产**：非容器化——systemd 多实例（`django-api.service` gunicorn / `django-worker` / `django-beat` / `svc-ai.service` uvicorn / `django-migrate` oneshot）+ Nginx 反向代理多活（`/api/ → django`、`/ai/ → svc-ai` 内网）。详见 `docs/superpowers/specs/2026-10-17-backend-django-rewrite-spec.md` §九。

## 文档索引

| 文档 | 内容 |
|------|------|
| `design/*.openapi.yaml` | 11 模块 REST 契约（唯一真源，前后端共同遵守） |
| `PRD/README.md` | 术语与通用规约（角色/单号/状态 token/密级/多法人） |
| `docs/superpowers/plans|specs/2026-10-17-backend-django-rewrite-*` | Django 重写计划与详细规格 |
| `TECH_ARCHITECTURE.md` | 架构方案（注意顶部 v2 选型变更横幅，Go 章节已过时） |
| `frontend/README.md` | 前端架构、13 屏路由与契约 mock 说明 |
| `DEPLOY.md` | 部署说明（横幅注明与现状的差异） |

> 旧 Go/Node 后端已移除，源码快照见 git tag `legacy-backend-20261017`。
