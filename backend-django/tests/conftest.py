"""测试夹具：fakeredis 注入 + 演示用户/角色 + JWT 辅助。"""
from __future__ import annotations

import pytest

from core import redis_util
from core.auth.jwt_util import gen_token

ADMIN_PW_HASH = "$2a$10$a1Cu2YSk60mLMlTC7Mq5t.DzD7Suj.jUkigRj1YNdKFRLPb61XTR2"  # Admin@123456


@pytest.fixture
def fakeredis_client(monkeypatch):
    import fakeredis

    client = fakeredis.FakeRedis()
    monkeypatch.setattr(redis_util, "get_client", lambda: client)
    return client


@pytest.fixture
def seed_auth(db):
    """8 基础角色 + admin/staff 演示用户（对齐 Go 000002 种子语义）。"""
    from apps.sysadmin.models import SysRole, SysUser, SysUserRole

    roles = {}
    for code, name in [
        ("R-STAFF", "科研人员"),
        ("R-MANAGER", "科研管理岗"),
        ("R-LEADER", "单位领导"),
        ("R-FINANCE", "财务"),
        ("R-AUDITOR", "审计"),
        ("R-EXPERT", "评审专家"),
        ("R-ETHICS", "伦理委员会"),
        ("R-ADMIN", "系统管理员"),
    ]:
        # 数据迁移 0003 已按 policy.csv 创建同名角色行，这里幂等取用
        role, _ = SysRole.objects.get_or_create(
            code=code, tenant_id=1, defaults={"name": name, "is_builtin": True}
        )
        roles[code] = role

    admin = SysUser.objects.create(
        username="admin", real_name="系统管理员", password_hash=ADMIN_PW_HASH,
        security_level="TOP_SECRET", status="ACTIVE", tenant_id=1, creator_id=1,
    )
    staff = SysUser.objects.create(
        username="staff", real_name="一线研究员", password_hash=ADMIN_PW_HASH,
        security_level="INTERNAL", status="ACTIVE", tenant_id=1, creator_id=1,
    )
    SysUserRole.objects.create(user=admin, role=roles["R-ADMIN"], tenant_id=1)
    SysUserRole.objects.create(user=staff, role=roles["R-STAFF"], tenant_id=1)
    return {"roles": roles, "admin": admin, "staff": staff}


@pytest.fixture
def seed_pages(db):
    """页面矩阵种子（对齐 Go 000014 的两条代表行）。"""
    from apps.sysadmin.models import PageGrant

    PageGrant.objects.create(tenant_id=1, page_name="dash", role_code="*")
    PageGrant.objects.create(tenant_id=1, page_name="bigscreen", role_code="R-LEADER")


@pytest.fixture
def seed_notify(db):
    """通知种子：staff 两读一未读。"""
    from apps.notify.models import SysNotification

    SysNotification.objects.create(
        tenant_id=1, user_id=2, typ="TODO", title="待办A", biz_ref="expense/1")
    SysNotification.objects.create(
        tenant_id=1, user_id=2, typ="WARNING", title="预警B")
    SysNotification.objects.create(
        tenant_id=1, user_id=2, typ="MESSAGE", title="已读C",
        read_at="2026-10-17T01:00:00Z")


def bearer(user_id: int, roles: list[str], tenant_id: int = 1) -> dict:
    tok = gen_token(user_id, tenant_id, 0, "INTERNAL", roles)
    return {"HTTP_AUTHORIZATION": f"Bearer {tok}"}
