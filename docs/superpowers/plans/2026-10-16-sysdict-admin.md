# Plan · 管理员数据字典维护（sys_dict 全生命周期）

> 2026-10-16 · 依据 PRD 2.8「数据字典管理」+ design/00-common.sql · 目标：R-ADMIN 在系统内统一维护所有字典信息，业务下拉全部字典化，消灭硬编码。

## 一、现状盘点（改动依据）

### 1.1 设计已有、实现缺位
| 层 | 现状 |
|---|---|
| PRD 2.8 | 所有下拉选项/类型枚举/科目编码一律走数据字典 `sys_dict`，由 **R-ADMIN** 维护，**禁止硬编码**；字典项支持多语言、生效时段、排序 |
| design/00-common.sql | `sys_dict`（tenant+code 唯一）+ `sys_dict_item`（item_code/label、树形 parent_id、扩展属性 ext_json、排序 sort_no、多语言 i18n_json、生效期 effective_from/to、active 开关）已完整定义 |
| migration 000001 | 两张表**已建**（含 uk_dict_code、uk_dict_item 部分唯一索引），但**零种子数据** |
| 后端 | **无任何端点**（全仓 grep sys_dict 零命中）；sysadmin 模块仅有 users/roles CRUD |
| 12-U 契约 | 无 dict 端点定义 |
| 前端 | 无字典管理页；admin 组已有 `/admin/users`、`/admin/roles` 两个路由 + 菜单项可参照 |

### 1.2 现存"字典类"数据散落两处（硬编码重灾区）
**A. 前端硬编码枚举（本期字典化的直接对象）**
| 位置 | 内容 |
|---|---|
| `GuideView.vue` TYPES | 项目类型 NSFC/KJBP/ZIGE/PROV/HENGXIANG → label |
| `OutputView.vue` / `ClaimView.vue` SOURCE_TEXT | 成果来源（期刊/会议/专利…） |
| `ActivityView.vue` TYPE_LABEL | 学术活动类型 CONFERENCE/LECTURE/SEMINAR/TRAINING/OTHER |
| `ExpenseView.vue` PAY_METHODS | 支付方式 |

**B. 专表维护型（业务属性强、已有独立 CRUD 端点，本期不并入）**
- F_SUBJECT 科目树（/subjects CRUD 已有）、E_PROJECT_CATEGORY、R_JOURNAL_SOURCE/R_JOURNAL_LEVEL、R_AGENCY、F_WARN_CONFIG、sys_legal_entity

### 1.3 权限现状
- policy.csv：R-ADMIN 已有 `/api/v1/*` 全通配读写 → **管理端点零新增策略**
- 全员读取端点（业务页拉下拉）需新增规则：所有已认证角色 `GET /api/v1/dicts/*`

## 二、方案

**管理端 + 消费端两层**：R-ADMIN 维护（/admin/dicts CRUD）；所有登录用户经公开只读端点（/dicts/{code}）拉取下拉数据；前端 `useDict()` composable 替换硬编码。

### Phase 0 · 契约先行（12-U openapi）
- `POST/GET /admin/dicts`（keyword 分页）、`GET/PUT/DELETE /admin/dicts/{dictId}`
- `POST /admin/dicts/{dictId}/items`、`PUT/DELETE /admin/dicts/{dictId}/items/{itemId}`、`PUT .../items/{itemId}/sort`
- 全员只读：`GET /dicts/{code}`（返回字典 + active 条目树，带 cache 头）
- Schema：`Dict`、`DictItem`（含 ext_json→`ext` object、i18n_json→`i18n`、effective_from/to、sort_no、active、parent_id）
- 提交点：契约文件同步（含 409 冲突响应：code/item_code 唯一索引）

### Phase 1 · 后端（TDD，sysadmin 模块内）
1. `db/schema/sys_schema.sql` 摘录 `sys_dict`/`sys_dict_item` 两表 CREATE（sqlc 编译期解析用，沿用"裁剪 schema、运行时打真库"既定模式）
2. `db/query_sys/u_dict.sql`：
   - `ListDicts`（keyword ILIKE code/name，分页）、`GetDict`、`GetDictByCode`
   - `UpsertDict`（按 tenant+code，ON CONFLICT 与 uk_dict_code 一致）
   - `SoftDeleteDict`（deleted=1，连带 items 随读随隐）
   - `ListItems`（dict_id，active 过滤，sort_no ASC, id ASC）、`UpsertItem`（dict_id+item_code+COALESCE(effective_from,'1970-01-01') 冲突更新）、`SetItemActive`、`SortItems`（批量 sort_no）、`DeleteItem`
3. `sqlc.yaml` U 块：rename sys_dict→Dict、sys_dict_item→DictItem；overrides 时间戳→time.Time、DATE 生效期→pgtype.Date 指针
4. `handler.go` + `routes.go`：管理端 8 端点（写路由仅 R-ADMIN——通配已覆盖）+ 全员读 `/dicts/:code`
5. `policy.csv` 追加：`p, R-STAFF ... /api/v1/dicts/*, GET`（各角色读规则，参照 T8/T20 写法，含子路径）
6. 测试（handler_test + contract_test）：
   - CRUD 闭环、uk_dict_item 冲突（同 dict 同 item_code 同生效期 → 409）
   - 越权：R-STAFF 调 /admin/dicts 写 → 403；读 /dicts/{code} → 200
   - 生效期过滤：effective_to < today 的条目不出现在公开端点
   - 契约校验（oapi.Validate）

### Phase 2 · 种子数据（migration 000013_dict_seed）
把 1.2-A 的硬编码值迁入字典（`INSERT ... ON CONFLICT DO NOTHING` 幂等）：
| dict code | items（来自前端硬编码） |
|---|---|
| project_type | NSFC/KJBP/ZIGE/PROV/HENGXIANG + 中文 label + ext_json（icon、color） |
| output_source | 期刊论文/会议论文/专利/软件著作权/著作… |
| activity_type | CONFERENCE/LECTURE/SEMINAR/TRAINING/OTHER |
| pay_method | 公务卡转账（默认）/对公转账/现金/备用金 |
| expense_type / asset_category / journal_level | 预留（本期可只建字典骨架） |

### Phase 3 · 前端
1. `views/admin/DictsView.vue`：左侧字典列表（新增/编辑 code/name/remark/软删）+ 右侧条目表格（增/改/停用/上下移排序/生效期区间/ext_json 高级 JSON 编辑框）；复用 UsersView 的 drawer+tbl 样式模式
2. 路由 `/admin/dicts`（roles: ['R-ADMIN']）+ App.vue 菜单「字典管理」（系统管理组，⚑ 同款）
3. `composables/useDict.ts`：`useDict(code)` → `api.get('/dicts/'+code)` + 模块级 Map 缓存 + `items.value`（active 过滤）+ `labelOf(itemCode)`；字典 404/空时 **fallback 到原硬编码数组**（防空下拉回归）
4. 替换硬编码：GuideView TYPES、OutputView/ClaimView SOURCE_TEXT、ActivityView TYPE_LABEL、ExpenseView PAY_METHODS → useDict 驱动（const 保留作 fallback）

### Phase 4 · 验证与交付
- 后端 `-p 1` 全量回归；前端 vue-tsc + build
- Docker 重建 backend+frontend → headless 冒烟：
  1. admin 登录 → /admin/dicts → 建/改/停用一个测试字典 → 删除
  2. staff 登录 → 申报指南页类型筛选下拉来自字典（改字典 label 后页面标签联动）
  3. R-STAFF 直访 /admin/dicts → 403/路由守卫拦截
- commit（develop）+ memory 记录

## 三、验收标准（对齐 PRD 2.9）
1. **功能正确性**：字典/条目 CRUD、排序、生效期过滤、公开读取缓存全通；同 code 重建返回 409
2. **权限隔离**：仅 R-ADMIN 可写；其它角色只能 GET /dicts/{code}；跨租户数据不可见（查询恒带 tenant_id）
3. **性能**：列表 < 500ms（两表数据量小，idx 足够）
4. **审计留痕**：字典写操作走 sys_audit_log（沿用 sysadmin 现有 Log 模式，如已接）

## 四、边界与风险
| 项 | 决策 |
|---|---|
| DB CHECK 状态机枚举（312 处 `status CHECK IN (...)`） | **不迁**——那是流程状态机不是数据字典 |
| 专表（F_SUBJECT/R_JOURNAL_*/R_AGENCY…） | 本期不并入统一字典（业务字段太强、已有维护端点）；后续可评估经 ext_json/视图归一 |
| i18n_json | 本期只存取不消费（界面固定中文） |
| 树形 parent_id | 表结构支持、API 返回 tree；管理界面本期做平铺+父级选择，拖拽树编辑后续迭代 |
| 下拉替换回归风险 | useDict 强制 fallback 原硬编码 + seed 迁移同 PR，保证字典缺失时 UI 不空 |
| uk_dict_item ON CONFLICT | 冲突目标须写全表达式 `(dict_id, item_code, COALESCE(effective_from, DATE '1970-01-01'))`，与索引定义逐字一致，否则 PG 报 no matching constraint |

## 五、工作量估算
- 后端：schema 摘录 + u_dict.sql + handler/mapper/routes + 测试 ≈ 6 文件
- 前端：DictsView + useDict + 4 视图替换 + 路由/菜单 ≈ 7 文件
- 种子：1 migration + down
