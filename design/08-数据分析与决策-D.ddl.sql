-- =============================================================================
-- 08-数据分析与决策-D.ddl.sql · 数据分析与决策支持（D）模块建表脚本
-- 版本 v1.0 · 2026-10-13
-- 上游：../PRD/08-数据分析与决策.md（D-01..D-19、数仓分层 §5.1、应用层表 §5.2、
--       ETL §6、AI §8、权限 §9、接口 §10、异常 §11、非功能 §12）、
--       ./README.md（全局约定 §2 数据库 / §3 API / §4 状态 token / §5 共享实体登记表）、
--       ../TECH_ARCHITECTURE.md（§二 技术选型 / §五 数据架构：ClickHouse OLAP、CDC、NL2SQL）
--
-- 【本模块特殊性：双引擎落地（ADR-003 OLTP 与 OLAP 双引擎）】
--   ┌───────────────────────────────────────────────────────────────────────┐
--   │ 第一部分：PostgreSQL 15 —— OLTP 配置 / 应用元数据 / AI 交互留痕         │
--   │   D_METRIC / D_REPORT / D_REPORT_INSTANCE / D_SCREEN / D_SUBSCRIPTION  │
--   │   D_QUERY_LOG / D_BENCHMARK / D_FORECAST / D_POLICY_QA / D_EXPORT      │
--   │   —— 事务型、低频读写、强一致、被 svc-analytics 直接维护                │
--   ├───────────────────────────────────────────────────────────────────────┤
--   │ 第二部分：ClickHouse —— 数仓 ODS/DWD/DWS/ADS 四层                       │
--   │   ods_expense / dwd_* / dim_* / dws_* / ads_*                          │
--   │   —— 列存高吞吐聚合、大屏/画像/趋势、经 CDC→Kafka→Flink T+1 灌入        │
--   │   信创替代（../TECH_ARCHITECTURE.md §二）：ClickHouse → Apache Doris    │
--   └───────────────────────────────────────────────────────────────────────┘
--   指标口径以 D_METRIC.formula_sql 为唯一真源（PRD §11 报送数据不一致以此为准）。
--   多法人合并视图（D-19）联动 X-10 并表口径：跨法人聚合表统一携带 legal_entity_id，
--   总院合并 = 各法人按主责法人口径聚合（避免重复计入），分院下钻 = WHERE legal_entity_id。
--
-- 【信创达梦差异声明（仅针对第一部分 PostgreSQL 15，对齐 design/README.md §2.4，达梦部署时按此替换）】
--   1) 自增主键：GENERATED ALWAYS AS IDENTITY  →  IDENTITY(1,1)
--   2) 时间戳：  TIMESTAMPTZ                    →  TIMESTAMP WITH TIME ZONE
--   3) 布尔：    BOOLEAN                        →  SMALLINT（0/1）
--   4) 半结构：  JSONB                          →  CLOB/VARCHAR 存 JSON 文本 + 应用层解析
--   5) 部分唯一索引 CREATE UNIQUE INDEX ... WHERE deleted=0  →  普通唯一索引 + deleted 复合键
--   6) 全文检索 GIN/trigram (pg_trgm/tsvector)   →  应用层 ES / 达梦全文索引
--   7) 表达式唯一索引中的函数（如 COALESCE）      →  应用层生成哈希列后建普通唯一索引
--   注：第二部分 ClickHouse 不受达梦方言影响，信创分析库替换路径为 Doris（列存语法近似，
--       ENGINE 改为 Distributed/MergeTree 系，COMMENT 语法兼容）。
--
-- 【通用列（§2.1，第一部分所有表内联，列名列型完全一致，DDL 不再逐表注释）】
--   id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
--   code VARCHAR(64), tenant_id BIGINT NOT NULL, status VARCHAR(32) NOT NULL,
--   deleted SMALLINT NOT NULL DEFAULT 0, creator_id BIGINT NOT NULL, modifier_id BIGINT,
--   created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
--   remark TEXT
--   治理三字段（§2.1 v1.1，携带于涉及法人隔离/密级的表）：legal_entity_id BIGINT、
--   security_level VARCHAR(16) DEFAULT 'INTERNAL'、policy_pack_id BIGINT（本模块基本不用）。
--
-- 【单号前缀（§2.3 / PRD 2.11）】D 模块配置类表 code 为业务可读编码（指标编码 / 报表编码 /
--   报送模板编码），非统一编号中心流水号；D 未登记独立单号前缀（见 detail §10 待细化）。
--
-- 【跨模块引用（§5 共享实体登记表，逻辑外键，跨微服务库不建物理 FK）】
--   user_id / *_user_id / generated_by → sys_user.id；report_id 引用 D_REPORT.id（同模块物理 FK）；
--   ClickHouse dim/事实表的 staff_id/department_id/project_id/subject_id 为业务库主键的镜像值。
-- =============================================================================


-- #############################################################################
-- 第一部分 · PostgreSQL 15（OLTP 配置 / 应用元数据 / AI 交互留痕）
-- #############################################################################

-- -----------------------------------------------------------------------------
-- 1) D_METRIC · 指标字典（口径唯一真源，D-01 / D-19）
--    PRD §5.2：id,code,name,category,unit,formula_sql,drill_dims,refresh_freq,owner_role。
--    口径版本化（PRD §11 指标口径变化）：version + effective_from/to + prev_metric_id，
--    历史报表实例引用其生成时的指标版本快照，新报表用最新 ACTIVE 版本。
-- -----------------------------------------------------------------------------
CREATE TABLE D_METRIC (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64)  NOT NULL,                          -- 指标编码（人可读，如 ACTIVE_PRJ_CNT）
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                   CHECK (status IN ('ACTIVE','DEPRECATED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列 -------------------------------------------------------------------
  name             VARCHAR(128) NOT NULL,                          -- 指标中文名
  category         VARCHAR(32)  NOT NULL
                   CHECK (category IN ('PROJECT','FUNDING','OUTPUT','TRANSFER','PEOPLE','RISK','COMPREHENSIVE')), -- 主题域（sys_dict 可配扩展）
  unit             VARCHAR(32),                                    -- 单位：万元/篇/项/%/人 等
  formula_sql      TEXT         NOT NULL,                          -- 口径 SQL（唯一真源，ADS 取数模板 / 下钻起点）
  drill_dims       JSONB        NOT NULL DEFAULT '[]',             -- 下钻维度 [{dim,path}] 如 部门→项目→报销
  refresh_freq     VARCHAR(16)  NOT NULL DEFAULT 'DAILY'
                   CHECK (refresh_freq IN ('REALTIME','HOURLY','DAILY','WEEKLY','MONTHLY')),
  owner_role       VARCHAR(32),                                    -- 归口角色（R-MANAGER/R-FINANCE/…）
  caliber_note     TEXT,                                            -- 口径说明 / 变更理由（评审留痕）
  version          INT          NOT NULL DEFAULT 1,                -- 口径版本（变更评审后递增）
  prev_metric_id   BIGINT       REFERENCES D_METRIC(id),          -- 上一版本（口径变更链，同模块物理 FK）
  effective_from   DATE         NOT NULL DEFAULT CURRENT_DATE,     -- 口径生效起
  effective_to     DATE,                                            -- 口径生效止（NULL=当前有效）
  -- 治理字段（法人归属 + 密级，指标可按法人差异化）
  legal_entity_id  BIGINT,                                          -- NULL=全院统一口径；非空=法人专属口径
  security_level   VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                   CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET'))
);
CREATE UNIQUE INDEX uk_metric_code_ver ON D_METRIC(tenant_id, code, version) WHERE deleted = 0;
CREATE UNIQUE INDEX uk_metric_active   ON D_METRIC(tenant_id, code) WHERE deleted = 0 AND effective_to IS NULL AND status = 'ACTIVE';
CREATE INDEX idx_metric_category      ON D_METRIC(tenant_id, category, status);
COMMENT ON TABLE  D_METRIC IS '指标字典（D-01）：全院核心指标口径唯一真源，指标命名统一避免口径歧义（PRD §12 数据治理）';
COMMENT ON COLUMN D_METRIC.formula_sql IS '指标口径 SQL，ADS 结果表与下钻取数的唯一真源；报送口径冲突以此为准（PRD §11）';
COMMENT ON COLUMN D_METRIC.drill_dims IS '下钻维度链 JSON：ADS→DWS→DWD→业务表的可下钻路径定义';
COMMENT ON COLUMN D_METRIC.version IS '口径版本；历史 D_REPORT_INSTANCE 冻结其生成时版本，新报表取最新 ACTIVE 版本';
COMMENT ON COLUMN D_METRIC.legal_entity_id IS 'NULL=总院统一口径（合并视图基准）；非空=分法人差异化口径';

-- -----------------------------------------------------------------------------
-- 2) D_REPORT · 报表定义（D-04/05，PRD §5.2）
--    id,code,name,type(DASHBOARD/TABLE/CHART),schema_json,data_source,permission_scope,schedule
-- -----------------------------------------------------------------------------
CREATE TABLE D_REPORT (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64)  NOT NULL,
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                   CHECK (status IN ('DRAFT','PUBLISHED','OFFLINE')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列 -------------------------------------------------------------------
  name             VARCHAR(128) NOT NULL,
  type             VARCHAR(16)  NOT NULL CHECK (type IN ('DASHBOARD','TABLE','CHART')), -- 报表类型
  schema_json      JSONB        NOT NULL DEFAULT '{}',             -- 设计器 DSL（字段树/透视/图表/参数化）
  data_source      VARCHAR(64)  NOT NULL,                          -- 数据源标识：ADS 表名 / 指标 code / JDBC 逻辑名
  permission_scope VARCHAR(32)  NOT NULL DEFAULT 'DEPT'
                   CHECK (permission_scope IN ('SELF','DEPT','ALL_INSTITUTE','FINANCE','AUDIT')), -- 可见范围（联动 detail §7）
  metric_refs      JSONB        NOT NULL DEFAULT '[]',             -- 引用指标 code 清单（联动 D_METRIC）
  schedule         VARCHAR(64),                                    -- 定时表达式 cron（生成 report.scheduled；空=手动）
  data_freshness   VARCHAR(16)  NOT NULL DEFAULT 'T_PLUS_1'
                   CHECK (data_freshness IN ('REALTIME','T_PLUS_1','T_PLUS_7')), -- 数据新鲜度标注（PRD §11 数据延迟提醒）
  -- 治理字段
  legal_entity_id  BIGINT,                                          -- NULL=全院报表；非空=法人专属报表
  security_level   VARCHAR(16)  NOT NULL DEFAULT 'INTERNAL'
                   CHECK (security_level IN ('PUBLIC','INTERNAL','SECRET','TOP_SECRET'))
);
CREATE UNIQUE INDEX uk_report_code ON D_REPORT(tenant_id, code) WHERE deleted = 0;
CREATE INDEX idx_report_main      ON D_REPORT(tenant_id, status, type);
CREATE INDEX idx_report_scope     ON D_REPORT(tenant_id, permission_scope);
COMMENT ON TABLE  D_REPORT IS '报表定义（D-04 多维分析 / D-05 自定义报表设计器）：预置 20+ 常用报表 + 用户自定义模板';
COMMENT ON COLUMN D_REPORT.permission_scope IS '可见范围 token，驱动 NL2SQL/取数的行级权限过滤（detail §4 权限过滤）';
COMMENT ON COLUMN D_REPORT.data_freshness IS '数据新鲜度标注，T+1 未刷新时报表/大屏顶部红色提醒（PRD §11）';

-- -----------------------------------------------------------------------------
-- 3) D_REPORT_INSTANCE · 报表实例（含快照，D-05/D-09/D-10，PRD §5.2/§5.3）
--    id,report_id,params,snapshot_url,generated_at,generated_by,expires_at
--    口径冻结：metric_version_snapshot 记录生成时各指标版本，历史报表留旧口径（PRD §11）
-- -----------------------------------------------------------------------------
CREATE TABLE D_REPORT_INSTANCE (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'GENERATED'
                   CHECK (status IN ('GENERATING','GENERATED','EXPIRED','FAILED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列 -------------------------------------------------------------------
  report_id        BIGINT       NOT NULL REFERENCES D_REPORT(id), -- 同模块物理外键
  params           JSONB        NOT NULL DEFAULT '{}',             -- 实例参数（时间/部门/项目类型切片）
  snapshot_url     VARCHAR(512),                                   -- 快照文件（对象存储 MinIO）
  metric_version_snapshot JSONB NOT NULL DEFAULT '{}',             -- 冻结口径版本 {code:version}（历史留旧口径）
  dq_flag          VARCHAR(16)  NOT NULL DEFAULT 'OK'
                   CHECK (dq_flag IN ('OK','PARTIAL_MISSING')),    -- 数据质量标注（PRD §11 质量下降标缺失）
  data_as_of       DATE,                                           -- 数据截至日期（大屏/报表顶部）
  generated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
  generated_by     BIGINT       NOT NULL,                          -- 生成人 sys_user.id（逻辑引用）
  expires_at       TIMESTAMPTZ                                     -- 快照过期（到期回收，PI 导出限时下载）
);
CREATE INDEX idx_inst_report ON D_REPORT_INSTANCE(report_id, generated_at DESC);
CREATE INDEX idx_inst_user   ON D_REPORT_INSTANCE(tenant_id, generated_by);
COMMENT ON TABLE  D_REPORT_INSTANCE IS '报表实例（含快照）：一键生成 / 定时生成 / 个人导出 / 上级报送的落地记录';
COMMENT ON COLUMN D_REPORT_INSTANCE.metric_version_snapshot IS '生成时冻结的指标口径版本，历史报表复算取旧口径，不受新口径影响（PRD §11）';
COMMENT ON COLUMN D_REPORT_INSTANCE.dq_flag IS '数据质量标注：PARTIAL_MISSING 时报表顶部显示"数据存在部分缺失"';

-- -----------------------------------------------------------------------------
-- 4) D_SCREEN · 数据大屏配置（D-06，PRD §5.2/§7.3）
--    id,name,layout_json,widgets([{type,data_metric_id,viz_config}]),rotation_seconds
-- -----------------------------------------------------------------------------
CREATE TABLE D_SCREEN (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64)  NOT NULL,
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                   CHECK (status IN ('DRAFT','PUBLISHED','OFFLINE')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列 -------------------------------------------------------------------
  name             VARCHAR(128) NOT NULL,
  theme            VARCHAR(32)                                        -- 预置模板：全景/经费监督/转化/人才/学科分布
                   CHECK (theme IS NULL OR theme IN ('OVERVIEW','FUNDING','TRANSFER','TALENT','DISCIPLINE')),
  layout_json      JSONB        NOT NULL DEFAULT '{}',               -- 拼图布局（栅格坐标/断点续播位点）
  widgets          JSONB        NOT NULL DEFAULT '[]',               -- [{widgetId,type,dataMetricId,vizConfig,drillPath}]
  rotation_seconds INT          NOT NULL DEFAULT 30,                 -- 轮播间隔秒（支持 6 组视图自动轮播）
  data_as_of_expr  VARCHAR(128),                                     -- 数据截至日期取值表达式（顶部展示 + T+1 提醒）
  -- 治理字段（大屏可含法人维度）
  legal_entity_id  BIGINT                                             -- NULL=总院合并大屏；非空=法人下钻大屏
);
CREATE UNIQUE INDEX uk_screen_code ON D_SCREEN(tenant_id, code) WHERE deleted = 0;
COMMENT ON TABLE  D_SCREEN IS '数据大屏配置（D-06）：全屏深色多块拼图，自动轮播 6 组视图，适配会议室 4K';
COMMENT ON COLUMN D_SCREEN.widgets IS '组件 JSON：每个 widget 引用 D_METRIC.code 取数，viz_config 存 ECharts 配置';

-- -----------------------------------------------------------------------------
-- 5) D_SUBSCRIPTION · 数据订阅（D-18，PRD §5.2/§12 三通道）
--    id,user_id,report_id,frequency(DAILY/WEEKLY/MONTHLY),channel(EMAIL/WECHAT/INBOX),last_sent_at
-- -----------------------------------------------------------------------------
CREATE TABLE D_SUBSCRIPTION (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                   CHECK (status IN ('ACTIVE','PAUSED','CANCELLED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列 -------------------------------------------------------------------
  user_id          BIGINT       NOT NULL,                            -- sys_user.id（逻辑引用）
  report_id        BIGINT       NOT NULL REFERENCES D_REPORT(id),    -- 同模块物理外键
  frequency        VARCHAR(16)  NOT NULL DEFAULT 'DAILY'
                   CHECK (frequency IN ('DAILY','WEEKLY','MONTHLY')),
  channel          VARCHAR(16)  NOT NULL DEFAULT 'EMAIL'
                   CHECK (channel IN ('EMAIL','WECHAT','INBOX')),    -- 邮件 / 企业微信 / 站内消息
  send_day         SMALLINT,                                         -- 发送日（周几/月几号，配合 frequency）
  last_sent_at     TIMESTAMPTZ,                                      -- 最近推送时间（幂等去重 + 排重）
  params_override  JSONB        NOT NULL DEFAULT '{}'                -- 订阅级参数覆盖（如仅看本部门）
);
CREATE UNIQUE INDEX uk_sub_user_report ON D_SUBSCRIPTION(tenant_id, user_id, report_id, frequency, channel) WHERE deleted = 0;
COMMENT ON TABLE  D_SUBSCRIPTION IS '数据订阅（D-18）：邮件/企业微信/站内消息三通道定时推送报表实例';
COMMENT ON COLUMN D_SUBSCRIPTION.channel IS '推送通道 token（对齐 PRD §12 三通道；实际投递经 svc-notify）';

-- -----------------------------------------------------------------------------
-- 6) D_QUERY_LOG · 自然语言查询日志（D-11，PRD §5.2/§8.1）
--    id,user_id,question_text,generated_sql,executed_at,row_count,feedback
--    权限改写审计：rewritten_sql 存注入 tenant_id/legal_entity/security_level 后的最终 SQL
-- -----------------------------------------------------------------------------
CREATE TABLE D_QUERY_LOG (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'SUCCESS'
                   CHECK (status IN ('SUCCESS','FAILED','TIMEOUT','REJECTED_UNMAPPED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列 -------------------------------------------------------------------
  user_id          BIGINT       NOT NULL,                            -- sys_user.id（逻辑引用）
  question_text    TEXT         NOT NULL,                            -- 原始自然语言问题
  matched_metrics  JSONB        NOT NULL DEFAULT '[]',               -- 命中的指标 code（Schema-aware 匹配）
  semantic_readback TEXT,                                             -- 语义回读文本"你是不是想问…"
  user_confirmed   BOOLEAN      NOT NULL DEFAULT FALSE,             -- 用户是否确认回读语义
  generated_sql    TEXT,                                             -- LLM 生成 SQL（改写前）
  rewritten_sql    TEXT,                                             -- 权限改写层注入过滤后的最终 SQL（审计）
  executed_at      TIMESTAMPTZ,                                      -- 执行时间
  row_count        INT,                                              -- 返回行数
  elapsed_ms       INT,                                              -- 端到端耗时（<5s SLA，超时中断）
  masked           BOOLEAN      NOT NULL DEFAULT FALSE,             -- 结果是否脱敏（掩码手机/身份证）
  feedback         VARCHAR(16)  CHECK (feedback IS NULL OR feedback IN ('THUMBS_UP','THUMBS_DOWN','CORRECTED')) -- 反馈回流评估集
);
CREATE INDEX idx_qlog_user  ON D_QUERY_LOG(tenant_id, user_id, created_at DESC);
CREATE INDEX idx_qlog_status ON D_QUERY_LOG(tenant_id, status);
COMMENT ON TABLE  D_QUERY_LOG IS 'NL2SQL 查询日志（D-11）：问题/生成SQL/改写SQL/语义回读/耗时/反馈，供评估与审计复算';
COMMENT ON COLUMN D_QUERY_LOG.rewritten_sql IS '权限改写层注入 tenant_id+legal_entity_id+security_level 过滤后的最终执行 SQL（detail §4）';
COMMENT ON COLUMN D_QUERY_LOG.status IS 'REJECTED_UNMAPPED=无法映射指标→兜底"未理解请联系管理员"不瞎猜（PRD §11）；TIMEOUT=5s 超时中断';

-- -----------------------------------------------------------------------------
-- 7) D_BENCHMARK · 机构对标（D-14，PRD §5.2/§7.5）
--    id,peer_institute_id,year,metric_code,peer_value,our_value,rank
-- -----------------------------------------------------------------------------
CREATE TABLE D_BENCHMARK (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                   CHECK (status IN ('ACTIVE','ARCHIVED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列 -------------------------------------------------------------------
  peer_institute_id BIGINT      NOT NULL,                            -- 对标院所标识（外部/公开数据主体）
  peer_name        VARCHAR(128) NOT NULL,                            -- 对标院所名称（雷达图标签）
  year             SMALLINT     NOT NULL,                            -- 对标年度
  metric_code      VARCHAR(64)  NOT NULL,                            -- 逻辑引用 D_METRIC.code（口径可比）
  peer_value       NUMERIC(18,2),                                    -- 对方值
  our_value        NUMERIC(18,2),                                    -- 本院值
  rank             INT,                                              -- 本院在该组中的排名
  data_source      VARCHAR(32)  NOT NULL DEFAULT 'PUBLIC'
                   CHECK (data_source IN ('PUBLIC','ANNUAL_REPORT')), -- 公开数据 / 上级单位年报
  legal_entity_id  BIGINT                                             -- NULL=全院对标；非空=法人对标
);
CREATE UNIQUE INDEX uk_benchmark ON D_BENCHMARK(tenant_id, peer_institute_id, year, metric_code) WHERE deleted = 0;
COMMENT ON TABLE  D_BENCHMARK IS '机构间对标（D-14）：本院 vs N 家同类院所关键指标对比，数据源公开 + 上级年报';
COMMENT ON COLUMN D_BENCHMARK.metric_code IS '逻辑引用 D_METRIC.code，保证本院与对方口径可比（同真源）';

-- -----------------------------------------------------------------------------
-- 8) D_FORECAST · 趋势预测快照（D-16，PRD §5.2/§8.4）
--    id,target_metric,model_type,forecast_date,predicted_value,confidence_interval
-- -----------------------------------------------------------------------------
CREATE TABLE D_FORECAST (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE'
                   CHECK (status IN ('ACTIVE','SUPERSEDED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列 -------------------------------------------------------------------
  target_metric    VARCHAR(64)  NOT NULL,                            -- 逻辑引用 D_METRIC.code（经费到账/论文产出/立项数）
  model_type       VARCHAR(32)  NOT NULL DEFAULT 'PROPHET'
                   CHECK (model_type IN ('PROPHET','ARIMA','LTSM','LINEAR_REG')), -- Prophet+外部指标为主
  forecast_date    DATE         NOT NULL,                            -- 预测目标日期（如明年到账）
  predicted_value  NUMERIC(18,2) NOT NULL,                           -- 预测值
  confidence_interval JSONB     NOT NULL DEFAULT '{}',               -- 置信区间 {lower,upper,level}
  key_assumptions  JSONB        NOT NULL DEFAULT '[]',               -- 关键假设（GDP/国家政策信号，展示可解释）
  generated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
  legal_entity_id  BIGINT
);
CREATE INDEX idx_forecast_metric ON D_FORECAST(tenant_id, target_metric, forecast_date);
COMMENT ON TABLE  D_FORECAST IS '趋势预测快照（D-16）：经费/成果/立项预测曲线 + 置信区间 + 关键假设';
COMMENT ON COLUMN D_FORECAST.confidence_interval IS '置信区间 JSON {lower,upper,level}，前端画阴影带（PRD §8.4）';

-- -----------------------------------------------------------------------------
-- 9) D_POLICY_QA · 政策问答留痕（D-12，PRD §5.2/§8.2）
--    id,question,answer_text,source_articles,confidence,user_feedback
-- -----------------------------------------------------------------------------
CREATE TABLE D_POLICY_QA (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64),
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'ANSWERED'
                   CHECK (status IN ('ANSWERED','FALLBACK','FAILED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列 -------------------------------------------------------------------
  user_id          BIGINT       NOT NULL,                            -- 提问人 sys_user.id
  question         TEXT         NOT NULL,                            -- 问题原文
  answer_text      TEXT,                                             -- LLM 组织回答
  source_articles  JSONB        NOT NULL DEFAULT '[]',               -- RAG Top-5 条款 [{pack,article,ref,url}]
  confidence       NUMERIC(6,4),                                     -- 置信度 0-1（低于阈值回落人工）
  amount_related   BOOLEAN      NOT NULL DEFAULT FALSE,             -- 是否涉及金额/审批权限（标注"请与科研办确认"）
  hit_policy_pack_id BIGINT,                                         -- 命中的制度包快照 sys_policy_pack.id
  user_feedback    VARCHAR(16)  CHECK (user_feedback IS NULL OR user_feedback IN ('THUMBS_UP','THUMBS_DOWN','CORRECTED')),
  latency_ms       INT                                                -- 端到端耗时（<5s）
);
CREATE INDEX idx_qa_user ON D_POLICY_QA(tenant_id, user_id, created_at DESC);
COMMENT ON TABLE  D_POLICY_QA IS 'AI 政策问答留痕（D-12）：RAG 检索条款 + LLM 组织回答 + 出处链接 + 反馈回流评估集';
COMMENT ON COLUMN D_POLICY_QA.amount_related IS '涉及具体金额/审批权限时 TRUE，答案强制标注"请与科研办确认"（PRD §8.2 风险控制）';
COMMENT ON COLUMN D_POLICY_QA.status IS 'FALLBACK=置信度低于阈值兜底人工/未理解（PRD 2.4 人工兜底）';

-- -----------------------------------------------------------------------------
-- 10) D_EXPORT · 上级报送模板与导出记录（D-07，PRD §7.6，支撑上级报送）
--     code,name,template_scope,target_org,format(CSV/EXCEL/PDF/XML),schema_json,version
-- -----------------------------------------------------------------------------
CREATE TABLE D_EXPORT (
  id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code             VARCHAR(64)  NOT NULL,                            -- 模板编码（EDU年报/CAST年报/CAS评价/省科技厅）
  tenant_id        BIGINT       NOT NULL,
  status           VARCHAR(32)  NOT NULL DEFAULT 'DRAFT'
                   CHECK (status IN ('DRAFT','ACTIVE','SUPERSEDED')),
  deleted          SMALLINT     NOT NULL DEFAULT 0,
  creator_id       BIGINT       NOT NULL,
  modifier_id      BIGINT,
  created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
  remark           TEXT,
  -- 业务列（模板属性）--------------------------------------------------------
  name             VARCHAR(128) NOT NULL,
  template_scope   VARCHAR(32)  NOT NULL
                   CHECK (template_scope IN ('ANNUAL_STAT','DISCIPLINE_EVAL','FUNDING_REPORT','Talent_STAT')), -- 报送范围/用途
  target_org       VARCHAR(128) NOT NULL,                            -- 报送对象（教育部/科技部/中科院/省科技厅）
  format           VARCHAR(16)  NOT NULL DEFAULT 'EXCEL'
                   CHECK (format IN ('CSV','EXCEL','PDF','XML')),     -- 导出/报文格式
  schema_json      JSONB        NOT NULL DEFAULT '{}',                -- 报送表格字段->数据源映射（免表：字段可直抽生成）
  metric_refs      JSONB        NOT NULL DEFAULT '[]',               -- 报送涉及指标 code（口径以 D_METRIC 为准）
  version          INT          NOT NULL DEFAULT 1,                  -- 模板版本（上级口径年度调整）
  prev_export_id   BIGINT       REFERENCES D_EXPORT(id),            -- 上一版本模板（同模块物理 FK）
  -- 业务列（导出记录，最近一次生成快照）------------------------------------
  last_generated_at TIMESTAMPTZ,                                     -- 最近生成时间
  last_generated_by BIGINT,                                          -- 最近生成人 sys_user.id
  last_output_url  VARCHAR(512),                                     -- 最近导出文件（对象存储，报送留痕）
  -- 治理字段
  legal_entity_id  BIGINT                                             -- NULL=总院合并报送；非空=分法人报送
);
CREATE UNIQUE INDEX uk_export_code_ver ON D_EXPORT(tenant_id, code, version) WHERE deleted = 0;
COMMENT ON TABLE  D_EXPORT IS '上级报送模板库与导出记录（D-07）：预置 4+ 报送模板，一键生成→审核→导出→报送留痕';
COMMENT ON COLUMN D_EXPORT.schema_json IS '报送表格字段映射，字段必须可从库直接抽取生成（免表，PRD 2.15 / ../TECH_ARCHITECTURE §四）';
COMMENT ON COLUMN D_EXPORT.format IS '导出格式 token，报送报文支持 CSV/EXCEL/PDF/XML';


-- #############################################################################
-- 第二部分 · ClickHouse OLAP（数仓 ODS/DWD/DWS/ADS 四层，MergeTree 引擎语法）
--   数据流（PRD §6.1）：业务库 → CDC(Debezium) → Kafka → Flink → ODS(每日02:00)
--                       → DWD → DWS → ADS(04:00) → 报表刷新；ETL 每层做质量检查。
--   约定：列类型 UInt64/Int*/Decimal(18,2)/String/LowCardinality(String)/Date/DateTime；
--         维度/事实/结果表统一携带 legal_entity_id 支持多法人合并/下钻（D-19 / 联动 X-10）；
--         ODS/DWD 明细用 MergeTree，维度用 ReplacingMergeTree 取最新，
--         DWS 轻度聚合用 SummingMergeTree/AggregatingMergeTree，ADS 结果用 MergeTree。
--   信创替代：ClickHouse → Apache Doris（列存/分区/ORDER BY 近似，Distributed 表引擎）。
-- #############################################################################

-- =============================================================================
-- 【ODS 贴源层】与业务库结构 1:1，日增量抽取（示例：ods_expense ← F_EXPENSE）
-- =============================================================================
CREATE TABLE dwh.ods_expense
(
    id              UInt64                COMMENT '报销单主键（镜像 F_EXPENSE.id）',
    tenant_id       UInt64                COMMENT '多租户隔离键（总院法人边界）',
    legal_entity_id UInt64                COMMENT '法人细分键（多法人合并/下钻）',
    code            String                COMMENT '报销单号 EXP-年-序',
    status          LowCardinality(String) COMMENT '状态 token：DRAFT/SUBMITTED/…/PAID/VOUCHER_SYNCED',
    project_id      UInt64                COMMENT '项目逻辑外键（E_PROJECT.id）',
    department_id   UInt64                COMMENT '部门逻辑外键（sys_org.id）',
    subject_id      UInt64                COMMENT '经费科目逻辑外键（F_SUBJECT.id）',
    apply_user_id   UInt64                COMMENT '报销申请人（sys_user.id）',
    amount          Decimal(18,2)         COMMENT '报销金额（元）',
    currency        LowCardinality(String) COMMENT '币种 CNY',
    expense_type    LowCardinality(String) COMMENT '费用类型（sys_dict 编码）',
    expense_date    Date                  COMMENT '发生日期',
    voucher_no      String                COMMENT '凭证号',
    security_level  LowCardinality(String) COMMENT '密级：PUBLIC/INTERNAL/SECRET/TOP_SECRET',
    deleted         UInt8                 COMMENT '逻辑删除（0/1）',
    remark          String                COMMENT '备注',
    src_updated_at  DateTime              COMMENT '源库更新时间（增量水位）',
    etl_load_time   DateTime              COMMENT 'ETL 装载时间',
    src_op          LowCardinality(String) COMMENT 'CDC 操作类型 I/U/D'
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(expense_date)
ORDER BY (tenant_id, legal_entity_id, expense_date, id)
COMMENT 'ODS 贴源层：1:1 镜像 F_EXPENSE，日增量（02:00），保留源库全部列不做清洗';


-- =============================================================================
-- 【DWD 明细层】清洗后的事实表（业务口径标准化 + 代理键 + 退化维度 + 审计列）
-- =============================================================================

-- DWD 事实：项目申报/立项（源 P/E）
CREATE TABLE dwh.dwd_project_apply
(
    apply_id        UInt64                COMMENT '申报/立项事实主键',
    tenant_id       UInt64                COMMENT '多租户隔离键',
    legal_entity_id UInt64                COMMENT '法人细分键（主责法人入账，避免合并重复计入）',
    project_code    String                COMMENT '项目编号 PRJ-年-序',
    project_name    String                COMMENT '项目名称',
    project_type_id UInt64                COMMENT '项目类型代理键（关联 dim_project_type）',
    department_id   UInt64                COMMENT '承担部门代理键（关联 dim_department）',
    pi_staff_id     UInt64                COMMENT '负责人代理键（关联 dim_staff）',
    fund_source     LowCardinality(String) COMMENT '经费来源：NATIONAL/PROVINCE/HORIZONTAL/SELF',
    apply_amount    Decimal(18,2)         COMMENT '申报经费额（元）',
    approved_amount Decimal(18,2)         COMMENT '批准经费额（元）',
    status          LowCardinality(String) COMMENT '生命周期状态 token（P/E 状态机）',
    apply_date      Date                  COMMENT '申报日期',
    start_date      Date                  COMMENT '立项/开始日期',
    end_date        Date                  COMMENT '计划结题日期',
    security_level  LowCardinality(String) COMMENT '密级（读取时按用户密级过滤）',
    fiscal_year     UInt16                COMMENT '立项财年（dim_time 派生）',
    etl_date        Date                  COMMENT 'ETL 批次日期'
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(apply_date)
ORDER BY (tenant_id, legal_entity_id, department_id, apply_date, apply_id)
COMMENT 'DWD 明细事实：项目申报/立项，清洗标准化，支撑在研项目数/立项数等指标下钻';

-- DWD 事实：经费报销（源 F，清洗后）
CREATE TABLE dwh.dwd_expense
(
    expense_id      UInt64                COMMENT '报销事实主键（源 F_EXPENSE.id）',
    tenant_id       UInt64                COMMENT '多租户隔离键',
    legal_entity_id UInt64                COMMENT '法人细分键',
    expense_code    String                COMMENT '报销单号 EXP-年-序',
    project_id      UInt64                COMMENT '项目代理键（关联 dwd_project_apply/业务项目）',
    department_id   UInt64                COMMENT '部门代理键（关联 dim_department）',
    subject_id      UInt64                COMMENT '科目代理键（关联 dim_subject）',
    apply_staff_id  UInt64                COMMENT '报销人代理键（关联 dim_staff）',
    amount          Decimal(18,2)         COMMENT '报销金额（元）',
    expense_type    LowCardinality(String) COMMENT '费用类型',
    status          LowCardinality(String) COMMENT '状态 token（清洗后统一）',
    expense_date    Date                  COMMENT '发生日期',
    paid_date       Nullable(Date)        COMMENT '实付日期（未付为空）',
    security_level  LowCardinality(String) COMMENT '密级',
    fiscal_year     UInt16                COMMENT '财年',
    fiscal_month    UInt8                 COMMENT '财月',
    etl_date        Date                  COMMENT 'ETL 批次日期'
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(expense_date)
ORDER BY (tenant_id, legal_entity_id, department_id, expense_date, expense_id)
COMMENT 'DWD 明细事实：经费报销，支撑经费执行率/到账支出画像，PI/部门/科目可下钻';

-- DWD 事实：成果（源 R）
CREATE TABLE dwh.dwd_output
(
    output_id       UInt64                COMMENT '成果事实主键（源 R_OUTPUT.id）',
    tenant_id       UInt64                COMMENT '多租户隔离键',
    legal_entity_id UInt64                COMMENT '法人细分键',
    output_code     String                COMMENT '成果编号',
    output_type     LowCardinality(String) COMMENT '类型：PAPER/PATENT/BOOK/AWARD/STANDARD',
    title           String                COMMENT '成果标题',
    journal         String                COMMENT '期刊/登记机构',
    publish_date    Date                  COMMENT '发表/授权日期',
    impact_factor   Decimal(9,4)          COMMENT '影响因子',
    cited_times     UInt32                COMMENT '被引次数',
    is_ns_series    UInt8                 COMMENT '是否 Nature/Science 系列（0/1）',
    district        LowCardinality(String) COMMENT '中科院分区/JCR 分区',
    first_author_staff_id UInt64          COMMENT '第一作者代理键（关联 dim_staff）',
    department_id   UInt64                COMMENT '署名部门代理键',
    project_id      UInt64                COMMENT '关联项目代理键（可空）',
    security_level  LowCardinality(String) COMMENT '密级',
    fiscal_year     UInt16                COMMENT '财年',
    etl_date        Date                  COMMENT 'ETL 批次日期'
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(publish_date)
ORDER BY (tenant_id, legal_entity_id, department_id, publish_date, output_id)
COMMENT 'DWD 明细事实：成果（论文/专利等），支撑篇均被引/NS 系列数/成果画像下钻';

-- DWD 事实：转化交易（源 T）
CREATE TABLE dwh.dwd_transfer_deal
(
    deal_id         UInt64                COMMENT '转化交易事实主键（源 T_DEAL.id）',
    tenant_id       UInt64                COMMENT '多租户隔离键',
    legal_entity_id UInt64                COMMENT '法人细分键',
    deal_code       String                COMMENT '交易编号 DEAL-年-序',
    output_id       UInt64                COMMENT '标的成果代理键',
    department_id   UInt64                COMMENT '承担部门代理键',
    pi_staff_id     UInt64                COMMENT '负责人代理键',
    deal_type       LowCardinality(String) COMMENT '转化方式（转让/许可/作价/合作）',
    contract_amount Decimal(18,2)         COMMENT '合同金额（元）',
    income_amount   Decimal(18,2)         COMMENT '到账金额（元）',
    distributed_amount Decimal(18,2)      COMMENT '已分配金额（元）',
    status          LowCardinality(String) COMMENT '交易状态 token（T 状态机）',
    signed_date     Nullable(Date)        COMMENT '签署日期',
    income_date     Nullable(Date)        COMMENT '到账日期',
    security_level  LowCardinality(String) COMMENT '密级',
    fiscal_year     UInt16                COMMENT '财年',
    etl_date        Date                  COMMENT 'ETL 批次日期'
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(income_date)
ORDER BY (tenant_id, legal_entity_id, department_id, income_date, deal_id)
COMMENT 'DWD 明细事实：科技成果转化交易，支撑转化收益/到账画像，联动模块 05';


-- =============================================================================
-- 【DWD 维度层】一致性维度（ReplacingMergeTree 按 etl_version 取最新，携带 legal_entity_id）
-- =============================================================================
CREATE TABLE dwh.dim_staff
(
    staff_id        UInt64                COMMENT '人员代理键（源 S_STAFF.id）',
    tenant_id       UInt64                COMMENT '多租户隔离键',
    legal_entity_id UInt64                COMMENT '法人细分键',
    staff_no        String                COMMENT '工号',
    staff_name      String                COMMENT '姓名',
    user_id         UInt64                COMMENT '关联 sys_user.id',
    title           LowCardinality(String) COMMENT '职称',
    education       LowCardinality(String) COMMENT '最高学历',
    department_id   UInt64                COMMENT '所属部门代理键',
    is_pi           UInt8                 COMMENT '是否项目负责人（0/1）',
    employment_status LowCardinality(String) COMMENT '雇佣状态 ONBOARD/RESIGNED/…',
    entry_date      Nullable(Date)        COMMENT '入职日期',
    security_level  LowCardinality(String) COMMENT '密级',
    etl_version     UInt64                COMMENT 'ETL 版本号（Replacing 取最新）'
)
ENGINE = ReplacingMergeTree(etl_version)
ORDER BY (tenant_id, legal_entity_id, staff_id)
COMMENT 'DWD 一致性维度：人员（PI 画像/团队分析），多法人下钻';

CREATE TABLE dwh.dim_department
(
    department_id   UInt64                COMMENT '部门代理键（源 sys_org.id）',
    tenant_id       UInt64                COMMENT '多租户隔离键',
    legal_entity_id UInt64                COMMENT '法人细分键',
    dept_code       String                COMMENT '部门编码',
    dept_name       String                COMMENT '部门名称',
    parent_dept_id  UInt64                COMMENT '上级部门代理键（组织树）',
    org_type        LowCardinality(String) COMMENT '节点类型 TOTAL_INSTITUTE/BRANCH_INSTITUTE/DEPT/LAB/PLATFORM',
    etl_version     UInt64                COMMENT 'ETL 版本号',
    _verified       UInt8                 COMMENT '法人校验通过（联动 X 法人树，未过标异常）'
)
ENGINE = ReplacingMergeTree(etl_version)
ORDER BY (tenant_id, legal_entity_id, department_id)
COMMENT 'DWD 一致性维度：部门/组织树（含法人层级），部门报表与下钻骨架';

CREATE TABLE dwh.dim_project_type
(
    type_id         UInt64                COMMENT '项目类型代理键',
    tenant_id       UInt64                COMMENT '多租户隔离键',
    type_code       String                COMMENT '类型编码',
    type_name       String                COMMENT '类型名称（纵向/横向/自选…）',
    fund_source_category LowCardinality(String) COMMENT '经费来源类别',
    etl_version     UInt64                COMMENT 'ETL 版本号'
)
ENGINE = ReplacingMergeTree(etl_version)
ORDER BY (tenant_id, type_id)
COMMENT 'DWD 一致性维度：项目类型（按类型切片分析）';

CREATE TABLE dwh.dim_subject
(
    subject_id      UInt64                COMMENT '科目代理键（源 F_SUBJECT.id）',
    tenant_id       UInt64                COMMENT '多租户隔离键',
    subject_code    String                COMMENT '科目编码',
    subject_name    String                COMMENT '科目名称',
    parent_subject_id UInt64              COMMENT '上级科目（树形）',
    subject_level   UInt8                 COMMENT '科目层级',
    etl_version     UInt64                COMMENT 'ETL 版本号'
)
ENGINE = ReplacingMergeTree(etl_version)
ORDER BY (tenant_id, subject_id)
COMMENT 'DWD 一致性维度：经费科目（科目维度支出结构分析）';

CREATE TABLE dwh.dim_time
(
    date_key        UInt32                COMMENT '日期代理键 yyyyMMdd',
    date            Date                  COMMENT '日期',
    year            UInt16                COMMENT '年',
    quarter         UInt8                 COMMENT '季',
    month           UInt8                 COMMENT '月',
    week            UInt8                 COMMENT '周（年内序）',
    day             UInt8                 COMMENT '日',
    is_weekend      UInt8                 COMMENT '是否周末（0/1）',
    fiscal_year     UInt16                COMMENT '财年',
    fiscal_month    UInt8                 COMMENT '财月'
)
ENGINE = MergeTree
ORDER BY (date_key)
COMMENT 'DWD 一致性维度：时间（年/季/月/周/财年下钻公共维度）';


-- =============================================================================
-- 【DWS 汇总层】轻度聚合主题宽表（SummingMergeTree，按尾列数值自动求和）
-- =============================================================================
CREATE TABLE dwh.dws_staff_yearly
(
    tenant_id       UInt64                COMMENT '多租户隔离键',
    legal_entity_id UInt64                COMMENT '法人细分键（合并=按法人主责去重聚合）',
    staff_id        UInt64                COMMENT '人员代理键',
    department_id   UInt64                COMMENT '部门代理键',
    fiscal_year     UInt16                COMMENT '年度',
    project_count   UInt64                COMMENT '承担项目数（可加度量）',
    approved_amount Decimal(18,2)         COMMENT '立项经费（可加度量）',
    expense_amount  Decimal(18,2)         COMMENT '报销支出（可加度量）',
    output_count    UInt64                COMMENT '成果数（可加度量）',
    cited_times     UInt64                COMMENT '被引合计（可加度量）',
    transfer_income Decimal(18,2)         COMMENT '转化到账收益（可加度量）',
    etl_date        Date                  COMMENT 'ETL 批次日期'
)
ENGINE = SummingMergeTree
PARTITION BY fiscal_year
ORDER BY (tenant_id, legal_entity_id, staff_id, fiscal_year)
COMMENT 'DWS 主题宽表：人员×年度（PI 画像/人均经费，Summing 累加尾列度量）';

CREATE TABLE dwh.dws_project_yearly
(
    tenant_id       UInt64                COMMENT '多租户隔离键',
    legal_entity_id UInt64                COMMENT '法人细分键',
    department_id   UInt64                COMMENT '部门代理键',
    project_type_id UInt64                COMMENT '项目类型代理键',
    fiscal_year     UInt16                COMMENT '年度',
    apply_count     UInt64                COMMENT '申报数',
    approved_count  UInt64                COMMENT '立项数',
    apply_amount    Decimal(18,2)         COMMENT '申报经费合计',
    approved_amount Decimal(18,2)         COMMENT '立项经费合计',
    expense_amount  Decimal(18,2)         COMMENT '支出合计',
    etl_date        Date                  COMMENT 'ETL 批次日期'
)
ENGINE = SummingMergeTree
PARTITION BY fiscal_year
ORDER BY (tenant_id, legal_entity_id, department_id, project_type_id, fiscal_year)
COMMENT 'DWS 主题宽表：项目×部门×类型×年度（立项数/经费执行率基础宽表）';

-- AggregatingMergeTree 示例：部门×月度（部分指标需去重/uniq，用 AggregateFunction 状态列）
CREATE TABLE dwh.dws_dept_monthly
(
    tenant_id       UInt64                COMMENT '多租户隔离键',
    legal_entity_id UInt64                COMMENT '法人细分键',
    department_id   UInt64                COMMENT '部门代理键',
    stat_year       UInt16                COMMENT '统计年',
    stat_month      UInt8                 COMMENT '统计月',
    expense_total   SimpleAggregateFunction(sum, Decimal(18,2)) COMMENT '支出合计（sum 状态）',
    budget_total    SimpleAggregateFunction(sum, Decimal(18,2)) COMMENT '预算合计（sum 状态）',
    active_prj      SimpleAggregateFunction(sum, UInt64)         COMMENT '在研项目数（sum 状态）',
    output_cnt      AggregateFunction(count, UInt64)             COMMENT '成果数（count 状态）',
    pi_uniq         AggregateFunction(uniq, UInt64)              COMMENT '活跃 PI 去重数（uniq 状态）',
    etl_date        Date                  COMMENT 'ETL 批次日期'
)
ENGINE = AggregatingMergeTree
PARTITION BY stat_year
ORDER BY (tenant_id, legal_entity_id, department_id, stat_year, stat_month)
COMMENT 'DWS 主题宽表：部门×月度（Aggregating 支持去重类指标，查询用 -Merge/-Final 终态）';


-- =============================================================================
-- 【ADS 应用层】面向驾驶舱 / 大屏 / 报送的结果表（MergeTree，直读前端 <1.5s）
-- =============================================================================
CREATE TABLE dwh.ads_leader_dashboard
(
    snapshot_date   Date                  COMMENT '快照日期（大屏顶部"数据截至日期"）',
    tenant_id       UInt64                COMMENT '多租户隔离键',
    legal_entity_id UInt64                COMMENT '法人：0=总院合并视图；非0=分法人下钻',
    active_project_count    UInt64        COMMENT '在研项目数（联动 D_METRIC 口径）',
    funding_received        Decimal(18,2) COMMENT '年度到账经费（元）',
    funding_expense         Decimal(18,2) COMMENT '年度支出（元）',
    execution_rate          Decimal(9,4)  COMMENT '经费执行率（比率）',
    output_count            UInt64        COMMENT '成果数',
    ns_series_count         UInt64        COMMENT 'Nature/Science 系列数',
    transfer_income         Decimal(18,2) COMMENT '转化收益（元）',
    risk_count              UInt64        COMMENT '风险预警条数',
    dq_flag                 LowCardinality(String) COMMENT '数据质量标注 OK/PARTIAL_MISSING',
    refreshed_at            DateTime      COMMENT 'ADS 刷新时间（T+1 04:00）',
    etl_date                Date          COMMENT 'ETL 批次日期'
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(snapshot_date)
ORDER BY (tenant_id, legal_entity_id, snapshot_date)
COMMENT 'ADS 应用结果：领导驾驶舱 KPI 卡（合并视图 legal_entity_id=0，下钻按法人）';

CREATE TABLE dwh.ads_funding_screen
(
    stat_date       Date                  COMMENT '统计日期',
    tenant_id       UInt64                COMMENT '多租户隔离键',
    legal_entity_id UInt64                COMMENT '法人细分键（0=合并）',
    department_id   UInt64                COMMENT '部门代理键',
    budget_amount   Decimal(18,2)         COMMENT '预算（元）',
    received_amount Decimal(18,2)         COMMENT '到账（元）',
    expense_amount  Decimal(18,2)         COMMENT '支出（元）',
    execution_rate  Decimal(9,4)          COMMENT '执行率',
    anomaly_count   UInt64                COMMENT '异常报销笔数（AI 复核命中）',
    dq_flag         LowCardinality(String) COMMENT '数据质量标注',
    etl_date        Date                  COMMENT 'ETL 批次日期'
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(stat_date)
ORDER BY (tenant_id, legal_entity_id, department_id, stat_date)
COMMENT 'ADS 应用结果：经费监督大屏（部门到账/支出/执行率/异常，60FPS 轮播取数）';

CREATE TABLE dwh.ads_transfer_screen
(
    stat_date       Date                  COMMENT '统计日期',
    tenant_id       UInt64                COMMENT '多租户隔离键',
    legal_entity_id UInt64                COMMENT '法人细分键（0=合并）',
    department_id   UInt64                COMMENT '部门代理键',
    deal_count      UInt64                COMMENT '转化交易数',
    contract_amount Decimal(18,2)         COMMENT '合同金额（元）',
    income_amount   Decimal(18,2)         COMMENT '到账金额（元）',
    distributed_amount Decimal(18,2)      COMMENT '已分配金额（元）',
    top_deal_codes  String                COMMENT '重点交易编号 JSON 文本（供大屏榜单）',
    dq_flag         LowCardinality(String) COMMENT '数据质量标注',
    etl_date        Date                  COMMENT 'ETL 批次日期'
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(stat_date)
ORDER BY (tenant_id, legal_entity_id, department_id, stat_date)
COMMENT 'ADS 应用结果：成果转化大屏（联动模块 05 T 事实，交易/合同/到账/分配）';
