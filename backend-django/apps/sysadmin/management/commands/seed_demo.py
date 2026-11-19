"""演示数据播种（对齐 Go seeddemo 语义：幂等，DEMO- 前缀/种子行存在即跳过）。

Phase 0 范围：8 基础角色、4 演示用户、字典种子、页面可见性矩阵种子。
Phase 4 扩展：16 业务域全域演示数据（notify/p/project/funding/output/expertreview/
activity/archive/performance/transform/ethics/staff/procure/asset/confsec + 法人/组织）。
用法：python manage.py seed_demo
"""
from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, timedelta

import bcrypt
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone as dj_tz

from apps.sysadmin.models import (
    PageGrant, SysDict, SysDictItem, SysLegalEntity, SysOrg, SysPartnerOrg, SysRole,
    SysUser, SysUserRole,
)

ROLES = [
    ("R-STAFF", "科研人员"),
    ("R-MANAGER", "科研管理岗"),
    ("R-LEADER", "单位领导"),
    ("R-FINANCE", "财务"),
    ("R-AUDITOR", "审计"),
    ("R-EXPERT", "评审专家"),
    ("R-ETHICS", "伦理委员会"),
    ("R-ADMIN", "系统管理员"),
    ("R-PARTNER", "外部机构用户"),  # M2-a：机构门户
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
    ("loan", "R-MANAGER"), ("loan", "R-FINANCE"),  # M1-a A2 借款管理（镜像 auth.ts PAGE_GRANTS loan 行）
    ("claim", "R-STAFF"), ("claim", "R-MANAGER"), ("claim", "R-LEADER"),
    ("output", "R-STAFF"), ("output", "R-MANAGER"), ("output", "R-LEADER"),
    ("transfer", "R-MANAGER"), ("transfer", "R-LEADER"), ("transfer", "R-ADMIN"),
    ("procurement", "R-MANAGER"), ("procurement", "R-FINANCE"), ("procurement", "R-ADMIN"),
    ("asset", "R-MANAGER"), ("asset", "R-FINANCE"), ("asset", "R-ADMIN"),
    ("portrait", "R-LEADER"), ("portrait", "R-MANAGER"), ("portrait", "R-ADMIN"),
    ("activity", "R-STAFF"), ("activity", "R-MANAGER"), ("activity", "R-LEADER"), ("activity", "R-AUDITOR"),
    ("performance", "R-MANAGER"), ("performance", "R-LEADER"),
    ("performance", "R-FINANCE"), ("performance", "R-AUDITOR"),
    ("expert-review", "R-EXPERT"), ("expert-review", "R-MANAGER"), ("expert-review", "R-LEADER"),
    ("expert-review", "R-AUDITOR"),
    ("archive", "R-ADMIN"), ("archive", "R-MANAGER"), ("archive", "R-AUDITOR"), ("archive", "R-STAFF"),
    ("admin-users", "R-ADMIN"), ("admin-roles", "R-ADMIN"), ("admin-roles", "R-AUDITOR"),
    ("admin-dicts", "R-ADMIN"),
    ("funding-config", "R-MANAGER"), ("funding-config", "R-FINANCE"),
    # M1-b：成本池核算 + 项目决算（镜像 auth.ts PAGE_GRANTS，policy 三角色同口径）
    ("funding-cost-pool", "R-MANAGER"), ("funding-cost-pool", "R-FINANCE"), ("funding-cost-pool", "R-LEADER"),
    ("funding-settle", "R-MANAGER"), ("funding-settle", "R-FINANCE"), ("funding-settle", "R-LEADER"),
    # M1-c：拨款管理 + 到账认领与回单识别（import-bank-flow / incomes claim
    # 由 R-MANAGER/R-FINANCE 既有 /incomes/* 通配覆盖，R-LEADER 无）
    ("funding-disburse", "R-MANAGER"), ("funding-disburse", "R-FINANCE"), ("funding-disburse", "R-LEADER"),
    ("funding-income", "R-MANAGER"), ("funding-income", "R-FINANCE"), ("funding-income", "R-LEADER"),
    # M2-a：外部机构门户（R-PARTNER）与资质审核台（R-MANAGER/R-ADMIN；镜像 auth.ts PAGE_GRANTS）
    ("portal", "R-PARTNER"),
    ("admin-partner-orgs", "R-MANAGER"), ("admin-partner-orgs", "R-ADMIN"),
    # M2-b：开放课题全流程（机构申报/指南建议/任务书/汇报/结题；镜像 auth.ts PAGE_GRANTS）
    ("portal-applications", "R-PARTNER"),
    ("portal-guide-suggest", "R-PARTNER"),
    ("portal-task-book", "R-PARTNER"),
    ("portal-project-report", "R-PARTNER"),
    ("admin-guide-suggestions", "R-MANAGER"),
    # M2-c：外部专家与供应商协同（C3/C4；镜像 auth.ts PAGE_GRANTS）
    ("admin-expert-applications", "R-MANAGER"),
    ("portal-expert-apply", "R-PARTNER"), ("portal-expert-apply", "R-EXPERT"),
    ("portal-expert", "R-EXPERT"),
    ("portal-supplier", "R-PARTNER"),
]


class Command(BaseCommand):
    help = "幂等播种演示数据（角色/用户/字典/页面矩阵）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="无视 ALLOW_DEMO_SEED 开关（生产仍要求 ARK_SEED_PASSWORD）",
        )

    def _guard(self, options) -> str | None:
        """E-8 门禁：演示数据不得在未审批的部署里自动落地。

        返回「覆盖所有演示账号口令」的替代口令（None 表示用各自的默认口令）。
        两把锁：①是否允许播种；②非开发形态必须由环境提供口令。
        """
        demo_mode = bool(getattr(settings, "ALLOW_DEMO_SEED", False))
        opt_in = bool(options.get("force")) or os.environ.get("ARK_SEED_DEMO") == "1"
        if not (demo_mode or opt_in):
            raise CommandError(
                "演示数据默认不播种。本机开发请用 config.settings.dev；"
                "部署如需演示数据，请显式设置 ARK_SEED_DEMO=1（或加 --force）。"
            )
        env_pwd = os.environ.get("ARK_SEED_PASSWORD") or None
        if not demo_mode and not env_pwd:
            raise CommandError(
                "非开发形态播种演示数据必须设置 ARK_SEED_PASSWORD，"
                "不接受仓库内置的默认口令（admin/Admin@123456 等公开凭据）。"
            )
        if env_pwd is not None:
            from core.startup import DEFAULT_SEED_PASSWORDS

            if env_pwd in DEFAULT_SEED_PASSWORDS:
                raise CommandError(
                    f"ARK_SEED_PASSWORD 不得是仓库内置的默认口令（含 Demo@123456）。"
                )
            if len(env_pwd) < 10:
                raise CommandError("ARK_SEED_PASSWORD 至少 10 位。")
        return env_pwd

    def _rotate_password(self, user, override_pwd: str | None) -> bool:
        """显式给了 ARK_SEED_PASSWORD 时，对**已存在**账号也轮换口令。

        `get_or_create` 只在首次创建时写 password_hash，因此升级/重建环境时旧口令
        （例如仓库默认的 admin/Admin@123456）会长期有效。这里把它改成「设了口令就
        轮换」，使 ARK_SEED_PASSWORD 成为唯一有效凭据。
        """
        if user is None or not override_pwd:
            return False
        current = (user.password_hash or "").encode()
        if current:
            try:
                if bcrypt.checkpw(override_pwd.encode(), current):
                    return False
            except ValueError:  # 库里是非法 hash → 直接覆盖
                pass
        user.password_hash = bcrypt.hashpw(override_pwd.encode(), bcrypt.gensalt()).decode()
        user.save(update_fields=["password_hash"])
        return True

    def handle(self, *args, **options):
        override_pwd = self._guard(options)
        n_roles = n_users = n_dicts = n_items = n_grants = 0

        role_objs = {}
        for code, name in ROLES:
            r, created = SysRole.objects.get_or_create(
                code=code, tenant_id=1, defaults={"name": name, "is_builtin": True}
            )
            if not created and r.name != name:
                r.name = name
                r.save(update_fields=["name"])
            role_objs[code] = r
            n_roles += int(created)

        user_objs = {}
        for username, real_name, email, staff_no, sec, pwd in USERS:
            effective_pwd = override_pwd or pwd
            u, created = SysUser.objects.get_or_create(
                username=username, tenant_id=1,
                defaults={
                    "real_name": real_name, "email": email, "staff_no": staff_no,
                    "security_level": sec, "status": "ACTIVE",
                    "password_hash": bcrypt.hashpw(effective_pwd.encode(), bcrypt.gensalt()).decode(),
                    "creator_id": 1,
                },
            )
            self._rotate_password(u, override_pwd)
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

        n = self._seed_domains(user_objs, override_pwd)
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

    def _seed_domains(self, users: dict, override_pwd: str | None = None) -> dict:
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
        from apps.funding.models import (
            FBudget, FBudgetLine, FExpense, FIncome, FInvoice, FLoan, FSubject,
            FTravelStandard, FDisbursement,
        )
        from apps.notify.models import SysImportLog, SysNotification, SysTask
        from apps.output.models import RDataset, RJournalSource, ROutput
        from apps.p.models import PApplication, PGuideline, PGuideSuggestion, PTaskBook
        from apps.performance.models import MPayout, MRecord, MScheme, MSchemeFactor
        from apps.procure.models import (  # noqa: F401
            GBid, GContract, GContractPayment, GOrder, GRequisition, GSupplier,
        )
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
        prj3 = put(EProject, {"tenant_id": T1, "code": "PRJ-DEMO-003"},
                   {"application_id": app.id, "title": "阴极界面相容性研究（院自立演示）",
                    "project_type": "ZIGE", "pi_user_id": users["manager"].id,
                    "member_ids": [users["manager"].id], "department_id": 1,
                    "legal_entity_id": ent.id,
                    "start_date": today - timedelta(days=10),
                    "end_date": today + timedelta(days=700), "total_budget": 800000,
                    "status": "ACTIVE", "creator_id": C1}, "project")
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
                   "total_approved": 2000000, "version": 1, "status": "EXECUTING",
                   "creator_id": C1, "approved_at": now, "approved_by": C1}, "funding")
        budl = put(FBudgetLine, {"tenant_id": T1, "code": "BUDL-DEMO-001", "budget_id": bud.id,
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

        # M1-a 演示数据：差旅标准（A3）/ 发票（A1）/ 借款（A2，PAID 部分冲销）
        put(FTravelStandard,
            {"tenant_id": T1, "staff_category": "普通员工", "city_tier": "一类城市"},
            {"name": "一类城市差旅标准（普通员工）", "accommodation_cap": 450,
             "meals_cap": 130, "transport_cap": 500,
             "effective_from": today - timedelta(days=30), "status": "ACTIVE",
             "creator_id": C1, "remark": "演示差旅标准（M1-a A3）"}, "funding")
        put(FTravelStandard,
            {"tenant_id": T1, "staff_category": "中层管理人员", "city_tier": "二类城市"},
            {"name": "二类城市差旅标准（中层管理人员）", "accommodation_cap": 380,
             "meals_cap": 100, "transport_cap": 400,
             "effective_from": today - timedelta(days=30), "status": "ACTIVE",
             "creator_id": C1, "remark": "演示差旅标准（M1-a A3）"}, "funding")
        put(FInvoice, {"tenant_id": T1, "number": "25301000000123456789"},
            {"status": "DRAFT", "invoice_type": "ELECTRONIC",
             "seller_name": "某某仪器设备有限公司", "seller_tax_id": "91330100MA27X0DEMO",
             "buyer_name": "演示研究院", "buyer_tax_id": "12100000MB1C00DEMO",
             "amount_excl_tax": 5000, "tax_amount": 650, "total_amount": 5650,
             "issue_date": today, "check_result": "PASS", "creator_id": C1,
             "remark": "演示发票（M1-a A1，DRAFT）"}, "funding")
        loan, loan_created = FLoan.objects.get_or_create(
            tenant_id=T1, code="LOAN-DEMO-0001",
            defaults=self._filt(FLoan, {
                "status": "PAID", "project_id": prj1.id,
                "budget_line_id": budl.id, "legal_entity_id": ent.id,
                "applicant_user_id": users["staff"].id, "amount": 20000,
                "reason": "外地测试出差借款（演示，PAID 部分冲销）",
                "write_off_amount": 8000, "refunded_amount": 0,
                "submitted_at": now - timedelta(days=3),
                "frozen_at": now - timedelta(days=3),
                "paid_at": now - timedelta(days=2),
                "creator_id": C1, "remark": "演示借款（M1-a A2）"}))
        cnt["funding"] += int(loan_created)
        if loan_created:
            # 台账自洽：借款 20000 付款后结转预算线 amount_used（320000 → 340000）
            FBudgetLine.objects.filter(id=budl.id).update(amount_used=340000)

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
                  "name": "X 射线衍射仪（演示）", "serial_no": "SN-DEMO-0001",
                  "value": 800000, "status": "IN_USE",
                  "source_type": "PURCHASE", "legal_entity_id": ent.id,
                  "dept_id": 1, "custodian_id": users["staff"].id,
                  "project_id": prj1.id, "creator_id": C1}, "asset")
        a2 = put(AAsset, {"tenant_id": T1, "code": "AST-DEMO-0002"},
                 {"asset_type": "FIXED", "category_code": "INSTRUMENT",
                  "name": "涉密光谱分析仪（演示）", "serial_no": "SN-DEMO-0002",
                  "value": 1500000, "status": "IN_USE",
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
                  "name": "激光粒度分析仪（演示·闲置）", "serial_no": "SN-DEMO-0004",
                  "value": 420000, "status": "IDLE",
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

        # ---- Q. M1-b 演示数据（凭证同步 A5 / 平行记账 4.5 / 成本池 A4 / 决算 A7） ----
        # 报销凭证同步：关联已 PAID 报销 EXP-DEMO-0001（M1-a 种子），sync_status=SUCCESS
        #   + voucher_no 回填；报销状态不翻转（保持 PAID，避免污染 M1-a 台账语义）。
        # 平行记账：同一报销落 EXPENSE 双分录（财务/预算两账各借贷平衡，POSTED/BALANCED）。
        # 成本池：PRJ-DEMO-001 当期 CALCULATED，direct=120000 + 间接 500 → full=120500。
        # 决算：PRJ-DEMO-001 APPROVED 结转，快照与 handlers 口径自洽（income=0，
        #   expense=120000，remaining=-120000）。
        from apps.funding.api import code_of
        from apps.funding.models import FAccountingEntry, FCostPool, FSettlement, FVoucherSync

        period = today.strftime("%Y%m")
        exp_sync = FExpense.objects.filter(
            tenant_id=T1, deleted=0, status="PAID").order_by("id").first()
        if exp_sync is None:  # 保守兜底：无 PAID 报销时种一条最小演示行
            exp_sync = put(FExpense, {"tenant_id": T1, "code": "EXP-DEMO-M1B-01"},
                           {"project_id": prj1.id, "legal_entity_id": ent.id,
                            "applicant_user_id": users["staff"].id, "amount": 120000,
                            "expense_category": "设备费", "expense_type": "EQUIPMENT",
                            "description": "M1-b 凭证同步演示报销", "status": "PAID",
                            "creator_id": C1, "paid_at": now}, "funding")
        vs = put(FVoucherSync, {"tenant_id": T1, "expense_id": exp_sync.id, "deleted": 0},
                 {"finance_system": "YONYOU", "voucher_no": "PZ-DEMO-2026-0001",
                  "sync_status": "SUCCESS", "status": "SUCCESS", "retry_count": 0,
                  "sync_at": now,
                  "payload_json": {"expenseId": exp_sync.id, "expenseCode": exp_sync.code,
                                   "financeSystem": "YONYOU",
                                   "amount": f"{exp_sync.amount:.2f}"},
                  "callback_json": {"result": "SUCCESS",
                                    "voucherNo": "PZ-DEMO-2026-0001",
                                    "detail": "演示回调回执（M1-b）"},
                  "creator_id": C1, "remark": "演示凭证同步（M1-b A5，SUCCESS）"},
                 "funding")
        if vs.code is None:
            vs.code = code_of("VCH", vs.id)
            vs.save(update_fields=["code"])
        ae = put(FAccountingEntry,
            {"tenant_id": T1, "source_txn_type": "EXPENSE",
             "source_txn_id": exp_sync.id, "period": period, "deleted": 0},
            {"project_id": exp_sync.project_id, "legal_entity_id": exp_sync.legal_entity_id,
             "status": "POSTED", "posted_finance": True, "posted_budget": True,
             "reconcile_status": "BALANCED", "voucher_sync_id": vs.id,
             "fin_entry_json": {"lines": [
                 {"subject": "5001", "direction": "debit", "amount": str(exp_sync.amount)},
                 {"subject": "1002", "direction": "credit", "amount": str(exp_sync.amount)},
             ]},
             "bud_entry_json": {"lines": [
                 {"subject": "7201", "direction": "debit", "amount": str(exp_sync.amount)},
                 {"subject": "8001", "direction": "credit", "amount": str(exp_sync.amount)},
             ]},
             "creator_id": C1, "remark": "演示平行记账（M1-b 4.5，EXPENSE 双分录）"},
            "funding")
        if ae.code is None:
            ae.code = code_of("ACC", ae.id)
            ae.save(update_fields=["code"])
        direct = exp_sync.amount
        indirect = [{"type": "管理费", "basis": "seed", "amount": "500.00"}]
        cp = put(FCostPool, {"tenant_id": T1, "project_id": prj1.id,
                             "period": period, "deleted": 0},
                 {"legal_entity_id": ent.id, "direct_cost": direct,
                  "indirect_alloc_json": indirect, "full_cost": direct + 500,
                  "status": "CALCULATED", "basis_rule_id": None,
                  "policy_pack_id": None, "creator_id": C1,
                  "remark": "演示成本池（M1-b A4，CALCULATED）"}, "funding")
        if cp.code is None:
            cp.code = code_of("CPL", cp.id)
            cp.save(update_fields=["code"])
        st = put(FSettlement, {"tenant_id": T1, "project_id": prj1.id, "deleted": 0},
                 {"legal_entity_id": ent.id, "closing_date": today,
                  "income_total": 0, "expense_total": direct, "remaining": -direct,
                  "treatment": "结转", "status": "APPROVED", "approved_by": C1,
                  "approved_at": now, "creator_id": C1,
                  "score_detail": {"disbursementTotal": "0.00"},
                  "remark": "演示决算单（M1-b A7，APPROVED 结转）"}, "funding")
        if st.code is None:
            st.code = code_of("SET", st.id)
            st.save(update_fields=["code"])

        # ---- R. M1-c 演示数据（拨款管理 7.1 / 到账认领与回单识别 7.2 / 核算开户 7.3） ----
        # 拨款单：外协分包合同 30 万拨 8 万，SUBMITTED→(approve,pay)→PAID，
        #   approval_chain 完整两步 + DISBURSEMENT 平行记账分录（与 pay handler 同模板：
        #   fin 7701 借/1002 贷，bud 7501 借/8001 贷），快照三列与 check 口径自洽
        #   （contract=300000 / before=0 / remain=300000-0-80000=220000）。
        # 回单识别：OCR 到账流水（UNCLAIMED，待认领），remark 为 ocr_receipt 审计形态
        #   "ocr:{fields,warnings,reasons,fileUrl}"，match_confidence=0.9000。
        # 核算开户（B1）：prj2 一键开户演示——科目行（外协费 applies_to=["F"]）+
        #   预算制 DRAFT 预算 + 零额度科目行（amount_planned=0），不经 handler 直写。
        import json as _json

        from apps.funding.models import FAccountingEntry

        con_m1c = put(GContract, {"tenant_id": T1, "code": "CON-DEMO-M1C-01"},
                      {"contract_type": "外协分包", "party_a": ent.name,
                       "party_b": "华科精密仪器有限公司（演示）", "amount": 300000,
                       "status": "ACTIVE", "project_id": prj1.id, "supplier": sup1,
                       "legal_entity_id": ent.id, "outsource": True,
                       "creator_id": C1}, "procure")
        disb = put(FDisbursement,
            {"tenant_id": T1, "contract_id": con_m1c.id, "phase": "进度", "deleted": 0},
            {"outsource_unit_id": sup1.id, "project_id": prj1.id,
             "legal_entity_id": ent.id, "amount": 80000, "status": "PAID",
             "approval_chain": [
                 {"userId": C1, "action": "approve", "at": now.isoformat()},
                 {"userId": C1, "action": "pay", "at": now.isoformat()},
             ],
             "contract_amount": 300000, "disbursed_before": 0,
             "remain_contract_amount": 220000, "voucher_status": "PENDING",
             "creator_id": C1, "remark": "演示拨款单（M1-c 7.1，PAID 已拨付）"},
            "funding")
        if disb.code is None:
            disb.code = code_of("DISB", disb.id)
            disb.save(update_fields=["code"])
        ae_disb = put(FAccountingEntry,
            {"tenant_id": T1, "source_txn_type": "DISBURSEMENT",
             "source_txn_id": disb.id, "period": period, "deleted": 0},
            {"project_id": disb.project_id, "legal_entity_id": disb.legal_entity_id,
             "status": "POSTED", "posted_finance": True, "posted_budget": True,
             "reconcile_status": "BALANCED",
             "fin_entry_json": {"lines": [
                 {"subject": "7701", "direction": "debit", "amount": str(disb.amount)},
                 {"subject": "1002", "direction": "credit", "amount": str(disb.amount)},
             ]},
             "bud_entry_json": {"lines": [
                 {"subject": "7501", "direction": "debit", "amount": str(disb.amount)},
                 {"subject": "8001", "direction": "credit", "amount": str(disb.amount)},
             ]},
             "creator_id": C1, "remark": "演示平行记账（M1-c 7.1，DISBURSEMENT 双分录）"},
            "funding")
        if ae_disb.code is None:
            ae_disb.code = code_of("ACC", ae_disb.id)
            ae_disb.save(update_fields=["code"])
        inc_ocr = put(FIncome, {"tenant_id": T1, "bank_flow_no": "BMFLW-DEMO-M1C-0001"},
                      {"amount": 50000, "payer_name": "华科精密仪器有限公司（演示）",
                       "payer_bank": "中国工商银行合肥高新区支行",
                       "purpose_text": "横向课题协作款（回单识别演示）",
                       "receipt_date": today, "receipt_no": "",
                       "claim_status": "UNCLAIMED", "match_confidence": "0.9000",
                       "remark": "ocr:" + _json.dumps(
                           {"fields": {"amount": "50000.00", "payerName": "华科精密仪器有限公司（演示）",
                                       "bankFlowNo": "BMFLW-DEMO-M1C-0001",
                                       "receiptDate": f"{today:%Y-%m-%d}"},
                            "warnings": [], "reasons": ["关键字段完整"],
                            "fileUrl": "/uploads/demo/receipt-m1c.jpg"},
                           ensure_ascii=False),
                       "legal_entity_id": 1, "creator_id": C1}, "funding")
        if inc_ocr.code is None:
            inc_ocr.code = code_of("INC", inc_ocr.id)
            inc_ocr.save(update_fields=["code"])
        sub_wx = put(FSubject, {"tenant_id": T1, "name": "外协费"},
                     {"category": "DIRECT", "applies_to": ["F"], "sort_no": 4,
                      "status": "ACTIVE", "creator_id": C1,
                      "remark": "M1-c 核算开户演示科目（B1）"}, "funding")
        if sub_wx.code is None:
            sub_wx.code = f"SJ-{today:%Y}-{sub_wx.id:06d}"
            sub_wx.save(update_fields=["code"])
        bud_m1c = put(FBudget, {"tenant_id": T1, "code": "BUD-DEMO-M1C-01"},
                      {"project_id": prj2.id, "legal_entity_id": ent.id,
                       "mode": "预算制", "status": "DRAFT", "total_approved": 500000,
                       "creator_id": C1, "remark": "演示核算开户预算（M1-c B1，DRAFT）"},
                      "funding")
        if bud_m1c.code is None:
            bud_m1c.code = code_of("BUD", bud_m1c.id)
            bud_m1c.save(update_fields=["code"])
        put(FBudgetLine, {"tenant_id": T1, "code": "BUDL-DEMO-M1C-01"},
            {"budget_id": bud_m1c.id, "subject_id": sub_wx.id,
             "amount_planned": 0, "status": "ACTIVE",
             "creator_id": C1, "remark": "演示开户科目行（M1-c B1，零额度待分配）"},
            "funding")

        # ---- R. M1-d 演示数据（统一评估 B3 / 变更版本 B4 / 指南发布 B5） ----
        from apps.project.models import (
            EChangeRequest, EChangeVersion, EEvalTemplate, EMidCheck, EReport,
        )

        tpl_mid = put(EEvalTemplate, {"tenant_id": T1, "code": "TPLM-DEMO-01"},
            {"name": "中期检查评估表（演示）", "scene": "MID_CHECK", "status": "ACTIVE",
             "sections": [
                 {"key": "progress", "label": "研究进度", "weight": 0.4,
                  "items": ["任务书指标达成情况", "里程碑完成率"]},
                 {"key": "finance", "label": "经费执行", "weight": 0.3,
                  "items": ["预算执行率", "外协合同履约"]},
                 {"key": "output", "label": "阶段成果", "weight": 0.3,
                  "items": ["论文/专利", "人才培养"]},
             ],
             "score_rubric": {"max": 100, "levels": [
                 {"min": 85, "label": "优秀"}, {"min": 70, "label": "良好"},
                 {"min": 60, "label": "合格"}, {"min": 0, "label": "不合格"}]},
             "creator_id": C1, "remark": "演示评估模板（M1-d B3，中期检查）"}, "project")
        put(EEvalTemplate, {"tenant_id": T1, "code": "TPLF-DEMO-01"},
            {"name": "结题验收评估表（演示）", "scene": "FINAL_ACCEPT", "status": "ACTIVE",
             "sections": [
                 {"key": "target", "label": "考核指标完成", "weight": 0.5,
                  "items": ["任务书全部指标", "技术就绪度"]},
                 {"key": "finance", "label": "经费决算", "weight": 0.3,
                  "items": ["决算与审计", "结转结余"]},
                 {"key": "archive", "label": "归档完整性", "weight": 0.2,
                  "items": ["档案清单齐备率"]},
             ],
             "score_rubric": {"max": 100, "levels": [
                 {"min": 85, "label": "通过"}, {"min": 60, "label": "整改后通过"},
                 {"min": 0, "label": "不通过"}]},
             "creator_id": C1, "remark": "演示评估模板（M1-d B3，结题验收）"}, "project")

        # B4：一般变更（提交即生效）+ 版本快照基线；重大变更留 SUBMITTED 供审批演示
        chg_gen = put(EChangeRequest,
            {"tenant_id": T1, "code": "CHG-DEMO-0001"},
            {"project": prj1, "change_type": "TITLE", "severity": "GENERAL",
             "old_value": {"title": "面向新能源的高熵催化剂研发"},
             "new_value": {"title": "面向新能源的高熵催化剂研发（二期）"},
             "reason": "研究范围扩大，题目同步调整（一般变更内部备案）",
             "status": "EFFECTIVE", "approval_status": "APPROVED",
             "approved_at": now, "creator_id": C1,
             "remark": "演示一般变更（M1-d B4，提交即生效）"}, "project")
        ver_gen = put(EChangeVersion,
            {"tenant_id": T1, "change_id": chg_gen.id, "version_no": 1},
            {"snapshot": {"title": "面向新能源的高熵催化剂研发",
                          "endDate": str(prj1.end_date),
                          "memberIds": prj1.member_ids,
                          "totalBudget": str(prj1.total_budget)},
             "creator_id": C1, "remark": "演示变更版本快照（M1-d B4 v1）"}, "project")
        if chg_gen.snapshot_ref is None:
            chg_gen.snapshot_ref = f"E_CHANGE_VERSION#{ver_gen.id}"
            chg_gen.save(update_fields=["snapshot_ref"])
        put(EChangeRequest,
            {"tenant_id": T1, "code": "CHG-DEMO-0002"},
            {"project": prj1, "change_type": "DELAY", "severity": "MAJOR",
             "old_value": {"endDate": str(prj1.end_date)},
             "new_value": {"endDate": str(prj1.end_date + timedelta(days=180))},
             "reason": "关键设备到货延期，申请顺延 6 个月（重大变更，待审批）",
             "status": "SUBMITTED", "approval_status": "PENDING",
             "creator_id": C1,
             "remark": "演示重大变更（M1-d B4，走逐级审批）"}, "project")

        # B3：中检结论 + 批文（一评估一批文）
        mid = put(EMidCheck,
            {"tenant_id": T1, "project": prj1, "check_round": 1},
            {"check_date": today - timedelta(days=20), "template_id": tpl_mid.id,
             "status": "CONCLUDED", "conclusion": "PASS",
             "score_detail": {"score": 88, "level": "优秀",
                              "items": [{"key": "progress", "score": 90},
                                        {"key": "finance", "score": 86},
                                        {"key": "output", "score": 88}]},
             "creator_id": C1, "remark": "演示中期检查（M1-d B3，已出结论）"}, "project")
        rpt = put(EReport,
            {"tenant_id": T1, "project": prj1, "doc_type": "MID_CHECK",
             "mid_check_id": mid.id},
            {"title": f"{prj1.title} 中期检查批文", "status": "ISSUED",
             "conclusion": "PASS",
             "content_rich": "经专家组评审，本项目中期检查结论为通过，请按专家意见推进后续研究。",
             "score_detail": mid.score_detail, "issued_at": now,
             "creator_id": C1, "remark": "演示评估批文（M1-d B3，RPT 单号）"}, "project")
        if rpt.code is None:
            rpt.code = code_of("RPT", rpt.id)
            rpt.save(update_fields=["code"])
        if mid.approval_doc_id is None:
            mid.approval_doc_id = rpt.id
            mid.save(update_fields=["approval_doc_id"])

        # B5：待发布指南（演示 publish 动作 → 通知科研人员）
        put(PGuideline, {"tenant_id": T1, "code": "GL-DEMO-2026-02"},
            {"title": "2027 年度院自主部署项目指南征集（演示）", "project_type": "ZIGE",
             "status": "DRAFT", "creator_id": C1,
             "apply_start_at": now + timedelta(days=30),
             "apply_end_at": now + timedelta(days=90),
             "funding_source": "院自主部署", "total_envelope": 3000000,
             "content_rich": "## 征集方向\n1. 新能源材料\n2. 智能装备",}, "p")

        # ---- M2-a：外部机构（C1）-----------------------------------------
        ptn_a = put(SysPartnerOrg, {"tenant_id": T1, "code": "PTN-2026-000001"},
                    {"name": "合作示例大学", "short_name": "示例大",
                     "credit_code": "91310000MA1K3XY12A", "org_type": "UNIVERSITY",
                     "contact_name": "张联系", "contact_phone": "13800000001",
                     "contact_email": "partner@example.edu.cn",
                     "address": "上海市杨浦区示例路 1 号", "status": "APPROVED",
                     "audit_user_id": 2, "audited_at": now,
                     "qualification_json": [{"name": "事业单位法人证书", "no": "12310000425000000X"}],
                     "creator_id": C1, "remark": "M2-a 演示：已通过审核的外部机构"}, "partner")
        ptn_b = put(SysPartnerOrg, {"tenant_id": T1, "code": "PTN-2026-000002"},
                    {"name": "待审核协作单位", "credit_code": "91110000MA2C4AB34B",
                     "org_type": "COLLAB", "contact_name": "李经办",
                     "contact_phone": "13800000002",
                     "contact_email": "pending@example.com", "status": "PENDING",
                     "creator_id": C1, "remark": "M2-a 演示：待审核（审核台有数据可操作）"}, "partner")
        partner_user, created = SysUser.objects.get_or_create(
            username="partner", tenant_id=T1,
            defaults={
                "real_name": "合作单位联系人", "email": "partner@example.edu.cn",
                "security_level": "PUBLIC", "status": "ACTIVE",  # 外部机构账号：最低密级
                "password_hash": bcrypt.hashpw(b"Partner@123456", bcrypt.gensalt()).decode(),
                "org_id": ptn_a.id, "user_source": "EXTERNAL", "creator_id": C1,
            },
        )
        cnt["partner"] = cnt.get("partner", 0) + int(created)
        # 设了口令则轮换（旧默认 Partner@123456 不得长期有效）
        self._rotate_password(partner_user, override_pwd)
        # 已存在则补归属列（幂等修数，不改状态）
        if not created and (partner_user.org_id != ptn_a.id or partner_user.user_source != "EXTERNAL"):
            partner_user.org_id = ptn_a.id
            partner_user.user_source = "EXTERNAL"
            partner_user.save(update_fields=["org_id", "user_source"])
        r_partner = SysRole.objects.filter(tenant_id=T1, code="R-PARTNER").first()
        if r_partner is not None:
            _, c = SysUserRole.objects.get_or_create(
                user=partner_user, role=r_partner, tenant_id=T1
            )
            cnt["partner"] = cnt.get("partner", 0) + int(c)
        # 门户公告（演示：机构登录即见审核通过与指南推送）
        put(SysNotification, {"tenant_id": T1, "user_id": partner_user.id,
                              "typ": "ANNOUNCE", "title": "机构资质审核通过"},
            {"content": "贵单位资质已通过审核，账号已激活；可在门户查看本单位相关数据与已发布指南。",
             "biz_ref": f"partner-org:{ptn_a.id}", "channel": "BOTH",
             "creator_id": C1}, "partner")

        # ---- M2-b：开放课题全流程（C2）-----------------------------------
        # 演示链路：机构 A → 一条待处理指南建议 → 一条外部申报（PUBLISHED）
        #          → 任务书（仅 PI 已签，留管理端签署演示）→ 立项项目（ext_org_id=机构A）+ 1 条阶段汇报
        if ptn_a is not None and partner_user is not None:
            sug = put(PGuideSuggestion,
                      {"tenant_id": T1, "title": "开放课题：智能育种方向建议（演示）"},
                      {"org_id": ptn_a.id, "proposer_user_id": partner_user.id,
                       "background": "面向 2030 的育种智能化需求，建议设立开放课题方向。",
                       "objective": "构建表型-基因型联合建模方法并开源工具链。",
                       "expected_output": "方法论文 2 篇、开源工具 1 套、示范数据集 1 个。",
                       "contact_name": "张联系", "contact_phone": "13800000001",
                       "contact_email": "partner@example.edu.cn",
                       "status": "PENDING", "creator_id": partner_user.id}, "p")
            if not sug.code:
                sug.code = f"SUG-{today.year}-{sug.id:06d}"
                sug.save(update_fields=["code"])

            ext_app = put(PApplication,
                          {"tenant_id": T1, "code": "APP-DEMO-M2B-01"},
                          {"guideline_id": gl.id, "title": "智能育种联合建模（外部机构申报·演示）",
                           "project_type": "开放课题", "pi_user_id": partner_user.id,
                           "status": "PUBLISHED", "creator_id": partner_user.id,
                           "applicant_org_id": ptn_a.id, "applicant_type": "EXTERNAL",
                           "duration_months": 24, "total_budget": 300000,
                           "abstract": "面向智能育种的表型-基因型联合建模与工具链建设。",
                           "is_horizontal": False}, "p")

            ext_prj = put(EProject,
                          {"tenant_id": T1, "code": "PRJ-DEMO-M2B-01"},
                          {"application_id": ext_app.id,
                           "title": "智能育种联合建模（外部机构·演示）",
                           "project_type": "开放课题", "pi_user_id": partner_user.id,
                           "member_ids": [partner_user.id], "department_id": 1,
                           "legal_entity_id": ent.id, "ext_org_id": ptn_a.id,
                           "start_date": today - timedelta(days=30),
                           "end_date": today + timedelta(days=700),
                           "total_budget": 300000, "received_amount": 150000,
                           "spent_amount": 40000, "health_score": 85, "risk_level": "LOW",
                           "status": "ACTIVE", "security_level": "PUBLIC",
                           "creator_id": partner_user.id}, "project")
            tb_seed = put(PTaskBook,
                          {"tenant_id": T1, "application_id": ext_app.id},
                          {"status": "DRAFT", "creator_id": partner_user.id,
                           "project_id": ext_prj.id,
                           "print_template_code": "TPL-TASKBK-OPEN",
                           "sign_records": [{"signerId": partner_user.id, "role": "PI",
                                             "signedAt": now.isoformat(), "result": "OK"}],
                           "content_snapshot": {
                               "title": ext_app.title, "project_type": ext_app.project_type,
                               "pi_user_id": ext_app.pi_user_id,
                               "applicant_org_id": ptn_a.id,
                               "total_budget": "300000.00",
                               "duration_months": 24,
                               "research_target": "表型-基因型联合建模方法",
                               "technical_route": "多组学特征融合 + 迁移学习",
                               "expected_output": "论文 2 篇、工具链 1 套",
                               "frozen_at": now.isoformat(),
                           }}, "p")
            if not tb_seed.code:
                tb_seed.code = f"PRJ-{today.year}-{tb_seed.id:06d}"
                tb_seed.save(update_fields=["code"])

            put(EProgressReport,
                {"tenant_id": T1, "project": ext_prj, "period": "2026Q1"},
                {"report_type": "QUARTERLY", "progress_percent": 30,
                 "content_rich": "已完成数据接入与基线模型复现，进入特征融合阶段。",
                 "next_plan": "完成融合模型训练与首轮验证。",
                 "status": "SUBMITTED", "submitted_at": now,
                 "creator_id": partner_user.id}, "project")

        # ---- M2-c：外部专家与供应商协同（C3/C4/C5）-----------------------
        if ptn_a is not None and partner_user is not None:
            # C3 演示：①待审专家申请（审核台有数据可操作）②已生效专家档案（门户可直接看）
            from apps.expertreview.models import NExpert  # noqa: F401  (已在上方导入，保持一致)

            app_h = put(NExpert,
                        {"tenant_id": T1, "user_id": partner_user.id, "deleted": 0},
                        {"name": "合作单位联系人（演示申请）", "title": "副教授",
                         "org_name": "合作示例大学", "email": "partner@example.edu.cn",
                         "phone": "13800000001", "source": "EXTERNAL",
                         "status": "CANDIDATE", "expertise_level": "EXPERT",
                         "field_tags": ["人工智能", "数据治理"],
                         "creator_id": partner_user.id,
                         "remark": "M2-c 演示：待审核专家申请"}, "partner")
            if not app_h.code:
                app_h.code = f"NEX-{today.year}-{app_h.id:06d}"
                app_h.save(update_fields=["code"])

            # 外部专家账号（C3 验收：外部专家线上注册→审核→门户看信用档案）
            expert_ext = put(SysUser,
                             {"tenant_id": T1, "username": "expert_ext"},
                             {"real_name": "王振华（外部专家）", "email": "expert@example.edu.cn",
                              "phone": "13800000002", "staff_no": "EXT-0001",
                              "status": "ACTIVE", "user_source": "EXTERNAL",
                              "org_id": ptn_a.id, "legal_entity_id": None,
                              "security_level": "PUBLIC", "creator_id": C1,
                              "password_hash": bcrypt.hashpw(
                                  b"Expert@123456", bcrypt.gensalt()
                              ).decode(),
                              "remark": "M2-c 演示：外部评审专家（机构 A）"}, "user")
            if expert_ext is not None:
                self._rotate_password(expert_ext, override_pwd)
                role_ext = SysRole.objects.filter(tenant_id=T1, code="R-EXPERT").first()
                if role_ext is not None:
                    SysUserRole.objects.get_or_create(
                        user=expert_ext, role=role_ext, tenant_id=T1
                    )

                e_demo = NExpert.objects.filter(tenant_id=T1, name="王振华（演示）").first()
                if e_demo is not None and e_demo.user_id != expert_ext.id:
                    # 已生效档案绑到该外部专家账号后，「专家门户」可直接演示信用档案
                    e_demo.user_id = expert_ext.id
                    e_demo.field_tags = e_demo.field_tags or ["材料科学"]
                    e_demo.save(update_fields=["user_id", "field_tags"])

            # C4 演示：机构 A 绑定供应商 → 询价（应价中）+ 已定标询价 + 合同进度
            sup_ext = put(GSupplier,
                          {"tenant_id": T1, "code": "SUP-DEMO-M2C-01"},
                          {"name": "合作大学资产经营公司（演示）", "credit_code": "91310000MA1K3XY12A",
                           "type": "供应商", "status": "IN_LIBRARY", "grade": "B",
                           "org_id": ptn_a.id, "creator_id": C1,
                           "remark": "M2-c 演示：绑定外部机构 A，供应商门户可应价"}, "procure")
            if sup_ext is not None and sup_ext.org_id != ptn_a.id:
                sup_ext.org_id = ptn_a.id
                sup_ext.save(update_fields=["org_id"])

            req_ext = put(GRequisition,
                          {"tenant_id": T1, "code": "REQ-DEMO-M2C-01"},
                          {"project_id": ext_prj.id if "ext_prj" in dir() else 1,
                           "applicant_id": partner_user.id, "category": "设备",
                           "item_name": "高性能计算服务器（演示）", "est_amount": 120000,
                           "purchase_way": "询价", "status": "BIDDING",
                           "creator_id": C1}, "procure")
            bid_open = put(GBid,
                           {"tenant_id": T1, "code": "BID-DEMO-M2C-01"},
                           {"requisition": req_ext,
                            "method": "询价", "status": "PUBLICIZING",
                            "invited_supplier_ids": [sup_ext.id] if sup_ext else [],
                            "bids_json": [], "creator_id": C1,
                            "publish_at": now, "bid_open_at": now + timedelta(days=7),
                            "remark": "M2-c 演示：供应商门户可在线应价"}, "procure")
            bid_won = put(GBid,
                          {"tenant_id": T1, "code": "BID-DEMO-M2C-02"},
                          {"requisition": req_ext, "method": "询价", "status": "AWARDED",
                           "invited_supplier_ids": [sup_ext.id] if sup_ext else [],
                           "winner_supplier_id": sup_ext.id if sup_ext else None,
                           "bids_json": [{"supplierId": sup_ext.id if sup_ext else 0,
                                          "supplierName": "合作大学资产经营公司（演示）",
                                          "totalAmount": "98000.00", "remark": "含税包邮"}],
                           "creator_id": C1, "award_at": now, "publish_at": now - timedelta(days=20),
                           "remark": "M2-c 演示：已定标（不可再应价）"}, "procure")
            con_ext = put(GContract,
                          {"tenant_id": T1, "code": "CON-DEMO-M2C-01"},
                          {"contract_type": "采购", "supplier": sup_ext,
                           "requisition": req_ext, "project_id": ext_prj.id if "ext_prj" in dir() else 1,
                           "amount": 98000, "status": "ACTIVE", "sign_date": today - timedelta(days=20),
                           "start_date": today - timedelta(days=20), "end_date": today + timedelta(days=345),
                           "party_a": "某某研究院", "party_b": "合作大学资产经营公司",
                           "creator_id": C1,
                           "remark": "M2-c 演示：供应商门户可见脱敏进度"}, "procure")
            put(GContractPayment,
                {"tenant_id": T1, "contract": con_ext, "phase": "预付"},
                {"plan_amount": 40000, "plan_date": today - timedelta(days=10),
                 "paid_amount": 40000, "paid_at": now, "status": "PAID",
                 "creator_id": C1}, "procure")
            put(GContractPayment,
                {"tenant_id": T1, "contract": con_ext, "phase": "验收"},
                {"plan_amount": 58000, "plan_date": today + timedelta(days=90),
                 "paid_amount": 0, "status": "PLANNED", "creator_id": C1}, "procure")

        return cnt
