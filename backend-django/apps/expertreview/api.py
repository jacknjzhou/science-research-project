"""专家评审域 N API（对齐 Go modules/expertreview：expert.go + draw.go + review.go + writeback.go）。

抽取：draw_rule 回避过滤 + 确定性随机（seed 可传，铁律 11）；
状态机：DRAFT→DRAWN→INVITING→QUORUM→IN_REVIEW→COLLECTING→CONCLUDED；
回写：按 biz_type 经 E/R 单一写者（NEVER 直接 UPDATE E_/R_ 表）。
"""
from __future__ import annotations

import random
from datetime import datetime
from decimal import Decimal

from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.expertreview.mappings import (
    num2,
    to_api_expert,
    to_api_invitation,
    to_api_review_task,
    to_api_score,
)
from apps.expertreview.models import (
    NExpert,
    NReviewFee,
    NReviewInvitation,
    NReviewScore,
    NReviewTask,
)
from core.auth.deps import domain_from
from core.httpx import (
    ApiError,
    CODE_BAD_REQUEST,
    CODE_CONFLICT,
    CODE_NOT_FOUND,
    ok,
    read_json,
    read_json_soft,
)

EXPERT_STATUSES = {"CANDIDATE", "ACTIVE", "SUSPENDED", "BLACKLIST"}


def page_args(request: HttpRequest) -> tuple[int, int, int, int]:
    try:
        page = max(int(request.GET.get("page", "1") or "1"), 1)
        size = min(max(int(request.GET.get("size", "20") or "20"), 1), 200)
    except ValueError:
        page, size = 1, 20
    return page, size, size, (page - 1) * size


def _get_expert_or_404(expert_id: int) -> NExpert:
    e = NExpert.objects.filter(id=expert_id, deleted=0).first()
    if e is None:
        raise ApiError(404, CODE_NOT_FOUND, "专家不存在")
    return e


def _get_task_or_404(task_id: int) -> NReviewTask:
    t = NReviewTask.objects.filter(id=task_id, deleted=0).first()
    if t is None:
        raise ApiError(404, CODE_NOT_FOUND, "评审任务不存在")
    return t


# ---------------------------------------------------------------------------
# 专家库 CRUD
# ---------------------------------------------------------------------------

def list_experts(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = NExpert.objects.filter(deleted=0)
    if v := request.GET.get("status"):
        qs = qs.filter(status=v)
    if v := request.GET.get("source"):
        qs = qs.filter(source=v)
    if v := request.GET.get("kw"):
        qs = qs.filter(name__icontains=v)
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_expert(e) for e in rows],
                        "total": total, "page": page, "size": size})


def get_expert(request: HttpRequest, id: int):
    return ok(request, to_api_expert(_get_expert_or_404(id)))


def create_expert(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    if not b.get("name"):
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    e = NExpert.objects.create(
        code="", tenant_id=d.tenant_id, status="CANDIDATE", creator_id=d.user_id,
        security_level=b.get("security_level") or "INTERNAL",
        name=b["name"], gender=b.get("gender"), title=b.get("title"),
        org_name=b.get("org_name"), user_id=b.get("user_id"),
        source=b.get("source") or "EXTERNAL",
        field_tags=b.get("field_tags") or [],
        expertise_level=b.get("expertise_level") or "EXPERT",
        avoid_orgs=b.get("avoid_orgs") or [],
        avoid_person_ids=b.get("avoid_person_ids") or [],
    )
    return ok(request, to_api_expert(e))


def update_expert(request: HttpRequest, id: int):
    d = domain_from(request)
    e = _get_expert_or_404(id)
    b = read_json(request)
    name = b.get("name") or e.name
    e.name = name
    if b.get("title") is not None:
        e.title = b["title"]
    if b.get("org_name") is not None:
        e.org_name = b["org_name"]
    if b.get("field_tags") is not None:
        e.field_tags = b["field_tags"]
    if b.get("avoid_orgs") is not None:
        e.avoid_orgs = b["avoid_orgs"]
    if b.get("avoid_person_ids") is not None:
        e.avoid_person_ids = b["avoid_person_ids"]
    e.modifier_id = d.user_id
    e.save()
    return ok(request, to_api_expert(e))


def set_expert_status(request: HttpRequest, id: int):
    e = _get_expert_or_404(id)
    b = read_json(request)
    status = b.get("status")
    if status not in EXPERT_STATUSES:
        raise ApiError(400, 40002, "状态取值非法")
    e.status = status
    e.save(update_fields=["status", "updated_at"])
    return ok(request, to_api_expert(e))


def delete_expert(request: HttpRequest, id: int):
    e = _get_expert_or_404(id)
    e.deleted = 1
    e.save(update_fields=["deleted", "updated_at"])
    return ok(request, None)


# ---------------------------------------------------------------------------
# 抽取（draw.go 语义忠实移植）
# ---------------------------------------------------------------------------

def _eligible(c: dict, rule: dict, avoid_orgs: list[str], avoid_user_ids: list[int]) -> bool:
    """领域匹配 + 回避（项目/PI 侧 exclude + 专家本人登记回避）。"""
    tags = rule.get("field_tags") or []
    if tags and not any(f in (c["fields"] or []) for f in tags):
        return False
    org = c["org_name"] or ""
    if org and (org in (rule.get("exclude_orgs") or []) or org in avoid_orgs):
        return False
    for o in c["avoid_org"] or []:
        if o in avoid_orgs or o in (rule.get("exclude_orgs") or []):
            return False
    uid = c["user_id"] or 0
    if uid and (uid in (rule.get("exclude_user_ids") or []) or uid in avoid_user_ids):
        return False
    for u in c["avoid_usr"] or []:
        if u in (rule.get("exclude_user_ids") or []) or u in avoid_user_ids:
            return False
    return True


def _draw_experts(pool: list[dict], rule: dict, n: int, seed: int) -> list[int]:
    ok_pool = [c for c in pool if _eligible(c, rule, [], [])]
    rnd = random.Random(seed)
    rnd.shuffle(ok_pool)
    if rule.get("org_diversity"):
        seen: set[str] = set()
        dedup = []
        for c in ok_pool:
            if c["org_name"] not in seen:
                seen.add(c["org_name"])
                dedup.append(c)
        for c in ok_pool:
            if len(dedup) >= n:
                break
            if all(c["expert_id"] != x["expert_id"] for x in dedup):
                dedup.append(c)
        ok_pool = dedup
    return [c["expert_id"] for c in ok_pool[:n]]


def _build_candidates(experts) -> list[dict]:
    return [{
        "expert_id": e.id, "user_id": e.user_id or 0, "org_name": e.org_name or "",
        "fields": e.field_tags or [], "avoid_org": e.avoid_orgs or [],
        "avoid_usr": e.avoid_person_ids or [],
    } for e in experts]


# ---------------------------------------------------------------------------
# 评审任务 CRUD + 状态机
# ---------------------------------------------------------------------------

def list_reviews(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = NReviewTask.objects.filter(deleted=0)
    if v := request.GET.get("biz_type"):
        qs = qs.filter(biz_type=v)
    if v := request.GET.get("status"):
        qs = qs.filter(status=v)
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_review_task(t) for t in rows],
                        "total": total, "page": page, "size": size})


def get_review(request: HttpRequest, id: int):
    return ok(request, to_api_review_task(_get_task_or_404(id)))


def create_review(request: HttpRequest):
    d = domain_from(request)
    b = read_json(request)
    if not b.get("biz_type") or not b.get("title"):
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    plan_count = b.get("plan_count") or 0
    if plan_count <= 0:
        plan_count = 3
    t = NReviewTask.objects.create(
        code="", tenant_id=d.tenant_id, creator_id=d.user_id,
        security_level=b.get("security_level") or "INTERNAL",
        biz_type=b["biz_type"], target_type=b.get("target_type"),
        target_id=b.get("target_id"), project_id=b.get("project_id"),
        title=b["title"], review_method=b.get("review_method") or "RANDOM",
        plan_count=plan_count, draw_rule=b.get("draw_rule") or {},
    )
    return ok(request, to_api_review_task(t))


def cancel_review(request: HttpRequest, id: int):
    t = _get_task_or_404(id)
    t.status = "CANCELLED"
    t.save(update_fields=["status", "updated_at"])
    return ok(request, None)


def draw_experts(request: HttpRequest, id: int):
    """回避过滤 + 确定性随机 → DRAFT→DRAWN；逐席位落 n_review_invitation。"""
    t = _get_task_or_404(id)
    b = read_json_soft(request)
    rule = t.draw_rule or {}
    experts = list(NExpert.objects.filter(status="ACTIVE", deleted=0))
    pool = _build_candidates(experts)
    n = b.get("plan_count") if isinstance(b, dict) else None
    if not n or n <= 0:
        n = t.plan_count
    seed = (b or {}).get("seed")
    seed = seed if seed is not None else dj_tz.now().timestamp_ns()
    drawn = _draw_experts(pool, rule, int(n), int(seed))
    seat = 0
    for eid in drawn:
        seat += 1
        NReviewInvitation.objects.create(
            tenant_id=t.tenant_id, task_id=t.id, expert_id=eid,
            seat_no=seat, avoid_hit=False, response="PENDING")
    t.status = "DRAWN"
    t.drawn_at = dj_tz.now()
    t.save(update_fields=["status", "drawn_at", "updated_at"])
    return ok(request, {"drawn": drawn, "count": len(drawn)})


def invite_experts(request: HttpRequest, id: int):
    """DRAWN→INVITING；MID_CHECK 经 E 单一写者回填 expert_ids。"""
    t = _get_task_or_404(id)
    t.status = "INVITING"
    t.save(update_fields=["status", "updated_at"])
    if t.biz_type == "MID_CHECK" and t.target_id:
        invites = list(NReviewInvitation.objects.filter(task_id=t.id))
        user_ids = []
        for iv in invites:
            ex = NExpert.objects.filter(id=iv.expert_id).first()
            if ex and ex.user_id:
                user_ids.append(ex.user_id)
        if user_ids:
            from apps.project.api import set_mid_check_experts
            set_mid_check_experts(t.target_id, user_ids)
    return ok(request, None)


def _respond(request: HttpRequest, id: int, resp: str):
    t = _get_task_or_404(id)
    b = read_json(request)
    expert_id = b.get("expert_id")
    if not expert_id:
        raise ApiError(400, CODE_BAD_REQUEST, "缺少 expert_id")
    iv = NReviewInvitation.objects.filter(task_id=id, expert_id=expert_id).first()
    if iv is None:
        raise ApiError(404, 40402, "邀请不存在")
    iv.response = resp
    iv.responded_at = dj_tz.now()
    iv.save(update_fields=["response", "responded_at"])
    if resp == "ACCEPT":
        accepted = NReviewInvitation.objects.filter(task_id=id, response="ACCEPT").count()
        if accepted >= t.plan_count:
            t.status = "QUORUM"
            t.save(update_fields=["status", "updated_at"])
    return ok(request, None)


def accept_invitation(request: HttpRequest, id: int):
    return _respond(request, id, "ACCEPT")


def decline_invitation(request: HttpRequest, id: int):
    return _respond(request, id, "DECLINE")


def start_review(request: HttpRequest, id: int):
    """QUORUM→IN_REVIEW。"""
    t = _get_task_or_404(id)
    if t.status != "QUORUM":
        raise ApiError(409, CODE_CONFLICT, "状态更新失败")
    t.status = "IN_REVIEW"
    t.started_at = dj_tz.now()
    t.save(update_fields=["status", "started_at", "updated_at"])
    return ok(request, None)


def submit_score(request: HttpRequest, id: int):
    """专家提交打分（Upsert）；已提交数达已接受数→COLLECTING。"""
    t = _get_task_or_404(id)
    b = read_json(request)
    if not b.get("expert_id") or b.get("total_score") in (None, ""):
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    sc = NReviewScore.objects.filter(task_id=id, expert_id=b["expert_id"]).first()
    if sc is None:
        sc = NReviewScore(tenant_id=t.tenant_id, task_id=id, expert_id=b["expert_id"])
    sc.target_type = b.get("target_type")
    sc.target_id = b.get("target_id")
    sc.dimension_scores = b.get("dimension_scores") or []
    try:
        sc.total_score = Decimal(str(b["total_score"]))
    except Exception:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误") from None
    sc.comment = b.get("comment")
    sc.save()
    submitted = NReviewScore.objects.filter(task_id=id).count()
    accepted = NReviewInvitation.objects.filter(task_id=id, response="ACCEPT").count()
    if accepted > 0 and submitted >= accepted:
        t.status = "COLLECTING"
        t.save(update_fields=["status", "updated_at"])
    return ok(request, to_api_score(sc))


def _build_score_summary(task_id: int) -> dict:
    scores = list(NReviewScore.objects.filter(task_id=task_id))
    per = []
    total = 0.0
    cnt = 0
    for s in scores:
        try:
            val = float(s.total_score)
        except Exception:
            val = 0.0
        total += val
        cnt += 1
        per.append({"expert_id": s.expert_id, "total_score": num2(s.total_score), "status": s.status})
    avg = "0"
    if cnt > 0:
        avg = f"{total / cnt:.2f}"
    return {"count": cnt, "avg": avg, "per_expert": per}


def conclude_review(request: HttpRequest, id: int):
    """汇总→CONCLUDED，按 biz_type 经单一写者回写 E/R。"""
    t = _get_task_or_404(id)
    b = read_json(request)
    conclusion = b.get("conclusion")
    if not conclusion:
        raise ApiError(400, CODE_BAD_REQUEST, "请求参数错误")
    summary = _build_score_summary(id)
    t.status = "CONCLUDED"
    t.conclusion = conclusion
    t.score_summary = summary
    t.concluded_at = dj_tz.now()
    t.save(update_fields=["status", "conclusion", "score_summary", "concluded_at", "updated_at"])
    _conclude_writeback(t.biz_type, t.target_id or 0, t.project_id or 0, conclusion, summary)
    return ok(request, to_api_review_task(t))


def _conclude_writeback(biz_type: str, target_id: int, project_id: int,
                        conclusion: str, summary: dict) -> None:
    """跨模块写纪律：N NEVER 直接 UPDATE E_/R_ 表；只调 E/R 单一写者导出方法。"""
    from apps.output.api import conclude_output_eval
    from apps.project.api import conclude_final_accept, conclude_mid_check

    if biz_type == "MID_CHECK":
        conclude_mid_check(target_id, project_id, conclusion, summary)
    elif biz_type == "FINAL_ACCEPT":
        status_map = {"PASS": "APPROVED", "REJECT": "REJECTED", "SUPPLEMENT": "NEED_SUPPLEMENT"}
        status = status_map.get(conclusion)
        if status:
            conclude_final_accept(target_id, status)
    elif biz_type == "OUTPUT_EVAL":
        conclude_output_eval(target_id, conclusion == "PASS")
    # PROJECT_APPLY/OTHER 暂无被写对象，no-op


def generate_fees(request: HttpRequest, id: int):
    """按已接受专家逐人生成评审费（联动 F 预留）。"""
    d = domain_from(request)
    t = _get_task_or_404(id)
    b = read_json_soft(request)
    amount = Decimal(str((b or {}).get("amount") or 0))
    accepted = list(NReviewInvitation.objects.filter(task_id=id, response="ACCEPT"))
    n = 0
    for a in accepted:
        NReviewFee.objects.create(
            code="", tenant_id=t.tenant_id, creator_id=d.user_id,
            task_id=id, expert_id=a.expert_id, amount=amount,
            pay_channel=(b or {}).get("pay_channel"))
        n += 1
    return ok(request, {"generated": n})


def get_review_detail(request: HttpRequest, id: int):
    t = _get_task_or_404(id)
    invites = list(NReviewInvitation.objects.filter(task_id=id).order_by("seat_no"))
    scores = list(NReviewScore.objects.filter(task_id=id).order_by("id"))
    inv = []
    for iv in invites:
        ex = NExpert.objects.filter(id=iv.expert_id).first()
        inv.append(to_api_invitation(iv, ex.name if ex else None))
    return ok(request, {"task": to_api_review_task(t), "invitations": inv,
                        "scores": [to_api_score(s) for s in scores]})
