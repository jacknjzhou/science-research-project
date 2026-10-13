## 科研管理系统 · 契约驱动前端（frontend/）

本工程把 `prototype/` 里 13 张静态高保真原型屏，改造成一个真正**数据驱动**的 Vue3 单页应用。它的核心主张是「契约即唯一真源」：页面不写死数据，而是运行时读取 `src/api/schema/` 下的 11 份 OpenAPI 3.0.3 契约，现场生成结构正确的 mock 响应喂给视图。等后端就绪时，只需删掉一行 `installMock()`，视图代码零改动即可对接真实接口——因为请求路径、字段名、枚举取值全部对齐契约。

技术栈受 Node v16.20.2 硬约束锁定：Vite 4.5、Vue 3.4、vue-router 4、TypeScript 5.3.3、vue-tsc 1.8.27、@faker-js/faker 8.4.1、js-yaml 4。因 Node16 无法跑 MSW，改用自研的 `window.fetch` 拦截器实现契约 mock。

### 运行

```bash
cd frontend
npm install
npm run dev        # 开发服务器，默认 http://127.0.0.1:5178
npm run typecheck  # 仅类型检查（vue-tsc --noEmit）
npm run build      # 类型检查 + 产物构建到 dist/
npm run preview    # 本地预览构建产物
```

登录浮层默认展示。若要在无头浏览器或截图里跳过登录直达某屏，在 URL 上带 `?autologin=1`，再用 hash 路由定位视图，例如 `http://127.0.0.1:5178/?autologin=1#/project`。路由用 hash 模式（`createWebHashHistory`），便于静态托管免配 rewrite。

### 13 屏与路由

`src/router/index.ts` 一屏一路由，`meta.zh/en` 驱动顶栏面包屑，视图组件全部懒加载：

```
/dash          工作台驾驶舱          /projects   我的项目
/bigscreen     经费监督大屏（暗色）   /project/:id? 项目详情
/guide         申报指南              /expense    报销填单
/editor        申报书撰写            /claim      成果认领
/review        评审工作台            /transfer   转化看板
/procurement   采购与合同            /asset      资产与耗材台账
/portrait      PI 画像
```

侧栏导航项（`App.vue` 的 5 个分组）与这 13 个路由名一一对应。

### 契约 mock 的数据流

一条请求从视图到渲染，经过这样一条链路：

```
视图 api.get('/project/90001')
  → client.ts 拼 /api/v1 前缀 + Bearer + (写操作)Idempotency-Key，调 fetch
  → mock/index.ts 拦截 fetch，matchRoute('GET','/api/v1/project/90001')
  → schema/index.ts 命中模板路由 GET /project/{id}
  → 先查 curated override（overrides/project.ts）命中则直接返回
  → 未命中则 generator.ts 依 200 响应 schema 现场造数（faker zh_CN）
  → 统一 {code:0,message,data,traceId,timestamp} 包裹返回
  → client.ts 解包 data、code!==0 抛 ApiError
  → 视图渲染
```

`schema/index.ts` 用 `import.meta.glob('./*.yaml', { query: '?raw', eager: true })` 把 11 份契约以纯文本导入、js-yaml 解析，归并成一张 `routeIndex`（键为 `METHOD 模板路径`）。`matchRoute` 先做精确匹配，再对 `{var}` 段做通配匹配，因此 `/project/90001` 能命中 `/project/{id}`。响应 200 的 schema 采用 `allOf: [ApiResponse, {properties:{data: <真实结构>}}]` 惯例，`extractDataSchema` 负责从里面剥出 `data` 子 schema 再生成；列表端点则生成 `PageResult {list,total,page,size}`。

`generator.ts` 按 schema 的 `type/format/enum/example` 递归造数，并对字段名做启发式（`code`→业务单号、`name`→中文机构/项目名、金额→合理区间、日期→近区间），保证生成的中文数据「看起来像真的」。

### 接真实后端

视图与 client 完全同构于真实接口，切换只需一步：删掉 `src/main.ts` 里的 `installMock()` 调用（或改成按环境变量条件启用）。之后 `fetch` 走原生，打到 `API_PREFIX = '/api/v1'` 指向的网关。若真实网关前缀不同，改 `client.ts` 与 `schema/index.ts` 的 `API_PREFIX` 即可。

### 编写某个视图的定制数据（override）

纯随机生成适合「有就行」的屏，但驾驶舱、项目详情这类要讲故事的屏需要精心编排的数据。做法是在 `src/api/mock/overrides/` 放一个 `<view>.ts`，导出一个 `overrides` 映射：

```ts
export const overrides: Record<string, unknown> = {
  // 键 = "METHOD 模板路径"，与契约里的 path 完全一致
  'GET /project/{id}': (url: string) => ({ id: 90001, title: '…', healthScore: 64, /* … */ }),
  'GET /project/{id}/risk-warnings': [ /* 静态数组也可以 */ ],
}
```

`overrides/index.ts` 通过 `import.meta.glob('./*.ts', { eager: true })` 自动收集同目录所有文件的 `overrides` 命名导出并合并（跳过 `index.ts` 自身），因此新增一屏只要丢一个文件，零冲突、无需改任何共享文件。值可以是静态对象，也可以是 `(url) => data` 的函数——函数形态便于从 URL 里解析 `id` 等参数动态返回。override 优先级最高，命中即返回，不走生成器。

字段名务必对齐该模块契约 schema 与 `../design/*.ddl.sql`，用 camelCase（视图接口也按 camelCase 消费）。

### 目录结构

```
frontend/
  src/
    api/
      schema/        11 份 OpenAPI 契约 + index.ts（解析/路由索引/matchRoute）
      mock/
        index.ts     fetch 拦截器 + override 优先 + 生成兜底 + 统一包裹
        generator.ts schema 驱动的造数器
        overrides/   各视图定制数据（每屏一个文件，自动合并）
      client.ts      类型化请求封装（get/post/put/del/list + 解包 + 幂等键）
    views/           13 个视图组件
    router/          路由表
    styles/          prototype.css（沿用原型设计系统）+ app.css
    App.vue          外壳：侧栏/顶栏/登录浮层/toast
    main.ts          挂载 + installMock()
  scripts/           gen-stubs.mjs（脚手架）、原型 HTML 参考
```

视觉沿用原型的设计系统：Fraunces + IBM Plex Mono 字体、`--seal/--ai/--warn/--bad/--gold` 等 CSS 变量，以及 `card / kpi-strip / stat / alert-line / timeline / chip / bar / spark / hbar` 等类名，确保 SPA 与 `prototype/index.html` 观感一致。

### 已知取舍

11 份契约以 `?raw` 内联进产物，使主 chunk 约 3MB（gzip 约 1.1MB）。原型阶段可接受；若要上线，可把契约从前端产物中移除、或按路由 code-split、或改为构建期生成静态类型（`openapi-typescript` 已在 devDependencies 中备用）。
