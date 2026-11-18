"""系统管理 API（对齐 Go internal/modules/sysadmin 全部端点行为）。

路由（挂 /api/v1）：
  GET  /auth/me
  GET|POST /admin/users          GET|PUT|DELETE /admin/users/{id}
  GET|POST /admin/roles          PUT|DELETE /admin/roles/{role_id}
  POST /admin/users/{id}/roles   DELETE /admin/users/{id}/roles/{role_id}
  GET|POST /admin/dicts          GET|DELETE /admin/dicts/{dict_id}
  POST /admin/dicts/{dict_id}/items        PUT|DELETE /admin/dicts/{dict_id}/items/{item_id}
  GET  /dicts/{code}             GET /page-grants   PUT /admin/page-grants
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import bcrypt
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.sysadmin.mappings import (
    dict_item_list,
    to_api_dict,
    to_api_dict_item,
    to_api_partner_org,
    to_api_role,
    to_api_user,
)
from apps.sysadmin.models import (
    PageGrant,
    SysDict,
    SysDictItem,
    SysPartnerOrg,
    SysRole,
    SysUser,
    SysUserRole,
)
from core.auth.casbin_util import build_caps
from core.auth.deps import domain_from
from core.httpx import (
    ApiError,
    CODE_BAD_REQUEST,
    CODE_CONFLICT,
    CODE_NOT_FOUND,
    CODE_ROLE_NOT_FOUND,
    CODE_UNKNOWN_PARAM,
    ok,
    read_json,
)


def page_args(request: HttpRequest) -> tuple[int, int, int, int]:
    try:
        page = int(request.GET.get("page", "1") or "1")
    except ValueError:
        page = 1
    try:
        size = int(request.GET.get("size", "20") or "20")
    except ValueError:
        size = 20
    if page < 1:
        page = 1
    if size < 1:
        size = 20
    if size > 200:
        size = 200
    return page, size, size, (page - 1) * size


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def role_codes_of(user_id: int) -> list[str]:
    return list(
        SysUserRole.objects.filter(user_id=user_id)
        .values_list("role__code", flat=True)
    )


# ---------------------------------------------------------------------------
# /auth/me
# ---------------------------------------------------------------------------
def get_me(request: HttpRequest):
    d = domain_from(request)
    codes = role_codes_of(d.user_id)
    roles = codes if codes else d.roles
    user = SysUser.objects.filter(id=d.user_id, tenant_id=d.tenant_id, deleted=0).first()
    if user is not None:
        user_obj = to_api_user(user, roles)
    else:
        user_obj = {"id": d.user_id, "security_level": d.security_level, "roles": roles}
    return ok(request, {"user": user_obj, "roles": roles, "caps": build_caps(roles)})


# ---------------------------------------------------------------------------
# 用户管理
# ---------------------------------------------------------------------------
def list_users(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = SysUser.objects.filter(tenant_id=d.tenant_id, deleted=0)
    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)
    kw = request.GET.get("keyword")
    if kw:
        like = f"%{kw}%"
        qs = qs.filter(
            Q(username__icontains=like)
            | Q(real_name__icontains=like)
            | Q(email__icontains=like)
            | Q(staff_no__icontains=like)
        )
    total = qs.count()
    rows = qs.order_by("id")[offset : offset + limit]
    return ok(
        request,
        {"list": [to_api_user(u, role_codes_of(u.id)) for u in rows],
         "total": total, "page": page, "size": size},
    )


def create_user(request: HttpRequest):
    d = domain_from(request)
    body = read_json(request)
    username = body.get("username")
    real_name = body.get("real_name")
    password = body.get("password")
    if not username or not real_name or not password:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    if SysUser.objects.filter(tenant_id=d.tenant_id, username=username, deleted=0).exists():
        raise ApiError(409, CODE_CONFLICT, "用户名已存在或写入冲突")
    u = SysUser.objects.create(
        username=username,
        real_name=real_name,
        password_hash=hash_password(password),
        email=body.get("email"),
        phone=body.get("phone"),
        staff_no=body.get("staff_no"),
        employment_status=body.get("employment_status") or "ONBOARD",
        security_level=body.get("security_level") or "INTERNAL",
        status="ACTIVE",
        tenant_id=d.tenant_id,
        creator_id=d.user_id,
    )
    for code in body.get("roles") or []:
        role = SysRole.objects.filter(tenant_id=d.tenant_id, code=code).first()
        if role is not None:  # 未知角色码忽略（对齐 Go）
            SysUserRole.objects.get_or_create(
                user_id=u.id, role_id=role.id, tenant_id=d.tenant_id
            )
    return ok(request, to_api_user(u, role_codes_of(u.id)))


def get_user(request: HttpRequest, id: int):
    d = domain_from(request)
    u = SysUser.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
    if u is None:
        raise ApiError(404, CODE_NOT_FOUND, "用户不存在")
    return ok(request, to_api_user(u, role_codes_of(u.id)))


def update_user(request: HttpRequest, id: int):
    d = domain_from(request)
    u = SysUser.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
    if u is None:
        raise ApiError(404, CODE_NOT_FOUND, "用户不存在")
    body = read_json(request)
    if body.get("real_name") is not None:
        u.real_name = body["real_name"]
    if body.get("email") is not None:
        u.email = body["email"]
    if body.get("phone") is not None:
        u.phone = body["phone"]
    if body.get("security_level") is not None:
        u.security_level = body["security_level"]
    if body.get("status") is not None:
        u.status = body["status"]
    if body.get("password"):
        u.password_hash = hash_password(body["password"])
    u.modifier_id = d.user_id
    u.save()
    return ok(request, to_api_user(u, role_codes_of(u.id)))


def delete_user(request: HttpRequest, id: int):
    d = domain_from(request)
    u = SysUser.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
    if u is None:
        raise ApiError(404, CODE_NOT_FOUND, "用户不存在")
    u.deleted = 1
    u.status = "DISABLED"
    u.modifier_id = d.user_id
    u.save()
    return ok(request, {"id": id, "deleted": True})


# ---------------------------------------------------------------------------
# 角色目录
# ---------------------------------------------------------------------------
def list_roles(request: HttpRequest):
    d = domain_from(request)
    rows = SysRole.objects.filter(tenant_id=d.tenant_id).order_by("id")
    return ok(request, {"list": [to_api_role(r) for r in rows]})


def create_role(request: HttpRequest):
    d = domain_from(request)
    body = read_json(request)
    code = body.get("code")
    name = body.get("name")
    if not code or not name or len(code) > 32 or len(name) > 64:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    if SysRole.objects.filter(tenant_id=d.tenant_id, code=code).exists():
        raise ApiError(409, CODE_CONFLICT, "角色编码已存在")
    r = SysRole.objects.create(code=code, name=name, is_builtin=False, tenant_id=d.tenant_id)
    return ok(request, to_api_role(r))


def update_role(request: HttpRequest, role_id: int):
    d = domain_from(request)
    body = read_json(request)
    name = body.get("name")
    if not name or len(name) > 64:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    r = SysRole.objects.filter(id=role_id, tenant_id=d.tenant_id).first()
    if r is None:
        raise ApiError(404, CODE_NOT_FOUND, "角色不存在")
    r.name = name
    r.save()
    return ok(request, to_api_role(r))


def delete_role(request: HttpRequest, role_id: int):
    d = domain_from(request)
    r = SysRole.objects.filter(id=role_id, tenant_id=d.tenant_id).first()
    if r is None:
        raise ApiError(404, CODE_NOT_FOUND, "角色不存在")
    if r.is_builtin:
        raise ApiError(409, CODE_CONFLICT, "内置角色不可删除")
    n = SysUserRole.objects.filter(role_id=role_id).count()
    if n > 0:
        raise ApiError(409, CODE_CONFLICT, f"角色已绑定 {n} 个用户，请先解除绑定")
    r.delete()
    return ok(request, {"id": role_id, "deleted": True})


def assign_role(request: HttpRequest, id: int):
    d = domain_from(request)
    body = read_json(request)
    role_id = body.get("role_id")
    if not role_id:
        raise ApiError(400, CODE_BAD_REQUEST, "role_id 必填")
    if not SysRole.objects.filter(id=role_id, tenant_id=d.tenant_id).exists():
        raise ApiError(404, CODE_ROLE_NOT_FOUND, "角色不存在或跨租户")
    u = SysUser.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
    if u is None:
        raise ApiError(404, CODE_NOT_FOUND, "用户不存在")
    SysUserRole.objects.get_or_create(user_id=id, role_id=role_id, tenant_id=d.tenant_id)
    return ok(request, to_api_user(u, role_codes_of(id)))


def revoke_role(request: HttpRequest, id: int, role_id: int):
    d = domain_from(request)
    u = SysUser.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
    if u is None:
        raise ApiError(404, CODE_NOT_FOUND, "用户不存在")
    SysUserRole.objects.filter(user_id=id, role_id=role_id, tenant_id=d.tenant_id).delete()
    return ok(request, to_api_user(u, role_codes_of(id)))


# ---------------------------------------------------------------------------
# 数据字典（PRD 2.8）
# ---------------------------------------------------------------------------
def list_dicts(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = SysDict.objects.filter(tenant_id=d.tenant_id, deleted=0)
    kw = request.GET.get("keyword")
    if kw:
        qs = qs.filter(Q(code__icontains=kw) | Q(name__icontains=kw))
    total = qs.count()
    rows = qs.order_by("id")[offset : offset + limit]
    return ok(request, {"list": [to_api_dict(r) for r in rows], "total": total, "page": page, "size": size})


def upsert_dict(request: HttpRequest):
    d = domain_from(request)
    body = read_json(request)
    code = body.get("code")
    name = body.get("name")
    if not code or not name or len(code) > 64 or len(name) > 128:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    row = SysDict.objects.filter(tenant_id=d.tenant_id, code=code, deleted=0).first()
    if row is None:
        row = SysDict.objects.create(
            code=code, name=name, tenant_id=d.tenant_id,
            remark=body.get("remark"), creator_id=d.user_id,
        )
    else:
        row.name = name
        row.remark = body.get("remark")
        row.modifier_id = d.user_id
        row.save()
    return ok(request, to_api_dict(row))


def get_dict(request: HttpRequest, dict_id: int):
    d = domain_from(request)
    row = SysDict.objects.filter(id=dict_id, tenant_id=d.tenant_id, deleted=0).first()
    if row is None:
        raise ApiError(404, CODE_NOT_FOUND, "字典不存在")
    items = SysDictItem.objects.filter(dict_id=dict_id, tenant_id=d.tenant_id).order_by("sort_no", "id")
    out = to_api_dict(row)
    out["items"] = dict_item_list(items)
    return ok(request, out)


def delete_dict(request: HttpRequest, dict_id: int):
    d = domain_from(request)
    row = SysDict.objects.filter(id=dict_id, tenant_id=d.tenant_id, deleted=0).first()
    if row is None:
        raise ApiError(404, CODE_NOT_FOUND, "字典不存在")
    row.deleted = 1
    row.modifier_id = d.user_id
    row.save()
    return ok(request, {"id": dict_id, "deleted": True})


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def upsert_dict_item(request: HttpRequest, dict_id: int, item_id: int = None):
    d = domain_from(request)
    if not SysDict.objects.filter(id=dict_id, tenant_id=d.tenant_id, deleted=0).exists():
        raise ApiError(404, CODE_NOT_FOUND, "字典不存在")
    body = read_json(request)
    item_code = body.get("item_code")
    item_label = body.get("item_label")
    if not item_code or not item_label:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    eff_from = _parse_date(body.get("effective_from"))
    eff_to = _parse_date(body.get("effective_to"))
    row = SysDictItem.objects.filter(
        dict_id=dict_id, tenant_id=d.tenant_id, item_code=item_code,
        effective_from=eff_from,
    ).first()
    if row is None:
        row = SysDictItem.objects.create(
            dict_id=dict_id, tenant_id=d.tenant_id, item_code=item_code,
            item_label=item_label, parent_id=body.get("parent_id"),
            ext_json=body.get("ext"), i18n_json=body.get("i18n"),
            sort_no=body.get("sort_no") or 0,
            active=body.get("active", True),
            effective_from=eff_from, effective_to=eff_to,
        )
    else:
        row.item_label = item_label
        row.parent_id = body.get("parent_id")
        row.ext_json = body.get("ext")
        row.i18n_json = body.get("i18n")
        row.sort_no = body.get("sort_no") or row.sort_no
        row.active = body.get("active", row.active)
        row.effective_to = eff_to
        row.save()
    return ok(request, to_api_dict_item(row))


def delete_dict_item(request: HttpRequest, dict_id: int, item_id: int):
    d = domain_from(request)
    n = SysDictItem.objects.filter(
        id=item_id, dict_id=dict_id, tenant_id=d.tenant_id
    ).delete()[0]
    if n == 0:
        raise ApiError(404, CODE_NOT_FOUND, "条目不存在")
    return ok(request, {"id": item_id, "deleted": True})


def get_dict_by_code(request: HttpRequest, code: str):
    d = domain_from(request)
    row = SysDict.objects.filter(tenant_id=d.tenant_id, code=code, deleted=0).first()
    if row is None:
        raise ApiError(404, CODE_NOT_FOUND, "字典不存在")
    today = dj_tz.localdate()
    items = SysDictItem.objects.filter(dict_id=row.id, tenant_id=d.tenant_id, active=True).filter(
        Q(effective_from__isnull=True) | Q(effective_from__lte=today)
    ).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=today)
    ).order_by("sort_no", "id")
    out = to_api_dict(row)
    out["items"] = dict_item_list(items)
    return ok(request, out)


# ---------------------------------------------------------------------------
# 页面可见性矩阵（PRD 2.9）
# ---------------------------------------------------------------------------
def _grant_list(request: HttpRequest) -> list[dict]:
    d = domain_from(request)
    rows = PageGrant.objects.filter(tenant_id=d.tenant_id).order_by("page_name", "role_code")
    return [{"page_name": r.page_name, "role_code": r.role_code} for r in rows]


def list_page_grants(request: HttpRequest):
    return ok(request, {"grants": _grant_list(request)})


def save_page_grants(request: HttpRequest):
    d = domain_from(request)
    body = read_json(request)
    grants = body.get("grants") or []
    for g in grants:
        if not g.get("page_name") or not g.get("role_code"):
            raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
        if len(g["page_name"]) > 64 or len(g["role_code"]) > 64:
            raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
        if g["role_code"] == "*":
            continue
        if not SysRole.objects.filter(tenant_id=d.tenant_id, code=g["role_code"]).exists():
            raise ApiError(400, CODE_UNKNOWN_PARAM, "未知角色码：" + g["role_code"])
    with transaction.atomic():
        PageGrant.objects.filter(tenant_id=d.tenant_id).delete()
        PageGrant.objects.bulk_create(
            [
                PageGrant(tenant_id=d.tenant_id, page_name=g["page_name"], role_code=g["role_code"])
                for g in grants
            ]
        )
    return ok(request, {"grants": _grant_list(request)})


def update_dict_item(request: HttpRequest, dict_id: int, item_id: int):
    """PUT 语义：同 upsert（item_code+生效期构成身份，对齐 Go UpdateDictItem→UpsertDictItem）。"""
    return upsert_dict_item(request, dict_id)


# ---------------------------------------------------------------------------
# 接口权限管理（Django auth_permission / Group.permissions 风格）
# ---------------------------------------------------------------------------
def _permission_row(p, holder_roles: dict[int, set[str]]) -> dict:
    return {
        "id": p.id, "code": p.code, "name": p.name, "obj": p.obj, "act": p.act,
        "domain": p.domain, "roles": sorted(holder_roles.get(p.id, set())),
    }


def list_permissions(request: HttpRequest):
    """GET /admin/permissions?role_code=&domain=&q=&page=&size=

    权限目录 + 指派矩阵（每个权限被哪些角色持有）。供「角色与权限」页渲染。
    """
    from apps.sysadmin.models import SysPermission, SysRolePermission

    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = SysPermission.objects.all().order_by("domain", "obj", "act")
    role_code = request.GET.get("role_code") or ""
    domain = request.GET.get("domain") or ""
    q = request.GET.get("q") or ""
    holder: dict[int, set[str]] = {}
    links = SysRolePermission.objects.select_related("role", "permission")
    if role_code:
        links = links.filter(role__code=role_code)
    for lk in links:
        holder.setdefault(lk.permission_id, set()).add(lk.role.code)
    # role_code 仅用于标注该角色持有状态（holder），不裁剪目录：
    # 勾选面板必须展示全量权限，未持有的行 roles=[]，供角色勾选新授权。
    if domain:
        qs = qs.filter(domain=domain)
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q) | Q(obj__icontains=q))
    total = qs.count()
    rows = list(qs[offset:offset + limit])
    # role_code 过滤时 holder 字典只含该角色的指派；全量时含所有角色
    domains = sorted(set(SysPermission.objects.values_list("domain", flat=True)))
    return ok(request, {
        "total": total, "page": page, "size": size,
        "domains": domains,
        "items": [_permission_row(p, holder) for p in rows],
    })


def list_role_permissions(request: HttpRequest, role_code: str):
    """GET /admin/roles/{role_code}/permissions —— 该角色持有的权限码集合。"""
    from apps.sysadmin.models import SysRolePermission

    role = SysRole.objects.filter(tenant_id=domain_from(request).tenant_id,
                                  code=role_code).first()
    if role is None:
        raise ApiError(404, CODE_NOT_FOUND, "角色不存在")
    codes = list(
        SysRolePermission.objects.filter(role=role)
        .values_list("permission__code", flat=True)
    )
    return ok(request, {"role": role_code, "permissions": sorted(codes)})


def update_role_permissions(request: HttpRequest, role_code: str):
    """PUT /admin/roles/{role_code}/permissions

    body: {"grants": ["code", ...], "revokes": ["code", ...]}
    授权/回收后 casbin enforcer 热重载（当前进程立即生效）。
    """
    from core.auth.casbin_util import broadcast_reload
    from apps.sysadmin.models import SysPermission, SysRolePermission

    d = domain_from(request)
    role = SysRole.objects.filter(tenant_id=d.tenant_id, code=role_code).first()
    if role is None:
        raise ApiError(404, CODE_NOT_FOUND, "角色不存在")
    body = read_json(request)
    grants = body.get("grants") or []
    revokes = body.get("revokes") or []
    if not isinstance(grants, list) or not isinstance(revokes, list):
        raise ApiError(400, CODE_BAD_REQUEST, "grants/revokes 必须为数组")
    overlap = set(grants) & set(revokes)
    if overlap:
        raise ApiError(400, CODE_BAD_REQUEST, f"同一权限不能同时授权与回收：{sorted(overlap)[:5]}")

    with transaction.atomic():
        grant_objs = list(SysPermission.objects.filter(code__in=grants))
        missing = set(grants) - {p.code for p in grant_objs}
        if missing:
            raise ApiError(400, CODE_UNKNOWN_PARAM, f"未知权限码：{sorted(missing)[:5]}")
        created = 0
        for p in grant_objs:
            _, c = SysRolePermission.objects.get_or_create(
                role=role, permission=p, defaults={"granted_by": d.user_id}
            )
            created += int(c)
        removed, _ = SysRolePermission.objects.filter(
            role=role, permission__code__in=revokes
        ).delete()
    broadcast_reload()  # 本进程立即重载 + Redis 广播（多 worker 全量热生效）
    codes = list(
        SysRolePermission.objects.filter(role=role)
        .values_list("permission__code", flat=True)
    )
    return ok(request, {
        "role": role_code, "granted": created, "revoked": removed,
        "permissions": sorted(codes),
    })


# ===========================================================================
# M2-a 外部机构：自助注册 + 门户（隔离维度＝org_id，tenant 仍为主办方）
# ===========================================================================

_ORG_TYPES = ("COLLAB", "SUPPLIER", "UNIVERSITY", "INSTITUTE")


def _notify_role_inapp(
    tenant_id: int, role_code: str, typ: str, title: str, content: str, biz_ref: str
) -> int:
    """给某角色全部在用用户投站内信（best-effort，失败不阻断业务）。"""
    from apps.notify.models import SysNotification

    try:
        uids = list(
            SysUserRole.objects.filter(
                role__code=role_code, tenant_id=tenant_id
            ).values_list("user_id", flat=True)
        )
        for uid in uids:
            SysNotification.objects.create(
                tenant_id=tenant_id,
                user_id=uid,
                typ=typ,
                title=title,
                content=content,
                biz_ref=biz_ref,
            )
        return len(uids)
    except Exception:  # pragma: no cover - 通知永不阻断主流程
        return 0


def _partner_org_or_404(tenant_id: int, org_id: int) -> SysPartnerOrg:
    o = SysPartnerOrg.objects.filter(
        id=org_id, tenant_id=tenant_id, deleted=0
    ).first()
    if o is None:
        raise ApiError(404, CODE_NOT_FOUND, "机构不存在")
    return o


def _my_partner_org(tenant_id: int, user_id: int) -> SysPartnerOrg:
    """当前外部用户所属机构；无 org_id（内部用户）或机构已删 → 404（不泄露存在性）。"""
    u = SysUser.objects.filter(id=user_id, tenant_id=tenant_id, deleted=0).first()
    if u is None or u.org_id is None:
        raise ApiError(404, CODE_NOT_FOUND, "机构不存在")
    return _partner_org_or_404(tenant_id, u.org_id)


def _str_field(body: dict, key: str, label: str, *, max_len: int, required: bool = True) -> str:
    raw = body.get(key)
    val = raw.strip() if isinstance(raw, str) else ""
    if not val:
        if required:
            raise ApiError(400, CODE_BAD_REQUEST, f"{label}不能为空")
        return ""
    if len(val) > max_len:
        raise ApiError(400, CODE_BAD_REQUEST, f"{label}超长（最多 {max_len} 字符）")
    return val


def _validate_password(pwd: str) -> None:
    if len(pwd) < 8:
        raise ApiError(400, CODE_BAD_REQUEST, "口令至少 8 位")
    if pwd.isdigit():
        raise ApiError(400, CODE_BAD_REQUEST, "口令不能为纯数字")
    if not any(c.isalpha() for c in pwd):
        raise ApiError(400, CODE_BAD_REQUEST, "口令须同时包含字母")


def register_partner(request: HttpRequest) -> object:
    """公开自助注册：建 PENDING 机构 + LOCKED 账号（未审核不可登录）。

    无 domain 上下文（无登录态），tenant 取 body.tenant_id 或 1。
    """
    body = read_json(request)
    try:
        tenant_id = int(body.get("tenant_id") or 1)
    except (TypeError, ValueError):
        raise ApiError(400, CODE_BAD_REQUEST, "tenant_id 非法") from None

    org_name = _str_field(body, "org_name", "机构名称", max_len=256)
    credit_code = _str_field(body, "credit_code", "统一社会信用代码", max_len=64)
    if len(credit_code) != 18 or not credit_code[0].isalnum():
        raise ApiError(400, CODE_BAD_REQUEST, "统一社会信用代码须为 18 位")
    org_type = (body.get("org_type") or "COLLAB")
    if org_type not in _ORG_TYPES:
        raise ApiError(400, CODE_BAD_REQUEST, f"机构类型须为 {list(_ORG_TYPES)} 之一")
    contact_name = _str_field(body, "contact_name", "联系人", max_len=64)
    contact_phone = _str_field(body, "contact_phone", "联系电话", max_len=32)
    contact_email = _str_field(body, "contact_email", "联系邮箱", max_len=128)
    if "@" not in contact_email:
        raise ApiError(400, CODE_BAD_REQUEST, "联系邮箱格式不正确")
    username = _str_field(body, "username", "登录名", max_len=64)
    if len(username) < 3:
        raise ApiError(400, CODE_BAD_REQUEST, "登录名至少 3 位")
    real_name = _str_field(body, "real_name", "姓名", max_len=64)
    password = body.get("password")
    if not isinstance(password, str):
        raise ApiError(400, CODE_BAD_REQUEST, "口令不能为空")
    _validate_password(password)
    address = _str_field(body, "address", "地址", max_len=256, required=False)

    if SysPartnerOrg.objects.filter(
        tenant_id=tenant_id, credit_code=credit_code, deleted=0
    ).exists():
        raise ApiError(409, CODE_CONFLICT, "机构或用户名已注册")
    if SysUser.objects.filter(
        tenant_id=tenant_id, username=username, deleted=0
    ).exists():
        raise ApiError(409, CODE_CONFLICT, "机构或用户名已注册")

    with transaction.atomic():
        org = SysPartnerOrg.objects.create(
            code="",  # 建行后按 id 回填 PTN-年-序
            tenant_id=tenant_id,
            name=org_name,
            credit_code=credit_code,
            org_type=org_type,
            contact_name=contact_name,
            contact_phone=contact_phone,
            contact_email=contact_email,
            address=address or None,
            status="PENDING",
            creator_id=1,  # 自助注册无登录态
            remark="self-register",
        )
        org.code = f"PTN-{dj_tz.localdate().year}-{org.id:06d}"
        org.save(update_fields=["code"])
        SysUser.objects.create(
            username=username,
            real_name=real_name,
            email=contact_email,
            phone=contact_phone,
            password_hash=hash_password(password),
            status="LOCKED",  # 未审核：既有登录逻辑对非 ACTIVE 一律 40302
            tenant_id=tenant_id,
            org_id=org.id,
            user_source="EXTERNAL",
            creator_id=1,
            remark="self-register",
        )
    _notify_role_inapp(
        tenant_id,
        "R-MANAGER",
        "TODO",
        "外部机构待审核",
        f"{org.name}（{org.credit_code}）提交了机构注册申请，请审核资质。",
        f"partner-org:{org.id}",
    )
    return ok(request, to_api_partner_org(org))


def list_partner_orgs(request: HttpRequest) -> object:
    """机构列表（R-MANAGER 审核台）：status/keyword 过滤，按 id 倒序。"""
    d = domain_from(request)
    page, size, _, offset = page_args(request)
    qs = SysPartnerOrg.objects.filter(tenant_id=d.tenant_id, deleted=0)
    status = (request.GET.get("status") or "").strip()
    if status:
        qs = qs.filter(status=status)
    kw = (request.GET.get("keyword") or "").strip()
    if kw:
        qs = qs.filter(Q(name__icontains=kw) | Q(credit_code__icontains=kw))
    total = qs.count()
    rows = qs.order_by("-id")[offset : offset + size]
    return ok(request, {
        "list": [to_api_partner_org(o) for o in rows],
        "total": total, "page": page, "size": size,
    })


def audit_partner_org(request: HttpRequest, id: int) -> object:
    """机构资质审核：APPROVE → 机构 APPROVED + 账号 ACTIVE + 授 R-PARTNER + 双通道通知。

    REJECT → 机构 REJECTED（必须给理由），账号保持 LOCKED。
    """
    from apps.notify.email import notify_inapp, send_mail_best_effort

    d = domain_from(request)
    body = read_json(request)
    action = (body.get("action") or "").strip().upper()
    if action not in ("APPROVE", "REJECT"):
        raise ApiError(400, CODE_BAD_REQUEST, "action 须为 APPROVE 或 REJECT")

    with transaction.atomic():
        org = _partner_org_or_404(d.tenant_id, id)
        if action == "APPROVE":
            if org.status == "APPROVED":  # 幂等：不重复授角色/重复通知
                return ok(request, to_api_partner_org(org))
            reason = None
        else:
            reason = _str_field(body, "reason", "驳回理由", max_len=512)
            if org.status == "REJECTED":
                return ok(request, to_api_partner_org(org))

        org.status = "APPROVED" if action == "APPROVE" else "REJECTED"
        org.audit_user_id = d.user_id
        org.audited_at = dj_tz.now()
        org.reject_reason = reason
        org.modifier_id = d.user_id
        org.save(
            update_fields=[
                "status", "audit_user_id", "audited_at", "reject_reason",
                "modifier_id", "updated_at",
            ]
        )

        user = SysUser.objects.filter(
            tenant_id=d.tenant_id, org_id=org.id, deleted=0
        ).first()
        if action == "APPROVE" and user is not None:
            user.status = "ACTIVE"
            user.modifier_id = d.user_id
            user.save(update_fields=["status", "modifier_id", "updated_at"])
            role = SysRole.objects.filter(code="R-PARTNER", tenant_id=d.tenant_id).first()
            if role is not None:
                SysUserRole.objects.get_or_create(
                    user_id=user.id, role_id=role.id,
                    defaults={"tenant_id": d.tenant_id},
                )

    # 通知（事务外，best-effort，绝不阻断审核）
    if user is not None:
        try:
            if action == "APPROVE":
                title = "机构资质审核通过"
                content = f"{org.name} 的注册申请已通过，可登录机构门户。"
                notify_inapp(d.tenant_id, user.id, "ANNOUNCE", title, content,
                             f"partner-org:{org.id}", channel="BOTH")
                send_mail_best_effort(
                    org.contact_email, title, content,
                    tenant_id=d.tenant_id, biz_ref=f"partner-org:{org.id}",
                )
            else:
                notify_inapp(d.tenant_id, user.id, "ANNOUNCE", "机构资质审核未通过",
                             f"{org.name} 的注册申请未通过：{reason}",
                             f"partner-org:{org.id}")
        except Exception:  # pragma: no cover - 通知永不阻断
            pass
    return ok(request, to_api_partner_org(org))
