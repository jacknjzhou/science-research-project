"""演示数据播种（对齐 Go seeddemo 语义：幂等，DEMO- 前缀/种子行存在即跳过）。

Phase 0 范围：8 基础角色、4 演示用户、字典种子、页面可见性矩阵种子。
用法：python manage.py seed_demo
"""
from __future__ import annotations

import bcrypt
from django.core.management.base import BaseCommand
from django.utils import timezone as dj_tz

from apps.sysadmin.models import PageGrant, SysDict, SysDictItem, SysRole, SysUser, SysUserRole

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

        self.stdout.write(
            self.style.SUCCESS(
                f"seed_demo 完成（幂等）：角色 +{n_roles}，用户 +{n_users}，"
                f"字典 +{n_dicts}，条目 +{n_items}，页面授权 +{n_grants}"
            )
        )
