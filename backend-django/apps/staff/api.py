"""人员与团队域 S API（对齐 design/07-人员与团队-S.openapi.yaml，纯契约实现）。

人员档案（HR 同步只读 + 科研专属可编辑）→ 异动/离职交接 → 画像快照（确定性聚合）→
合作网络时间切片 → AI 方向标签/简历（确定性降级）→ 团队/成员（S_MEMBERSHIP 权威主存 +
member_ids 快照同步）→ 客座/访问学者（申请建 S_STAFF 档 + 审批）→ 学生登记 → 人才计划 →
AI 梯队缺口分析（确定性统计）。敏感列（身份证/银行卡）响应脱敏。
"""
from __future__ import annotations

import time
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone as dj_tz

from apps.staff.models import (
    SCollabGraph,
    SMembership,
    SPortrait,
    SStaff,
    SStudent,
    STalentPlan,
    STeam,
    SVisitor,
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
from apps.output.api import page_args, _parse_date  # 共用分页/日期解析

EMPLOYMENT_MAP = {"RESIGN": "RESIGNED", "RETIRE": "RETIRED", "TRANSFER_DEPT": "ONBOARD",
                  "REHIRE": "REHIRE", "LEAVE": "ONBOARD"}
MEMBER_ROLES = {"LEADER", "CORE", "MEMBER", "STUDENT", "VISITOR"}


def _now():
    return dj_tz.now()


def _get_staff_or_404(sid: int) -> SStaff:
    s = SStaff.objects.filter(id=sid, deleted=0).first()
    if s is None:
        raise ApiError(404, CODE_NOT_FOUND, "人员档案不存在")
    return s


def _parse_dt(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s)[:19])
    except ValueError:
        return None
    return dj_tz.make_aware(dt) if dj_tz.is_naive(dt) else dt


# ---------------------------------------------------------------------------
# 映射（契约 Staff schema；敏感列脱敏）
# ---------------------------------------------------------------------------


def to_api_staff(r: SStaff, detail: bool = False) -> dict:
    data = {
        "id": r.id,
        "code": r.code,
        "tenant_id": r.tenant_id,
        "status": r.status,
        "user_id": r.user_id,
        "hr_code": r.hr_code,
        "name": r.name,
        "name_en": r.name_en,
        "gender": r.gender,
        "birth_year": r.birth_year,
        "id_card_masked": "******" if r.id_card_hash else None,
        "email": r.email,
        "phone": r.phone,
        "department_id": r.department_id,
        "secondary_dept_ids": r.secondary_dept_ids or [],
        "staff_type": r.staff_type,
        "position": r.position,
        "title": r.title,
        "education": r.education,
        "hire_date": f"{r.hire_date:%Y-%m-%d}" if r.hire_date else None,
        "leave_date": f"{r.leave_date:%Y-%m-%d}" if r.leave_date else None,
        "employment_status": r.employment_status,
        "photo_url": r.photo_url,
        "orcid": r.orcid,
        "wos_researcher_id": r.wos_researcher_id,
        "scopus_id": r.scopus_id,
        "cnki_author_id": r.cnki_author_id,
        "bio": r.bio if detail else None,
        "research_expertise": r.research_expertise or [],
        "external_appointments": r.external_appointments or [],
        "is_pi": r.is_pi,
        "legal_entity_id": r.legal_entity_id,
        "security_level": r.security_level,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
        "remark": r.remark,
    }
    return data


def _fmt_date(d):
    return f"{d:%Y-%m-%d}" if d else None


# ---------------------------------------------------------------------------
# 人员档案
# ---------------------------------------------------------------------------


def list_staff(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = SStaff.objects.filter(tenant_id=domain_from(request).tenant_id, deleted=0)
    for k in ("staff_type", "employment_status"):
        if v := request.GET.get(k):
            qs = qs.filter(**{k: v})
    if v := request.GET.get("department_id"):
        try:
            qs = qs.filter(department_id=int(v))
        except ValueError:
            pass
    if kw := (request.GET.get("keyword") or request.GET.get("kw")):
        qs = qs.filter(Q(name__icontains=kw) | Q(name_en__icontains=kw) | Q(hr_code__icontains=kw))
    if request.GET.get("is_pi") in ("true", "1"):
        qs = qs.filter(is_pi=True)
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [to_api_staff(r) for r in rows],
                        "total": total, "page": page, "size": size})


def get_me(request: HttpRequest):
    s = SStaff.objects.filter(tenant_id=domain_from(request).tenant_id, user_id=domain_from(request).user_id,
                              deleted=0).first()
    if s is None:
        raise ApiError(404, CODE_NOT_FOUND, "当前用户无人员档案")
    data = to_api_staff(s, detail=True)
    data["teams"] = [
        {"team_id": m.team_id, "team_name": m.team.name, "role": m.role,
         "joined_at": m.joined_at.isoformat(), "status": m.status}
        for m in SMembership.objects.filter(staff=s, deleted=0, left_at__isnull=True)
    ]
    data["students"] = [
        {"id": st.id, "name": st.staff.name, "student_type": st.student_type}
        for st in SStudent.objects.filter(supervisor_staff=s, deleted=0)
    ]
    return ok(request, data)


@transaction.atomic
def update_my_research(request: HttpRequest):
    """S-02/S-05/S-16：编辑科研专属字段（bio/研究方向/学术任职/外部标识）。"""
    dom = domain_from(request)
    s = SStaff.objects.filter(tenant_id=dom.tenant_id, user_id=dom.user_id, deleted=0).first()
    if s is None:
        raise ApiError(404, CODE_NOT_FOUND, "当前用户无人员档案")
    b = read_json(request)
    for k in ("bio", "orcid", "wos_researcher_id", "scopus_id", "cnki_author_id",
              "external_appointments"):
        if b.get(k) is not None:
            setattr(s, k, b[k])
    if b.get("research_expertise") is not None:
        # 自建标签 source=MANUAL 保留；AI 标签可被覆盖
        manual = [t for t in (s.research_expertise or []) if t.get("source") == "MANUAL"]
        s.research_expertise = manual + [
            {**t, "source": t.get("source", "MANUAL"), "updated_at": _now().isoformat()}
            for t in b["research_expertise"]
        ]
    s.modifier_id = dom.user_id
    s.save()
    return ok(request, to_api_staff(s, detail=True))


def get_staff(request: HttpRequest, id: int):
    s = _get_staff_or_404(id)
    return ok(request, to_api_staff(s, detail=True))


TRANSFER_ACTIONS = {"RESIGN", "RETIRE", "TRANSFER_DEPT", "REHIRE", "LEAVE"}


@transaction.atomic
def transfer_staff(request: HttpRequest, id: int):
    """异动/离职交接（S-10）：employment_status 迁移 + leave_date + PI 交接。"""
    dom = domain_from(request)
    s = _get_staff_or_404(id)
    b = read_json(request)
    action = b.get("action")
    if action not in TRANSFER_ACTIONS:
        raise ApiError(400, CODE_BAD_REQUEST, "action 必须为 RESIGN/RETIRE/TRANSFER_DEPT/REHIRE/LEAVE")
    s.employment_status = EMPLOYMENT_MAP[action]
    if action in ("RESIGN", "RETIRE"):
        s.status = "INACTIVE"
        s.is_pi = False
    if action == "TRANSFER_DEPT" and b.get("target_department_id"):
        s.department_id = int(b["target_department_id"])
    if b.get("effective_date"):
        s.leave_date = _parse_date(b["effective_date"])
    s.modifier_id = dom.user_id
    s.remark = "; ".join(filter(None, [s.remark, b.get("reason"),
                                       f"交接 PI: {b.get('handover_pi_staff_id')}"]))
    s.save()
    return ok(request, to_api_staff(s, detail=True))


# ---------------------------------------------------------------------------
# 画像 / 合作网络 / AI
# ---------------------------------------------------------------------------


def get_portrait(request: HttpRequest, id: int):
    s = _get_staff_or_404(id)
    p = SPortrait.objects.filter(staff=s, deleted=0).order_by("-snapshot_date").first()
    if p is None:
        raise ApiError(404, CODE_NOT_FOUND, "暂无画像快照（先触发刷新）")
    data = {
        "staff_id": s.id,
        "snapshot_date": _fmt_date(p.snapshot_date),
        "project_count_total": p.project_count_total,
        "project_count_active": p.project_count_active,
        "funding_total": float(p.funding_total),
        "funding_yearly": float(p.funding_yearly),
        "output_count_papers": p.output_count_papers,
        "output_count_patents": p.output_count_patents,
        "h_index": p.h_index,
        "total_citations": p.total_citations,
        "top_journals": p.top_journals or [],
        "expertise_tags": p.expertise_tags or [],
        "collaboration_score": float(p.collaboration_score),
        "mentoring_count": p.mentoring_count,
        "career_stage": p.career_stage,
        "ai_summary": p.ai_summary,
        # integrity_flag 仅纪检/管理员可见（detail §7）
        **({"integrity_flag": p.integrity_flag} if {"R-AUDITOR", "R-ADMIN"} & set(domain_from(request).roles) else {}),
    }
    return ok(request, data)


@transaction.atomic
def refresh_portrait(request: HttpRequest, id: int):
    """画像刷新：确定性聚合（项目 pi/成果 authors/学生导师数），人日唯一 upsert。"""
    dom = domain_from(request)
    s = _get_staff_or_404(id)
    uid = s.user_id
    from apps.project.models import EProject
    from apps.output.models import ROutput
    from django.db.models import Q as _Q
    projects = EProject.objects.filter(tenant_id=dom.tenant_id, deleted=0)
    pi_total = projects.filter(pi_user_id=uid).count()
    pi_active = projects.filter(pi_user_id=uid, status__in=["EXECUTING", "UNDER_REVIEW"]).count()
    papers = [o for o in ROutput.objects.filter(tenant_id=dom.tenant_id, deleted=0, output_type="PAPER")
              if any(int(a) == uid for a in (o.authors or []) if isinstance(a, (int, str)) and str(a).isdigit())]
    patents = [o for o in ROutput.objects.filter(tenant_id=dom.tenant_id, deleted=0, output_type="PATENT")
               if any(int(a) == uid for a in (o.authors or []) if isinstance(a, (int, str)) and str(a).isdigit())]
    mentoring = SStudent.objects.filter(tenant_id=dom.tenant_id, deleted=0,
                                        supervisor_staff=s, graduate_year__isnull=True).count()
    today = dj_tz.localdate()
    p, _ = SPortrait.objects.update_or_create(
        staff=s, snapshot_date=today, deleted=0,
        defaults={
            "tenant_id": dom.tenant_id,
            "creator_id": dom.user_id,
            "project_count_total": pi_total,
            "project_count_active": pi_active,
            "output_count_papers": len(papers),
            "output_count_patents": len(patents),
            "expertise_tags": [{"tag": t.get("tag"), "weight": t.get("weight", 0.5)}
                               for t in (s.research_expertise or []) if t.get("tag")],
            "mentoring_count": mentoring,
            "career_stage": "RISING" if pi_active > 0 else "STABLE",
            "ai_summary": f"{s.name}：主持在研项目 {pi_active} 项，论文 {len(papers)} 篇、专利 {len(patents)} 件，"
                          f"在培研究生 {mentoring} 人（确定性聚合，LLM 摘要未启用）。",
            "modifier_id": dom.user_id,
        },
    )
    return ok(request, {"staff_id": s.id, "snapshot_date": _fmt_date(p.snapshot_date),
                        "project_count_total": p.project_count_total,
                        "project_count_active": p.project_count_active,
                        "output_count_papers": p.output_count_papers,
                        "mentoring_count": p.mentoring_count})


def get_collab_graph(request: HttpRequest, id: int):
    """S-14 合作网络：时间切片（snapshot_date 参数，缺省最新切片）。"""
    s = _get_staff_or_404(id)
    qs = SCollabGraph.objects.filter(tenant_id=domain_from(request).tenant_id, deleted=0)
    if v := request.GET.get("snapshot_date"):
        qs = qs.filter(snapshot_date=_parse_date(v))
    edges_a = qs.filter(staff_a_id=s.id)
    edges_b = qs.filter(staff_b_id=s.id)
    if not v:
        # 最新切片：取任一侧最大 snapshot_date
        dates = list(edges_a.values_list("snapshot_date", flat=True).distinct()) + \
                list(edges_b.values_list("snapshot_date", flat=True).distinct())
        if dates:
            latest = max(dates)
            edges_a = edges_a.filter(snapshot_date=latest)
            edges_b = edges_b.filter(snapshot_date=latest)
    edges = []
    latest = None
    nodes = [{"staff_id": s.id, "name": s.name, "degree": 0}]
    name_map = {s.id: s.name}
    for e in list(edges_a) + list(edges_b):
        latest = max(latest, e.snapshot_date) if latest else e.snapshot_date
        other_id = e.staff_b_id if e.staff_a_id == s.id else e.staff_a_id
        if other_id not in name_map:
            other = SStaff.objects.filter(id=other_id, deleted=0).first()
            name_map[other_id] = other.name if other else f"staff-{other_id}"
        edges.append({"staff_a_id": e.staff_a_id, "staff_b_id": e.staff_b_id,
                      "weight": e.weight, "snapshot_date": _fmt_date(e.snapshot_date)})
    for nid, nm in name_map.items():
        deg = sum(1 for e in edges if nid in (e["staff_a_id"], e["staff_b_id"]))
        nodes.append({"staff_id": nid, "name": nm, "degree": deg})
    nodes[0]["degree"] = len(edges)
    return ok(request, {"center_staff_id": s.id,
                        "snapshot_date": _fmt_date(latest) if latest else dj_tz.localdate().isoformat(),
                        "nodes": nodes, "edges": edges})


@transaction.atomic
def ai_expertise(request: HttpRequest, id: int):
    """S-05 AI 方向标签：确定性从自建标签+bio 关键词聚合（LLM 增强由 svc-ai 承接）。"""
    s = _get_staff_or_404(id)
    b = read_json_soft(request)
    incremental = bool(b.get("incremental", True))
    max_tags = int(b.get("max_tags") or 8)
    existing = list(s.research_expertise or [])
    if incremental and existing:
        tags = existing
    else:
        tags = []
    # bio 关键词确定性补充：取 bio 中的顿号/逗号分词命中已有标签则加权
    if s.bio:
        for t in list(tags):
            if t.get("tag") and t["tag"] in s.bio:
                t["weight"] = min(1.0, float(t.get("weight", 0.5)) + 0.1)
    tags = tags[:max_tags]
    for t in tags:
        if t.get("source") != "MANUAL":
            t["source"] = "AI"
            t["updated_at"] = _now().isoformat()
    s.research_expertise = tags
    s.modifier_id = domain_from(request).user_id
    s.save(update_fields=["research_expertise", "modifier_id", "updated_at"])
    return ok(request, {"staff_id": s.id, "tags": tags})


@transaction.atomic
def ai_resume(request: HttpRequest, id: int):
    """S-05 AI 学术简历：从档案+画像+人才计划确定性导出（PDF/DOCX 由模板引擎套打）。"""
    s = _get_staff_or_404(id)
    b = read_json(request)
    fmt = b.get("format") or "PDF"
    portrait = SPortrait.objects.filter(staff=s, deleted=0).order_by("-snapshot_date").first()
    plans = list(STalentPlan.objects.filter(staff=s, deleted=0))
    resume = {
        "name": s.name,
        "name_en": s.name_en,
        "title": s.title,
        "orcid": s.orcid,
        "bio": s.bio,
        "research_expertise": [t.get("tag") for t in (s.research_expertise or [])],
        "appointments": s.external_appointments or [],
        "portrait": {
            "project_count_total": portrait.project_count_total if portrait else 0,
            "output_count_papers": portrait.output_count_papers if portrait else 0,
            "output_count_patents": portrait.output_count_patents if portrait else 0,
            "h_index": portrait.h_index if portrait else 0,
        } if portrait else None,
        "talent_plans": [{"plan_name": p.plan_name, "level": p.level,
                          "awarded_year": p.awarded_year} for p in plans],
        "sections": b.get("sections") or ["BASIC", "EXPERTISE", "OUTPUTS", "TALENT"],
        "language": b.get("language") or "zh-CN",
        "download_url": f"/downloads/staff/{s.id}/resume.{fmt.lower()}",
    }
    return ok(request, resume)


# ---------------------------------------------------------------------------
# 团队 / 成员
# ---------------------------------------------------------------------------


def _sync_team_snapshot(team: STeam):
    members = SMembership.objects.filter(team=team, deleted=0, left_at__isnull=True)
    team.member_ids = [
        {"user_id": m.user_id, "staff_id": m.staff_id, "role": m.role,
         "joined_at": m.joined_at.isoformat()}
        for m in members
    ]
    team.save(update_fields=["member_ids", "updated_at"])


def list_teams(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = STeam.objects.filter(tenant_id=domain_from(request).tenant_id, deleted=0)
    for k in ("team_type", "status"):
        if v := request.GET.get(k):
            qs = qs.filter(**{k: v})
    if v := request.GET.get("department_id"):
        try:
            qs = qs.filter(department_id=int(v))
        except ValueError:
            pass
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [{
        "id": t.id, "code": t.code, "name": t.name, "team_type": t.team_type,
        "status": t.status, "pi_staff_id": t.pi_staff_id, "pi_user_id": t.pi_user_id,
        "department_id": t.department_id,
        "member_count": len(t.member_ids or []),
        "formed_date": _fmt_date(t.formed_date),
    } for t in rows], "total": total, "page": page, "size": size})


@transaction.atomic
def create_team(request: HttpRequest):
    dom = domain_from(request)
    b = read_json(request)
    if not b.get("name"):
        raise ApiError(400, CODE_BAD_REQUEST, "name 必填")
    pi_staff = None
    if b.get("pi_staff_id"):
        pi_staff = _get_staff_or_404(int(b["pi_staff_id"]))
        if not pi_staff.is_pi:
            pi_staff.is_pi = True
            pi_staff.save(update_fields=["is_pi", "updated_at"])
    t = STeam.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        name=b["name"], team_type=b.get("team_type") or "PI_GROUP",
        pi_staff=pi_staff, pi_user_id=pi_staff.user_id if pi_staff else b.get("pi_user_id"),
        department_id=b.get("department_id"),
        formed_date=_parse_date(b.get("formed_date")),
        evaluation_cycle=b.get("evaluation_cycle"),
        legal_entity_id=dom.legal_entity_id or 1,
        status="ACTIVE",
    )
    if pi_staff:
        SMembership.objects.create(
            tenant_id=dom.tenant_id, creator_id=dom.user_id, team=t, staff=pi_staff,
            user_id=pi_staff.user_id, role="LEADER",
        )
        _sync_team_snapshot(t)
    return ok(request, {"id": t.id, "name": t.name, "status": t.status,
                        "pi_staff_id": t.pi_staff_id, "member_count": len(t.member_ids or [])})


def get_team(request: HttpRequest, id: int):
    t = STeam.objects.filter(id=id, deleted=0).first()
    if t is None:
        raise ApiError(404, CODE_NOT_FOUND, "团队不存在")
    members = SMembership.objects.filter(team=t, deleted=0).order_by("joined_at")
    return ok(request, {
        "id": t.id, "code": t.code, "name": t.name, "team_type": t.team_type,
        "status": t.status, "pi_staff_id": t.pi_staff_id, "pi_user_id": t.pi_user_id,
        "department_id": t.department_id, "member_count": len(t.member_ids or []),
        "formed_date": _fmt_date(t.formed_date),
        "evaluation_cycle": t.evaluation_cycle,
        "members": [{
            "id": m.id, "staff_id": m.staff_id, "user_id": m.user_id, "role": m.role,
            "joined_at": m.joined_at.isoformat(), "left_at": m.left_at.isoformat() if m.left_at else None,
            "contribution_summary": m.contribution_summary, "status": m.status,
        } for m in members],
    })


def list_team_members(request: HttpRequest, id: int):
    t = STeam.objects.filter(id=id, deleted=0).first()
    if t is None:
        raise ApiError(404, CODE_NOT_FOUND, "团队不存在")
    only_active = request.GET.get("include_left") not in ("true", "1")
    qs = SMembership.objects.filter(team=t, deleted=0)
    if only_active:
        qs = qs.filter(left_at__isnull=True)
    return ok(request, {"list": [{
        "id": m.id, "staff_id": m.staff_id, "user_id": m.user_id, "role": m.role,
        "name": m.staff.name, "joined_at": m.joined_at.isoformat(),
        "left_at": m.left_at.isoformat() if m.left_at else None,
        "contribution_summary": m.contribution_summary, "status": m.status,
    } for m in qs.order_by("joined_at")], "total": qs.count()})


@transaction.atomic
def add_team_member(request: HttpRequest, id: int):
    dom = domain_from(request)
    t = STeam.objects.filter(id=id, deleted=0).first()
    if t is None:
        raise ApiError(404, CODE_NOT_FOUND, "团队不存在")
    b = read_json(request)
    if not b.get("staff_id") or b.get("role") not in MEMBER_ROLES:
        raise ApiError(400, CODE_BAD_REQUEST, "staff_id 与 role(LEADER/CORE/MEMBER/STUDENT/VISITOR) 必填")
    s = _get_staff_or_404(int(b["staff_id"]))
    if SMembership.objects.filter(team=t, staff=s, deleted=0, left_at__isnull=True).exists():
        raise ApiError(409, CODE_CONFLICT, "成员已在册（同团队在册唯一）")
    m = SMembership.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id, team=t, staff=s,
        user_id=s.user_id, role=b["role"],
        contribution_summary=b.get("contribution_summary"),
    )
    _sync_team_snapshot(t)
    return ok(request, {"id": m.id, "staff_id": m.staff_id, "role": m.role,
                        "team_member_count": len(t.member_ids or [])})


@transaction.atomic
def remove_team_member(request: HttpRequest, id: int):
    dom = domain_from(request)
    t = STeam.objects.filter(id=id, deleted=0).first()
    if t is None:
        raise ApiError(404, CODE_NOT_FOUND, "团队不存在")
    b = read_json(request)
    if not b.get("staff_id"):
        raise ApiError(400, CODE_BAD_REQUEST, "staff_id 必填")
    m = SMembership.objects.filter(team=t, staff_id=int(b["staff_id"]), deleted=0,
                                   left_at__isnull=True).first()
    if m is None:
        raise ApiError(404, CODE_NOT_FOUND, "成员不在册")
    m.left_at = _now()
    m.status = "LEFT"
    m.remark = "; ".join(filter(None, [m.remark, b.get("reason")]))
    m.modifier_id = dom.user_id
    m.save()
    _sync_team_snapshot(t)
    return ok(request, {"id": m.id, "left_at": m.left_at.isoformat(),
                        "team_member_count": len(t.member_ids or [])})


# ---------------------------------------------------------------------------
# 客座 / 访问学者
# ---------------------------------------------------------------------------


def list_visitors(request: HttpRequest):
    page, size, limit, offset = page_args(request)
    qs = SVisitor.objects.filter(tenant_id=domain_from(request).tenant_id, deleted=0)
    if v := request.GET.get("status"):
        qs = qs.filter(status=v)
    if v := request.GET.get("host_pi_staff_id"):
        try:
            qs = qs.filter(host_pi_staff_id=int(v))
        except ValueError:
            pass
    total = qs.count()
    rows = list(qs.order_by("-id")[offset:offset + limit])
    return ok(request, {"list": [{
        "id": r.id, "code": r.code, "status": r.status, "staff_id": r.staff_id,
        "staff_name": r.staff.name,
        "host_pi_staff_id": r.host_pi_staff_id, "host_team_id": r.host_team_id,
        "home_institution": r.home_institution, "visit_type": r.visit_type,
        "start_date": _fmt_date(r.start_date), "end_date": _fmt_date(r.end_date),
        "funding_source": r.funding_source, "project_id": r.project_id,
        "permissions_scope": r.permissions_scope or {}, "reminder_stage": r.reminder_stage,
    } for r in rows], "total": total, "page": page, "size": size})


@transaction.atomic
def apply_visitor(request: HttpRequest):
    """S-08：申请即建 S_STAFF 档（VISITING_SCHOLAR/GUEST）+ S_VISITOR(APPLIED)。"""
    dom = domain_from(request)
    b = read_json(request)
    for k in ("name", "hr_code_placeholder", "host_pi_staff_id", "visit_type",
              "start_date", "end_date", "permissions_scope"):
        if b.get(k) is None:
            raise ApiError(400, CODE_BAD_REQUEST, f"{k} 必填")
    if SStaff.objects.filter(tenant_id=dom.tenant_id, hr_code=b["hr_code_placeholder"], deleted=0).exists():
        raise ApiError(409, CODE_CONFLICT, "工号已存在")
    staff = SStaff.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        user_id=0,  # 客座尚未开通账号
        hr_code=b["hr_code_placeholder"], name=b["name"], name_en=b.get("name_en"),
        email=b.get("email"),
        department_id=b.get("department_id") or 0,
        staff_type="VISITING_SCHOLAR" if b["visit_type"] == "LONG_TERM" else "GUEST",
        employment_status="VISITING" if b["visit_type"] == "LONG_TERM" else "GUEST",
        legal_entity_id=dom.legal_entity_id or 1,
    )
    v = SVisitor.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id, staff=staff,
        host_pi_staff_id=int(b["host_pi_staff_id"]),
        host_team_id=b.get("host_team_id"),
        home_institution=b.get("home_institution"),
        visit_type=b["visit_type"],
        start_date=_parse_date(b["start_date"]), end_date=_parse_date(b["end_date"]),
        funding_source=b.get("funding_source"), project_id=b.get("project_id"),
        permissions_scope=b["permissions_scope"],
    )
    return ok(request, {"id": v.id, "staff_id": staff.id, "status": v.status,
                        "visit_type": v.visit_type})


@transaction.atomic
def approve_visitor(request: HttpRequest, id: int):
    dom = domain_from(request)
    v = SVisitor.objects.filter(id=id, deleted=0).first()
    if v is None:
        raise ApiError(404, CODE_NOT_FOUND, "客座申请不存在")
    if v.status != "APPLIED":
        raise ApiError(409, CODE_CONFLICT, f"审批状态机冲突：当前 {v.status}")
    b = read_json(request)
    decision = b.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise ApiError(400, CODE_BAD_REQUEST, "decision 必须为 APPROVE/REJECT")
    v.status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    if decision == "APPROVE":
        scope = v.permissions_scope or {}
        if b.get("role_codes"):
            scope["role_codes"] = b["role_codes"]
        v.permissions_scope = scope
    v.remark = "; ".join(filter(None, [v.remark, b.get("comment")]))
    v.modifier_id = dom.user_id
    v.save()
    return ok(request, {"id": v.id, "status": v.status,
                        "permissions_scope": v.permissions_scope or {}})


# ---------------------------------------------------------------------------
# 学生登记 / 人才计划 / 梯队分析
# ---------------------------------------------------------------------------


@transaction.atomic
def register_student(request: HttpRequest):
    """S-09：学生参与科研登记（建 S_STAFF[STUDENT] + S_STUDENT）。"""
    dom = domain_from(request)
    b = read_json(request)
    for k in ("name", "student_type", "supervisor_staff_id"):
        if b.get(k) is None:
            raise ApiError(400, CODE_BAD_REQUEST, f"{k} 必填")
    supervisor = _get_staff_or_404(int(b["supervisor_staff_id"]))
    staff = SStaff.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id,
        user_id=b.get("user_id") or 0, hr_code=b.get("hr_code") or f"STU-{time.time_ns() % 10**8}",
        name=b["name"], department_id=supervisor.department_id,
        staff_type="STUDENT", position="STUDENT", employment_status="ONBOARD",
        legal_entity_id=dom.legal_entity_id or 1,
    )
    st = SStudent.objects.create(
        tenant_id=dom.tenant_id, creator_id=dom.user_id, staff=staff,
        student_type=b["student_type"], supervisor_staff=supervisor,
        supervisor_user_id=supervisor.user_id,
        enroll_year=b.get("enroll_year"), thesis_topic=b.get("thesis_topic"),
        associated_project_ids=b.get("associated_project_ids") or [],
    )
    return ok(request, {"id": st.id, "staff_id": staff.id, "student_type": st.student_type,
                        "supervisor_staff_id": supervisor.id})


def list_talent_plans(request: HttpRequest, id: int):
    """S-12 人才计划与称号（画像时间轴数据源）。"""
    s = _get_staff_or_404(id)
    qs = STalentPlan.objects.filter(staff=s, deleted=0).order_by("-awarded_year")
    if v := request.GET.get("status"):
        qs = qs.filter(status=v)
    return ok(request, {"list": [{
        "id": p.id, "staff_id": s.id, "plan_name": p.plan_name, "plan_code": p.plan_code,
        "level": p.level, "awarded_year": p.awarded_year, "duration_years": p.duration_years,
        "end_year": p.end_year, "batch": p.batch, "status": p.status,
    } for p in qs], "total": qs.count()})


def talent_analysis(request: HttpRequest):
    """S-15 AI 梯队缺口分析：按层级统计在期计划 + 确定性缺口提示。"""
    dom = domain_from(request)
    qs = STalentPlan.objects.filter(tenant_id=dom.tenant_id, deleted=0)
    by_level = {}
    for lv in ("NATIONAL", "MINISTRY", "PROVINCE", "INSTITUTE"):
        by_level[lv] = qs.filter(level=lv, status="ACTIVE").count()
    total_pi = SStaff.objects.filter(tenant_id=dom.tenant_id, deleted=0, is_pi=True).count()
    gaps = []
    if by_level["NATIONAL"] == 0:
        gaps.append("国家级人才在期 0 人：建议培育杰青/优青梯队候选人")
    if by_level["INSTITUTE"] < max(1, total_pi // 10):
        gaps.append("院所自立人才储备不足 PI 总量的 10%：建议扩充院内培养计划")
    return ok(request, {
        "total_pi": total_pi,
        "active_by_level": by_level,
        "pipeline_candidates": qs.filter(status="CANDIDATE").count(),
        "gaps": gaps,
        "note": "确定性统计（LLM 梯队策略建议由 svc-ai 增强未启用）",
    })
