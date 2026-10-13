-- =============================================================================
-- 11-涉密管理与多法人治理-X.ddl.sql · 模块 X（Confidentiality & Multi-legal-entity Governance）建表脚本
-- 版本 v1.1 · 日期 2026-10-13
-- 方言：PostgreSQL 15（默认）
-- 上游：design/README.md §2/§3/§4/§5；PRD/11-涉密管理与多法人治理.md §5.1；TECH_ARCHITECTURE.md §七/§八
--
-- ┌─ 一、与 00-common.sql 的表映射与复用说明（本模块【不重复建表】）────────────────┐
-- │  ① 法人主体 / 法人树（X_LEGAL_ENTITY，PRD 名）  ==>  已建 sys_legal_entity（common §1）  │
-- │     · sys_legal_entity 提供 code(LE-年-序)/name/credit_code/entity_type/short_code/       │
-- │       consolidated/status(ACTIVE|DEREGISTERED)/tenant_id；PRD 的 parent_id 法人树层级由     │
-- │       sys_org(parent_id,org_type=TOTAL_INSTITUTE|BRANCH_INSTITUTE) 承载，法人↔组织 1:1。    │
-- │     · 本模块对法人只做【读写编排 + 分级授权 + 并表口径】，DDL 不重复定义法人表。            │
-- │  ② 涉密输出 / 跨网流向审批（X_FLOW_AUDIT，PRD 名） ==>  已建 x_flow_audit（common §7）      │
-- │     · x_flow_audit 提供 code(EXF-年-序)/direction(DOWN|UP)/from_domain/to_domain/          │
-- │       applicant_id/second_verifier_id/status(APPLIED|PRE_REVIEW|SEC_REVIEW|RELEASED|        │
-- │       REJECTED|RECORDED)/security_level。PRD §5.1 的 payload_digest/desensitize_note/       │
-- │       approver1/approver2/release_scope 等扩展位由本模块 X_SEC_LOG + sys_audit_log 补齐。    │
-- │     · 本模块【不重复建】流向审批表，POST /security/export 落到 x_flow_audit。               │
-- │  ③ 通用审计日志 sys_audit_log（common §6，含 prev_sig/sig 哈希链）已存在                    │
-- │     · 分工：sys_audit_log = 全系统通用操作审计（CRUD/审批/导出/打印，字段级 diff + SM2 签名）；│
-- │       X_SEC_LOG = 涉密网【专用安全日志】，增加 network_zone / granted_level 校验结果          │
-- │       (result ALLOW|DENY) / risk_flag 语义与独立 SM3 哈希链，服务越权探测/跨域告警稽核。        │
-- │     · 二者不互斥：涉密域判定事件写 X_SEC_LOG，业务数据变更仍写 sys_audit_log，traceId 关联。   │
-- │  ④ 三员职责 sys_admin_duty（common §1，uk_admin_duty_user(user_id) 唯一）为三员分立的物理约束， │
-- │     本模块据此做“禁止兼任 / 兼任即冻结”的裁决，不重复建三员表。                                │
-- │  ⑤ 制度包 sys_policy_pack（common §3）：X_SECURITY_POLICY 是“密级/流向”专用制度包的一种，      │
-- │     通过 policy_pack_id 逻辑联动，不重复建制度包主表。                                          │
-- └──────────────────────────────────────────────────────────────────────────────┘
--
-- ┌─ 二、信创达梦差异注记（design/README.md §2.4，达梦部署时按此替换）───────────────┐
-- │ 自增主键  GENERATED ALWAYS AS IDENTITY → IDENTITY(1,1)                            │
-- │ 时间戳    TIMESTAMPTZ → TIMESTAMP WITH TIME ZONE                                  │
-- │ 布尔      BOOLEAN → SMALLINT（0/1）；本脚本 mfa_bound/risk_flag/secret_eligible     │
-- │           已达梦风格用 SMALLINT + CHECK (0,1[,2])                                   │
-- │ JSON      JSONB（matrix_json/field_diff_json/training_records/leave_clearance）     │
-- │           → CLOB/VARCHAR 存 JSON 文本 + 应用层解析；高频判定字段提升为生成列         │
-- │ 数组      applied_modules VARCHAR(128)[] → 达梦不支持数组，改用 VARCHAR 存 ',' 分隔 │
-- │           或 JSON 文本 + 应用层展开（对齐 sys_policy_pack.applied_modules 同规则）   │
-- │ 部分唯一索引 CREATE UNIQUE INDEX ... WHERE deleted=0 → 普通唯一索引 + deleted 复合键 │
-- │ 枚举      统一 VARCHAR + CHECK (IN (...))，不用原生 ENUM，便于灰度扩值              │
-- └──────────────────────────────────────────────────────────────────────────────┘
--
-- ┌─ 三、国产密码算法（等保三级 / 涉密信息系统分级保护 BMB）─────────────────────────┐
-- │ SM3（摘要/哈希）：X_SEC_LOG.hash_prev / hash_self 构成哈希链，逐条 SM3 链式摘要，   │
-- │                  防篡改；断裂即触发最高级安全告警并转只读取证模式。                  │
-- │ SM2（数字签名）：涉密输出放行 / 定密解密等关键操作的审批签名与 sys_audit_log.sig     │
-- │                  采用 SM2 椭圆曲线签名（替代 RSA/ECDSA）。                            │
-- │ SM4（对称加密）：SECRET/TOP_SECRET 对象的正文与附件在涉密网内以 SM4 密文落库；        │
-- │                  matrix_json 中的敏感策略项可按需 SM4 列加密。                        │
-- │ 说明：哈希链/签名字段仅存算法输出（hex/base64），密钥由信创密码机/HSM 托管，         │
-- │       不落应用配置；具体字段注释标注所用算法。                                        │
-- └──────────────────────────────────────────────────────────────────────────────┘
--
-- 【通用列（§2.1，所有业务表内联，列名列型完全一致，DDL 不再逐表注释）】
--   id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
--   code VARCHAR(64), tenant_id BIGINT NOT NULL, status VARCHAR(32) NOT NULL,
--   deleted SMALLINT NOT NULL DEFAULT 0, creator_id BIGINT NOT NULL, modifier_id BIGINT,
--   created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
--   remark TEXT
--
-- 【治理三字段（§2.1 v1.1 / PRD 2.12/2.13）】本模块所有独有风险表默认携带：
--   legal_entity_id BIGINT NOT NULL（法人细分，逻辑引用 sys_legal_entity.id）
--   security_level  VARCHAR(16) NOT NULL DEFAULT 'INTERNAL' CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET'))
--   （policy_pack_id 见 X_SECURITY_POLICY，联动 sys_policy_pack）
--
-- 【密级 token 与 PRD §6.2 密级状态机对齐 —— 两套取值切勿混淆】
--   · 对象/可见密级集合（security_level / granted_level）：PUBLIC / INTERNAL / SECRET / TOP_SECRET（静态分级，README 2.13）。
--   · 定/降/解密【工作态】（classify_status，落 X_PERSONNEL_SEC 及单据）：UNCLASSIFIED=待定密 / DOWN_CLASSIFY=降密中 / DECLASSIFY=解密中；
--     这是审批流程的过渡态，不表示对象密级；对象密级始终以 security_level 为准，工作态走完再回写 security_level。
--
-- 【外键】同底座物理外键 REFERENCES sys_user(id)（common 与 X 共库可建）；
--   跨微服务库（S_STAFF/07、E_PROJECT/02、sys_policy_pack 引用值等）仅以 *_id 逻辑外键注释表达，不建物理外键（README §2.3/§3.1）。
--
-- 【单号前缀（PRD 2.11 / design/README.md §2.3）】
--   · LE（法人）、EXF（输出/流向审批）已登记于 00-common.sql seq_prefix_registry，分别归 sys_legal_entity / x_flow_audit，本模块直接复用。
--   · SEC（涉密事项：策略/授权/人员涉密档案）——本模块使用 SEC-{yyyy}-{seq6}；PRD 声明前缀为 SEC，但 2.11 注册表当前【未登记 SEC】，
--     故本脚本仅声明 code 列不强约束前缀，正式下发前须先在 seq_prefix_registry 登记 SEC（owner_module='X'），避免规则漂移。
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1) X_SECURITY_POLICY 密级/流向策略（制度包的一种；版本化；单号 SEC-年-序）
--    定义 security_level → 可见网络域 / 角色白名单 / 可否导出 / 可否跨网 的判定矩阵
-- -----------------------------------------------------------------------------
CREATE TABLE X_SECURITY_POLICY (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            VARCHAR(64)  NOT NULL,              -- SEC-{yyyy}-{seq6}（待 2.11 登记 SEC 后由编号中心下发）
  tenant_id       BIGINT       NOT NULL,              -- 总院法人边界
  legal_entity_id BIGINT       NOT NULL,              -- 法人细分（逻辑引用 sys_legal_entity.id；默认总院法人）
  security_level  VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                  CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')), -- 本策略自身密级

  version         INT          NOT NULL DEFAULT 1,    -- 策略版本号（同 code 多版本并存，历史留快照）
  effective_from  DATE         NOT NULL,              -- 生效起
  effective_to    DATE,                               -- 生效止（NULL=当前有效）
  matrix_json     JSONB        NOT NULL,              -- 判定矩阵：每 security_level 的 visible_zones/role_whitelist/can_export/can_cross_net/desensitize；SM3 摘要校验完整性
  applied_modules VARCHAR(128) [] NOT NULL,           -- 生效模块集合 {P,E,F,R,T,G,A,C,D...}（达梦改 ','分隔/JSON 文本）
  policy_pack_id  BIGINT,                            -- 逻辑联动 sys_policy_pack.id（等同制度包的一种，可复算/可解释）

  status          VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                  CHECK (status IN ('DRAFT','ACTIVE','SUPERSEDED')),  -- 草稿/生效/被取代（对齐 sys_policy_pack token）
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  creator_id      BIGINT       NOT NULL,
  modifier_id     BIGINT,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT
);
CREATE UNIQUE INDEX uk_secpolicy_code_ver ON X_SECURITY_POLICY(tenant_id, code, version) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_secpolicy_active   ON X_SECURITY_POLICY(tenant_id, applied_modules) WHERE status = 'ACTIVE' AND deleted = 0; -- 同租户同模块集合仅一套 ACTIVE
CREATE INDEX        idx_secpolicy_ent     ON X_SECURITY_POLICY(tenant_id, legal_entity_id, status);
CREATE INDEX        idx_secpolicy_pack    ON X_SECURITY_POLICY(policy_pack_id);

COMMENT ON TABLE  X_SECURITY_POLICY                IS '密级/流向策略（版本化制度包的一种）：security_level×网络域×角色可见性矩阵，联动 sys_policy_pack';
COMMENT ON COLUMN X_SECURITY_POLICY.matrix_json    IS '判定矩阵 JSONB：{"SECRET":{"visible_zones":["SECRET_NET"],"role_whitelist":[...],"can_export":false,"can_cross_net":false,"desensitize":"placeholder"},...}；网关 zone-guard 据此判定';
COMMENT ON COLUMN X_SECURITY_POLICY.applied_modules IS '生效模块集合 {P,E,F,R,T,G,A,C,D...}；决定哪些业务对象的 security_level 走本策略';
COMMENT ON COLUMN X_SECURITY_POLICY.policy_pack_id IS '逻辑引用 sys_policy_pack.id；策略与制度包同源，命中写 sys_rule_hit 可复算';
COMMENT ON COLUMN X_SECURITY_POLICY.status         IS 'DRAFT 草稿/ACTIVE 生效（同集合唯一）/SUPERSEDED 被新版本取代';
COMMENT ON COLUMN X_SECURITY_POLICY.code           IS 'SEC-年-序；SEC 前缀须先在 2.11 注册表登记方可由编号中心正式下发';


-- -----------------------------------------------------------------------------
-- 2) X_ACCESS_GRANT 授权与密级许可（谁，在哪个网络域，最高可见到什么密级；SEC-年-序）
--    ABAC 属性源：subject_user_id + scope(法人/部门/项目/密级) + granted_level + network_zone
-- -----------------------------------------------------------------------------
CREATE TABLE X_ACCESS_GRANT (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            VARCHAR(64)  NOT NULL,              -- SEC-{yyyy}-{seq6}
  tenant_id       BIGINT       NOT NULL,
  legal_entity_id BIGINT       NOT NULL,              -- 授权归属法人（逻辑引用 sys_legal_entity.id）
  security_level  VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                  CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')), -- 本授权记录自身密级

  subject_user_id BIGINT       NOT NULL REFERENCES sys_user(id), -- 被授权人（同底座物理外键）
  scope_type      VARCHAR(16)  NOT NULL
                  CHECK (scope_type IN ('LEGAL_ENTITY','DEPT','PROJECT','SECURITY_LEVEL')), -- 法人|部门|项目|密级
  scope_ref       BIGINT,                            -- 范围对象 id：法人 sys_legal_entity.id / 部门 sys_org.id / 项目 E_PROJECT.id（逻辑引用）；scope_type=SECURITY_LEVEL 时可空
  granted_level   VARCHAR(16)  NOT NULL
                  CHECK (granted_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')), -- 可见最高密级
  network_zone    VARCHAR(16)  NOT NULL
                  CHECK (network_zone IN ('INTERNET','OFFICE','SECRET_NET')),           -- 授权生效网络域：互联网/办公内网/涉密网
  mfa_bound       SMALLINT     NOT NULL DEFAULT 0
                  CHECK (mfa_bound IN (0,1)),        -- 是否绑定硬件 Key/生物（达梦 SMALLINT）；SECRET+ 强制 1
  valid_from      TIMESTAMPTZ  NOT NULL,             -- 授权生效起
  valid_to        TIMESTAMPTZ,                       -- 授权到期（NULL=长期；到期自动失效）

  status          VARCHAR(32)  NOT NULL DEFAULT 'EFFECTIVE'
                  CHECK (status IN ('EFFECTIVE','FROZEN','REVOKED')),  -- 生效/冻结/吊销
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  creator_id      BIGINT       NOT NULL,
  modifier_id     BIGINT,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT
);
CREATE UNIQUE INDEX uk_grant_code      ON X_ACCESS_GRANT(tenant_id, code) WHERE deleted = 0;
CREATE INDEX        idx_grant_subject  ON X_ACCESS_GRANT(subject_user_id, status);          -- 取当前有效授权（判定主路径）
CREATE INDEX        idx_grant_level_zn ON X_ACCESS_GRANT(granted_level, network_zone);      -- zone-guard 按密级×域过滤
CREATE INDEX        idx_grant_ent      ON X_ACCESS_GRANT(tenant_id, legal_entity_id, status);
CREATE INDEX        idx_grant_scope    ON X_ACCESS_GRANT(scope_type, scope_ref);

COMMENT ON TABLE  X_ACCESS_GRANT               IS '授权与密级许可（ABAC 属性源）：subject_user 在指定网络域/范围内可见的最高密级';
COMMENT ON COLUMN X_ACCESS_GRANT.scope_type    IS 'LEGAL_ENTITY 法人/DEPT 部门/PROJECT 项目/SECURITY_LEVEL 按密级授权';
COMMENT ON COLUMN X_ACCESS_GRANT.scope_ref     IS '范围对象 id（法人/部门/项目逻辑引用，不建物理外键）；SECURITY_LEVEL 范围时可空';
COMMENT ON COLUMN X_ACCESS_GRANT.granted_level IS '授予可见最高密级；判定 actor.granted_level >= object.security_level';
COMMENT ON COLUMN X_ACCESS_GRANT.network_zone  IS 'INTERNET 互联网/OFFICE 办公内网/SECRET_NET 涉密网；跨域授权需二次鉴别';
COMMENT ON COLUMN X_ACCESS_GRANT.mfa_bound     IS '0 未绑定/1 已绑定硬件 Key 或生物；SECRET/TOP_SECRET 授权强制 1';
COMMENT ON COLUMN X_ACCESS_GRANT.valid_to      IS '到期时间；客座/访问学者短期许可到期自动失效（联动 07 S-11）';
COMMENT ON COLUMN X_ACCESS_GRANT.status        IS 'EFFECTIVE 生效/FROZEN 冻结（离岗未清退降为只读占位）/REVOKED 吊销';


-- -----------------------------------------------------------------------------
-- 3) X_SEC_LOG 涉密网专用安全日志（append-only，SM3 哈希链防篡改；越权/跨域/流向稽核）
--    分工：与 common.sys_audit_log 互补——本表专管三网访问判定结果(allow/deny)、risk、zone、granted_level 校验语义。
--    【设计取舍】作为不可篡改追加日志，有意省略 status/deleted/creator_id/modifier_id/updated_at/remark 等可编辑列
--                （与 sys_audit_log 同为特例），仅保留追加所需列；任何 UPDATE/DELETE 应由数据库权限禁止。
-- -----------------------------------------------------------------------------
CREATE TABLE X_SEC_LOG (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id       BIGINT       NOT NULL,              -- 总院法人边界
  legal_entity_id BIGINT       NOT NULL,              -- 事件归属法人（逻辑引用 sys_legal_entity.id）

  actor_id        BIGINT       NOT NULL,              -- who：操作人 user_id（逻辑引用 sys_user.id）
  actor_role      VARCHAR(32),                         -- 操作时角色（R-*，快照）
  network_zone    VARCHAR(16)  NOT NULL
                  CHECK (network_zone IN ('INTERNET','OFFICE','SECRET_NET')), -- 请求来源网络域
  action          VARCHAR(32)  NOT NULL,              -- READ/CREATE/UPDATE/DELETE/EXPORT/PRINT/GRANT/CLASSIFY/CROSS_NET/LOGIN ...
  object_type     VARCHAR(32)  NOT NULL,              -- 表名或单据类型（E_PROJECT/F_EXPENSE/DOC/...）
  object_id       BIGINT       NOT NULL,              -- 被访问对象主键
  field_diff_json JSONB,                               -- 字段级前后值（what/why，达梦 CLOB 存 JSON 文本）
  security_level  VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                  CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')), -- 被访问对象密级
  granted_level   VARCHAR(16)
                  CHECK (granted_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')),  -- 校验时 actor 的授权最高密级快照（NULL 表示未命中授权）
  result          VARCHAR(8)   NOT NULL
                  CHECK (result IN ('ALLOW','DENY')),  -- 判定结果：放行/拒绝
  risk_flag       SMALLINT     NOT NULL DEFAULT 0
                  CHECK (risk_flag IN (0,1,2)),        -- 0 常规/1 风险（跨域尝试）/2 高危（越权探测/哈希链断裂）
  hash_prev       VARCHAR(128),                        -- 前一条 SM3 链摘要（哈希链，SM3）
  hash_self       VARCHAR(128) NOT NULL,               -- 本条 SM3 链式摘要（SM3），覆盖上列业务字段，防篡改
  occurred_at     TIMESTAMPTZ  NOT NULL,              -- when：事件发生时间
  source_ip       VARCHAR(64),                         -- where：来源 IP
  device_id       VARCHAR(128)                         -- where：设备指纹/终端 ID
);
CREATE INDEX idx_seclog_time     ON X_SEC_LOG(occurred_at);                              -- 时序稽核/窗口扫描
CREATE INDEX idx_seclog_risk     ON X_SEC_LOG(risk_flag, occurred_at) WHERE risk_flag > 0; -- 风险事件（告警检索，达梦去 WHERE 用 risk_flag 普通索引）
CREATE INDEX idx_seclog_obj      ON X_SEC_LOG(object_type, object_id);                   -- 对象访问追溯
CREATE INDEX idx_seclog_ent      ON X_SEC_LOG(legal_entity_id, occurred_at);             -- 分法人稽核
CREATE INDEX idx_seclog_actor    ON X_SEC_LOG(tenant_id, actor_id, occurred_at);         -- 行为人轨迹
CREATE INDEX idx_seclog_zone_lvl ON X_SEC_LOG(network_zone, security_level, result);     -- 跨域拒绝分析

COMMENT ON TABLE  X_SEC_LOG               IS '涉密网专用安全审计日志（追加不可改，SM3 哈希链防篡改）；与 common.sys_audit_log 分工：本表专管三网判定/越权/流向，通用数据变更走 sys_audit_log，traceId 关联';
COMMENT ON COLUMN X_SEC_LOG.network_zone  IS '请求来源网络域；与对象 security_level 的可见域比对，不匹配即 DENY+risk';
COMMENT ON COLUMN X_SEC_LOG.granted_level IS '判定时 actor 的授权最高密级快照（来自 X_ACCESS_GRANT），用于事后复算为何放行/拒绝';
COMMENT ON COLUMN X_SEC_LOG.result        IS 'ALLOW 放行/DENY 拒绝；对 DENY 不向前端暴露对象细节（防探测）';
COMMENT ON COLUMN X_SEC_LOG.risk_flag     IS '0 常规/1 风险/2 高危；哈希链断裂或连续越权探测置 2，触发最高级告警与只读取证';
COMMENT ON COLUMN X_SEC_LOG.hash_prev     IS '前一条链摘要（SM3）；首条为 NULL 或创世常量';
COMMENT ON COLUMN X_SEC_LOG.hash_self     IS '本条 SM3 摘要，覆盖业务字段+hash_prev，构成不可篡改哈希链';


-- -----------------------------------------------------------------------------
-- 4) X_PERSONNEL_SEC 涉密人员（联动 07 S_STAFF；入职审查/在岗复审/离岗清退/密级许可）
-- -----------------------------------------------------------------------------
CREATE TABLE X_PERSONNEL_SEC (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            VARCHAR(64)  NOT NULL,              -- SEC-{yyyy}-{seq6}（人员涉密档案号）
  tenant_id       BIGINT       NOT NULL,
  legal_entity_id BIGINT       NOT NULL,              -- 人员归属法人（逻辑引用 sys_legal_entity.id）
  security_level  VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                  CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')), -- 档案记录密级

  user_id         BIGINT       NOT NULL REFERENCES sys_user(id), -- 登录态（同底座物理外键）
  staff_id        BIGINT,                            -- 逻辑引用 S_STAFF.id（07 模块，跨库不建物理外键）
  secret_eligible SMALLINT     NOT NULL DEFAULT 0
                  CHECK (secret_eligible IN (0,1)),  -- 是否具备涉密岗资格（达梦 SMALLINT）
  granted_level   VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                  CHECK (granted_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET')), -- 当前密级许可（与 X_ACCESS_GRANT 对齐）
  classify_status VARCHAR(16)  NOT NULL DEFAULT 'UNCLASSIFIED'
                  CHECK (classify_status IN ('UNCLASSIFIED','DOWN_CLASSIFY','DECLASSIFY')), -- 定/降/解密【工作态】（≠ security_level）
  review_date     DATE,                              -- 最近一次在岗复审日期
  next_review_date DATE,                             -- 下次复审到期日（逾期触发复审提醒/冻结）
  training_records JSONB       NOT NULL DEFAULT '[]', -- 保密培训记录 [{type,training_date,result,trainer,cert_ref}]（达梦 CLOB 存 JSON）
  leave_clearance  JSONB,                            -- 离岗清退 {carrier_returned:0/1,access_revoked:0/1,undertaking_signed:0/1,closed_by,closed_at}；未完成则权限收敛

  status          VARCHAR(32)  NOT NULL DEFAULT 'PENDING_REVIEW'
                  CHECK (status IN ('PENDING_REVIEW','GRANTED','RE_REVIEW','FROZEN','CLEARED_OUT')), -- 待审/已授权在岗/复审中/冻结/已清退
  deleted         SMALLINT     NOT NULL DEFAULT 0,
  creator_id      BIGINT       NOT NULL,
  modifier_id     BIGINT,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark          TEXT
);
CREATE UNIQUE INDEX uk_personnel_sec_user ON X_PERSONNEL_SEC(user_id) WHERE deleted = 0;  -- 一人一份涉密档案
CREATE UNIQUE INDEX uk_personnel_sec_code ON X_PERSONNEL_SEC(tenant_id, code) WHERE deleted = 0;
CREATE INDEX        idx_personnel_sec_ent ON X_PERSONNEL_SEC(tenant_id, legal_entity_id, status);
CREATE INDEX        idx_personnel_sec_lvl ON X_PERSONNEL_SEC(granted_level);
CREATE INDEX        idx_personnel_sec_rev ON X_PERSONNEL_SEC(next_review_date);           -- 复审到期扫描

COMMENT ON TABLE  X_PERSONNEL_SEC               IS '涉密人员管理（联动 07）：入职审查→在岗复审→离岗清退；承载密级许可与定/降/解密工作态';
COMMENT ON COLUMN X_PERSONNEL_SEC.user_id       IS '登录态 sys_user.id（同底座物理外键）；与 S_STAFF.user_id 一致';
COMMENT ON COLUMN X_PERSONNEL_SEC.staff_id      IS '科研人员档案（跨微服务库逻辑引用 S_STAFF.id，07 模块）';
COMMENT ON COLUMN X_PERSONNEL_SEC.granted_level IS '当前密级许可；与 X_ACCESS_GRANT.granted_level 对齐，判定取交集';
COMMENT ON COLUMN X_PERSONNEL_SEC.classify_status IS '定/降/解密工作态：UNCLASSIFIED 待定密/DOWN_CLASSIFY 降密中/DECLASSIFY 解密中；此为流程过渡态，不覆盖对象 security_level';
COMMENT ON COLUMN X_PERSONNEL_SEC.leave_clearance IS '离岗清退：载体归还/权限回收/保密承诺 三项全 1 方视为完成；否则权限收敛为只读占位';
COMMENT ON COLUMN X_PERSONNEL_SEC.status        IS 'PENDING_REVIEW 待审查/GRANTED 已授权在岗/RE_REVIEW 复审中/FROZEN 冻结/CLEARED_OUT 已清退';
