# Passthrough 登记表 · Go 后端（M0）

**目的：** 记录 `design/*.openapi.yaml` 契约中**已声明但本轮未由真实 Go handler+store 实现**、由 `oapi.Passthrough`（gin `NoRoute` 兜底，见 `backend-go/internal/router.go:76`）依契约生成合规示例响应的端点，满足计划 `2026-10-14-project-lifecycle-expert-review-archive.md` 任务 5.3 与 DoD #1。

**判定口径：** 某契约 operation 视为 passthrough ⟺ 它出现在对应模块 `*.openapi.yaml` 的 `paths` 中，却**不在**对应 Go 模块 `routes.go` 的 `r.<VERB>(...)` 注册集合里（真实已注册路由因 gin 已命中而不进 `NoRoute`）。下表由 `design/02,04,15,16` 契约 `paths` 逐条与 `internal/modules/{project,output,expertreview,archive}/routes.go` 注册集合求差得出（非照抄计划初稿的示意表）。

> 注意：`NoRoute` 不经 `/api/v1` 分组中间件链，passthrough 响应不经过鉴权/幂等；M0 阶段可接受（仅返回契约一致的样例数据，不回写、不触库）。真实化这些端点时应改为在 `routes.go` 注册显式 handler。

---

## E · 项目过程管理（`design/02-项目过程管理-E.openapi.yaml`）

计算型 / 聚合型 DTO，规格 §3.2 明确本轮延后（依赖跨域聚合、趋势计算与健康度模型）。

| 方法 | 路径 | 类别 | 延后理由 |
|---|---|---|---|
| GET | `/project/{id}/health-score` | 计算型 DTO | 健康度评分需多维指标聚合 |
| GET | `/project/{id}/risk-warnings` | 聚合型 | 风险预警规则引擎未接 |
| POST | `/project/{id}/risk-warnings/{warningId}/ack` | 计算型动作 | 依附 risk-warnings，同上 |
| GET | `/project/{id}/archive-checklist` | 聚合型 | 归档清单需跨 O 域汇总 |
| POST | `/project/{id}/archive-checklist/validate` | 计算型动作 | 依附 archive-checklist |
| GET | `/project/{id}/trace` | 聚合型 | 全链路追溯视图，只读聚合 |

## R · 科研成果管理（`design/04-科研成果管理-R.openapi.yaml`）

AI 生成 / 去重 / 外部抓取 / 导出类，规格 §4.2 明确本轮保留 passthrough。

| 方法 | 路径 | 类别 | 延后理由 |
|---|---|---|---|
| POST | `/output/ai-fill` | AI | 依赖外部 LLM 服务 |
| POST | `/output/ai-dedup` | AI | 依赖相似度/向量服务 |
| GET | `/output/patents` | 外部抓取 | 专利数据源集成未接 |
| GET | `/output/{id}/metrics` | 聚合型 | 引用/被引等指标抓取延后 |
| POST | `/output/{id}/metrics` | 外部抓取 | 同上，触发刷新 |
| POST | `/output/export` | 导出 | 批量导出管线延后 |

> 计划初稿示意表写作 `/metrics/refresh-cited`；实际契约以 `/output/{id}/metrics`（GET 读 / POST 触发）建模，无 `refresh-cited` 路径。以契约为准登记。

## N · 专家与评审管理（`design/15-专家与评审管理-N.openapi.yaml`）

**无 passthrough。** 契约 19 个 operation 全部由 `internal/modules/expertreview/routes.go` 真实实现（专家 CRUD+状态、评审建单/取消/详情、抽取 draw、invite/accept/decline/start、scores、conclude 回写 E/R、fees）。

## O · 科研档案管理（`design/16-科研档案管理-O.openapi.yaml`）

**无 passthrough。** 契约 24 个 operation 全部由 `internal/modules/archive/routes.go` 真实实现（文档上传/下载/软删/全文检索/单读、案卷 CRUD+门类清单+摄取、提交/四性检测落库/入库/销毁状态机、借阅申请/审批/拒绝/归还）。

> 与 passthrough 不同的另一类兜底：O 的存储依赖端点（`POST /documents` 上传、`GET /documents/{id}/download` presign）在**宿主未配置 MinIO**（`RouterDeps.Storage == nil`）时，由 `Handler.guardStorage` 运行期返回 `code:50301`，**不是** passthrough（请求仍命中真实路由，只是判定存储不可用）。有 MinIO 时端到端可用。

---

## 校验复算方式

对每域，diff 契约 `paths` 的 `METHOD + 模板路径` 与 `routes.go` 的注册集合即可复现上表：

```bash
# 契约侧
python -c "import yaml;[print(V.upper(),P) for P,M in yaml.safe_load(open('design/02-项目过程管理-E.openapi.yaml',encoding='utf-8'))['paths'].items() for V in M if V.lower() in ('get','post','put','delete','patch')]"
# 注册侧
grep -nE "r\.(GET|POST|PUT|DELETE|PATCH)" backend-go/internal/modules/project/routes.go
```

差集应恰为上表所列 E:6 / R:6 / N:0 / O:0，无漏网业务端点。

## 结论（DoD #1）

E/R 的「真实化」类端点全部由真实 Go handler+store 提供；N/O 全域端点真实；上表 E/R 共 12 个计算/AI/导出/外部抓取端点保留 passthrough 兜底并在此登记。
