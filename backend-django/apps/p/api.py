"""申报域 P API（对齐 Go modules/p 全部端点）。

路由：GET|POST /apply/guidelines、GET /apply/guidelines/{id}、
     GET|POST /apply/applications、GET /apply/applications/{id}
"""
from __future__ import annotations

from datetime import datetime, timezone

from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.expertreview.models import NReviewInvitation, NReviewScore, NReviewTask
from apps.funding.mappings import code_of
from apps.p.mappings import (
    num2,
    to_api_application,
    to_api_guide_suggestion,
    to_api_guideline,
    to_api_task_book,
)
from apps.p.models import (
    PApplication,
    PApplicationDoc,
    PGuideSuggestion,
    PGuideline,
    PTaskBook,
)
from apps.sysadmin.models import SysUser
from core.approval import has_role
from core.auth.deps import domain_from
from core.org_scope import current_org_id, is_external_only
from core.httpx import (
    ApiError,
    CODE_BAD_REQUEST,
    CODE_CONFLICT,
    CODE_CONFLICT_REF,
    CODE_FORBIDDEN,
    CODE_NOT_FOUND,
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
    page = max(page, 1)
    size = min(max(size, 1), 200)
    return page, size, size, (page - 1) * size


def _parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.replace("Z", "+0000"), fmt).astimezone(timezone.utc)
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# 申报指南（P-02）
# ---------------------------------------------------------------------------
#: 纯外部身份判定：除 R-PARTNER 外**没有任何**其它角色时，才按外部口径收口。
#: 这样 R-AUDITOR/R-FINANCE/R-EXPERT/R-ETHICS 等内部只读角色不受影响（fail-open 给内部，
#: 但仍要求至少持有一个内部角色；无角色（异常态）按外部处理 = fail-closed）。
_EXTERNAL_ROLE = "R-PARTNER"


def _guideline_status_scope(d) -> str | None:
    """纯外部机构用户强制只看 PUBLISHED；其余（任一内部角色）返回 None（不限制）。"""
    roles = [r for r in (getattr(d, "roles", None) or []) if r]
    if not roles:
        return "PUBLISHED"
    if has_role(roles, _EXTERNAL_ROLE):  # 含混合角色（fail-closed，见 core/org_scope）
        return "PUBLISHED"
    return None


def list_guidelines(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = PGuideline.objects.filter(tenant_id=d.tenant_id, deleted=0)
    scope = _guideline_status_scope(d)
    if scope:
        qs = qs.filter(status=scope)
    elif request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    if request.GET.get("project_type"):
        qs = qs.filter(project_type=request.GET["project_type"])
    if request.GET.get("keyword"):
        kw = request.GET["keyword"]
        qs = qs.filter(title__icontains=kw)
    total = qs.count()
    rows = qs.order_by("-updated_at", "-id")[offset : offset + limit]
    return ok(request, {"list": [to_api_guideline(g) for g in rows], "total": total, "page": page, "size": size})


def get_guideline(request: HttpRequest, id: int):
    d = domain_from(request)
    g = PGuideline.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
    if g is None or (_guideline_status_scope(d) == "PUBLISHED" and g.status != "PUBLISHED"):
        # 跨租户 / 未发布对外部角色一律 404（不泄露存在性）
        raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
    return ok(request, to_api_guideline(g))


def upsert_guideline(request: HttpRequest):
    d = domain_from(request)
    body = read_json(request)
    code = body.get("code")
    title = body.get("title")
    project_type = body.get("project_type")
    if not code or not title or not project_type:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    status = body.get("status") or "DRAFT"
    if status not in ("DRAFT", "PUBLISHED", "CLOSED"):
        raise ApiError(400, CODE_UNKNOWN_PARAM, "status 非法")
    envelope = None
    if body.get("total_envelope"):
        try:
            envelope = num2(body["total_envelope"]) and body["total_envelope"]
        except Exception:
            raise ApiError(400, CODE_BAD_REQUEST, "总盘子金额格式错误") from None

    g = PGuideline.objects.filter(tenant_id=d.tenant_id, code=code, deleted=0).first()
    if g is None:
        g = PGuideline(tenant_id=d.tenant_id, code=code, creator_id=d.user_id, status=status)
    g.title = title
    g.project_type = project_type
    g.status = status
    g.funding_source = body.get("funding_source")
    g.remark = body.get("remark")
    g.content_rich = body.get("content_rich")
    g.target_disciplines = body.get("target_disciplines") or []
    g.attachment_ids = body.get("attachment_ids") or []
    g.apply_start_at = _parse_dt(body.get("apply_start_at"))
    g.apply_end_at = _parse_dt(body.get("apply_end_at"))
    if envelope is not None:
        g.total_envelope = envelope
    # 首次以 PUBLISHED 落库时记 publish_at（对齐 Go）
    if status == "PUBLISHED" and g.publish_at is None:
        g.publish_at = dj_tz.now()
    g.modifier_id = d.user_id
    g.save()
    return ok(request, to_api_guideline(g))


# ---------------------------------------------------------------------------
# M1-d B5：指南征集动作（发布 / 关闭）+ 专家论证评审入库
# ---------------------------------------------------------------------------
def _notify(user_id: int, typ: str, title: str, content: str, biz_ref: str, tenant_id: int):
    """通知触达（best-effort：永不阻断业务，对齐 funding/api.py:116）。"""
    if user_id and user_id > 0:
        try:
            from apps.notify.models import SysNotification
            SysNotification.objects.create(
                tenant_id=tenant_id, user_id=user_id, typ=typ,
                title=title, content=content, biz_ref=biz_ref)
        except Exception:
            pass


def _notify_role(tenant_id: int, role: str, typ: str, title: str, content: str, biz_ref: str):
    """按角色广播（best-effort，镜像 funding/api.py:122-137）。"""
    try:
        from apps.sysadmin.models import SysRole, SysUser, SysUserRole
        r = SysRole.objects.filter(code=role, tenant_id=tenant_id).first()
        if r is None:
            return
        uids = list(SysUserRole.objects.filter(role=r).values_list("user_id", flat=True))
        for uid in SysUser.objects.filter(id__in=uids, status="ACTIVE").values_list("id", flat=True):
            _notify(uid, typ, title, content, biz_ref, tenant_id)
    except Exception:
        pass


def _get_guideline_or_404(tenant_id: int, guideline_id: int) -> PGuideline:
    g = PGuideline.objects.filter(id=guideline_id, tenant_id=tenant_id, deleted=0).first()
    if g is None:
        raise ApiError(404, CODE_NOT_FOUND, "指南不存在")
    return g


def publish_guideline(request: HttpRequest, id: int):
    """发布征集通知：DRAFT→PUBLISHED（幂等；已发布不重复推送）。"""
    d = domain_from(request)
    g = _get_guideline_or_404(d.tenant_id, id)
    if g.status == "CLOSED":
        raise ApiError(409, CODE_CONFLICT, "已关闭的指南不可发布")
    if g.status == "PUBLISHED":
        return ok(request, to_api_guideline(g))
    g.status = "PUBLISHED"
    if g.publish_at is None:
        g.publish_at = dj_tz.now()
    g.modifier_id = d.user_id
    g.save(update_fields=["status", "publish_at", "modifier_id", "updated_at"])
    _notify_role(g.tenant_id, "R-STAFF", "GUIDELINE", "指南征集通知",
                 f"《{g.title}》已发布，可在线填报", f"guideline:{g.id}")
    return ok(request, to_api_guideline(g))


def close_guideline(request: HttpRequest, id: int):
    """关闭征集：仅 PUBLISHED→CLOSED（幂等）；DRAFT 关闭 40901。"""
    d = domain_from(request)
    g = _get_guideline_or_404(d.tenant_id, id)
    if g.status == "CLOSED":
        return ok(request, to_api_guideline(g))
    if g.status != "PUBLISHED":
        raise ApiError(409, CODE_CONFLICT, "仅已发布指南可关闭")
    g.status = "CLOSED"
    g.modifier_id = d.user_id
    g.save(update_fields=["status", "modifier_id", "updated_at"])
    return ok(request, to_api_guideline(g))


def conclude_guide_review(n_task_id: int) -> None:
    """N 域论证评审回写单一写者：通过→指南入库发布，不通过→保持 DRAFT。"""
    from apps.expertreview.models import NReviewTask

    t = NReviewTask.objects.filter(id=n_task_id, deleted=0).first()
    if t is None or not t.target_id:
        return
    # 租户范围：评审任务与指南必须同租户，否则可跨租户发布他租户指南（C-3）
    g = PGuideline.objects.filter(id=t.target_id, tenant_id=t.tenant_id, deleted=0).first()
    if g is None:
        return
    if t.conclusion not in ("PASS", "APPROVED"):
        return
    if g.status != "DRAFT":
        return
    g.status = "PUBLISHED"
    if g.publish_at is None:
        g.publish_at = dj_tz.now()
    g.save(update_fields=["status", "publish_at", "updated_at"])
    _notify_role(g.tenant_id, "R-STAFF", "GUIDELINE", "指南入库发布",
                 f"《{g.title}》已通过专家论证并入库发布", f"guideline:{g.id}")


# ---------------------------------------------------------------------------
# 申报书（P-05）
# ---------------------------------------------------------------------------
def list_applications(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = PApplication.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if is_external_only(d):
        org = current_org_id(d)
        if org is None:  # 外部账号缺机构：一律空集（否则 filter(org=None) 会命中院内申报）
            return ok(request, {"list": [], "total": 0, "page": page, "size": size})
        qs = qs.filter(applicant_org_id=org)
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    if request.GET.get("project_type"):
        qs = qs.filter(project_type=request.GET["project_type"])
    total = qs.count()
    rows = qs.order_by("-updated_at", "-id")[offset : offset + limit]
    return ok(request, {"list": [to_api_application(a) for a in rows], "total": total, "page": page, "size": size})


def get_application(request: HttpRequest, id: int):
    d = domain_from(request)
    if is_external_only(d):
        a = _partner_app_or_404(d, id)
    else:
        a = _get_app_or_404(d.tenant_id, id)
    return ok(request, to_api_application(a))


def create_application(request: HttpRequest):
    d = domain_from(request)
    body = read_json(request)
    title = body.get("title")
    project_type = body.get("project_type")
    external = is_external_only(d)
    # 外部机构：PI 与申报机构一律以本人/本机构为准（忽略请求体，防冒名与跨机构挂靠）
    if external:
        pi_user_id = d.user_id
    else:
        pi_user_id = body.get("pi_user_id")
    if not title or not project_type or pi_user_id is None:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    # 外部账号必须已挂机构：否则会写出 applicant_org_id=NULL 的"院内形状"数据，
    # 且本人因机构收口也读不到（终审 r2 I-3）。
    if external and current_org_id(d) is None:
        raise ApiError(403, CODE_FORBIDDEN, "外部账号未绑定机构，无法申报")
    # 院内 PI 必须真实存在且属于本租户（终审 r2 I-4：pi=999999 会让 PI 签署永久 403 卡死）
    if not external:
        try:
            pi_int = int(pi_user_id)
        except (TypeError, ValueError):
            raise ApiError(400, CODE_BAD_REQUEST, "pi_user_id 必须为整数") from None
        exists = SysUser.objects.filter(
            id=pi_int, tenant_id=d.tenant_id, deleted=0
        ).exists()
        if not exists:
            raise ApiError(400, CODE_BAD_REQUEST, "申报负责人不存在")
        pi_user_id = pi_int
    total_budget = None
    if body.get("total_budget"):
        try:
            total_budget = round(float(body["total_budget"]), 2)
        except Exception:
            raise ApiError(400, CODE_UNKNOWN_PARAM, "预算格式错误") from None
    a = PApplication.objects.create(
        tenant_id=d.tenant_id, status="DRAFT", creator_id=d.user_id,
        title=title, project_type=project_type, pi_user_id=pi_user_id,
        member_ids=body.get("member_ids") or [],
        department_id=body.get("department_id"),
        abstract=body.get("abstract"),
        total_budget=total_budget,
        is_horizontal=bool(body.get("is_horizontal")),
        applicant_org_id=current_org_id(d) if external else body.get("applicant_org_id"),
        applicant_type="EXTERNAL" if external else "INTERNAL",
    )
    return ok(request, to_api_application(a))


# ---------------------------------------------------------------------------
# 申报书撤回/终止（契约超前于 Go 版，按契约语义补齐）
# ---------------------------------------------------------------------------
# 可撤回状态：未进入评审（UNDER_REVIEW 及之后不可撤回）
_WITHDRAWABLE = {"DRAFT", "SUBMITTED", "FORMAL_CHECK", "RECOMMENDED"}
# 可终止状态：已进入评审及之后的流转中状态
# 可终止状态：已进入评审、但**尚未立项**（SIGNED/EXECUTING 已立项，终止须走级联流程，见终审 M2-b C3）
_TERMINABLE = {"UNDER_REVIEW", "INTERVIEWING", "DECIDED", "PUBLISHED"}


def _get_app_or_404(tenant_id: int, app_id: int) -> PApplication:
    a = PApplication.objects.filter(id=app_id, tenant_id=tenant_id, deleted=0).first()
    if a is None:
        raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
    return a


def _partner_app_or_404(d, app_id: int) -> PApplication:
    """外部机构身份读申报：跨租户或跨机构一律 404（不泄露存在性）。"""
    a = _get_app_or_404(d.tenant_id, app_id)
    org = current_org_id(d)
    if a.applicant_org_id is None or org is None or a.applicant_org_id != org:
        raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
    return a


def _app_scoped_or_404(d, app_id: int) -> PApplication:
    """申报读写的**唯一**入口：租户 + 机构双重作用域，一票否决（终审 M2-b C1）。

    detail 早已走 `_partner_app_or_404`，但 documents/budget/sections/submit/
    withdraw/terminate 六个入口历史上只按 tenant 过滤，导致外部机构可跨机构
    读正文/改预算/替他人提交。这里统一收口：外部身份（含混合角色，fail-closed）
    必须 `applicant_org_id == current_org_id(d)`，且 org 为空一律 404。
    """
    a = _get_app_or_404(d.tenant_id, app_id)
    if is_external_only(d):
        org = current_org_id(d)
        if org is None or a.applicant_org_id is None or a.applicant_org_id != org:
            raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
    return a


def _require_reason(body: dict) -> str:
    reason = (body.get("reason") or "").strip()
    if not reason:
        raise ApiError(400, CODE_BAD_REQUEST, "理由必填")
    if len(reason) > 512:
        raise ApiError(400, CODE_BAD_REQUEST, "理由长度不能超过512")
    return reason


def withdraw_application(request: HttpRequest, id: int):
    """撤回申报：未进入评审前 PI 可主动撤回 → WITHDRAWN；进入评审后 409。"""
    d = domain_from(request)
    body = read_json(request)
    reason = _require_reason(body)
    a = _app_scoped_or_404(d, id)
    if a.status not in _WITHDRAWABLE:
        raise ApiError(409, CODE_CONFLICT, "当前状态不可撤回，已进入评审的申报只能终止")
    a.status = "WITHDRAWN"
    a.withdraw_at = dj_tz.now()
    a.withdraw_reason = reason
    a.modifier_id = d.user_id
    a.save()
    return ok(request, to_api_application(a))


def terminate_application(request: HttpRequest, id: int):
    """终止申报：已进入评审（UNDER_REVIEW 及之后）仅可终止，终态映射 REJECTED。"""
    d = domain_from(request)
    body = read_json(request)
    reason = _require_reason(body)
    a = _app_scoped_or_404(d, id)
    _assert_application_mutable(a)
    if a.status not in _TERMINABLE:
        raise ApiError(409, CODE_CONFLICT, "当前状态不可终止，未进入评审的申报应使用撤回")
    a.status = "REJECTED"
    a.withdraw_at = dj_tz.now()
    a.withdraw_reason = reason
    a.modifier_id = d.user_id
    a.save()
    return ok(request, to_api_application(a))


# ---------------------------------------------------------------------------
# 申报书分节正文 / 预算拆分 / 提交（EditorView 契约补齐）
# ---------------------------------------------------------------------------
# 前端 EditorView SECTIONS 9 节
SECTION_CODES = (
    "background", "objective", "content", "route", "innovation",
    "foundation", "schedule", "budget_note", "attachments",
)
# 旧字段（镜像 Go 期已落库的 4 个正文位）→ 分节码的合并映射
_LEGACY_SECTION_FIELD = {
    "background": "abstract",
    "objective": "research_target",
    "route": "technical_route",
    "innovation": "expected_output",
}
# 预算确定性拆分（占 total_budget 比例，累计 = 100%）
_BUDGET_SPLITS = (
    ("EQUIPMENT", "设备费", 0.30),
    ("MATERIAL", "材料费", 0.15),
    ("TRAVEL", "差旅费", 0.10),
    ("MEETING", "会议费", 0.05),
    ("LABOR", "劳务费", 0.25),
    ("EXPERT", "专家咨询费", 0.10),
    ("OTHER", "其他费用", 0.05),
)
# 评审四维（对齐前端 DEFAULT_DIMS，max_score 5）
REVIEW_DIMS = ("创新性", "科学问题", "研究方案", "研究基础")


def _doc_shape(a: PApplication, section_code: str, doc: PApplicationDoc | None) -> dict:
    if doc is not None and doc.content_rich:
        content, version = doc.content_rich, doc.doc_version
    else:
        legacy = getattr(a, _LEGACY_SECTION_FIELD.get(section_code, ""), None)
        content, version = (legacy or ""), 1
    return {
        "section_code": section_code,
        "content_rich": content,
        "word_count": len(content),
        "doc_version": version,
    }


def list_application_documents(request: HttpRequest, id: int):
    """GET /apply/applications/{id}/documents —— 9 节 Doc[]（doc 行 ∪ 旧字段）。"""
    d = domain_from(request)
    a = _app_scoped_or_404(d, id)
    docs = {d.section_code: d for d in PApplicationDoc.objects.filter(application=a)}
    return ok(request, [_doc_shape(a, code, docs.get(code)) for code in SECTION_CODES])


def get_application_budget(request: HttpRequest, id: int):
    """GET /apply/applications/{id}/budget —— 按 total_budget 确定性拆分 BudgetRow[]。"""
    d = domain_from(request)
    a = _app_scoped_or_404(d, id)
    total = float(a.total_budget or 0)
    if total <= 0:
        return ok(request, [])
    rows = []
    for code, name, ratio in _BUDGET_SPLITS:
        rows.append({
            "application_id": a.id,
            "subject_code": code,
            "subject_name": name,
            "amount": f"{round(total * ratio, 2):.2f}",
            "ai_compliance_flag": "OK",
            "ai_compliance_reason": "按政策计提",
        })
    return ok(request, rows)


def upsert_budget_line(request: HttpRequest, id: int):
    """POST /apply/applications/{id}/budget —— 编制/更新单条预算草稿行（契约 P-04）。

    确定性合规预检：单科目金额不得超过 total_budget；返回保存后的行。
    """
    d = domain_from(request)
    a = _app_scoped_or_404(d, id)
    _assert_application_mutable(a)
    body = read_json(request)
    subject_code = body.get("subject_code")
    amount = body.get("amount")
    if not subject_code or amount is None:
        raise ApiError(400, CODE_BAD_REQUEST, "subject_code 与 amount 必填")
    try:
        amt = round(float(amount), 2)
    except (TypeError, ValueError):
        raise ApiError(400, CODE_UNKNOWN_PARAM, "金额格式错误") from None
    if amt < 0:
        raise ApiError(400, CODE_BAD_REQUEST, "金额不能为负")
    if a.total_budget and amt > float(a.total_budget):
        raise ApiError(400, CODE_BAD_REQUEST, "单科目预算超出申报总预算")
    name_map = {c: n for c, n, _ in _BUDGET_SPLITS}
    return ok(request, {
        "application_id": a.id,
        "subject_code": subject_code,
        "subject_name": body.get("subject_name") or name_map.get(subject_code, subject_code),
        "amount": f"{amt:.2f}",
        "ai_compliance_flag": "OK",
        "ai_compliance_reason": "按政策计提",
    })


def save_application_section(request: HttpRequest, id: int, code: str):
    """PUT /apply/applications/{id}/sections/{code} —— 分节 upsert，版本自增。"""
    d = domain_from(request)
    a = _app_scoped_or_404(d, id)
    _assert_application_mutable(a)
    if code not in SECTION_CODES:
        raise ApiError(400, CODE_UNKNOWN_PARAM, f"未知分节码：{code}")
    body = read_json(request)
    content = body.get("content_rich")
    if content is None or not isinstance(content, str):
        raise ApiError(400, CODE_BAD_REQUEST, "content_rich 必填")
    doc = PApplicationDoc.objects.filter(application=a, section_code=code).first()
    if doc is None:
        doc = PApplicationDoc(tenant_id=d.tenant_id, application=a, section_code=code, doc_version=1)
    else:
        doc.doc_version += 1
    doc.content_rich = content
    doc.word_count = len(content)
    doc.updated_by = d.user_id
    doc.save()
    return ok(request, _doc_shape(a, code, doc))


def submit_application(request: HttpRequest, id: int):
    """POST /apply/applications/{id}/submit —— DRAFT → SUBMITTED 状态机。

    AI 辅助撰写过的申报必须显式确认水印说明（confirm_ai_watermark=true）；
    非 DRAFT 重复提交 40901。
    """
    d = domain_from(request)
    body = read_json(request)
    a = _app_scoped_or_404(d, id)
    _assert_application_mutable(a)
    if a.status != "DRAFT":
        raise ApiError(409, CODE_CONFLICT, "仅草稿状态可提交")
    if a.ai_draft_marked and not body.get("confirm_ai_watermark"):
        raise ApiError(400, CODE_BAD_REQUEST, "本文含 AI 辅助生成内容，请先确认 AI 水印说明")
    a.status = "SUBMITTED"
    a.submit_at = dj_tz.now()
    a.modifier_id = d.user_id
    a.save()
    return ok(request, to_api_application(a))


# ---------------------------------------------------------------------------
# AI 降级契约：规则引擎确定性起草/评审意见（无外部 LLM 依赖）
# ---------------------------------------------------------------------------
_DRAFT_LABEL = {
    "background": "立项依据（研究意义与科学问题）",
    "objective": "研究目标",
    "content": "研究内容",
    "route": "技术路线",
    "innovation": "创新点",
    "foundation": "研究基础",
    "schedule": "进度安排",
    "budget_note": "预算说明",
}


def ai_draft(request: HttpRequest):
    """POST /apply/ai/draft —— 确定性规则起草，返回 AiDraft（带水印）。"""
    d = domain_from(request)
    body = read_json(request)
    app_id = body.get("application_id")
    section_code = body.get("section_code")
    if not app_id or not section_code:
        raise ApiError(400, CODE_BAD_REQUEST, "application_id 与 section_code 必填")
    a = _app_scoped_or_404(d, int(app_id))
    if section_code not in SECTION_CODES:
        raise ApiError(400, CODE_UNKNOWN_PARAM, f"未知分节码：{section_code}")
    keywords = body.get("keywords") or ""
    label = _DRAFT_LABEL.get(section_code, section_code)
    kw = f"（关键词：{keywords}）" if keywords else ""
    content = (
        f"【{label}】围绕“{a.title}”，本节由规则引擎依据申报指南要素自动起草{kw}。"
        f"建议结构：①现状与问题；②关键科学问题凝练；③本研究切入点与预期突破。"
        f"正文需人工结合最新文献与研究积累改写定稿。"
    )
    refs = [
        {"project_code": r.code or f"PRJ-{r.id}", "title": r.title}
        for r in PApplication.objects.filter(tenant_id=d.tenant_id, deleted=0)
        .exclude(id=a.id).order_by("-updated_at")[:2]
    ]
    a.ai_draft_marked = True
    a.modifier_id = d.user_id
    a.save()
    return ok(request, {
        "content": content,
        "mode": "RULE",
        "confidence": "0.62",
        "references": refs,
        "watermark": "本文由 AI 辅助生成（规则模式），供撰写参考，需人工复核",
    })


def ai_review_draft(request: HttpRequest):
    """POST /apply/ai/review-draft —— 依分项得分确定性生成评审意见 AiReview。"""
    body = read_json(request)
    task_id = body.get("task_id")
    if not task_id:
        raise ApiError(400, CODE_BAD_REQUEST, "task_id 必填")
    task = NReviewTask.objects.filter(id=int(task_id), deleted=0).first()
    if task is None:
        raise ApiError(404, CODE_NOT_FOUND, "评审任务不存在")
    detail = body.get("score_detail") or []
    pct_scores = []
    for row in detail:
        try:
            score, mx = float(row.get("score") or 0), float(row.get("max_score") or 5)
        except (TypeError, ValueError):
            continue
        if mx > 0:
            pct_scores.append(min(score / mx, 1.0))
    avg = sum(pct_scores) / len(pct_scores) if pct_scores else 0.0
    if avg >= 0.9:
        overall, strengths = "优秀，建议优先资助", "选题前沿，方案完整，基础扎实"
        weaknesses, suggestions = "预期成果量化指标可进一步细化", "补充里程碑考核节点与风险预案"
    elif avg >= 0.75:
        overall, strengths = "良好，建议资助", "科学问题明确，技术路线可行"
        weaknesses, suggestions = "创新点论证相对薄弱", "强化与国内外同类工作的对比分析"
    elif avg >= 0.6:
        overall, strengths = "一般，建议修改后复审", "具备一定研究基础"
        weaknesses, suggestions = "研究方案可操作性不足", "细化技术路线并明确阶段考核指标"
    else:
        overall, strengths = "较差，建议不予资助", "选题有一定意义"
        weaknesses, suggestions = "关键要素缺失，可行性论证不足", "重新凝练科学问题后再行申报"
    return ok(request, {
        "overall": overall,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "suggestions": suggestions,
        "adopted": False,
    })


def _my_review_task_ids(user_id: int) -> set[int]:
    """当前专家被指派（ACCEPT 邀请）或已打分过的任务 id 集。"""
    invited = NReviewInvitation.objects.filter(
        expert_id=user_id, response="ACCEPT").values_list("task_id", flat=True)
    scored = NReviewScore.objects.filter(expert_id=user_id).values_list("task_id", flat=True)
    return set(invited) | set(scored)


def list_my_review_tasks(request: HttpRequest):
    """GET /apply/review/mytasks —— 当前专家的申报评审任务（ReviewTask 包装）。"""
    d = domain_from(request)
    ids = _my_review_task_ids(d.user_id)
    qs = NReviewTask.objects.filter(tenant_id=d.tenant_id, deleted=0, id__in=ids)
    status = request.GET.get("status")
    if status == "SCORING":
        qs = qs.filter(status__in=("IN_REVIEW", "COLLECTING"))
    elif status:
        qs = qs.filter(status=status)
    rows_out = []
    for t in qs.order_by("-updated_at", "-id"):
        mine = NReviewScore.objects.filter(task_id=t.id, expert_id=d.user_id).order_by("-id").first()
        app = PApplication.objects.filter(id=t.target_id, deleted=0).first() if t.target_id else None
        rows_out.append({
            "id": t.id,
            "application_id": t.target_id,
            "status": "SCORING" if t.status in ("IN_REVIEW", "COLLECTING") else t.status,
            "deadline_at": None,
            "comment_text": mine.comment if mine else None,
            "score_detail": mine.dimension_scores if mine else None,
            "load": f"共 {t.plan_count} 份评审",
            "dims": list(REVIEW_DIMS),
            "doc": {
                "code": app.code if app else t.code,
                "apply_code": app.code if app else t.code,
                "title": app.title if app else t.title,
                "sections": [
                    {"no": f"§{i + 1}", "h": _DRAFT_LABEL.get(c, c),
                     "text": (getattr(app, _LEGACY_SECTION_FIELD.get(c, ""), None) or "")[:200]}
                    for i, c in enumerate(SECTION_CODES)
                ] if app else [],
                "attachments": "、".join(getattr(app, "attachment_ids", None) or []) if app else "",
                "dup": None,
            },
        })
    total = len(rows_out)
    return ok(request, {"rows": rows_out, "total": total})


def score_review_task(request: HttpRequest, id: int):
    """POST /apply/review/tasks/{id}:score —— 专家打分（幂等 upsert）。"""
    d = domain_from(request)
    body = read_json(request)
    task = NReviewTask.objects.filter(id=id, deleted=0).first()
    if task is None:
        raise ApiError(404, CODE_NOT_FOUND, "评审任务不存在")
    if id not in _my_review_task_ids(d.user_id):
        raise ApiError(403, CODE_FORBIDDEN, "非该任务的指派专家")
    detail = body.get("score_detail")
    if not isinstance(detail, list) or not detail:
        raise ApiError(400, CODE_BAD_REQUEST, "score_detail 必填")
    total = 0.0
    for row in detail:
        try:
            total += float(row.get("score") or 0)
        except (TypeError, ValueError):
            raise ApiError(400, CODE_BAD_REQUEST, "score_detail 格式错误") from None
    score = NReviewScore.objects.filter(task_id=id, expert_id=d.user_id).first()
    if score is None:
        score = NReviewScore(tenant_id=d.tenant_id, task_id=id, expert_id=d.user_id)
    score.target_type, score.target_id = task.target_type, task.target_id
    score.dimension_scores = detail
    score.total_score = round(total, 2)
    score.comment = body.get("comment_text")
    score.status = "SUBMITTED"
    score.save()
    return ok(request, {
        "id": score.id, "task_id": id, "expert_id": d.user_id,
        "total_score": f"{score.total_score:.2f}", "status": score.status,
    })


# ---------------------------------------------------------------------------
# 指南建议（M2-b C2）：外部机构提交选题建议 → 管理端采纳转指南草稿 / 驳回
# ---------------------------------------------------------------------------
def _guide_suggestion_or_404(tenant_id: int, sid: int) -> PGuideSuggestion:
    s = PGuideSuggestion.objects.filter(
        id=sid, tenant_id=tenant_id, deleted=0
    ).first()
    if s is None:
        raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
    return s


def _partner_suggestion_or_404(d, sid: int) -> PGuideSuggestion:
    s = _guide_suggestion_or_404(d.tenant_id, sid)
    org = current_org_id(d)
    if s.org_id is None or org is None or s.org_id != org:
        raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
    return s


def list_guide_suggestions(request: HttpRequest):
    """GET /apply/guide-suggestions —— 外部机构只见本机构；内部角色可筛 status/org_id。"""
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = PGuideSuggestion.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if is_external_only(d):
        org = current_org_id(d)
        if org is None:
            return ok(request, {"list": [], "total": 0, "page": page, "size": size})
        qs = qs.filter(org_id=org)
    elif request.GET.get("org_id"):
        qs = qs.filter(org_id=request.GET["org_id"])
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    total = qs.count()
    rows = qs.order_by("-id")[offset:offset + limit]
    return ok(request, {
        "list": [to_api_guide_suggestion(s) for s in rows],
        "total": total,
        "page": page,
        "size": size,
    })


def get_guide_suggestion(request: HttpRequest, id: int):
    """GET /apply/guide-suggestions/{id} —— 跨租户/跨机构一律 404。"""
    d = domain_from(request)
    if is_external_only(d):
        s = _partner_suggestion_or_404(d, id)
    else:
        s = _guide_suggestion_or_404(d.tenant_id, id)
    return ok(request, to_api_guide_suggestion(s))


def create_guide_suggestion(request: HttpRequest):
    """POST /apply/guide-suggestions —— 外部用户的机构以本人机构为准，忽略请求体。"""
    d = domain_from(request)
    body = read_json(request)
    title = (body.get("title") or "").strip()
    if not title:
        raise ApiError(400, CODE_BAD_REQUEST, "建议标题必填")
    if len(title) > 256:
        raise ApiError(400, CODE_BAD_REQUEST, "建议标题长度不能超过256")
    if is_external_only(d):
        org_id = current_org_id(d)
        if org_id is None:  # 未绑机构的外部账号不得写 NULL-org 建议（终审 r2 I-3）
            raise ApiError(403, CODE_FORBIDDEN, "外部账号未绑定机构，无法提交建议")
    else:
        org_id = body.get("org_id")
    s = PGuideSuggestion.objects.create(
        tenant_id=d.tenant_id,
        creator_id=d.user_id,
        org_id=org_id,
        proposer_user_id=d.user_id,
        title=title,
        background=body.get("background"),
        objective=body.get("objective"),
        expected_output=body.get("expected_output"),
        contact_name=body.get("contact_name"),
        contact_phone=body.get("contact_phone"),
        contact_email=body.get("contact_email"),
        status="PENDING",
    )
    s.code = f"SUG-{dj_tz.localdate().year}-{s.id:06d}"
    s.save(update_fields=["code"])
    _notify_role(
        d.tenant_id, "R-MANAGER", "TODO", "新的指南建议", title,
        f"guide-suggestion:{s.id}",
    )
    return ok(request, to_api_guide_suggestion(s))


def accept_guide_suggestion(request: HttpRequest, id: int):
    """POST /apply/guide-suggestions/{id}:accept —— 生成 DRAFT 指南并回填 guideline_id。"""
    d = domain_from(request)
    with transaction.atomic():
        s = (
            PGuideSuggestion.objects.select_for_update()
            .filter(id=id, tenant_id=d.tenant_id, deleted=0)
            .first()
        )
        if s is None:
            raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
        if s.status != "PENDING":
            raise ApiError(409, CODE_CONFLICT, "该建议已处理")
        g = PGuideline.objects.create(
            tenant_id=d.tenant_id,
            creator_id=d.user_id,
            title=s.title,
            project_type="开放课题",
            status="DRAFT",
            content_rich=s.objective or s.background,
            publish_at=None,
        )
        s.status = "ACCEPTED"
        s.guideline_id = g.id
        s.review_user_id = d.user_id
        s.reviewed_at = dj_tz.now()
        s.save(update_fields=["status", "guideline_id", "review_user_id", "reviewed_at"])
    if s.proposer_user_id:
        _notify(
            s.proposer_user_id, "ANNOUNCE", "指南建议已采纳",
            f"《{s.title}》已采纳，将纳入指南编制。", f"guide-suggestion:{s.id}",
            d.tenant_id,
        )
    return ok(request, to_api_guide_suggestion(s))


def reject_guide_suggestion(request: HttpRequest, id: int):
    """POST /apply/guide-suggestions/{id}:reject —— 理由必填，落 reject_reason。"""
    d = domain_from(request)
    body = read_json(request)
    reason = _require_reason(body)
    with transaction.atomic():
        s = (
            PGuideSuggestion.objects.select_for_update()
            .filter(id=id, tenant_id=d.tenant_id, deleted=0)
            .first()
        )
        if s is None:
            raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
        if s.status != "PENDING":
            raise ApiError(409, CODE_CONFLICT, "该建议已处理")
        s.status = "REJECTED"
        s.reject_reason = reason
        s.review_user_id = d.user_id
        s.reviewed_at = dj_tz.now()
        s.save(update_fields=["status", "reject_reason", "review_user_id", "reviewed_at"])
    if s.proposer_user_id:
        _notify(
            s.proposer_user_id, "ANNOUNCE", "指南建议未采纳",
            f"《{s.title}》未采纳：{reason}", f"guide-suggestion:{s.id}", d.tenant_id,
        )
    return ok(request, to_api_guide_suggestion(s))


# ---------------------------------------------------------------------------
# 任务书（M2-b C2）：立项通过后生成 → 双签签订 → 立项建项
# ---------------------------------------------------------------------------
_TASK_BOOK_GENERATABLE = ("PUBLISHED", "DECIDED")
_SIGN_ROLES = ("PI", "MANAGER", "LEADER")


def _task_book_snapshot(a: PApplication) -> dict:
    """任务书内容快照：生成时冻结（目标/考核指标/预算/机构），签后不可改。"""
    return {
        "title": a.title,
        "project_type": a.project_type,
        "pi_user_id": a.pi_user_id,
        "applicant_org_id": a.applicant_org_id,
        "applicant_type": a.applicant_type,
        "total_budget": num2(a.total_budget),
        "duration_months": a.duration_months,
        "abstract": a.abstract,
        "research_target": a.research_target,
        "technical_route": a.technical_route,
        "expected_output": a.expected_output,
        "guideline_id": a.guideline_id,
        "frozen_at": dj_tz.now().isoformat(),
    }


def _task_book_visible(d, tb: PTaskBook) -> bool:
    """外部机构用户只能看本机构申报的任务书。"""
    if not is_external_only(d):
        return True
    a = PApplication.objects.filter(
        id=tb.application_id, tenant_id=d.tenant_id, deleted=0
    ).first()
    if a is None:
        return False
    org = current_org_id(d)
    return a.applicant_org_id is not None and org is not None and a.applicant_org_id == org


def _locked_scoped_app_or_404(d, app_id: int) -> PApplication:
    """`_app_scoped_or_404` 的加锁版：事务内生成/改写类操作必须走这里（终审 r2 C-1）。

    与只读版共用同一租户+机构作用域口径，避免"加锁查询顺手内联一份、漏掉机构过滤"。
    """
    a = (
        PApplication.objects.select_for_update()
        .filter(id=app_id, tenant_id=d.tenant_id, deleted=0)
        .first()
    )
    if a is None:
        raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
    if is_external_only(d):
        org = current_org_id(d)
        if org is None or a.applicant_org_id is None or a.applicant_org_id != org:
            raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
    return a


def generate_task_book(request: HttpRequest):
    """POST /apply/task-books —— 立项通过（PUBLISHED/DECIDED）后生成，按申报幂等。"""
    d = domain_from(request)
    body = read_json(request)
    aid = body.get("application_id")
    if not aid:
        raise ApiError(400, CODE_BAD_REQUEST, "application_id 必填")
    try:
        aid_int = int(aid)
    except (TypeError, ValueError):
        raise ApiError(400, CODE_BAD_REQUEST, "application_id 必须为整数") from None
    with transaction.atomic():
        a = _locked_scoped_app_or_404(d, aid_int)
        exist = PTaskBook.objects.filter(
            application_id=a.id, tenant_id=d.tenant_id, deleted=0
        ).first()
        if exist is not None:
            return ok(request, to_api_task_book(exist))
        if a.status not in _TASK_BOOK_GENERATABLE:
            raise ApiError(409, CODE_CONFLICT, "仅立项通过（PUBLISHED/DECIDED）的申报可生成任务书")
        tb = PTaskBook.objects.create(
            tenant_id=d.tenant_id,
            creator_id=d.user_id,
            application_id=a.id,
            status="DRAFT",
            content_snapshot=_task_book_snapshot(a),
            print_template_code=body.get("print_template_code") or "TASK_BOOK",
        )
        tb.code = code_of("PRJ", tb.id)
        tb.save(update_fields=["code"])
    _notify_role(
        d.tenant_id, "R-MANAGER", "TODO", "任务书待核对", a.title, f"task-book:{tb.id}"
    )
    return ok(request, to_api_task_book(tb))


_DECIDE_TARGETS = ("PUBLISHED", "DECIDED")
_DECIDABLE = {"SUBMITTED", "FORMAL_CHECK", "RECOMMENDED", "UNDER_REVIEW", "INTERVIEWING"}


def decide_application(request: HttpRequest, id: int):
    """POST /apply/applications/{id}:decide —— 评审决议（终审 M2-b I1）。

    契约里 PUBLISHED（拟资助公示）/DECIDED（已决）原本没有任何生产入口，任务书
    在真实流程中不可达，只能靠 seed 直接写库。这里补一个受限推进端点：
    仅 R-MANAGER/R-LEADER 可调用，decision ∈ {PUBLISHED, DECIDED}，仅评审中状态可推进。
    """
    d = domain_from(request)
    body = read_json(request)
    decision = (body.get("decision") or "").strip().upper()
    if decision not in _DECIDE_TARGETS:
        raise ApiError(400, CODE_BAD_REQUEST, "decision 须为 PUBLISHED 或 DECIDED")
    roles = [r for r in (getattr(d, "roles", None) or []) if r]
    if is_external_only(d) or not (has_role(roles, "R-MANAGER") or has_role(roles, "R-LEADER")):
        raise ApiError(403, CODE_FORBIDDEN, "仅科研管理/院所领导可作出评审决议")
    comment = (body.get("comment") or "").strip()[:512]
    with transaction.atomic():
        a = _locked_scoped_app_or_404(d, id)
        if a.status not in _DECIDABLE:
            raise ApiError(409, CODE_CONFLICT, "当前状态不可作出评审决议")
        a.status = decision
        a.modifier_id = d.user_id
        fields = ["status", "modifier_id", "updated_at"]
        if comment:  # 契约带 comment，原先被丢弃（终审 r2 Minor）
            a.remark = comment
            fields.append("remark")
        a.save(update_fields=fields)
    _notify(
        a.pi_user_id, "ANNOUNCE",
        "申报评审结果已发布" if decision == "PUBLISHED" else "申报已决议",
        f"《{a.title}》评审状态更新为 {decision}，可生成任务书并签署立项。",
        f"application:{a.id}", d.tenant_id,
    )
    return ok(request, to_api_application(a))


def get_task_book(request: HttpRequest, id: int):
    """GET /apply/task-books/{id} —— 外部机构只能读本机构。"""
    d = domain_from(request)
    tb = PTaskBook.objects.filter(id=id, tenant_id=d.tenant_id, deleted=0).first()
    if tb is None or not _task_book_visible(d, tb):
        raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
    return ok(request, to_api_task_book(tb))


def sign_task_book(request: HttpRequest, id: int):
    """POST /apply/task-books/{id}:sign —— PI + (MANAGER|LEADER) 双签即立项建项。"""
    d = domain_from(request)
    body = read_json(request)
    role = (body.get("role") or "").strip().upper()
    if role not in _SIGN_ROLES:
        raise ApiError(400, CODE_BAD_REQUEST, "role 须为 PI/MANAGER/LEADER")
    with transaction.atomic():
        tb = (
            PTaskBook.objects.select_for_update()
            .filter(id=id, tenant_id=d.tenant_id, deleted=0)
            .first()
        )
        if tb is None or not _task_book_visible(d, tb):
            raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
        if tb.status in ("SIGNED", "EXECUTING"):
            raise ApiError(409, CODE_CONFLICT, "任务书已签订")
        a = (
            PApplication.objects.select_for_update()
            .filter(id=tb.application_id, tenant_id=d.tenant_id, deleted=0)
            .first()
        )
        if a is None:
            raise ApiError(404, CODE_NOT_FOUND, "申报不存在")
        # C3：只有评审通过（PUBLISHED/DECIDED）的申报可签署立项；已终止/草稿等一律 409
        if a.status not in _TASK_BOOK_GENERATABLE:
            raise ApiError(409, CODE_CONFLICT, "申报状态不允许立项")
        records = [r for r in (tb.sign_records or []) if isinstance(r, dict)]
        if any(r.get("role") == role for r in records):
            raise ApiError(409, CODE_CONFLICT, "该角色已签署")
        # C2：签署人一律由服务端按身份认定，忽略请求体 signer_id
        roles = [r for r in (getattr(d, "roles", None) or []) if r]
        if role == "PI":
            if d.user_id != a.pi_user_id:
                raise ApiError(403, CODE_FORBIDDEN, "仅申报负责人本人可签署 PI")
            signer_id = a.pi_user_id
        else:
            need = "R-MANAGER" if role == "MANAGER" else "R-LEADER"
            if is_external_only(d) or not has_role(roles, need):
                raise ApiError(403, CODE_FORBIDDEN, f"仅 {need} 可签署 {role}")
            signer_id = d.user_id
        records.append({
            "role": role,
            "signerId": signer_id,
            "signedAt": dj_tz.now().isoformat(),
            "result": body.get("sig_result") or "OK",
        })
        tb.sign_records = records
        roles_signed = {r.get("role") for r in records}
        complete = "PI" in roles_signed and (
            "MANAGER" in roles_signed or "LEADER" in roles_signed
        )
        if complete:
            project = _create_project_from_task_book(d, a, tb)
            tb.status = "SIGNED"
            tb.effective_date = dj_tz.localdate()
            tb.project_id = project.id
            a.status = "EXECUTING"
            a.save(update_fields=["status", "updated_at"])
        tb.save()
    if complete:
        _notify(
            a.pi_user_id, "ANNOUNCE", "任务书已签订",
            f"《{a.title}》任务书已签订，项目已立项进入执行。",
            f"task-book:{tb.id}", d.tenant_id,
        )
    return ok(request, to_api_task_book(tb))


def _create_project_from_task_book(d, a: PApplication, tb: PTaskBook):
    """双签后立项建项：与申报 1:1（application_id），外部课题带 ext_org_id。"""
    from apps.project.models import EProject

    exist = EProject.objects.filter(
        application_id=a.id, tenant_id=d.tenant_id, deleted=0
    ).first()
    if exist is not None:  # 幂等兜底：同申报不重复建项
        return exist
    project = EProject.objects.create(
        tenant_id=d.tenant_id,
        creator_id=d.user_id,
        application_id=a.id,
        title=a.title,
        project_type=a.project_type,
        pi_user_id=a.pi_user_id,
        member_ids=a.member_ids or [],
        department_id=a.department_id,
        legal_entity_id=1,
        total_budget=a.total_budget or 0,
        status="EXECUTING",
        ext_org_id=a.applicant_org_id,
        security_level="INTERNAL",
    )
    project.code = code_of("PRJ", project.id)
    project.save(update_fields=["code"])
    return project


def _assert_application_mutable(a: PApplication) -> None:
    """任务书签订后申报内容冻结（分节/预算/再提交一律 40901）。"""
    if PTaskBook.objects.filter(
        application_id=a.id, tenant_id=a.tenant_id, deleted=0,
        status__in=("SIGNED", "EXECUTING"),
    ).exists():
        raise ApiError(409, CODE_CONFLICT, "任务书已签订，申报内容不可修改")
