# 科研管理系统 · 契约驱动参考后端

Node 16 + Fastify 实现的**契约驱动（contract-first）**参考后端。它不写死任何一条业务路由，而是启动时加载仓库根目录 `design/` 下的 11 份 OpenAPI 3.0.3 契约，把每一条 operation 变成运行时可解析的路由，并按其 200 响应 schema 现场造数返回。前端只要把契约 mock 关掉（`VITE_USE_MOCK=false`），走 `/api/v1` 就能打到这个后端，实现「契约即路由、即响应、即真源」。

## 与生产目标的关系

`docs/TECH_ARCHITECTURE.md` 规定的生产栈是 **Java 17 + Spring Cloud Alibaba + PostgreSQL**。本机环境只有 Node v16.20.2（无 JDK / Maven / Gradle / Docker / PostgreSQL），无法在此构建、运行那套栈。因此本目录提供的是一个**可运行、可自验的参考实现（reference backend）**，用来把契约跑通、把前端 swap 验证闭环——它是 Java/Spring 落地的**伴生验证件，而非替代品**。路由形态、统一响应包裹、分页体、幂等头、状态机业务码都严格对齐契约，Java 侧照 `design/*.openapi.yaml` 生成 controller/DTO 即可平滑替换。

## 运行

```bash
cd backend
npm install          # 首次
npm start            # 监听 http://127.0.0.1:8787/api/v1
npm run dev          # node --watch 热重载
npm run verify       # 契约一致性自验（ajv 校验全部 GET 响应体）
```

环境变量：`PORT`（默认 8787）、`HOST`（默认 127.0.0.1）。

自检接口：

- `GET /healthz` —— `{ ok, modules, operations, ts }`
- `GET /api/v1/_stats` —— 已注册操作数与内存集合计数
- `GET /api/v1/_openapi` —— 各模块契约文件、标题、路径数汇总

## 与前端联调（真实后端 swap）

前端默认拦截 fetch 用契约 mock 造数。要改打这个后端：

```bash
# 终端 1
cd backend  && npm start                 # :8787

# 终端 2（关键：关掉 mock 拦截）
cd frontend && VITE_USE_MOCK=false npm run dev
```

`frontend/vite.config.ts` 已配 `/api` → `http://127.0.0.1:8787` 代理，`main.ts` 里 `installMock()` 被 `if (import.meta.env.VITE_USE_MOCK !== 'false')` 兜住。设成 `false` 后 SPA 直接走真实 HTTP。

> 注意：Windows 下若用 git-bash 启动，赋值要用 `VITE_USE_MOCK=false npm run dev`（bash 语法）；`set VITE_USE_MOCK=false` 是 cmd 语法，在 bash 里只会设位置参数、不会注入环境变量。

已验证：mock 关闭后 `#/project` 渲染出的是后端造的数据（如 `BIZ-2026-…` 单号、拉丁 lorem 文本），而非前端 curated 的中文演示数据，证明请求确实打到了 `:8787`。

## 架构与数据流

```
HTTP 请求
  └─ Fastify 通配分发器  app.route({ method, url: '/api/v1/*' })   （GET/POST/PUT/DELETE/PATCH 各一条）
       └─ dispatch(req)
            ├─ matchRoute(METHOD, url)  →  契约 op（含 200 responseSchema）
            ├─ 未命中          →  envelope(40401, "契约未定义该路由")
            ├─ 写流程命中 flows →  状态机 + Idempotency-Key 去重 + 实体叠加 schema 形状
            └─ 其它            →  genericResponse：generate(200.data schema) (+ GET-by-id 读回 + 分页填充)
```

核心模块：

- `src/schema.js` —— 加载 `design/*.openapi.yaml`，构建 `routeIndex`（`"METHOD /模板路径" → op`）；`resolveRef` / `extractDataSchema`（从 `allOf:[ApiResponse,{data}]` 抽 `data` 子 schema）/ `matchRoute` / `toFastifyPath`。与前端 `src/api/schema/index.ts` 同构。
- `src/generator.js` —— 按 schema 造数（faker `zh_CN`）。`$ref`/`allOf`/`oneOf`/`anyOf`、`format`、`enum`、`nullable` 全支持；`depth` 以值传递递归（避免兄弟节点串改深度导致中途返回 null）。金额等 `type:string` 精度字段按契约原样输出字符串。
- `src/store.js` —— 进程内 Map 存储 + 自增 `nextId()`（90000 起）+ `idempotent(key, produce)` 去重缓存。
- `src/flows.js` —— 核心写流程状态机：申报 `DRAFT→SUBMITTED→…`、报销提交、成果认领、转化披露/签约；非法流转返回业务码（40905 禁止撤回、40901 状态冲突）。`READ_BACK` 让写过的实体在 GET-by-id 时可读回。
- `src/server.js` —— 分发器、统一 `envelope{code,message,data,traceId,timestamp}`、`fillPage`、CORS、自检路由、`isMain` 监听守卫。

## 为什么用「单通配分发器」而不是逐条注册路由

246 条 operation 里大量使用 Google-AIP 风格的自定义动词，动词嵌在路径段内：`/apply/applications/{id}:withdraw`、`/apply/review/tasks/{id}:score`。这种 `:verb` 与 Fastify 的路径参数语法（`:param`）直接冲突，逐条注册会解析错乱。因此每个 HTTP 方法只挂一条 `/api/v1/*` 通配路由，运行时用 `matchRoute` 把请求反解析回契约操作，`extractParams`（正则 `([^/]+?)`）从 `{id}:withdraw` 这类模板里抽参数。代价是放弃了 Fastify 的 schema 编译校验，换来对契约路径形态的完全兼容。

## 统一响应约定

所有响应都包在 `envelope` 里：`code=0` 成功、非 0 为业务错误码（沿用 `design/README §4`：40001 校验 / 40101 未认证 / 40301 越权 / 40401 不存在 / 40901+ 冲突 / 42901 频率 / 50301 AI 不可用），HTTP 状态码表达传输层。分页体 `PageResult{list,total,page,size}` 由 `fillPage` 依 query 的 `page`/`size` 回填。写接口支持 `Idempotency-Key` 头，同键重试返回同一结果。

## 命名大小写混用（务必知悉）

各模块契约的字段大小写**不统一**，后端严格「契约怎么写就怎么发」：P/F/R/T 用 snake_case（`project_type`、`apply_start_at`、`ai_compliance_flag`），E/D 用 camelCase（`budgetExecRate`、`occurredAt`、`tenantId`）。前端视图与后端都按各自契约原样对接，不做统一转换。

## 契约一致性自验

`npm run verify` 遍历所有 GET 操作，把路径参数替换成 `1` 注入分发器，取 `envelope.data`，用 ajv（draft-07 + 仅标准 format）对照该操作自己的 `data` schema 校验。`normalize` 会把 OpenAPI 折成 JSON Schema：解 `$ref`（带引用栈断环）、剔除 `example/discriminator` 等非标准键、`nullable:true` 时把 `type` 并上 `null` 且给 `enum` 追加 `null`。

当前结果：**87 / 87 GET 路由响应体全部符合各自契约 schema。**

## 已知限制

- 进程内存储，重启即清空；无鉴权（`traceId` 为随机串）。仅用于契约走通与前端联调。
- 造数是 schema 合规的随机值（部分文本字段为拉丁 lorem），金额按契约以字符串承载，前端若按 number 解析会显示 `NaN`——这是视图格式化假设与契约 string 精度表达的落差，非后端缺陷。
- 写流程只覆盖申报/评审/报销/成果/转化的主干动词，其余写操作走通用幂等 + schema 生成响应。
