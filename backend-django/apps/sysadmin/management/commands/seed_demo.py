"""演示数据播种（对齐 Go seeddemo 语义：幂等，DEMO- 前缀/种子行存在即跳过）。

Phase 0 范围：8 基础角色、4 演示用户、字典种子、页面可见性矩阵种子。
Phase 4 扩展：16 业务域全域演示数据（notify/p/project/funding/output/expertreview/
activity/archive/performance/transform/ethics/staff/procure/asset/confsec + 法人/组织）。
用法：python manage.py seed_demo
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta

import bcrypt
from django.core.management.base import BaseCommand
from django.utils import timezone as dj_tz

from apps.sysadmin.models import PageGrant, SysDict, SysDictItem, SysLegalEntity, SysOrg, SysRole, SysUser, SysUserRole

ROLES = [
    ("R-STAFF", "科研人员"),
    ("R-MANAGER", "科研管理岗"),
    ("R-LEADER", "单位领导"),
    ("R-FINANCE", "财务"),
    ("R-AUDITOR", "审计"),
    ("R-EXPERT", "评审专家"),
    ("R-ETHICS", "伦理委员会"),
    ("R-ADMIN", "系统管理员"),
]

USERS = [  # (username, real_name, email, staff_no, security_level, password)
    ("admin", "系统管理员", "admin@eplugger.com", "A0001", "TOP_SECRET", "Admin@123456"),
    ("manager", "科研管理岗", "manager@eplugger.com", "A0002", "SECRET", "Manager@123456"),
    ("staff", "一线研究员", "staff@eplugger.com", "A0003", "INTERNAL", "Staff@123456"),
    ("finance", "财务专员", "finance@eplugger.com", "A0004", "SECRET", "Finance@123456"),
]

USER_ROLES = {
    "admin": ["R-ADMIN"],
    "manager": ["R-MANAGER", "R-LEADER"],
    "staff": ["R-STAFF"],
    "finance": ["R-FINANCE"],
}

DICTS = {
    "project_type": (
        "项目类型",
        [("NSFC", "国家自然科学基金", {"icon": "自", "color": "#2C6E49"}),
         ("KJBP", "重点研发计划", {"icon": "重", "color": "#A8842F"}),
         ("ZIGE", "院自立项目", {"icon": "院", "color": "#41598C"}),
         ("PROV", "省部级", {"icon": "省", "color": "#5B4FA0"}),
         ("HENGXIANG", "横向委托", {"icon": "横", "color": "#C2402C"})],
    ),
    "output_source": (
        "成果来源",
        [("WOS", "WoS", None), ("SCOPUS", "Scopus", None), ("CNKI", "知网", None),
         ("WANFANG", "万方", None), ("CNIPA", "国家知识产权局", None),
         ("CROSSREF", "CrossRef", None), ("FETCH", "增量抓取", None),
         ("MANUAL", "手动录入", None), ("ALTMETRIC", "Altmetric", None)],
    ),
    "activity_type": (
        "学术活动类型",
        [("CONFERENCE", "学术会议", None), ("LECTURE", "讲座报告", None),
         ("SEMINAR", "研讨班", None), ("TRAINING", "培训", None), ("OTHER", "其他", None)],
    ),
    "activity_level": (
        "学术活动级别",
        [("INTERNATIONAL", "国际", None), ("NATIONAL", "国家", None),
         ("PROVINCIAL", "省级", None), ("CAMPUS", "校内", None)],
    ),
    "pay_method": (
        "支付方式",
        [("GWC", "公务卡转账（默认）", None), ("DG", "对公转账", None), ("XJ", "现金/备用金", None)],
    ),
}

PAGE_GRANTS = [
    ("dash", "*"), ("guide", "*"), ("project", "*"),
    ("bigscreen", "R-LEADER"), ("bigscreen", "R-FINANCE"), ("bigscreen", "R-AUDITOR"), ("bigscreen", "R-ADMIN"),
    ("editor", "R-STAFF"), ("editor", "R-MANAGER"), ("editor", "R-LEADER"),
    ("review", "R-MANAGER"), ("review", "R-EXPERT"), ("review", "R-ETHICS"), ("review", "R-LEADER"), ("review", "R-ADMIN"),
    ("projects", "R-STAFF"), ("projects", "R-MANAGER"), ("projects", "R-LEADER"),
    ("expense", "R-STAFF"), ("expense", "R-MANAGER"), ("expense", "R-FINANCE"),
    ("claim", "R-STAFF"), ("claim", "R-MANAGER"), ("claim", "R-LEADER"),
    ("output", "R-STAFF"), ("output", "R-MANAGER"), ("output", "R-LEADER"),
    ("transfer", "R-MANAGER"), ("transfer", "R-LEADER"), ("transfer", "R-ADMIN"),
    ("procurement", "R-MANAGER"), ("procurement", "R-FINANCE"), ("procurement", "R-ADMIN"),
    ("asset", "R-MANAGER"), ("asset", "R-FINANCE"), ("asset", "R-ADMIN"),
    ("portrait", "R-LEADER"), ("portrait", "R-MANAGER"), ("portrait", "R-ADMIN"),
    ("activity", "R-STAFF"), ("activity", "R-MANAGER"), ("activity", "R-LEADER"), ("activity", "R-AUDITOR"),
    ("performance", "R-STAFF"), ("performance", "R-MANAGER"), ("performance", "R-LEADER"),
    ("performance", "R-FINANCE"), ("performance", "R-AUDITOR"),
    ("expert-review", "R-EXPERT"), ("expert-review", "R-MANAGER"), ("expert-review", "R-LEADER"),
    ("expert-review", "R-AUDITOR"),
    ("archive", "R-ADMIN"), ("archive", "R-MANAGER"), ("archive", "R-AUDITOR"),
    ("admin-users", "R-ADMIN"), ("admin-roles", "R-ADMIN"), ("admin-roles", "R-AUDITOR"),
    ("admin-dicts", "R-ADMIN"),
    ("funding-config", "R-MANAGER"), ("funding-config", "R-FINANCE"),
]


class Command(BaseCommand):
    help = "幂等播种演示数据（角色/用户/字典/页面矩阵）"

    def handle(self, *args, **options):
        n_roles = n_users = n_dicts = n_items = n_grants = 0

        role_objs = {}
        for code, name in ROLES:
            r, created = SysRole.objects.get_or_create(
                code=code, tenant_id=1, defaults={"name": name, "is_builtin": True}
            )
            role_objs[code] = r
            n_roles += int(created)

        user_objs = {}
        for username, real_name, email, staff_no, sec, pwd in USERS:
            u, created = SysUser.objects.get_or_create(
                username=username, tenant_id=1,
                defaults={
                    "real_name": real_name, "email": email, "staff_no": staff_no,
                    "security_level": sec, "status": "ACTIVE",
                    "password_hash": bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode(),
                    "creator_id": 1,
                },
            )
            user_objs[username] = u
            n_users += int(created)
            for code in USER_ROLES[username]:
                SysUserRole.objects.get_or_create(
                    user=u, role=role_objs[code], tenant_id=1
                )

        for code, (name, items) in DICTS.items():
            d, created = SysDict.objects.get_or_create(
                code=code, tenant_id=1, deleted=0,
                defaults={"name": name, "remark": "种子（迁自前端硬编码枚举）", "creator_id": 1},
            )
            n_dicts += int(created)
            for idx, (ic, label, ext) in enumerate(items, start=1):
                _, c = SysDictItem.objects.get_or_create(
                    dict=d, item_code=ic, effective_from=None,
                    defaults={"item_label": label, "ext_json": ext, "sort_no": idx,
                              "active": True, "tenant_id": 1},
                )
                n_items += int(c)

        for page_name, role_code in PAGE_GRANTS:
            _, c = PageGrant.objects.get_or_create(
                tenant_id=1, page_name=page_name, role_code=role_code
            )
            n_grants += int(c)

        n = self._seed_domains(user_objs)
        n.update(roles=n_roles, users=n_users, dicts=n_dicts, items=n_items, grants=n_grants)
        self.stdout.write(
            self.style.SUCCESS(
                "seed_demo 完成（幂等）：" + "，".join(f"{k} +{v}" for k, v in n.items() if v)
            )
        )

    # ------------------------------------------------------------------
    # Phase 4：16 业务域全域种子（幂等，DEMO 前缀）
    # ------------------------------------------------------------------

    @staticmethod
    def _filt(model, kwargs: dict) -> dict:
        """过滤掉模型上不存在的字段名，避免可选字段落库 FieldError。"""
        valid = {f.name for f in model._meta.fields}
        return {k: v for k, v in kwargs.items() if k in valid}

    def _seed_domains(self, users: dict) -> dict:
        from datetime import date as _date

        from apps.activity.models import VActivity, VActivityParticipant
        from apps.archive.models import OBorrow, OArchive, OArchiveItem, ODocument
        from apps.asset.models import (
            AAsset, AConsumable, ADepreciation, ADisposal, AStockTxn,
        )
        from apps.confsec.models import (
            XAccessGrant, XFlowAudit, XPersonnelSec, XSecLog, XSecurityPolicy,
        )
        from apps.ethics.models import CEthicsCase, CIntegrityPledge, CIntegrityRecord, CReviewerAssign
        from apps.expertreview.models import (
            NExpert, NExpertGroup, NReviewFee, NReviewScore, NReviewTask,
        )
        from apps.funding.models import FBudget, FBudgetLine, FExpense, FIncome, FSubject
        from apps.notify.models import SysImportLog, SysNotification, SysTask
        from apps.output.models import RDataset, RJournalSource, ROutput
        from apps.p.models import PApplication, PGuideline
        from apps.performance.models import MPayout, MRecord, MScheme, MSchemeFactor
        from apps.procure.models import GBid, GContract, GOrder, GRequisition, GSupplier
        from apps.project.models import EProject, EProgressReport, EMilestone, ETask
        from apps.staff.models import SMembership, SStaff, SStudent, STeam, SVisitor
        from apps.transform.models import (
            TAnnualReport, TContract, TDeal, TDisclosure, TDistributionRecord,
            TDistributionRule, TEnterpartner, TIncome, TPublicity, TValuation,
        )

        cnt: dict[str, int] = {}

        def put(model, key: dict, defaults: dict, domain: str) -> object:
            obj, created = model.objects.get_or_create(
                **key, defaults=self._filt(model, defaults)
            )
            cnt[domain] = cnt.get(domain, 0) + int(created)
            return obj

        T1, C1 = 1, 1
        today = dj_tz.localdate()
        now = dj_tz.now()

        # ---- A. 法人 / 组织 ------------------------------------------------
        ent = put(SysLegalEntity,
                  {"code": "LE-DEMO-01", "tenant_id": T1},
                  {"name": "演示研究院", "entity_type": "INSTITUTE"}, "legal")
        put(SysOrg, {"code": "ORG-DEMO-01", "tenant_id": T1},
            {"name": "新材料研究中心", "org_type": "DEPT", "status": "ACTIVE"}, "legal")

        # ---- B. S 人员团队 --------------------------------------------------
        sstaff = {}
        for username, u in users.items():
            sstaff[username] = put(SStaff, {"tenant_id": T1, "user_id": u.id},
                                   {"hr_code": f"EMP-{username.upper():0>6}", "name": u.real_name,
                                    "department_id": 1, "employment_status": "ACTIVE",
                                    "status": "ACTIVE", "creator_id": C1, "is_pi": username == "manager"},
                                   "staff")
        # 客座 / 学生档案（无系统账号，user_id=0）
        sstaff["visitor"] = put(SStaff, {"tenant_id": T1, "hr_code": "VIS-DEMO-01"},
                                {"user_id": 0, "name": "张客座", "department_id": 1,
                                 "employment_status": "ACTIVE", "status": "ACTIVE", "creator_id": C1}, "staff")
        sstaff["student"] = put(SStaff, {"tenant_id": T1, "hr_code": "STU-DEMO-01"},
                                {"user_id": 0, "name": "李研究生", "department_id": 1,
                                 "employment_status": "ACTIVE", "status": "ACTIVE", "creator_id": C1}, "staff")
        team = put(STeam, {"tenant_id": T1, "code": "TEAM-DEMO-01"},
                   {"name": "催化材料团队", "team_type": "RESEARCH", "status": "ACTIVE",
                    "creator_id": C1, "description": "新能源催化方向演示团队"}, "staff")
        put(SMembership, {"tenant_id": T1, "team": team, "staff": sstaff["manager"]},
            {"role": "PI", "user_id": users["manager"].id, "status": "ACTIVE",
             "creator_id": C1, "joined_at": now}, "staff")
        put(SMembership, {"tenant_id": T1, "team": team, "staff": sstaff["staff"]},
            {"role": "MEMBER", "user_id": users["staff"].id, "status": "ACTIVE",
             "creator_id": C1, "joined_at": now}, "staff")
        put(SVisitor, {"tenant_id": T1, "code": "VIS-DEMO-01"},
            {"staff": sstaff["visitor"], "visit_type": "LONG_TERM",
             "start_date": today, "end_date": today + timedelta(days=365),
             "home_institution": "海外大学", "host_pi_staff": sstaff["manager"],
             "permissions_scope": {"modules": ["project", "output"]},
             "status": "ACTIVE", "creator_id": C1}, "staff")
        put(SStudent, {"tenant_id": T1, "code": "STU-DEMO-01"},
            {"staff": sstaff["student"], "student_type": "MASTER",
             "supervisor_staff": sstaff["manager"], "enroll_year": today.year,
             "thesis_topic": "高熵催化剂构效关系", "status": "ACTIVE", "creator_id": C1}, "staff")

        # ---- C. P 申报指南 / 申请 -------------------------------------------
        gl = put(PGuideline, {"tenant_id": T1, "code": "GL-DEMO-2026-01"},
                 {"title": "2026 年度国家自然科学基金申报指南（演示）", "project_type": "NSFC",
                  "status": "PUBLISHED", "creator_id": C1,
                  "apply_start_at": now, "apply_end_at": now + timedelta(days=60),
                  "funding_source": "NSFC", "total_envelope": 5000000,
                  "publish_at": now, "content_rich": "演示指南正文"}, "p")
        app = put(PApplication, {"tenant_id": T1, "code": "APP-DEMO-2026-01"},
                  {"guideline_id": gl.id, "title": "高熵催化剂申报书（演示）",
                   "project_type": "NSFC", "pi_user_id": users["manager"].id,
                   "status": "SUBMITTED", "creator_id": C1,
                   "duration_months": 36, "total_budget": 2000000,
                   "abstract": "演示摘要", "is_horizontal": False}, "p")

        # ---- D. E 项目（任务/里程碑/进展报告） -------------------------------
        prj1 = put(EProject, {"tenant_id": T1, "code": "PRJ-DEMO-001"},
                   {"application_id": app.id, "title": "面向新能源的高熵催化剂研发",
                    "project_type": "NSFC", "pi_user_id": users["manager"].id,
                    "member_ids": [users["manager"].id, users["staff"].id],
                    "department_id": 1, "legal_entity_id": ent.id,
                    "start_date": today - timedelta(days=120),
                    "end_date": today + timedelta(days=610),
                    "total_budget": 2000000, "received_amount": 1000000,
                    "spent_amount": 320000, "health_score": 90, "risk_level": "LOW",
                    "status": "ACTIVE", "creator_id": C1}, "project")
        prj2 = put(EProject, {"tenant_id": T1, "code": "PRJ-DEMO-002"},
                   {"application_id": app.id, "title": "固态电解质界面修饰研究（横向演示）",
                    "project_type": "HENGXIANG", "pi_user_id": users["staff"].id,
                    "member_ids": [users["staff"].id], "department_id": 1,
                    "legal_entity_id": ent.id, "start_date": today - timedelta(days=30),
                    "end_date": today + timedelta(days=335), "total_budget": 500000,
                    "status": "ACTIVE", "creator_id": C1, "security_level": "INTERNAL"}, "project")
        put(ETask, {"tenant_id": T1, "code": "TASK-DEMO-001", "project": prj1},
            {"name": "催化剂前驱体合成", "status": "DOING", "owner_user_id": users["staff"].id,
             "creator_id": C1, "progress_percent": 40,
             "planned_start": today - timedelta(days=60), "planned_end": today + timedelta(days=60),
             "description": "演示任务"}, "project")
        put(ETask, {"tenant_id": T1, "code": "TASK-DEMO-002", "project": prj1},
            {"name": "电催化性能评价", "status": "PENDING", "owner_user_id": users["manager"].id,
             "creator_id": C1, "progress_percent": 0,
             "planned_start": today + timedelta(days=61), "planned_end": today + timedelta(days=180),
             "description": "演示任务（依赖前驱体合成）", "dep_task_ids": []}, "project")
        put(EMilestone, {"tenant_id": T1, "code": "MS-DEMO-001", "project": prj1},
            {"name": "开题论证", "due_date": today - timedelta(days=100), "status": "DONE",
             "actual_date": today - timedelta(days=98), "creator_id": C1,
             "deliverable_type": "DOC"}, "project")
        put(EMilestone, {"tenant_id": T1, "code": "MS-DEMO-002", "project": prj1},
            {"name": "中期检查", "due_date": today + timedelta(days=185), "status": "PENDING",
             "creator_id": C1, "deliverable_type": "REPORT"}, "project")
        put(EProgressReport, {"tenant_id": T1, "code": "RPT-DEMO-2026Q3", "project": prj1},
            {"period": "2026-Q3", "report_type": "QUARTERLY", "progress_percent": 45,
             "content_rich": "季度进展演示", "issues_text": "无重大问题",
             "next_plan": "推进性能评价", "status": "SUBMITTED", "creator_id": C1,
             "submitted_at": now}, "project")

        # ---- E. F 经费（科目/预算/报销/到账） --------------------------------
        subj_m = put(FSubject, {"tenant_id": T1, "name": "设备费"},
                     {"category": "DIRECT", "level": 1, "is_leaf": True, "sort_no": 1,
                      "status": "ACTIVE", "creator_id": C1}, "funding")
        subj_m_2 = put(FSubject, {"tenant_id": T1, "name": "材料费"},
                       {"category": "DIRECT", "level": 1, "is_leaf": True, "sort_no": 2,
                        "status": "ACTIVE", "creator_id": C1}, "funding")
        put(FSubject, {"tenant_id": T1, "name": "管理费"},
            {"category": "INDIRECT", "level": 1, "is_leaf": True, "sort_no": 3,
             "ratio_limit": 0.1, "status": "ACTIVE", "creator_id": C1}, "funding")
        bud = put(FBudget, {"tenant_id": T1, "code": "BUD-DEMO-001"},
                  {"project_id": prj1.id, "legal_entity_id": ent.id, "mode": "ANNUAL",
                   "total_approved": 2000000, "version": 1, "status": "APPROVED",
                   "creator_id": C1, "approved_at": now, "approved_by": C1}, "funding")
        put(FBudgetLine, {"tenant_id": T1, "code": "BUDL-DEMO-001", "budget_id": bud.id,
                          "subject_id": subj_m.id},
            {"amount_planned": 800000, "amount_used": 320000, "status": "ACTIVE",
             "creator_id": C1}, "funding")
        put(FBudgetLine, {"tenant_id": T1, "code": "BUDL-DEMO-002", "budget_id": bud.id,
                          "subject_id": subj_m_2.id},
            {"amount_planned": 400000, "status": "ACTIVE", "creator_id": C1}, "funding")
        put(FExpense, {"tenant_id": T1, "code": "EXP-DEMO-0001"},
            {"project_id": prj1.id, "legal_entity_id": ent.id,
             "applicant_user_id": users["staff"].id, "amount": 120000,
             "expense_category": "设备费", "expense_type": "EQUIPMENT",
             "description": "X 射线衍射仪采购尾款（演示）", "status": "PAID",
             "creator_id": C1, "paid_at": now}, "funding")
        put(FExpense, {"tenant_id": T1, "code": "EXP-DEMO-0002"},
            {"project_id": prj1.id, "legal_entity_id": ent.id,
             "applicant_user_id": users["staff"].id, "amount": 6800,
             "expense_category": "材料费", "expense_type": "MATERIAL",
             "description": "实验耗材采购（演示）", "status": "SUBMITTED",
             "creator_id": C1, "submit_mode": "GWC"}, "funding")
        put(FIncome, {"tenant_id": T1, "code": "INC-DEMO-0001"},
            {"project_id": prj2.id, "legal_entity_id": ent.id, "amount": 500000,
             "receipt_no": "RCP-DEMO-0001", "receipt_date": today,
             "payer_name": "某某新能源科技有限公司", "purpose_text": "横向课题首付款（演示）",
             "claim_status": "UNCLAIMED", "status": "CONFIRMED", "creator_id": C1}, "funding")

        # ---- F. R 成果 -------------------------------------------------------
        out1 = put(ROutput, {"tenant_id": T1, "title": "一种高熵合金催化剂及其制备方法"},
                   {"output_type": "PATENT", "status": "MANUAL_DRAFT", "source": "MANUAL",
                    "creator_id": C1, "authors": [], "project_ids": [prj1.id],
                    "legal_entity_id": ent.id}, "output")
        put(ROutput, {"tenant_id": T1, "title": "High-entropy catalysts for HER（演示）"},
            {"output_type": "PAPER", "status": "MANUAL_DRAFT", "source": "WOS",
             "creator_id": C1, "authors": [], "project_ids": [prj1.id],
             "legal_entity_id": ent.id}, "output")
        put(ROutput, {"tenant_id": T1, "title": "催化数据可视化软件 V1.0（演示）"},
            {"output_type": "SOFTWARE", "status": "MANUAL_DRAFT", "source": "MANUAL",
             "creator_id": C1, "authors": [], "project_ids": [prj2.id],
             "legal_entity_id": ent.id}, "output")
        put(ROutput, {"tenant_id": T1, "title": "高熵催化剂电化学测试数据集（演示）"},
            {"output_type": "DATASET", "status": "MANUAL_DRAFT", "source": "MANUAL",
             "creator_id": C1, "authors": [], "project_ids": [prj1.id],
             "legal_entity_id": ent.id}, "output")
        put(ROutput, {"tenant_id": T1, "title": "高效电解水制氢催化剂（转化演示标的）"},
            {"output_type": "PATENT", "status": "MANUAL_DRAFT", "source": "MANUAL",
             "creator_id": C1, "authors": [], "project_ids": [prj1.id],
             "legal_entity_id": ent.id}, "output")
        ds = ROutput.objects.filter(tenant_id=T1, title__contains="数据集").first()
        if ds is not None:
            put(RDataset, {"tenant_id": T1, "output_id": ds.id},
                {"name": "HER 电化学测试原始数据", "creator_id": C1}, "output")
        put(RJournalSource, {"tenant_id": T1, "name": "Nature Catalysis"},
            {"creator_id": C1}, "output")

        # ---- G. N 专家评审 ----------------------------------------------------
        e1 = put(NExpert, {"tenant_id": T1, "name": "王振华（演示）"},
                 {"user_id": 0, "status": "ACTIVE", "org_name": "浙江大学", "title": "教授",
                  "field_tags": ["催化", "材料"], "expertise_level": "NATIONAL",
                  "source": "MANUAL", "creator_id": C1}, "expert")
        e2 = put(NExpert, {"tenant_id": T1, "name": "刘敏（演示）"},
                 {"user_id": 0, "status": "ACTIVE", "org_name": "上海交通大学", "title": "研究员",
                  "field_tags": ["电化学"], "expertise_level": "PROVINCIAL",
                  "source": "MANUAL", "creator_id": C1}, "expert")
        grp = put(NExpertGroup, {"tenant_id": T1, "name": "材料与催化评审组（演示）"},
                  {"expert_ids": [e1.id, e2.id], "criteria": {}, "status": "ACTIVE",
                   "creator_id": C1}, "expert")
        task = put(NReviewTask, {"tenant_id": T1, "code": "RT-DEMO-001"},
                   {"biz_type": "PROJECT", "title": "高熵催化剂项目评审（演示）",
                    "target_type": "PROJECT", "target_id": prj1.id, "project_id": prj1.id,
                    "review_method": "BLIND", "plan_count": 3, "status": "OPEN",
                    "creator_id": C1}, "expert")
        put(NReviewScore, {"tenant_id": T1, "task_id": task.id, "expert_id": e1.id,
                           "target_type": "PROJECT", "target_id": prj1.id},
            {"dimension_scores": {"创新性": 90, "可行性": 85}, "total_score": 88,
             "comment": "方案创新性突出（演示）", "status": "SUBMITTED",
             "submitted_at": now}, "expert")
        put(NReviewFee, {"tenant_id": T1, "task_id": task.id, "expert_id": e1.id},
            {"amount": 800, "status": "PENDING", "creator_id": C1}, "expert")

        # ---- H. V 学术活动 ----------------------------------------------------
        act1 = put(VActivity, {"tenant_id": T1, "code": "ACT-DEMO-001"},
                   {"activity_type": "CONFERENCE", "title": "2026 先进催化国际会议（演示）",
                    "level": "INTERNATIONAL", "start_at": now + timedelta(days=45),
                    "end_at": now + timedelta(days=47), "venue": "杭州国际会展中心",
                    "status": "APPROVED", "est_attendees": 300, "creator_id": C1,
                    "sign_in_count": 0}, "activity")
        put(VActivity, {"tenant_id": T1, "code": "ACT-DEMO-002"},
            {"activity_type": "LECTURE", "title": "固态电池前沿讲座（演示）",
             "level": "CAMPUS", "start_at": now - timedelta(days=10),
             "end_at": now - timedelta(days=10) + timedelta(hours=2),
             "status": "ARCHIVED", "est_attendees": 80, "sign_in_count": 76,
             "creator_id": C1}, "activity")
        put(VActivityParticipant, {"tenant_id": T1, "activity_id": act1.id,
                                   "user_id": users["staff"].id, "role": "SPEAKER"},
            {"report_title": "高熵催化剂最新进展", "guest_name": "一线研究员"}, "activity")
        put(VActivityParticipant, {"tenant_id": T1, "activity_id": act1.id,
                                   "user_id": users["manager"].id, "role": "ORGANIZER"},
            {"guest_name": "科研管理岗"}, "activity")

        # ---- I. O 档案 --------------------------------------------------------
        doc1 = put(ODocument, {"tenant_id": T1, "code": "DOC-DEMO-001"},
                   {"name": "高熵催化剂项目申报书 v2（演示）", "doc_type": "PROPOSAL",
                    "status": "ACTIVE", "uploader_id": C1, "uploaded_at": now,
                    "source_module": "project", "source_id": prj1.id,
                    "size_bytes": 1048576, "creator_id": C1}, "archive")
        doc2 = put(ODocument, {"tenant_id": T1, "code": "DOC-DEMO-002"},
                   {"name": "中期检查报告（演示）", "doc_type": "REPORT",
                    "status": "ACTIVE", "uploader_id": C1, "uploaded_at": now,
                    "source_module": "project", "source_id": prj1.id,
                    "size_bytes": 524288, "creator_id": C1}, "archive")
        arc = put(OArchive, {"tenant_id": T1, "code": "ARC-DEMO-001"},
                  {"title": "高熵催化剂项目综合档案（演示）", "archive_type": "PROJECT",
                   "source_module": "project", "source_id": prj1.id,
                   "source_code": prj1.code, "retention_years": 10, "status": "FILED",
                   "owner_dept_id": 1, "submitter_id": C1, "submit_at": now,
                   "filed_at": now, "creator_id": C1}, "archive")
        put(OArchiveItem, {"tenant_id": T1, "archive_id": arc.id, "doc_id": doc1.id},
            {"category_code": "PROPOSAL", "category_name": "申报材料", "required": True,
             "sort_no": 1, "status": "ACTIVE"}, "archive")
        put(OArchiveItem, {"tenant_id": T1, "archive_id": arc.id, "doc_id": doc2.id},
            {"category_code": "REPORT", "category_name": "过程材料", "required": False,
             "sort_no": 2, "status": "ACTIVE"}, "archive")
        put(OBorrow, {"tenant_id": T1, "code": "BOR-DEMO-001"},
            {"archive_id": arc.id, "borrower_user_id": users["finance"].id,
             "purpose": "审计抽查（演示）", "borrow_type": "READ",
             "due_at": now + timedelta(days=14), "status": "PENDING", "creator_id": C1}, "archive")

        # ---- J. M 绩效 --------------------------------------------------------
        sch = put(MScheme, {"tenant_id": T1, "code": "SCH-DEMO-001"},
                  {"name": "2026 年度绩效考核方案（演示）", "period_type": "ANNUAL",
                   "effective_period": str(today.year), "status": "ACTIVE",
                   "creator_id": C1}, "performance")
        f1 = put(MSchemeFactor, {"tenant_id": T1, "scheme_id": sch.id, "factor_code": "OUTPUT"},
                 {"data_source": "OUTPUT_DB", "weight": 0.4, "creator_id": C1}, "performance")
        put(MSchemeFactor, {"tenant_id": T1, "scheme_id": sch.id, "factor_code": "PROJECT"},
            {"data_source": "PROJECT_DB", "weight": 0.4, "creator_id": C1}, "performance")
        put(MSchemeFactor, {"tenant_id": T1, "scheme_id": sch.id, "factor_code": "ACTIVITY"},
            {"data_source": "ACTIVITY_DB", "weight": 0.2, "creator_id": C1}, "performance")
        rec = put(MRecord, {"tenant_id": T1, "code": "MREC-DEMO-001"},
                  {"scheme_id": sch.id, "staff_user_id": users["staff"].id,
                   "period": str(today.year), "total_score": 88.5, "status": "CONFIRMED",
                   "legal_entity_id": ent.id, "creator_id": C1,
                   "calc_detail": {"OUTPUT": 90, "PROJECT": 88, "ACTIVITY": 85},
                   "calc_at": now}, "performance")
        put(MPayout, {"tenant_id": T1, "record_id": rec.id,
                      "payee_user_id": users["staff"].id},
            {"amount": 12000, "status": "PENDING", "creator_id": C1}, "performance")

        # ---- K. T 成果转化 ----------------------------------------------------
        out_t = ROutput.objects.filter(tenant_id=T1, title="高效电解水制氢催化剂（转化演示标的）").first()
        disc = put(TDisclosure, {"tenant_id": T1, "code": "DIS-DEMO-001"},
                   {"output_id": out_t.id, "disclosed_by": users["staff"].id,
                    "disclosure_date": today - timedelta(days=90),
                    "tech_summary": "电解水制氢高熵催化剂（演示）", "status": "SUBMITTED",
                    "maturity_level": 5, "is_core_tech": True,
                    "legal_entity_id": ent.id, "creator_id": C1}, "transform")
        val = put(TValuation, {"tenant_id": T1, "code": "VAL-DEMO-001"},
                  {"disclosure": disc, "valuator_type": "EXTERNAL",
                   "valuator_org": "中企华评估（演示）", "method": "收益法",
                   "valuation_amount": 1200000, "status": "DONE",
                   "valuation_date": today - timedelta(days=60), "creator_id": C1}, "transform")
        ep = put(TEnterpartner, {"tenant_id": T1, "company_name": "某某新材料科技有限公司（演示）"},
                 {"credit_code": "91330100DEMO00001X", "industry": "新材料",
                  "contact": {"name": "王工", "phone": "0571-88880000"},
                  "business_check_json": {"abnormal": False}, "check_abnormal": False,
                  "last_checked_at": now, "creator_id": C1}, "transform")
        put(TEnterpartner, {"tenant_id": T1, "company_name": "某某能源装备有限公司（演示）"},
            {"credit_code": "91330100DEMO00002X", "industry": "能源装备",
             "contact": {"name": "李经理"}, "check_abnormal": False,
             "last_checked_at": now, "creator_id": C1}, "transform")
        deal = put(TDeal, {"tenant_id": T1, "code": "DEAL-DEMO-001"},
                   {"disclosure": disc, "output_id": out_t.id, "enterpartner": ep,
                    "deal_type": "转让", "partner_name": ep.company_name,
                    "partner_credit_code": ep.credit_code, "contract_amount": 600000,
                    "payment_method": "一次性", "status": "EXECUTING",
                    "partner_check_abnormal": False, "legal_entity_id": ent.id,
                    "creator_id": C1}, "transform")
        put(TContract, {"tenant_id": T1, "code": "TCON-DEMO-001"},
            {"deal": deal, "contract_no": "HT-DEMO-001", "status": "ACTIVE",
             "version": 1, "creator_id": C1, "signed_at": now}, "transform")
        inc = put(TIncome, {"tenant_id": T1, "code": "TINC-DEMO-001"},
                  {"deal": deal, "received_date": today - timedelta(days=10),
                   "amount": 300000, "payer_name": ep.company_name,
                   "status": "MATCHED", "creator_id": C1}, "transform")
        rule = put(TDistributionRule, {"tenant_id": T1, "rule_name": "转化收益默认分配（演示）"},
                   {"applies_to": "转让", "team_pct": 0.6, "institute_pct": 0.25,
                    "individual_pct": 0.15, "min_team_pct": 0.5,
                    "effective_from": today - timedelta(days=365),
                    "status": "ACTIVE", "creator_id": C1}, "transform")
        put(TDistributionRecord, {"tenant_id": T1, "income": inc, "deal": deal},
            {"rule": rule, "total_amount": 300000, "team_amount": 180000,
             "institute_amount": 75000, "individual_amount": 45000,
             "status": "ISSUED", "issued_at": now, "creator_id": C1}, "transform")
        pub = TPublicity.objects.filter(tenant_id=T1, deal=deal).first()
        if pub is None:
            TPublicity.objects.create(
                tenant_id=T1, creator_id=C1, deal=deal,
                publish_start_at=now - timedelta(days=30),
                publish_end_at=now - timedelta(days=1),
                status="COMPLETED", objection_open=False,
                summary_json={"subject": out_t.title, "deal_amount": 600000})
            cnt["transform"] = cnt.get("transform", 0) + 1
        # 可挂牌演示交易（T-05 挂牌要求 VALUATED/NEGOTIATING，转化看板门控按钮需要这两态）
        ep2 = TEnterpartner.objects.filter(tenant_id=T1, company_name="某某能源装备有限公司（演示）").first()
        put(TDeal, {"tenant_id": T1, "code": "DEAL-DEMO-002"},
            {"disclosure": disc, "output_id": out_t.id, "enterpartner": ep2,
             "deal_type": "许可", "partner_name": ep2.company_name,
             "partner_credit_code": ep2.credit_code, "contract_amount": 350000,
             "payment_method": "分期", "status": "NEGOTIATING",
             "partner_check_abnormal": False, "legal_entity_id": ent.id,
             "creator_id": C1}, "transform")
        put(TDeal, {"tenant_id": T1, "code": "DEAL-DEMO-003"},
            {"disclosure": disc, "output_id": out_t.id, "enterpartner": ep,
             "deal_type": "作价投资", "partner_name": ep.company_name,
             "partner_credit_code": ep.credit_code, "contract_amount": 800000,
             "payment_method": "作价入股", "status": "VALUATED",
             "partner_check_abnormal": False, "legal_entity_id": ent.id,
             "creator_id": C1}, "transform")
        put(TAnnualReport, {"tenant_id": T1, "report_year": today.year - 1},
            {"status": "GENERATED", "creator_id": C1, "legal_entity_id": ent.id,
             "total_deals": 1, "total_contract_amount": 600000,
             "total_income": 300000, "total_distributed": 300000,
             "generated_at": now}, "transform")

        # ---- L. C 诚信伦理 ----------------------------------------------------
        case1 = put(CEthicsCase, {"tenant_id": T1, "code": "ETH-DEMO-001"},
                    {"review_type": "HUMAN", "protocol_title": "基于类器官的药物筛选研究（演示）",
                     "applicant_user_id": users["staff"].id, "status": "APPROVED",
                     "risk_level": "MED", "creator_id": C1, "legal_entity_id": ent.id}, "ethics")
        put(CEthicsCase, {"tenant_id": T1, "code": "ETH-DEMO-002"},
            {"review_type": "ANIMAL", "protocol_title": "动物实验方案（演示）",
             "applicant_user_id": users["staff"].id, "status": "FORMAL_CHECK",
             "risk_level": "LOW", "creator_id": C1, "legal_entity_id": ent.id}, "ethics")
        put(CReviewerAssign, {"tenant_id": T1, "case": case1, "reviewer_user_id": users["manager"].id},
            {"role": "CHIEF", "status": "ACTIVE", "creator_id": C1}, "ethics")
        put(CIntegrityPledge, {"tenant_id": T1, "user_id": users["staff"].id,
                               "pledge_type": "ANNUAL", "content_version": "v1.0"},
            {"read_seconds": 60, "creator_id": C1,
             "ip": "127.0.0.1", "ua": "seed_demo"}, "ethics")
        put(CIntegrityRecord, {"tenant_id": T1, "user_id": users["staff"].id,
                               "event_type_code": "HONOR"},
            {"event_type": "诚信表彰", "description": "年度科研诚信示范（演示）",
             "is_public": True, "status": "ACTIVE", "creator_id": C1,
             "legal_entity_id": ent.id, "security_level": "INTERNAL"}, "ethics")

        # ---- M. G 采购合同 ----------------------------------------------------
        req1 = put(GRequisition, {"tenant_id": T1, "code": "REQ-DEMO-0001"},
                   {"project_id": prj1.id, "applicant_id": users["staff"].id,
                    "category": "EQUIPMENT", "item_name": "X 射线衍射仪（演示）",
                    "est_amount": 800000, "budget_subject_code": "SB-01",
                    "status": "WAY_DECIDED", "purchase_way": "PUBLIC_BID",
                    "frozen_amount": 800000, "legal_entity_id": ent.id,
                    "creator_id": C1}, "procure")
        put(GRequisition, {"tenant_id": T1, "code": "REQ-DEMO-0002"},
            {"project_id": prj1.id, "applicant_id": users["staff"].id,
             "category": "CONSUMABLE", "item_name": "实验耗材一批（演示）",
             "est_amount": 20000, "budget_subject_code": "SB-02",
             "status": "WAY_DECIDED", "purchase_way": "PRICE_COMPARE",
             "legal_entity_id": ent.id, "creator_id": C1}, "procure")
        sup1 = put(GSupplier, {"tenant_id": T1, "name": "国仪量子技术有限公司（演示）"},
                   {"credit_code": "91330100SUPP000001X", "type": "EQUIPMENT",
                    "status": "ACTIVE", "blacklist": False, "grade": "A",
                    "qualification_expire_date": today + timedelta(days=365),
                    "creator_id": C1}, "procure")
        put(GSupplier, {"tenant_id": T1, "name": "某某皮包科技有限公司（演示）"},
            {"credit_code": "91330100SUPP000002X", "type": "SERVICE",
             "status": "BLOCKED", "blacklist": True,
             "remark": "履约严重违约列入黑名单（演示）", "creator_id": C1}, "procure")
        put(GBid, {"tenant_id": T1, "code": "BID-DEMO-0001"},
            {"requisition": req1, "method": "PUBLIC_BID", "status": "AWARDED",
             "creator_id": C1}, "procure")
        put(GContract, {"tenant_id": T1, "code": "CON-DEMO-0001"},
            {"contract_type": "PROCUREMENT", "party_b": sup1.name,
             "amount": 780000, "status": "ACTIVE", "requisition": req1,
             "supplier": sup1, "legal_entity_id": ent.id, "creator_id": C1}, "procure")
        put(GOrder, {"tenant_id": T1, "code": "ORD-DEMO-0001"},
            {"requisition": req1, "supplier": sup1, "status": "RECEIVED",
             "creator_id": C1}, "procure")

        # ---- N. A 资产耗材 ----------------------------------------------------
        a1 = put(AAsset, {"tenant_id": T1, "code": "AST-DEMO-0001"},
                 {"asset_type": "FIXED", "category_code": "INSTRUMENT",
                  "name": "X 射线衍射仪（演示）", "value": 800000, "status": "IN_USE",
                  "source_type": "PURCHASE", "legal_entity_id": ent.id,
                  "dept_id": 1, "custodian_id": users["staff"].id,
                  "project_id": prj1.id, "creator_id": C1}, "asset")
        a2 = put(AAsset, {"tenant_id": T1, "code": "AST-DEMO-0002"},
                 {"asset_type": "FIXED", "category_code": "INSTRUMENT",
                  "name": "涉密光谱分析仪（演示）", "value": 1500000, "status": "IN_USE",
                  "security_level": "SECRET", "source_type": "PURCHASE",
                  "legal_entity_id": ent.id, "dept_id": 1,
                  "custodian_id": users["manager"].id, "creator_id": C1}, "asset")
        a3 = put(AAsset, {"tenant_id": T1, "code": "AST-DEMO-0003"},
                 {"asset_type": "FIXED", "category_code": "FURNITURE",
                  "name": "报废实验台（演示）", "value": 3000, "status": "DISPOSED",
                  "legal_entity_id": ent.id, "dept_id": 1, "creator_id": C1}, "asset")
        # IDLE 演示资产：让「领用」有可见状态变化对象（IDLE → IN_USE）
        a4 = put(AAsset, {"tenant_id": T1, "code": "AST-DEMO-0004"},
                 {"asset_type": "FIXED", "category_code": "INSTRUMENT",
                  "name": "激光粒度分析仪（演示·闲置）", "value": 420000, "status": "IDLE",
                  "source_type": "PURCHASE", "legal_entity_id": ent.id,
                  "dept_id": 2, "location": "材料所 201 室", "creator_id": C1}, "asset")
        # a1 的领用流水：让「操作历史」有 REQUISITION 事件可展示
        put(AStockTxn, {"tenant_id": T1, "code": "STK-DEMO-0002"},
            {"type": "REQUISITION", "ref_asset_id": a1.id, "qty": 1, "balance_after": 1,
             "status": "ISSUED", "txn_time": now, "project_id": prj1.id,
             "operator_id": users["staff"].id, "remark": "演示：X 射线衍射仪领用至项目",
             "creator_id": C1}, "asset")
        con = put(AConsumable, {"tenant_id": T1, "sku": "SKU-DEMO-001"},
                  {"name": "高纯氩气（演示）", "unit": "瓶", "stock_qty": 20,
                   "category": "GAS", "batch_no": "B202610", "status": "ACTIVE",
                   "safe_stock": 5, "expire_date": today + timedelta(days=300),
                   "creator_id": C1}, "asset")
        put(AStockTxn, {"tenant_id": T1, "code": "STK-DEMO-0001"},
            {"type": "IN", "ref_sku": con.sku, "ref_batch_no": con.batch_no,
             "qty": 20, "amount": 4000, "operator_id": users["staff"].id,
             "balance_after": 20, "status": "DONE", "txn_time": now,
             "project_id": prj1.id, "creator_id": C1}, "asset")
        put(ADepreciation, {"tenant_id": T1, "asset": a1, "period": "2026-10"},
            {"depr_amount": 6666.67, "status": "POSTED", "posted": True,
             "creator_id": C1}, "asset")
        put(ADisposal, {"tenant_id": T1, "asset": a3, "method": "SCRAP"},
            {"status": "DONE", "residualValue": 0, "residual_value": 0,
             "appraisal": {"reason": "达到使用年限"}, "creator_id": C1}, "asset")

        # ---- O. X 涉密治理 ----------------------------------------------------
        put(XSecurityPolicy, {"tenant_id": T1, "code": "XPL-DEMO-001"},
            {"matrix_json": {"PROJECT": {"SECRET": ["R-LEADER"]},
                             "ASSET": {"SECRET": ["R-MANAGER"]}},
             "applied_modules": ["project", "asset"], "status": "ACTIVE",
             "version": 1, "effectiveFrom": str(today), "effective_from": str(today),
             "creator_id": C1}, "confsec")
        put(XAccessGrant, {"tenant_id": T1, "subject_user_id": users["staff"].id,
                           "scope_type": "PROJECT"},
            {"granted_level": "INTERNAL", "network_zone": "OFFICE",
             "status": "GRANTED", "scope_ref": prj1.id, "mfa_bound": False,
             "creator_id": C1}, "confsec")
        put(XAccessGrant, {"tenant_id": T1, "subject_user_id": users["manager"].id,
                           "scope_type": "ASSET"},
            {"granted_level": "SECRET", "network_zone": "CONTROL",
             "status": "GRANTED", "scope_ref": a2.id, "mfa_bound": True,
             "creator_id": C1}, "confsec")
        put(XPersonnelSec, {"tenant_id": T1, "user_id": users["manager"].id},
            {"classify_status": "TRAINED", "status": "ACTIVE",
             "secret_eligible": True, "granted_level": "SECRET",
             "review_date": str(today), "creator_id": C1}, "confsec")
        # 安全日志：复用 confsec API 的 _sec_log（保证 sm3- 哈希格式与链语义一致），
        # 动态续既有链尾；以（action, object_type, object_id）自然键幂等。
        from apps.confsec.api import _sec_log
        for action, otype, oid in [("GRANT", "ACCESS_GRANT", 1), ("VIEW", "ASSET", 2)]:
            if XSecLog.objects.filter(tenant_id=T1, action=action,
                                      object_type=otype, object_id=oid).exists():
                continue
            last_log = XSecLog.objects.filter(tenant_id=T1).order_by("-id").first()
            base_ts = last_log.occurred_at if last_log else now
            _sec_log(T1, actor_id=users["manager"].id, actor_role="R-MANAGER",
                     network_zone="CONTROL", action=action, object_type=otype,
                     object_id=oid, result="OK", security_level="SECRET",
                     occurred_at=base_ts + timedelta(minutes=1),
                     source_ip="10.0.0.2")
            cnt["confsec"] = cnt.get("confsec", 0) + 1
        put(XFlowAudit, {"tenant_id": T1, "code": "XFA-DEMO-001"},
            {"direction": "OUT", "object_type": "EXPORT", "object_id": 1,
             "from_domain": "asset", "to_domain": "finance",
             "applicant_id": users["finance"].id, "reason": "资产折旧凭证同步（演示）",
             "status": "APPROVED", "payload_digest": "0" * 64,
             "release_scope": "MINIMAL", "legal_entity_id": ent.id,
             "security_level": "SECRET", "creator_id": C1}, "confsec")

        # ---- P. 通知 / 待办 / 导入日志 -----------------------------------------
        put(SysNotification, {"tenant_id": T1, "user_id": users["staff"].id,
                              "title": "您的报销单已通过初审（演示）"},
            {"typ": "APPROVAL", "content": "EXP-DEMO-0002 已通过初审，等待财务复核。",
             "biz_ref": "EXP-DEMO-0002"}, "notify")
        put(SysNotification, {"tenant_id": T1, "user_id": users["manager"].id,
                              "title": "采购申请待定标（演示）"},
            {"typ": "TODO", "content": "REQ-DEMO-0001 已完成公开招标，请及时定标。",
             "biz_ref": "REQ-DEMO-0001"}, "notify")
        put(SysTask, {"tenant_id": T1, "assignee_id": users["manager"].id,
                      "typ": "APPROVAL", "title": "待审批：实验耗材采购报销（演示）"},
            {"role_code": "R-MANAGER", "biz_ref": "EXP-DEMO-0002", "status": "PENDING"}, "notify")
        put(SysTask, {"tenant_id": T1, "assignee_id": users["finance"].id,
                      "typ": "PAYMENT", "title": "待付款：X 射线衍射仪尾款（演示）"},
            {"role_code": "R-FINANCE", "biz_ref": "EXP-DEMO-0001", "status": "PENDING"}, "notify")
        put(SysImportLog, {"tenant_id": T1, "user_id": C1, "biz_type": "OUTPUT",
                           "filename": "成果批量导入演示.xlsx"},
            {"total_rows": 100, "ok_rows": 98, "fail_rows": 2,
             "snapshot": {"failed": ["第 37 行：DOI 重复", "第 88 行：字段缺失"]},
             "undone": False}, "notify")

        return cnt
