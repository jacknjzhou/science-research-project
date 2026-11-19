"""通知出站通道（M2-a C5 最小实现）。

两个职责：
- `send_mail_best_effort`：邮件下发，任何异常只记日志，**绝不抛出**（审核等业务不因 SMTP 挂掉而失败）；
- `notify_inapp`：站内信落库薄封装（写 SysNotification，带 channel 标记）。

`send_mail` 在模块级导入，便于测试 monkeypatch 该名字。
"""
from __future__ import annotations

import logging

from django.core.mail import send_mail

from apps.notify.models import SysNotification

logger = logging.getLogger(__name__)

CHANNEL_INAPP = "INAPP"
CHANNEL_EMAIL = "EMAIL"
CHANNEL_BOTH = "BOTH"


def _valid_address(to: str | None) -> str:
    addr = (to or "").strip()
    if not addr or "@" not in addr or " " in addr:
        return ""
    return addr


def send_mail_best_effort(
    to: str | None, subject: str, body: str, *, tenant_id: int, biz_ref: str = ""
) -> bool:
    """发一封邮件；成功 True，任何失败（含地址非法）False，永不抛出。"""
    addr = _valid_address(to)
    if not addr:
        logger.info(
            "skip mail: invalid address tenant=%s biz_ref=%s", tenant_id, biz_ref
        )
        return False
    try:
        sent = send_mail(subject, body, None, [addr], fail_silently=False)
        return int(sent or 0) > 0
    except Exception:  # noqa: BLE001 - 通道故障不得影响业务主流程
        logger.warning(
            "send mail failed tenant=%s biz_ref=%s to=%s",
            tenant_id,
            biz_ref,
            addr,
            exc_info=True,
        )
        return False


def notify_inapp(
    tenant_id: int,
    user_id: int,
    typ: str,
    title: str,
    content: str | None,
    biz_ref: str | None,
    channel: str = CHANNEL_INAPP,
) -> SysNotification:
    """写一条站内信（channel 标记投递渠道，供前端/审计区分）。"""
    return SysNotification.objects.create(
        tenant_id=tenant_id,
        user_id=user_id,
        typ=typ,
        title=title,
        content=content,
        biz_ref=biz_ref,
        channel=channel,
    )


def notify_user(
    tenant_id: int,
    user_id: int,
    typ: str,
    title: str,
    content: str | None,
    biz_ref: str | None = None,
) -> SysNotification:
    """统一投递（C5）：站内信落库 + best-effort 邮件到该用户邮箱。

    邮件失败不影响站内信；用户不存在/无邮箱时只落站内信。
    """
    from apps.sysadmin.models import SysUser

    row = notify_inapp(
        tenant_id, user_id, typ, title, content, biz_ref, channel=CHANNEL_BOTH
    )
    try:
        u = SysUser.objects.filter(id=user_id, tenant_id=tenant_id, deleted=0).first()
        addr = getattr(u, "email", None) if u is not None else None
        if addr:
            send_mail_best_effort(
                addr, title, content or title, tenant_id=tenant_id, biz_ref=biz_ref or ""
            )
    except Exception:  # noqa: BLE001 - 通知永不阻断业务
        logger.warning("notify_user mail branch failed user=%s", user_id, exc_info=True)
    return row
