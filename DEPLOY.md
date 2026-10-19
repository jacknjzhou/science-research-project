# 部署方案 · Docker Compose 一键启动全套服务

> **✅ 现状速览（2026-10-17，Phase 4 完成）**：`docker-compose.yml` 已演进为**全套六服务编排**：`backend`（Django :8787）+ `svc-ai`（FastAPI :8900）+ `frontend`（nginx :8080）+ `postgres`/`redis`/`minio`。一键 `docker compose up -d --build`，全部容器自带 healthcheck，演示账号 `admin / Admin@123456`。速查见根目录 `README.md`；生产 systemd 非容器化方案见 `docs/superpowers/specs/2026-10-17-backend-django-rewrite-spec.md` §九。**本文以下正文描述旧 Node/Fastify 参考栈，仅作历史参考**（源码快照：git tag `legacy-backend-20261017`）。

本方案用 Docker Compose 把「契约驱动参考栈」整套拉起：nginx 托管的前端 SPA + Node/Fastify 参考后端，二者同源、开箱可访问。生产目标（Java 17 + Spring Cloud Alibaba + PostgreSQL）落地后，只需替换同名 `backend` 服务，前端与反代保持不变。

## 前置条件

安装 Docker（含 BuildKit）与 Docker Compose v2：

```bash
docker --version          # 需 20.10+
docker compose version    # 需 v2.x
```

> 本仓库当前开发机未安装 Docker，故以下配置以「静态审查 + 底层构建已验证」方式交付：`frontend` 的 `npm run build`（vue-tsc + vite）与 `backend` 的 `npm run verify`（87/87 契约自验）在宿主机均已跑通；镜像只是把这两步搬进容器。装好 Docker 的机器上按下方命令即可实跑。

## 一键启动

在仓库根目录执行：

```bash
docker compose up -d --build
```

启动后：

- 前端入口：<http://localhost:8080> （浏览器打开即可，已登录态演示用 `http://localhost:8080/?autologin=1#/project`）
- 后端 API：<http://localhost:8787/api/v1> （自检 <http://localhost:8787/healthz>、统计 <http://localhost:8787/api/v1/_stats>、契约清单 <http://localhost:8787/api/v1/_openapi>）

常用运维命令：

```bash
docker compose ps                 # 查看服务与健康状态
docker compose logs -f backend    # 跟踪后端日志
docker compose logs -f frontend   # 跟踪 nginx 访问日志
docker compose restart backend    # 只重启后端
docker compose down               # 停止并移除容器（保留镜像）
docker compose down -v            # 连数据卷一起清（含 --profile db 起的 postgres）
```

## 服务拓扑

```
浏览器 :8080
   │
   ▼
┌──────────────────────────┐        ┌───────────────────────────┐
│ frontend (nginx:1.25)    │  /api/ │ backend (node:16 Fastify) │
│  · 托管 SPA 静态产物      │───────▶│  · 读 design/ 契约造路由   │
│  · 同源反代 /api/v1       │ :8787  │  · 统一 envelope/分页/幂等 │
└──────────────────────────┘        └───────────────────────────┘
                                             ▲
                        （可选 profile=db）    │ 逻辑外键，参考栈暂用进程内存储
                    ┌──────────────────┐      │
                    │ postgres:15      │──────┘  预留给生产目标持久化
                    └──────────────────┘
```

前端 `client.ts` 走相对路径 `/api/v1`，由 nginx 反代到 `backend:8787`，单源部署天然无跨域（后端本身 `CORS origin:true` 作直连兜底）。

## 构建上下文说明（两个服务不同）

后端运行时用 `fs` 读取仓库根 `design/` 契约（`DESIGN_DIR = resolve(__dirname,'..','..','design')`），所以后端镜像**构建上下文 = 仓库根**，Dockerfile 用 `dockerfile: backend/Dockerfile` 指定，镜像内保留 `/srv/app/backend` 与 `/srv/app/design` 的相对布局。根 `.dockerignore` 把上下文裁剪到只含所需内容（排除 `frontend/`、`prototype/`、`node_modules` 等）。

前端契约 yaml 已随 `frontend/src/api/schema/` 提交（构建期由 `import.meta.glob('./*.yaml')` 载入），故前端镜像**构建上下文 = `frontend/`**，自包含、不依赖仓库根。

## 关键环境变量

后端（`docker-compose.yml` / `backend/Dockerfile`）：

- `HOST=0.0.0.0`：容器内必须监听 0.0.0.0，否则其它容器/宿主机无法访问。
- `PORT=8787`：监听端口。
- `NODE_ENV=production`。

前端（构建期，`frontend/Dockerfile`）：

- `VITE_USE_MOCK=false`：**必须**。`main.ts` 里 `installMock()` 由 `if (import.meta.env.VITE_USE_MOCK !== 'false')` 兜住；不显式设 false，生产包会仍走浏览器端契约 mock 而非真实后端。该值在 `vite build` 时被内联进产物，因此是**构建期**变量，改它要重新 build 镜像。

## 数据持久化与数据库

当前 Node 参考后端使用**进程内存储**（`store.js` 的 Map + 自增 id），重启即清空，仅用于契约走通与联调，故默认 compose 不含数据库。

为对齐生产目标，已内置一个 profile 化的 PostgreSQL，默认不启动：

```bash
docker compose --profile db up -d      # 额外拉起 postgres:15，数据落在命名卷 pgdata
```

Java/Spring 后端接入时，把 `backend` 服务替换为 Spring Boot 镜像，并用 `--profile db` 或独立 compose 提供 PostgreSQL / Nacos / Redis / MQ，`depends_on` 与网络拓扑沿用本文件即可。

## 单独构建某个镜像

```bash
# 后端（上下文=仓库根）
docker build -f backend/Dockerfile -t eplugger-backend:0.1.0 .

# 前端（上下文=frontend/）
docker build -t eplugger-frontend:0.1.0 ./frontend
```

## 验证清单

启动后逐项确认：

1. `docker compose ps` 两服务均 `healthy`。
2. `curl http://localhost:8787/healthz` → `{"ok":true,"modules":11,"operations":246,...}`。
3. `curl http://localhost:8080/api/v1/_stats` → 经 nginx 反代返回后端 JSON（证明同源代理链路通）。
4. 浏览器打开 <http://localhost:8080/?autologin=1#/project> → 项目详情金额显示为 `¥xxx万`、执行率显示为正常百分比（非 `NaN`、非天文数字），说明真实后端 + string 精度解析链路完整。

## 已知限制

- 参考后端为进程内存储、无鉴权，`traceId` 为随机串；仅用于契约联调与演示，不可直接对外生产。
- 造数为 schema 合规的随机值（部分文本字段为拉丁 lorem）；金额按契约以字符串承载 `NUMERIC(18,2)` 精度，前端 `utils/money.ts` 已稳健解析。
- 若要真实持久化与业务闭环，请走生产目标（Java/Spring + PostgreSQL），本 compose 的 service 拓扑可直接复用。
