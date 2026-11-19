"""E-7 activity 域：活动/参与人按租户收口（跨租户一律 404，不泄露存在性）。"""
import json

from django.test import Client

from apps.activity.models import VActivity, VActivityParticipant
from tests.conftest import bearer


def _c():
    return Client()


def _json(r):
    return json.loads(r.content.decode())


def _mk_activity(tenant_id: int = 1, title: str = "学术年会") -> VActivity:
    return VActivity.objects.create(
        tenant_id=tenant_id, status="DRAFT", creator_id=1,
        activity_type="CONFERENCE", title=title,
    )


def test_cross_tenant_activity_detail_is_404(seed_auth):
    a = _mk_activity()
    r = _c().get(f"/api/v1/activities/{a.id}", **bearer(2, ["R-STAFF"], tenant_id=2))
    assert r.status_code == 404
    assert _json(r)["code"] == 40401


def test_cross_tenant_activity_update_and_delete_are_404(seed_auth):
    a = _mk_activity()
    c = _c()
    # PUT/DELETE 在 policy 里只给 R-MANAGER，用他租户管理员令牌打（授权通过后才轮到租户判定）
    r = c.put(f"/api/v1/activities/{a.id}", data=json.dumps({"title": "被改了"}),
              content_type="application/json", **bearer(1, ["R-MANAGER"], tenant_id=2))
    assert r.status_code == 404
    r = c.delete(f"/api/v1/activities/{a.id}", **bearer(1, ["R-MANAGER"], tenant_id=2))
    assert r.status_code == 404

    a.refresh_from_db()
    assert a.title == "学术年会" and a.deleted == 0


def test_cross_tenant_activity_state_transitions_are_404(seed_auth):
    a = _mk_activity()
    c = _c()
    # 各动作的授权角色不同（submit=R-STAFF，approve/hold/cancel=R-MANAGER，archive=R-MANAGER）
    cases = (
        ("submit", 2, ["R-STAFF"]),
        ("approve", 1, ["R-MANAGER"]),
        ("hold", 1, ["R-MANAGER"]),
        ("cancel", 1, ["R-MANAGER"]),
        ("archive", 1, ["R-MANAGER"]),
    )
    for action, uid, roles in cases:
        r = c.post(f"/api/v1/activities/{a.id}/{action}", data=json.dumps({}),
                   content_type="application/json",
                   **bearer(uid, roles, tenant_id=2))
        assert r.status_code == 404, (action, r.status_code)

    a.refresh_from_db()
    assert a.status == "DRAFT"


def test_cross_tenant_participants_are_404(seed_auth):
    a = _mk_activity()
    p = VActivityParticipant.objects.create(
        activity_id=a.id, tenant_id=1, guest_name="外聘专家", role="SPEAKER")
    c = _c()

    r = c.get(f"/api/v1/activities/{a.id}/participants", **bearer(2, ["R-STAFF"], tenant_id=2))
    assert r.status_code == 404

    r = c.post(f"/api/v1/activities/{a.id}/participants",
               data=json.dumps({"guest_name": "混进来的", "role": "CHAIR"}),
               content_type="application/json", **bearer(2, ["R-STAFF"], tenant_id=2))
    assert r.status_code == 404

    r = c.delete(f"/api/v1/activities/{a.id}/participants/{p.id}",
                 **bearer(2, ["R-STAFF"], tenant_id=2))
    assert r.status_code == 404
    assert VActivityParticipant.objects.filter(id=p.id).exists()
