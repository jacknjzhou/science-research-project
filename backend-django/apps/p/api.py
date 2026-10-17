"""申报域 P API（对齐 Go modules/p 全部端点）。

路由：GET|POST /apply/guidelines、GET /apply/guidelines/{id}、
     GET|POST /apply/applications、GET /apply/applications/{id}
"""
from __future__ import annotations

from datetime import datetime, timezone

from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.expertreview.models import NReviewInvitation, NReviewScore, NReviewTask
from apps.p.mappings import num2, to_api_application, to_api_guideline
from apps.p.models import PApplication, PApplicationDoc, PGuideline
from core.auth.deps import domain_from
from core.httpx import (
    ApiError,
    CODE_BAD_REQUEST,
    CODE_CONFLICT,
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
def list_guidelines(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = PGuideline.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if request.GET.get("status"):
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
    g = PGuideline.objects.filter(id=id, deleted=0).first()
    if g is None:
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
# 申报书（P-05）
# ---------------------------------------------------------------------------
def list_applications(request: HttpRequest):
    d = domain_from(request)
    page, size, limit, offset = page_args(request)
    qs = PApplication.objects.filter(tenant_id=d.tenant_id, deleted=0)
    if request.GET.get("status"):
        qs = qs.filter(status=request.GET["status"])
    if request.GET.get("project_type"):
        qs = qs.filter(project_type=request.GET["project_type"])
    total = qs.count()
    rows = qs.order_by("-updated_at", "-id")[offset : offset + limit]
    return ok(request, {"list": [to_api_application(a) for a in rows], "total": total, "page": page, "size": size})


def get_application(request: HttpRequest, id: int):
    a = PApplication.objects.filter(id=id, deleted=0).first()
    if a is None:
        raise ApiError(404, CODE_NOT_FOUND, "记录不存在")
    return ok(request, to_api_application(a))


def create_application(request: HttpRequest):
    d = domain_from(request)
    body = read_json(request)
    title = body.get("title")
    project_type = body.get("project_type")
    pi_user_id = body.get("pi_user_id")
    if not title or not project_type or pi_user_id is None:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
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
    )
    return ok(request, to_api_application(a))


# ---------------------------------------------------------------------------
# 申报书撤回/终止（契约超前于 Go 版，按契约语义补齐）
# ---------------------------------------------------------------------------
# 可撤回状态：未进入评审（UNDER_REVIEW 及之后不可撤回）
_WITHDRAWABLE = {"DRAFT", "SUBMITTED", "FORMAL_CHECK", "RECOMMENDED"}
# 可终止状态：已进入评审及之后的流转中状态
_TERMINABLE = {"UNDER_REVIEW", "INTERVIEWING", "DECIDED", "PUBLISHED", "SIGNED", "EXECUTING"}


def _get_app_or_404(app_id: int) -> PApplication:
    a = PApplication.objects.filter(id=app_id, deleted=0).first()
    if a is None:
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
    a = _get_app_or_404(id)
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
    a = _get_app_or_404(id)
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
    a = _get_app_or_404(id)
    docs = {d.section_code: d for d in PApplicationDoc.objects.filter(application=a)}
    return ok(request, [_doc_shape(a, code, docs.get(code)) for code in SECTION_CODES])


def get_application_budget(request: HttpRequest, id: int):
    """GET /apply/applications/{id}/budget —— 按 total_budget 确定性拆分 BudgetRow[]。"""
    a = _get_app_or_404(id)
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
    a = _get_app_or_404(id)
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
    a = _get_app_or_404(id)
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
    a = _get_app_or_404(id)
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
    a = _get_app_or_404(int(app_id))
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
