"""M2-a C5 最小实现：邮件通道 best-effort + 通知渠道列。"""
from __future__ import annotations

import pytest

from django.core import mail

from apps.notify.email import notify_inapp, send_mail_best_effort

pytestmark = pytest.mark.django_db


def test_send_mail_writes_outbox():
    assert send_mail_best_effort("a@b.com", "主题", "正文", tenant_id=1) is True
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["a@b.com"]


def test_send_mail_swallows_failure(monkeypatch):
    import apps.notify.email as m

    def boom(*a, **k):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(m, "send_mail", boom)
    assert send_mail_best_effort("a@b.com", "s", "b", tenant_id=1) is False  # 绝不抛出


def test_send_mail_skips_invalid_address():
    assert send_mail_best_effort("not-an-email", "s", "b", tenant_id=1) is False
    assert send_mail_best_effort(None, "s", "b", tenant_id=1) is False
    assert mail.outbox == []


def test_notify_inapp_marks_channel():
    n = notify_inapp(1, 7, "TODO", "标题", "正文", "ref:1")
    assert n.channel == "INAPP" and n.user_id == 7
