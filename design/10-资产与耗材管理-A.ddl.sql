-- =============================================================================
-- 10-资产与耗材管理-A.ddl.sql · 模块 A（Asset & Consumable）建表脚本
-- 版本 v1.1 · 2026-10-13
-- 方言：PostgreSQL 15（默认）
-- 上游：design/README.md §2/§4/§5；PRD/10-资产与耗材管理.md §5.1
-- 单号前缀：资产卡 AST、处置单 DSP（见 00-common.sql seq_prefix_registry，per_entity=TRUE 按法人分号段）
--
-- ┌─ 信创达梦差异注记（design/README.md §2.4，达梦部署时按此替换）──────────────┐
-- │ 自增主键  GENERATED ALWAYS AS IDENTITY → IDENTITY(1,1)                      │
-- │ 时间戳    TIMESTAMPTZ → TIMESTAMP WITH TIME ZONE                            │
-- │ 布尔      BOOLEAN → SMALLINT（0/1）；本脚本 share_flag/open_flag/is_hazard   │
-- │           /posted 达梦下改用 SMALLINT CHECK (0,1)                            │
-- │ JSON      JSONB → CLOB/VARCHAR 存 JSON 文本 + 应用层解析                      │
-- │ 部分唯一索引 CREATE UNIQUE INDEX ... WHERE deleted=0                          │
-- │           → 达梦用普通唯一索引 + (tenant_id,code,deleted) 复合键替代          │
-- │ 枚举      统一 VARCHAR + CHECK (IN (...))，不用原生 ENUM，便于灰度扩值        │
-- │ 可配枚举  asset_type/depr_method/source_type/category/hazard_level/method     │
-- │           取值以 sys_dict 为准（PRD 2.8 禁止硬编码），CHECK 仅为基线守卫        │
-- └────────────────────────────────────────────────────────────────────────────┘
--
-- 治理列：A 模块所有业务表均携带 legal_entity_id / security_level（v1.1，README §2.1）；
--         折旧/资产表 A_ASSET / A_DEPRECIATION 另携带 policy_pack_id（折旧政策快照，可复算）。
-- 外键：同模块物理外键 REFERENCES；跨模块（E_PROJECT/F_EXPENSE/G_CONTRACT/sys_policy_pack）
--       仅以 *_id 逻辑外键注释表达，不建物理外键（微服务库隔离，一致性走事件，README §2.3/§3.1）。
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1) A_ASSET 资产卡（固定资产 / 无形资产台账；单号 AST-年-序）
-- -----------------------------------------------------------------------------
CREATE TABLE A_ASSET (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            VARCHAR(64)  NOT NULL,              -- 资产编号 AST-{yyyy}-{seq6}（统一编号中心，按法人分号段）
  tenant_id       BIGINT       NOT NULL,              -- 多租户隔离键（总院法人边界）
  legal_entity_id BIGINT       NOT NULL,              -- 法人细分（PRD 2.12；主责法人建卡）
  security_level  VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                  CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),  -- 涉密资产（PRD 2.13）
  policy_pack_id  BIGINT,                             -- 命中折旧政策制度包快照（逻辑引用 sys_policy_pack.id，可复算）

  asset_type      VARCHAR(16)  NOT NULL
                  CHECK (asset_type IN ('FIXED','INTANGIBLE')),   -- 固定资产/无形资产（走字典 asset_type）
  category_code   VARCHAR(64)  NOT NULL,              -- 资产分类字典编码（逻辑引用 sys_dict_item：asset_category 树）
  name            VARCHAR(256) NOT NULL,              -- 资产名称
  brand           VARCHAR(128),                        -- 品牌
  model           VARCHAR(128),                        -- 型号
  serial_no       VARCHAR(128),                        -- 出厂序列号（一物一码，A-04 条码/RFID 关联键）

  value           NUMERIC(18,2) NOT NULL DEFAULT 0,   -- 入账原值（元）
  purchase_date   DATE,                               -- 购置日期
  in_date         DATE,                               -- 入账/启用日期
  depr_method     VARCHAR(16)  NOT NULL DEFAULT 'STRAIGHT_LINE'
                  CHECK (depr_method IN ('STRAIGHT_LINE','WORKLOAD','ACCELERATED','NONE')), -- 直线/工作量/加速/不计提
  depr_years      SMALLINT     CHECK (depr_years IS NULL OR depr_years BETWEEN 0 AND 100),   -- 折旧年限
  depr_accum      NUMERIC(18,2) NOT NULL DEFAULT 0,   -- 累计折旧
  net_value       NUMERIC(18,2) NOT NULL DEFAULT 0,   -- 净值 = value - depr_accum（生成/应用维护）

  custodian_id    BIGINT,                             -- 责任人 user_id（逻辑引用 sys_user.id）
  dept_id         BIGINT,                             -- 存放部门（逻辑引用 sys_org.id）
  location        VARCHAR(256),                       -- 存放地点
  source_type     VARCHAR(16)  NOT NULL DEFAULT 'PURCHASE'
                  CHECK (source_type IN ('PURCHASE','SELF_DEV','DONATION','TRANSFER')), -- 采购/自研/捐赠/调拨
  source_ref      BIGINT,                             -- 来源引用（跨模块逻辑引用 G_CONTRACT.id / 订单/验收单）
  project_id      BIGINT,                             -- 形成/占用项目，成本归属（跨模块逻辑引用 E_PROJECT.id）

  usage_rate      NUMERIC(5,4),                        -- 使用率 0~1（大型仪器共享 A-13）
  share_flag      BOOLEAN      NOT NULL DEFAULT FALSE, -- 是否纳入共享台账
  open_flag       BOOLEAN      NOT NULL DEFAULT FALSE, -- 是否对外开放共享

  status          VARCHAR(32)  NOT NULL DEFAULT 'PENDING_RECEIPT'
                  CHECK (status IN ('PENDING_RECEIPT','IN_USE','IDLE','UNDER_MAINT','TRANSFERRING','PENDING_DISPOSE','DISPOSED')),
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  creator_id      BIGINT       NOT NULL,
  modifier_id     BIGINT,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT
);
CREATE UNIQUE INDEX uk_asset_code     ON A_ASSET(tenant_id, code) WHERE deleted = 0;              -- 部分唯一（软删后编号不复用）
CREATE INDEX        idx_asset_tenant ON A_ASSET(tenant_id, legal_entity_id, status);              -- 查询主路径
CREATE INDEX        idx_asset_proj   ON A_ASSET(project_id);                                       -- 成本归属
CREATE INDEX        idx_asset_custd  ON A_ASSET(custodian_id);                                     -- 名下资产
CREATE INDEX        idx_asset_dept   ON A_ASSET(dept_id);                                          -- 存放部门
CREATE INDEX        idx_asset_serial ON A_ASSET(tenant_id, serial_no);                            -- 一物一码扫码/盘点比对
CREATE INDEX        idx_asset_cat    ON A_ASSET(tenant_id, category_code);                        -- 分类统计/重复购置识别

COMMENT ON TABLE  A_ASSET                 IS '资产卡台账（固定/无形资产，单号 AST-年-序），资产全生命周期主表';
COMMENT ON COLUMN A_ASSET.code            IS '资产编号，AST-{yyyy}-{seq6}，统一编号中心按法人分号段分配';
COMMENT ON COLUMN A_ASSET.legal_entity_id IS '主责法人；跨法人在使用法人登记领用（README 2.12）';
COMMENT ON COLUMN A_ASSET.security_level  IS '密级；>=SECRET 为涉密资产，仅涉密网登记与查看（联动 11）';
COMMENT ON COLUMN A_ASSET.policy_pack_id  IS '命中的折旧政策制度包快照 id，用于按月折旧复算与审计';
COMMENT ON COLUMN A_ASSET.asset_type      IS 'FIXED=固定资产 / INTANGIBLE=无形资产';
COMMENT ON COLUMN A_ASSET.category_code   IS '资产分类字典编码（sys_dict_item:asset_category，树形，可扩）';
COMMENT ON COLUMN A_ASSET.value           IS '入账原值（元，NUMERIC(18,2)）；缺失则整卡置 PENDING_RECEIPT 待确认';
COMMENT ON COLUMN A_ASSET.depr_method     IS '折旧方法：STRAIGHT_LINE 直线/WORKLOAD 工作量/ACCELERATED 加速/NONE 不计提';
COMMENT ON COLUMN A_ASSET.depr_accum      IS '累计折旧，由 A_DEPRECIATION 按月汇总回写';
COMMENT ON COLUMN A_ASSET.net_value       IS '净值 = value - depr_accum';
COMMENT ON COLUMN A_ASSET.usage_rate      IS '使用率(0~1)，来自 A-13 机时登记，供闲置/重复购置看板';
COMMENT ON COLUMN A_ASSET.source_ref      IS '来源单据引用（跨模块逻辑外键：G_CONTRACT/验收单），不建物理外键';
COMMENT ON COLUMN A_ASSET.project_id      IS '形成/占用项目（跨模块逻辑外键 E_PROJECT.id）';
COMMENT ON COLUMN A_ASSET.status          IS 'PENDING_RECEIPT 待验收/IN_USE 在用/IDLE 闲置/UNDER_MAINT 维修/TRANSFERRING 调拨中/PENDING_DISPOSE 待处置/DISPOSED 已处置';


-- -----------------------------------------------------------------------------
-- 2) A_CONSUMABLE 耗材/试剂库存（批次+效期+危化；sku 为业务主键）
-- -----------------------------------------------------------------------------
CREATE TABLE A_CONSUMABLE (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            VARCHAR(64)  NOT NULL,              -- 库存记录编号（内部编号中心）
  tenant_id       BIGINT       NOT NULL,
  legal_entity_id BIGINT       NOT NULL,
  security_level  VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                  CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),

  sku             VARCHAR(64)  NOT NULL,              -- 物料主编码（跨模块登记表被引列名 ref_sku）
  name            VARCHAR(256) NOT NULL,
  category        VARCHAR(32)  NOT NULL
                  CHECK (category IN ('REAGENT','CONSUMABLE','COMPONENT','OFFICE')), -- 试剂/耗材/元器件/办公（走字典 consumable_category）
  is_hazard       BOOLEAN      NOT NULL DEFAULT FALSE,-- 危化品标识（A-08）
  hazard_level    VARCHAR(16),                        -- 危化管理级别（走字典 hazard_level；管制类触发硬拦截）
  msds_url        VARCHAR(512),                       -- 安全技术说明书 MSDS 文档地址（对象存储）

  stock_qty       NUMERIC(18,3) NOT NULL DEFAULT 0,   -- 现存量（数量 NUMERIC(18,3)）
  unit            VARCHAR(16),                        -- 计量单位（瓶/kg/mL…）
  batch_no        VARCHAR(64),                        -- 批次号（效期/追溯/FIFO 依据）
  produce_date    DATE,                               -- 生产日期
  expire_date     DATE,                               -- 有效期至（效期预警 A-16）
  safe_stock      NUMERIC(18,3),                       -- 安全库存水位（规则引擎，低于则 LOW_STOCK）
  location        VARCHAR(256),                       -- 存放位置（危化专区双锁）
  custodian_id    BIGINT,                             -- 库管员 user_id（逻辑引用 sys_user.id）

  status          VARCHAR(32)  NOT NULL DEFAULT 'IN_STOCK'
                  CHECK (status IN ('IN_STOCK','LOW_STOCK','NEAR_EXPIRY','EXPIRED','STAGNANT')),
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  creator_id      BIGINT       NOT NULL,
  modifier_id     BIGINT,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT
);
CREATE UNIQUE INDEX uk_consumable_code ON A_CONSUMABLE(tenant_id, code) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_consumable_sku  ON A_CONSUMABLE(tenant_id, batch_no, sku) WHERE deleted = 0; -- 同租户同批次同 SKU 唯一库存记录
CREATE INDEX        idx_consumable_tenant ON A_CONSUMABLE(tenant_id, legal_entity_id, status);
CREATE INDEX        idx_consumable_expiry ON A_CONSUMABLE(sku, expire_date);                         -- 效期扫描（临期/过期批处理）
CREATE INDEX        idx_consumable_hazard ON A_CONSUMABLE(tenant_id, is_hazard);                      -- 危化专区检索

COMMENT ON TABLE  A_CONSUMABLE             IS '耗材/试剂库存（批次+效期+危化），SKU 维度库存台账';
COMMENT ON COLUMN A_CONSUMABLE.sku         IS '物料主编码；A_STOCK_TXN.ref_sku 以 (tenant_id,batch_no,sku) 定位库存';
COMMENT ON COLUMN A_CONSUMABLE.is_hazard   IS '危化品：出库领用强制双人双锁+双人确认（A-08）';
COMMENT ON COLUMN A_CONSUMABLE.hazard_level IS '危化管理级别；管制类超额/单锁硬拦截并告警安全管理员';
COMMENT ON COLUMN A_CONSUMABLE.safe_stock  IS '安全库存水位，由规则引擎（制度包）配置，驱动 LOW_STOCK';
COMMENT ON COLUMN A_CONSUMABLE.expire_date IS '有效期；过期批次自动冻结不可领用，走危废/报废处置';
COMMENT ON COLUMN A_CONSUMABLE.status      IS 'IN_STOCK 在库/LOW_STOCK 低库存/NEAR_EXPIRY 临期/EXPIRED 过期/STAGNANT 呆滞';


-- -----------------------------------------------------------------------------
-- 3) A_STOCK_TXN 出入库/领用流水（不可篡改台账，记录余额快照）
-- -----------------------------------------------------------------------------
CREATE TABLE A_STOCK_TXN (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64)  NOT NULL,             -- 流水编号（领用单等，内部编号中心）
  tenant_id        BIGINT       NOT NULL,
  legal_entity_id  BIGINT       NOT NULL,
  security_level   VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                   CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),

  type             VARCHAR(24)  NOT NULL
                   CHECK (type IN ('STOCK_IN','STOCK_OUT','REQUISITION','RETURN','RETURN_TO_STOCK','HAZARD_DISPOSE','COUNT_GAIN','COUNT_LOSS')),
                                                          -- 入库/出库/领用/归还/退库/危废处置/盘盈/盘亏（走字典 stock_txn_type）
  ref_asset_id     BIGINT,                              -- 资产流水：同模块物理外键 A_ASSET(id)
  ref_sku          VARCHAR(64),                          -- 耗材流水：定位 A_CONSUMABLE（逻辑引用 sku+batch_no）
  ref_batch_no     VARCHAR(64),                          -- 耗材批次（效期/FIFO 校验）
  qty              NUMERIC(18,3) NOT NULL,              -- 数量（正/负按方向由 type 决定）
  amount           NUMERIC(18,2),                       -- 金额（元）

  project_id       BIGINT,                              -- 领用归属项目（跨模块逻辑引用 E_PROJECT.id）
  operator_id      BIGINT       NOT NULL,               -- 经办/操作人 user_id
  double_confirm_by BIGINT,                             -- 危化第二确认人 user_id（A-08 双人双锁，管制类必填）
  related_expense_id BIGINT,                            -- 关联报销/经费（跨模块逻辑引用 F_EXPENSE.id）
  txn_time         TIMESTAMPTZ  NOT NULL DEFAULT now(), -- 发生时间
  balance_after    NUMERIC(18,3),                       -- 交易后余额快照（对账/追溯）
  fifo_exempt      BOOLEAN      NOT NULL DEFAULT FALSE, -- FIFO 违反授权豁免留痕（A-07/§11）

  status           VARCHAR(32)  NOT NULL DEFAULT 'ISSUED'
                   CHECK (status IN ('REQUESTED','DOUBLE_CONFIRM','ISSUED')),  -- 领用状态机 token（README §4）
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,

  CONSTRAINT fk_stocktxn_asset FOREIGN KEY (ref_asset_id) REFERENCES A_ASSET(id)
);
CREATE UNIQUE INDEX uk_stocktxn_code ON A_STOCK_TXN(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_stocktxn_tenant ON A_STOCK_TXN(tenant_id, legal_entity_id, status);
CREATE INDEX idx_stocktxn_asset  ON A_STOCK_TXN(ref_asset_id);
CREATE INDEX idx_stocktxn_sku    ON A_STOCK_TXN(tenant_id, ref_sku, ref_batch_no);
CREATE INDEX idx_stocktxn_proj   ON A_STOCK_TXN(project_id);
CREATE INDEX idx_stocktxn_time   ON A_STOCK_TXN(tenant_id, txn_time);

COMMENT ON TABLE  A_STOCK_TXN                IS '资产/耗材出入库与领用流水，账实一致与追溯的明细底稿';
COMMENT ON COLUMN A_STOCK_TXN.type           IS 'STOCK_IN 入库/STOCK_OUT 出库/REQUISITION 领用/RETURN 归还/RETURN_TO_STOCK 退库/HAZARD_DISPOSE 危废处置/COUNT_GAIN 盘盈/COUNT_LOSS 盘亏';
COMMENT ON COLUMN A_STOCK_TXN.ref_asset_id   IS '资产流水关联 A_ASSET.id（同模块物理外键）';
COMMENT ON COLUMN A_STOCK_TXN.ref_sku        IS '耗材流水关联 A_CONSUMABLE.sku（+ ref_batch_no 定位批次）';
COMMENT ON COLUMN A_STOCK_TXN.double_confirm_by IS '危化品第二确认人；管制类缺失则拒绝出库（双人双锁不可绕过）';
COMMENT ON COLUMN A_STOCK_TXN.related_expense_id IS '关联费用单据（跨模块逻辑外键 F_EXPENSE.id）';
COMMENT ON COLUMN A_STOCK_TXN.balance_after  IS '本次交易后库存余额快照';
COMMENT ON COLUMN A_STOCK_TXN.fifo_exempt    IS '未按 FIFO 出库时须授权豁免并留痕';
COMMENT ON COLUMN A_STOCK_TXN.status         IS '领用状态机：REQUESTED 领用申请/DOUBLE_CONFIRM 双人确认/ISSUED 已出库';


-- -----------------------------------------------------------------------------
-- 4) A_DEPRECIATION 折旧记录（按月计提；携带 policy_pack_id 复算；(asset_id,period) 唯一）
-- -----------------------------------------------------------------------------
CREATE TABLE A_DEPRECIATION (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64)  NOT NULL,              -- 折旧记录编号
  tenant_id        BIGINT       NOT NULL,
  legal_entity_id  BIGINT       NOT NULL,
  security_level   VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                   CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  policy_pack_id   BIGINT,                            -- 本次计提所用折旧政策快照（逻辑引用 sys_policy_pack.id，可复算）

  asset_id         BIGINT       NOT NULL,              -- 资产：同模块物理外键 A_ASSET(id)
  period           VARCHAR(7)   NOT NULL,              -- 计提期间 YYYY-MM
  depr_amount      NUMERIC(18,2) NOT NULL,             -- 本期折旧额（元）
  alloc_project_ids JSONB       NOT NULL DEFAULT '[]', -- 分摊明细 [{project_id,ratio,amount}]，成本分摊依据（A-12）
  voucher_id       BIGINT,                            -- 生成财务凭证（跨模块逻辑引用 F，凭证/F-11）
  posted           SMALLINT     NOT NULL DEFAULT 0     -- 是否已过账（0 未过账 / 1 已过账）
                   CHECK (posted IN (0,1)),

  status           VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                   CHECK (status IN ('DRAFT','CALCULATED','POSTED','REVERSED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,

  CONSTRAINT fk_depreciation_asset FOREIGN KEY (asset_id) REFERENCES A_ASSET(id),
  CONSTRAINT uk_depr_asset_period  UNIQUE (asset_id, period)   -- 同一资产同月只计提一次（幂等重算基础）
);
CREATE UNIQUE INDEX uk_depr_code   ON A_DEPRECIATION(tenant_id, code) WHERE deleted = 0;
CREATE INDEX        idx_depr_tenant ON A_DEPRECIATION(tenant_id, legal_entity_id, status);
CREATE INDEX        idx_depr_period ON A_DEPRECIATION(tenant_id, period);

COMMENT ON TABLE  A_DEPRECIATION                IS '资产按月折旧计提记录，是财务凭证与项目成本分摊的数据源';
COMMENT ON COLUMN A_DEPRECIATION.policy_pack_id IS '计提所用折旧政策快照 id，支持审计复算（README 2.10）';
COMMENT ON COLUMN A_DEPRECIATION.period         IS '计提期间 YYYY-MM；与 asset_id 组合物理唯一，防止重复计提';
COMMENT ON COLUMN A_DEPRECIATION.alloc_project_ids IS '分摊到项目的明细 JSON 数组：[{project_id,ratio,amount}]；跨法人按使用比例拆分避免重复计入';
COMMENT ON COLUMN A_DEPRECIATION.voucher_id     IS '回调财务生成的凭证 id（跨模块逻辑外键 F-11）';
COMMENT ON COLUMN A_DEPRECIATION.posted         IS '过账标志（0/1，达梦 SMALLINT）';


-- -----------------------------------------------------------------------------
-- 5) A_DISPOSAL 资产处置单（报废/变卖/转让/销毁；单号 DSP-年-序）
-- -----------------------------------------------------------------------------
CREATE TABLE A_DISPOSAL (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64)  NOT NULL,             -- 处置单号 DSP-{yyyy}-{seq6}（按法人分号段）
  tenant_id        BIGINT       NOT NULL,
  legal_entity_id  BIGINT       NOT NULL,
  security_level   VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                   CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),

  asset_id         BIGINT       NOT NULL,             -- 处置对象：同模块物理外键 A_ASSET(id)
  method           VARCHAR(16)  NOT NULL
                   CHECK (method IN ('SCRAP','SELL','TRANSFER','DESTROY')),  -- 报废/变卖/转让/销毁（走字典 disposal_method）
  appraisal        JSONB,                             -- 技术鉴定意见 {conclusion,expert_ids,attachment_ref,opinion}
  residual_value   NUMERIC(18,2),                     -- 残值（元）；>原值或<0 转财务复核（A-10）
  approval_chain   JSONB        NOT NULL DEFAULT '[]', -- 审批链 [{node,approver_id,action,at,comment}] 全程留痕
  related_voucher  BIGINT,                            -- 残值入账凭证（跨模块逻辑引用 F）
  archive_ref      VARCHAR(64),                       -- 归档引用（跨模块逻辑引用 E_PROJECT_DOC/档案 E-05）

  status           VARCHAR(32)  NOT NULL DEFAULT 'APPLIED'
                   CHECK (status IN ('APPLIED','APPRAISED','APPROVED','EXECUTING','BOOKED','ARCHIVED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,

  CONSTRAINT fk_disposal_asset FOREIGN KEY (asset_id) REFERENCES A_ASSET(id)
);
CREATE UNIQUE INDEX uk_disposal_code  ON A_DISPOSAL(tenant_id, code) WHERE deleted = 0;
CREATE INDEX        idx_disposal_tenant ON A_DISPOSAL(tenant_id, legal_entity_id, status);
CREATE INDEX        idx_disposal_asset  ON A_DISPOSAL(asset_id);

COMMENT ON TABLE  A_DISPOSAL               IS '资产处置单（报废/变卖/转让/销毁），技术鉴定→审批→残值入账→归档（A-10）';
COMMENT ON COLUMN A_DISPOSAL.method        IS 'SCRAP 报废/SELL 变卖/TRANSFER 转让/DESTROY 销毁';
COMMENT ON COLUMN A_DISPOSAL.appraisal     IS '技术鉴定意见（JSONB）；进入 APPROVED 前须完成鉴定（APPRAISED）';
COMMENT ON COLUMN A_DISPOSAL.residual_value IS '残值；合理性校验：残值>资产原值或为负则转财务复核';
COMMENT ON COLUMN A_DISPOSAL.approval_chain IS '审批链留痕（JSONB 数组），支持审计追溯';
COMMENT ON COLUMN A_DISPOSAL.archive_ref   IS '档案封存引用（跨模块逻辑外键，E-05 项目归档/档案系统）';
COMMENT ON COLUMN A_DISPOSAL.status        IS 'APPLIED 申请/APPRAISED 鉴定/APPROVED 审批/EXECUTING 执行/BOOKED 入账/ARCHIVED 归档';
