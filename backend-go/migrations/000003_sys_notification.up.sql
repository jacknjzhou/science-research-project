-- 000003_sys_notification.up.sql · 通知中心（T8）。手写增量迁移（不参与 go generate）。
-- 读模型：PushRole 在写入侧扇出为每用户一行，读路径只按 user_id 查询（无 role join）。
-- typ：TODO 待办 / MESSAGE 站内消息 / WARNING 预警 / ANNOUNCE 公告（P6 任务中心复用）。

CREATE TABLE sys_notification (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id  BIGINT       NOT NULL,
  user_id    BIGINT       NOT NULL,                -- 收件人
  typ        VARCHAR(16)  NOT NULL DEFAULT 'TODO'
             CHECK (typ IN ('TODO','MESSAGE','WARNING','ANNOUNCE')),
  title      VARCHAR(200) NOT NULL,
  content    TEXT,
  biz_ref    VARCHAR(128),                         -- 业务定位串（如 expense/123）
  read_at    TIMESTAMPTZ,
  created_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_notif_user ON sys_notification(user_id, created_at DESC);
CREATE INDEX idx_notif_unread ON sys_notification(user_id) WHERE read_at IS NULL;
