"""S 人员团队域 · 接口请求 Schema 验证定义（pydantic v2，配合 core.reqschema.validate_body）。"""
from __future__ import annotations

from core.reqschema import BaseIn


class TransferIn(BaseIn):
    action: str  # RESIGN/RETIRE/TRANSFER_DEPT/REHIRE/LEAVE（枚举由 handler 判定）
    target_department_id: int | None = None
    effective_date: str | None = None
    handover_pi_staff_id: int | None = None
    reason: str | None = None
    remark: str | None = None


class TeamIn(BaseIn):
    name: str
    team_type: str | None = None
    description: str | None = None
    pi_staff_id: int | None = None
    member_ids: list | None = None
    legal_entity_id: int | None = None
    remark: str | None = None


class TeamMemberIn(BaseIn):
    staff_id: int
    role: str
    join_date: str | None = None


class TeamMemberRemoveIn(BaseIn):
    staff_id: int
    reason: str | None = None


class VisitorIn(BaseIn):
    name: str
    hr_code_placeholder: str
    host_pi_staff_id: int
    visit_type: str
    start_date: str
    end_date: str
    permissions_scope: dict | list
    home_institution: str | None = None
    affiliation: str | None = None
    id_type: str | None = None
    id_no: str | None = None
    remark: str | None = None


class StudentIn(BaseIn):
    name: str
    student_type: str
    supervisor_staff_id: int
    enrollment_date: str | None = None
    remark: str | None = None
