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
    to_api_role,
    to_api_user,
)
from apps.sysadmin.models import PageGrant, SysDict, SysDictItem, SysRole, SysUser, SysUserRole
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
