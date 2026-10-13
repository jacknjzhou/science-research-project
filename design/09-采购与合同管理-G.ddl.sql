-- =============================================================================
-- 09-采购与合同管理-G.ddl.sql · 模块 G（Procurement & Contract）建表脚本
-- 版本 v1.1 · 2026-10-13
-- 方言：PostgreSQL 15（信创达梦差异见 design/README.md §2.4，达梦部署时按此替换）
-- 上游：design/README.md §2 数据库约定 / §4 状态 token / §5 共享实体；PRD/09-采购与合同管理.md §5.1
-- 覆盖表：G_REQUISITION · G_SUPPLIER · G_BID · G_CONTRACT · G_CONTRACT_PAYMENT ·
--         G_ORDER · G_OUTSOURCE
--
-- 【信创达梦差异注记（本模块专用，顶部统一声明）】
--   1) 自增主键  PG: BIGINT GENERATED ALWAYS AS IDENTITY  →  达梦: BIGINT IDENTITY(1,1)
--   2) 时间戳    PG: TIMESTAMPTZ                          →  达梦: TIMESTAMP WITH TIME ZONE
--   3) 布尔      PG: BOOLEAN                              →  达梦: SMALLINT（0/1）；本模块 blacklist/outsource_flag
--                直接以 SMALLINT(0/1) 落地，两端一致
--   4) JSONB     PG: JSONB（qualification_json/bids_json/pay_terms_json/deliverables_json/
--                ai_parse_json/ai_risk_json 等）
--                →  达梦: CLOB/VARCHAR 存 JSON 文本 + 应用层解析；表达式索引改应用层维护
--   5) 部分唯一索引 CREATE UNIQUE INDEX ... WHERE deleted=0
--                →  达梦: 以普通唯一索引 + (tenant_id,code,deleted) 复合键替代
--   6) CHECK(col IN(...)) 枚举  PG/达梦一致，保持 VARCHAR+CHECK（便于灰度扩值，不建原生 ENUM）
--   7) 全文/向量检索  PG: pg_trgm/tsvector/pgvector  →  达梦: 应用层 ES / Milvus 独立服务
--
-- 【金额/时间/半结构化】金额一律 NUMERIC(18,2)（元）；比例/进度/置信度 NUMERIC(6,4)；
--   时间 TIMESTAMPTZ（落库 UTC，展示 Asia/Shanghai）；纯日期 DATE；半结构化 JSONB。
-- 【治理三列】G 模块所有表携带 legal_entity_id / security_level / policy_pack_id
--   （design/README.md §2.1 v1.1；PRD 2.12/2.13/2.10）。
-- 【跨模块引用】E_PROJECT(project_id) / F_SUBJECT(budget_subject_code) / F_EXPENSE(expense_id) /
--   E_ARCHIVE_CHECKLIST(archive_checklist_id) / sys_policy_pack(policy_pack_id) / sys_user(*_id 人员)
--   只存对方主键 id，不建物理外键（微服务库隔离，PRD §5 共享实体登记表）。
--   同模块内物理外键：G_BID/G_CONTRACT/G_ORDER→G_REQUISITION；G_CONTRACT/G_ORDER/G_OUTSOURCE→G_SUPPLIER；
--   G_CONTRACT_PAYMENT/G_OUTSOURCE→G_CONTRACT 等（见下 REFERENCES）。
-- 【单号前缀（PRD 2.11 注册表，取自统一编号中心 svc-numbering，作废不回收·重试幂等）】
--   采购申请 REQ · 采购订单 ORD · 供应商 SUP · 外协单位 SOSC · 合同 CON · 外协/分包合同 OSC。
-- =============================================================================


-- -----------------------------------------------------------------------------
-- G-01/G-02/G-03 · G_REQUISITION 采购申请（预算冻结 · 采购方式判定，携带制度包快照）
-- -----------------------------------------------------------------------------
CREATE TABLE G_REQUISITION (
  -- 通用列（design/README.md §2.1）
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                                -- REQ-年-序（统一编号中心分配）
  tenant_id         BIGINT       NOT NULL,
  legal_entity_id   BIGINT       NOT NULL,                      -- 主责法人（PRD 2.12）
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),  -- 涉密采购密级（PRD 2.13）
  policy_pack_id    BIGINT,                                     -- 采购方式判定所依据制度包快照（复算，PRD 2.10）
  status            VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','SUBMITTED','WAY_DECIDED','BIDDING','ORDERED','CANCELLED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列（PRD §5.1）
  project_id        BIGINT       NOT NULL,                      -- 逻辑引用 E_PROJECT(id)→02 E
  applicant_id      BIGINT       NOT NULL,                      -- 申请人 user_id（逻辑引用 sys_user）
  category          VARCHAR(16)  NOT NULL
                    CHECK (category IN ('设备','材料','试剂耗材','服务','软件','外协')),  -- 采购标的类别
  item_name         VARCHAR(256) NOT NULL,                      -- 采购标的名称
  spec              TEXT,                                       -- 技术参数/规格要求
  est_amount        NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 预算（估算）金额，触发方式判定
  budget_subject_code VARCHAR(64),                              -- 占用经费科目编码（逻辑引用 F_SUBJECT.subject_code→03 F）
  frozen_amount     NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 冻结金额（联动 F-10，超预算拦截、不允许负余额）
  purchase_way      VARCHAR(16)
                    CHECK (purchase_way IN ('公开招标','邀请招标','竞争性谈判','单一来源','询价','自行采购')),  -- G-03 判定结果
  way_basis_rule_id BIGINT                                      -- 命中的制度规则号（逻辑引用 sys_rule_hit，可解释）
);
CREATE UNIQUE INDEX uk_req_code ON G_REQUISITION(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_req_tenant_entity_status ON G_REQUISITION(tenant_id, legal_entity_id, status);
CREATE INDEX idx_req_project ON G_REQUISITION(project_id);
CREATE INDEX idx_req_applicant ON G_REQUISITION(tenant_id, applicant_id, status);
CREATE INDEX idx_req_security ON G_REQUISITION(tenant_id, security_level, status);
COMMENT ON TABLE  G_REQUISITION IS '采购申请（G-01/G-02/G-03）：预算冻结 + 采购方式判定结果落库，携带制度包快照供复算';
COMMENT ON COLUMN G_REQUISITION.category           IS '采购标的类别：设备/材料/试剂耗材/服务/软件/外协';
COMMENT ON COLUMN G_REQUISITION.frozen_amount      IS '提交时在对应经费科目冻结的额度，联动 F-10；驳回/废标释放';
COMMENT ON COLUMN G_REQUISITION.purchase_way       IS 'G-03 采购方式判定引擎输出（金额+经费性质+制度包），人不越权';
COMMENT ON COLUMN G_REQUISITION.way_basis_rule_id  IS '命中制度规则号，配合 policy_pack_id 使方式判定可解释、可复算';
COMMENT ON COLUMN G_REQUISITION.project_id         IS '逻辑引用 E_PROJECT(id)，跨模块只存 id，一致性走事件';
COMMENT ON COLUMN G_REQUISITION.budget_subject_code IS '逻辑引用 F_SUBJECT 科目编码，占用/冻结定位到科目';
COMMENT ON COLUMN G_REQUISITION.security_level     IS '涉密采购密级，参与涉密域读写过滤（PRD 2.13）';


-- -----------------------------------------------------------------------------
-- G-04/G-09 · G_SUPPLIER 供应商 / 外协单位库（资质证照、分级、黑名单、入库状态）
-- -----------------------------------------------------------------------------
CREATE TABLE G_SUPPLIER (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                                -- SUP-年-序=供应商 / SOSC-年-序=外协单位（前缀随 type 分流）
  tenant_id         BIGINT       NOT NULL,
  legal_entity_id   BIGINT       NOT NULL,                      -- 入库法人
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),  -- 涉密供应商资质密级
  policy_pack_id    BIGINT,                                     -- 资质审查规则制度包快照
  status            VARCHAR(32)  NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING','IN_LIBRARY','REJECTED','EXPIRED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列（PRD §5.1）
  name              VARCHAR(256) NOT NULL,                      -- 供应商/外协单位名称
  credit_code       VARCHAR(64),                                -- 统一社会信用代码（唯一去重键）
  type              VARCHAR(16)  NOT NULL DEFAULT '供应商'
                    CHECK (type IN ('供应商','外协单位','服务商')),  -- 主体类型（决定 code 前缀 SUP/SOSC）
  qualification_json JSONB,                                     -- 资质证照 ISO/CNAS/保密资质等 [{cert,no,issue,expire,url}]
  grade             VARCHAR(2)   NOT NULL DEFAULT 'C'
                    CHECK (grade IN ('A','B','C','D')),          -- 分级（A 优 ~ D 差）
  blacklist         SMALLINT     NOT NULL DEFAULT 0
                    CHECK (blacklist IN (0,1)),                 -- 是否黑名单（1=硬拦截，禁止参与任何新合同）
  review_status     VARCHAR(16)  NOT NULL DEFAULT 'PENDING'
                    CHECK (review_status IN ('PENDING','IN_LIBRARY','REJECTED','EXPIRED')),  -- 资质入库审查状态（对齐 status）
  expire_date       DATE                                         -- 资质到期日（到期自动置 EXPIRED，禁止新合同引用）
);
CREATE UNIQUE INDEX uk_sup_code ON G_SUPPLIER(tenant_id, code) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_sup_credit ON G_SUPPLIER(tenant_id, credit_code) WHERE deleted = 0 AND credit_code IS NOT NULL;
CREATE INDEX idx_sup_tenant_entity_status ON G_SUPPLIER(tenant_id, legal_entity_id, status);
CREATE INDEX idx_sup_type_status ON G_SUPPLIER(tenant_id, type, review_status);
CREATE INDEX idx_sup_blacklist ON G_SUPPLIER(tenant_id, blacklist);
CREATE INDEX idx_sup_expire ON G_SUPPLIER(expire_date);
COMMENT ON TABLE  G_SUPPLIER IS '供应商/外协单位库（G-04/G-09）：资质入库、分级、黑名单硬拦截、到期禁止新合同';
COMMENT ON COLUMN G_SUPPLIER.code            IS '单号前缀随 type 分流：供应商 SUP-年-序；外协单位 SOSC-年-序';
COMMENT ON COLUMN G_SUPPLIER.qualification_json IS '资质证照 JSONB：每项含证书号/机关/有效期/附件；供 svc-policy 校验到期与齐全度';
COMMENT ON COLUMN G_SUPPLIER.blacklist       IS '黑名单标记（0/1）；命中即禁止参与新合同/新招标，历史只读';
COMMENT ON COLUMN G_SUPPLIER.review_status   IS '资质入库状态，与 status 同源；到期任务自动置 EXPIRED';
COMMENT ON COLUMN G_SUPPLIER.expire_date     IS '最近一项资质到期日，过期后禁止被新合同引用（PRD 11）';


-- -----------------------------------------------------------------------------
-- G-05 · G_BID 招标/比价/询价记录（报价、评标、定标、公示、节资）
-- -----------------------------------------------------------------------------
CREATE TABLE G_BID (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                                -- 招标编号（沿用 REQ 关联，可扩展独立前缀）
  tenant_id         BIGINT       NOT NULL,
  legal_entity_id   BIGINT       NOT NULL,
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  policy_pack_id    BIGINT,                                     -- 评标办法/公示规则制度包快照
  status            VARCHAR(32)  NOT NULL DEFAULT 'PUBLICIZING'
                    CHECK (status IN ('PUBLICIZING','AWARDED','CHALLENGE')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列（PRD §5.1）
  requisition_id    BIGINT       NOT NULL REFERENCES G_REQUISITION(id),  -- 同模块物理外键（1:0..1）
  method            VARCHAR(16)  NOT NULL
                    CHECK (method IN ('公开招标','邀请招标','竞争性谈判','单一来源','询价')),  -- 招标方式（源自申请判定）
  publish_at        TIMESTAMPTZ,                                -- 发标时间
  bid_open_at       TIMESTAMPTZ,                                -- 开标时间
  award_at          TIMESTAMPTZ,                                -- 定标时间
  bids_json         JSONB,                                      -- 报价/评标明细 [{supplier_id,price,score,tech_eval,commercial_eval}]
  winner_supplier_id BIGINT      REFERENCES G_SUPPLIER(id),     -- 中标供应商（同模块物理外键）
  saving_amount     NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 节资金额（预算-中标价）
  winner_reason     TEXT,                                       -- 定标理由（审计可复算）
  publicity_status  VARCHAR(16)  NOT NULL DEFAULT 'PUBLICIZING'
                    CHECK (publicity_status IN ('PUBLICIZING','AWARDED','CHALLENGE'))  -- 公示状态（对齐 status）
);
CREATE UNIQUE INDEX uk_bid_code ON G_BID(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_bid_tenant_entity_status ON G_BID(tenant_id, legal_entity_id, status);
CREATE INDEX idx_bid_requisition ON G_BID(requisition_id);
CREATE INDEX idx_bid_winner ON G_BID(winner_supplier_id);
CREATE INDEX idx_bid_security ON G_BID(tenant_id, security_level, status);
COMMENT ON TABLE  G_BID IS '招标/比价/询价记录（G-05）：发标/开标/定标、报价评标明细、公示与质疑、节资统计';
COMMENT ON COLUMN G_BID.bids_json        IS '各家报价与评分明细（JSONB 数组），审计可逐笔复算评标过程';
COMMENT ON COLUMN G_BID.winner_supplier_id IS '中标供应商 id（同模块物理外键→G_SUPPLIER）';
COMMENT ON COLUMN G_BID.saving_amount    IS '节资金额=预算金额-中标价，供 G-16 看板节资率统计';
COMMENT ON COLUMN G_BID.publicity_status IS '公示状态：PUBLICIZING=公示中/AWARDED=已定标/CHALLENGE=质疑处理（对齐 status）';


-- -----------------------------------------------------------------------------
-- G-07/G-10/G-11/G-13/G-14 · G_CONTRACT 合同（统一：采购/外协分包/横向委托/技术服务）
-- -----------------------------------------------------------------------------
CREATE TABLE G_CONTRACT (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                                -- CON-年-序=采购/技术服务/横向 / OSC-年-序=外协分包
  tenant_id         BIGINT       NOT NULL,
  legal_entity_id   BIGINT       NOT NULL,                      -- 主责法人；参与法人只读（PRD 2.12/§11）
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),  -- 涉密合同仅涉密网（PRD 2.13）
  policy_pack_id    BIGINT,                                     -- 合同评审/条款红线判定制度包快照
  status            VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','REVIEW','TO_SIGN','ACTIVE','AMENDING','SETTLING','ARCHIVED','TERMINATED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列（PRD §5.1）
  requisition_id    BIGINT      REFERENCES G_REQUISITION(id),   -- 关联采购申请（可空·横向委托无前置申请）
  contract_type     VARCHAR(16) NOT NULL
                    CHECK (contract_type IN ('采购','外协分包','横向委托','技术服务','其他')),  -- 合同类型（外协分包→派生 G_OUTSOURCE）
  project_id        BIGINT,                                     -- 逻辑引用 E_PROJECT(id)→02 E
  supplier_id       BIGINT      REFERENCES G_SUPPLIER(id),      -- 相对方供应商/外协单位（同模块物理外键；须 IN_LIBRARY 且非黑名单）
  party_a           VARCHAR(256),                               -- 甲方
  party_b           VARCHAR(256),                               -- 乙方
  amount            NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 合同金额（付款累计上限基准，含变更）
  currency          VARCHAR(8)  NOT NULL DEFAULT 'CNY',         -- 币种
  pay_terms_json    JSONB,                                      -- 付款条款 [{phase:预付/到货/验收/质保,ratio,trigger}]
  deliverables_json JSONB,                                      -- 交付物清单
  sign_date         DATE,                                       -- 签署日期
  start_date        DATE,                                       -- 履行开始
  end_date          DATE,                                       -- 履行结束
  sign_method       VARCHAR(8)  CHECK (sign_method IN ('电子签','异地','纸质')),  -- 签署方式（联动 P-12；CA 不可用降级纸质）
  archive_checklist_id BIGINT,                                   -- 逻辑引用 E_ARCHIVE_CHECKLIST(id)→02 E（归档联动 E-15）
  ai_parse_json     JSONB,                                      -- G-13 AI 解析结果（逐字段来源+置信度，人工确认后落字段）
  ai_risk_json      JSONB                                       -- G-14 AI 风险提示（条款/风险类型/等级/建议/命中规则号）
);
CREATE UNIQUE INDEX uk_con_code ON G_CONTRACT(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_con_tenant_entity_status ON G_CONTRACT(tenant_id, legal_entity_id, status);
CREATE INDEX idx_con_project ON G_CONTRACT(project_id);
CREATE INDEX idx_con_supplier ON G_CONTRACT(supplier_id);
CREATE INDEX idx_con_requisition ON G_CONTRACT(requisition_id);
CREATE INDEX idx_con_type_status ON G_CONTRACT(tenant_id, contract_type, status);
CREATE INDEX idx_con_security ON G_CONTRACT(tenant_id, security_level, status);
COMMENT ON TABLE  G_CONTRACT IS '合同主表（G-07/G-10/G-11/G-13/G-14）：统一四类合同全生命周期 + AI 解析/风险';
COMMENT ON COLUMN G_CONTRACT.code             IS '单号前缀：CON=采购/技术服务/横向委托；OSC=外协分包合同';
COMMENT ON COLUMN G_CONTRACT.contract_type    IS '合同类型；外协分包派生 G_OUTSOURCE 台账，横向委托可无 requisition_id';
COMMENT ON COLUMN G_CONTRACT.supplier_id      IS '同模块物理外键→G_SUPPLIER；入库(IN_LIBRARY)且非黑名单方可签约';
COMMENT ON COLUMN G_CONTRACT.amount           IS '合同金额=付款计划累计硬上限（含变更 AMENDING 后调增），超出拦截';
COMMENT ON COLUMN G_CONTRACT.pay_terms_json   IS '付款条款数组，G-08 据此生成付款计划；关键项须人工确认后方生效';
COMMENT ON COLUMN G_CONTRACT.archive_checklist_id IS '逻辑引用 E_ARCHIVE_CHECKLIST(id)，归档联动 E-15';
COMMENT ON COLUMN G_CONTRACT.ai_parse_json    IS 'G-13 LLM 解析结果，附字段级置信度与来源；<0.85 标黄强制人工复核';
COMMENT ON COLUMN G_CONTRACT.ai_risk_json     IS 'G-14 风险卡片列表；高风险必须法务人工签意见，AI 不得单独放行';
COMMENT ON COLUMN G_CONTRACT.security_level   IS '涉密合同密级≥SECRET 仅涉密网可见，非涉密域访问拒绝并审计告警';


-- -----------------------------------------------------------------------------
-- G-08/G-09 · G_CONTRACT_PAYMENT 付款计划与执行（关联 F 报销/凭证、外拨标记）
-- -----------------------------------------------------------------------------
CREATE TABLE G_CONTRACT_PAYMENT (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                                -- 付款计划编号（沿用合同号+阶段序）
  tenant_id         BIGINT       NOT NULL,
  legal_entity_id   BIGINT       NOT NULL,
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  policy_pack_id    BIGINT,                                     -- 付款条款合规判定制度包快照
  status            VARCHAR(32)  NOT NULL DEFAULT 'PLANNED'
                    CHECK (status IN ('PLANNED','DUE','PAID','VOUCHER_SYNCED','CANCELLED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列（PRD §5.1）
  contract_id       BIGINT       NOT NULL REFERENCES G_CONTRACT(id),  -- 同模块物理外键（1:N）
  phase             VARCHAR(8)   NOT NULL
                    CHECK (phase IN ('预付','到货','验收','质保','进度','尾款')),  -- 付款阶段
  plan_amount       NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 计划付款金额
  plan_date         DATE,                                       -- 计划付款日期
  paid_amount       NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 实付金额（回调回填）
  pay_date          DATE,                                       -- 实付日期
  expense_id        BIGINT,                                     -- 逻辑引用 F_EXPENSE(id)→03 F（付款/报销单）
  voucher_status    VARCHAR(16)  NOT NULL DEFAULT 'PENDING'
                    CHECK (voucher_status IN ('PENDING','SUCCESS','FAILED','MANUAL')),  -- 凭证同步状态（→F-11）
  invoice_url       VARCHAR(512),                               -- 发票/收据附件（对象存储）
  outsource_flag    SMALLINT     NOT NULL DEFAULT 0
                    CHECK (outsource_flag IN (0,1))             -- 是否外拨（1=联动 F-22 外拨经费）
);
CREATE UNIQUE INDEX uk_pay_code ON G_CONTRACT_PAYMENT(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_pay_tenant_entity_status ON G_CONTRACT_PAYMENT(tenant_id, legal_entity_id, status);
CREATE INDEX idx_pay_contract ON G_CONTRACT_PAYMENT(contract_id);
CREATE INDEX idx_pay_expense ON G_CONTRACT_PAYMENT(expense_id);
CREATE INDEX idx_pay_outsource ON G_CONTRACT_PAYMENT(tenant_id, outsource_flag, status);
COMMENT ON TABLE  G_CONTRACT_PAYMENT IS '付款计划与执行（G-08/G-09）：条款驱动生成计划、累计≤合同额硬拦截、外拨标记';
COMMENT ON COLUMN G_CONTRACT_PAYMENT.plan_amount   IS '各阶段计划金额之和累计不得超过 G_CONTRACT.amount（含变更）';
COMMENT ON COLUMN G_CONTRACT_PAYMENT.expense_id    IS '逻辑引用 F_EXPENSE(id)，付款执行回调落 F，凭证经 F-11 同步';
COMMENT ON COLUMN G_CONTRACT_PAYMENT.voucher_status IS '凭证同步状态：PENDING/SUCCESS/FAILED/MANUAL（转人工，→F-11）';
COMMENT ON COLUMN G_CONTRACT_PAYMENT.outsource_flag IS '外拨标记，=1 时联动 F-22 外拨经费并受合同剩余额约束';


-- -----------------------------------------------------------------------------
-- G-06/G-17 · G_ORDER 采购订单与到货验收（到货一键转资产/耗材）
-- -----------------------------------------------------------------------------
CREATE TABLE G_ORDER (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                                -- ORD-年-序（统一编号中心分配）
  tenant_id         BIGINT       NOT NULL,
  legal_entity_id   BIGINT       NOT NULL,
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  policy_pack_id    BIGINT,                                     -- 订单/验收规则制度包快照
  status            VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','CONFIRMED','EXECUTING','COMPLETED','CANCELLED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列（PRD §5.1）
  requisition_id    BIGINT       NOT NULL REFERENCES G_REQUISITION(id),  -- 同模块物理外键
  contract_id       BIGINT      REFERENCES G_CONTRACT(id),      -- 可空·限额内自行采购无合同
  supplier_id       BIGINT       NOT NULL REFERENCES G_SUPPLIER(id),     -- 同模块物理外键
  order_amount      NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 订单金额
  currency          VARCHAR(8)  NOT NULL DEFAULT 'CNY',         -- 币种
  order_date        DATE,                                       -- 下单日期
  expect_delivery_date DATE,                                    -- 预计到货日期
  delivery_status   VARCHAR(16)  NOT NULL DEFAULT 'PENDING'
                    CHECK (delivery_status IN ('PENDING','SHIPPED','ARRIVED','ACCEPTED','REJECTED')),  -- 到货/验收状态机
  acceptance_by     BIGINT,                                     -- 验收人 user_id
  acceptance_date   DATE,                                       -- 验收日期
  converted_asset   SMALLINT     NOT NULL DEFAULT 0
                    CHECK (converted_asset IN (0,1))            -- 到货转资产标记（→ G-17 / 模块10 A_ASSET·A_CONSUMABLE）
);
CREATE UNIQUE INDEX uk_ord_code ON G_ORDER(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_ord_tenant_entity_status ON G_ORDER(tenant_id, legal_entity_id, status);
CREATE INDEX idx_ord_requisition ON G_ORDER(requisition_id);
CREATE INDEX idx_ord_contract ON G_ORDER(contract_id);
CREATE INDEX idx_ord_supplier ON G_ORDER(supplier_id);
CREATE INDEX idx_ord_delivery ON G_ORDER(tenant_id, delivery_status);
CREATE INDEX idx_ord_security ON G_ORDER(tenant_id, security_level, status);
COMMENT ON TABLE  G_ORDER IS '采购订单（G-06/G-17）：下单→到货→验收状态机，验收通过一键转资产/耗材';
COMMENT ON COLUMN G_ORDER.contract_id     IS '逻辑可空：限额内自行采购（无合同）直接由 requisition_id 下单';
COMMENT ON COLUMN G_ORDER.delivery_status IS '到货状态机：PENDING=待发货/SHIPPED=在途/ARRIVED=到货/ACCEPTED=验收合格/REJECTED=拒收';
COMMENT ON COLUMN G_ORDER.converted_asset IS '到货转资产标记：ACCEPTED 后置 1 表示已推送模块 10 生成 A_ASSET/A_CONSUMABLE，防重复录入';


-- -----------------------------------------------------------------------------
-- G-09 · G_OUTSOURCE 外协台账（从属于 contract_type=外协分包 的合同，联动 F-22 外拨）
-- -----------------------------------------------------------------------------
CREATE TABLE G_OUTSOURCE (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code              VARCHAR(64),                                -- 外协台账编号（沿用 OSC 合同号）
  tenant_id         BIGINT       NOT NULL,
  legal_entity_id   BIGINT       NOT NULL,
  security_level    VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                    CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),
  policy_pack_id    BIGINT,                                     -- 外协合规（禁止整体转包/外拨限额）制度包快照
  status            VARCHAR(32)  NOT NULL DEFAULT 'EXECUTING'
                    CHECK (status IN ('EXECUTING','SETTLING','COMPLETED','TERMINATED')),
  deleted           SMALLINT     NOT NULL DEFAULT 0,
  creator_id        BIGINT       NOT NULL,
  modifier_id       BIGINT,
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark            TEXT,
  -- 业务列（PRD §5.1）——从属 G_CONTRACT(contract_type=外协分包)，1:1
  contract_id       BIGINT       NOT NULL REFERENCES G_CONTRACT(id),         -- 同模块物理外键（1:1 外协合同）
  outsource_unit_id BIGINT       NOT NULL REFERENCES G_SUPPLIER(id),         -- 外协单位（type=外协单位）同模块物理外键
  scope             TEXT,                                       -- 外协任务范围
  outsource_amount  NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 外拨总额（受合同额约束）
  disbursed_amount  NUMERIC(18,2) NOT NULL DEFAULT 0,           -- 已拨金额（联动 F-22 累计）
  progress          NUMERIC(6,4)  NOT NULL DEFAULT 0,           -- 外协进度（0-1）
  deliverable_check VARCHAR(16)   NOT NULL DEFAULT 'PENDING'
                    CHECK (deliverable_check IN ('PENDING','PASSED','FAILED')),  -- 成果验收
  compliance_note   TEXT                                         -- 合规说明（不得整体转包、单一来源需说明等）
);
CREATE UNIQUE INDEX uk_outs_code ON G_OUTSOURCE(tenant_id, code) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_outs_contract ON G_OUTSOURCE(contract_id) WHERE deleted = 0;  -- 与外协合同 1:1
CREATE INDEX idx_outs_tenant_entity_status ON G_OUTSOURCE(tenant_id, legal_entity_id, status);
CREATE INDEX idx_outs_unit ON G_OUTSOURCE(outsource_unit_id);
CREATE INDEX idx_outs_security ON G_OUTSOURCE(tenant_id, security_level, status);
COMMENT ON TABLE  G_OUTSOURCE IS '外协台账（G-09）：从属于外协分包合同(1:1)，禁止整体转包、外拨额度联动 F-22 剩余额拦截';
COMMENT ON COLUMN G_OUTSOURCE.contract_id      IS '同模块物理外键→G_CONTRACT；仅 contract_type=外协分包 的合同派生，1:1';
COMMENT ON COLUMN G_OUTSOURCE.outsource_unit_id IS '外协单位（同模块物理外键→G_SUPPLIER，须 type=外协单位 且入库非黑名单）';
COMMENT ON COLUMN G_OUTSOURCE.disbursed_amount IS '已拨累计；本次外拨 > (outsource_amount - disbursed_amount) 即硬拦截（F-22）';
COMMENT ON COLUMN G_OUTSOURCE.compliance_note  IS '整体转包禁用/单一来源说明等合规校验记录，命中规则升级审批';


-- =============================================================================
-- 备注：
--   1) 单号前缀 REQ/ORD/SUP/SOSC/CON/OSC 已在 00-common.sql `seq_prefix_registry` 登记（owner=G），
--      业务取号一律走 svc-numbering，作废不回收、重试幂等（PRD 2.11）。
--   2) 跨模块引用（project_id / budget_subject_code / expense_id / archive_checklist_id /
--      policy_pack_id / applicant_id 等人员）不建物理外键，仅存对方主键 id；
--      一致性走 Kafka 事件 + Saga（TECH_ARCH §八）。
--   3) G 模块全部表携带治理三列 legal_entity_id / security_level / policy_pack_id（PRD 2.12/2.13/2.10）；
--      方式判定/合同红线/外拨限额均落 policy_pack_id 快照供复算。
--   4) 达梦部署：JSONB→CLOB + 应用解析；BOOLEAN→SMALLINT(0/1)（本模块 blacklist/outsource_flag/
--      converted_asset 已用 SMALLINT）；部分唯一索引以 (tenant_id,code,deleted) 普通唯一索引替代；
--      TIMESTAMPTZ→TIMESTAMP WITH TIME ZONE。
-- =============================================================================
