"""一次性脚本：把 @validate_body(XxxIn) 套到六域 api.py 的写端点上。

规则：
- 装饰器插到 handler 装饰器块（@transaction.atomic 等）的最上方 → 验证先于事务。
- 已有 @validate_body 的 handler 跳过（幂等）。
- action/soft-body 端点（submit/approve/sign/ai_* 等）本轮不套，保留手工校验（渐进迁移）。
"""
from __future__ import annotations

import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # backend-django

MAPPING: dict[str, dict[str, str]] = {
    "transform": {
        "create_disclosure": "DisclosureIn",
        "assign_valuation": "ValuationIn",
        "create_deal": "DealIn",
        "save_negotiation": "NegotiationIn",
        "draft_contract": "ContractDraftIn",
        "register_partner": "PartnerIn",
        "handle_objection": "ObjectionHandleIn",
        "register_income": "IncomeIn",
        "save_distribution_rule": "DistributionRuleIn",
        "issue_distribution": "DistributionIssueIn",
        "generate_annual_report": "AnnualReportIn",
    },
    "ethics": {
        "create_ethics_case": "CaseIn",
        "formal_check": "FormalCheckIn",
        "assign_reviewers": "AssignReviewersIn",
        "submit_opinion": "OpinionIn",
        "meeting_vote": "MeetingVoteIn",
        "submit_amendment": "AmendmentIn",
        "decide_amendment": "AmendmentDecisionIn",
        "report_adverse_event": "AdverseEventIn",
        "submit_annual_review": "AnnualReviewIn",
        "sign_pledge": "PledgeIn",
        "create_integrity_record": "IntegrityRecordIn",
        "update_integrity_record": "IntegrityRecordIn",
        "appeal_integrity_record": "AppealIn",
        "create_misconduct_scan": "MisconductScanIn",
        "create_hgr_filing": "HgrFilingIn",
    },
    "staff": {
        "transfer_staff": "TransferIn",
        "create_team": "TeamIn",
        "add_team_member": "TeamMemberIn",
        "remove_team_member": "TeamMemberRemoveIn",
        "apply_visitor": "VisitorIn",
        "register_student": "StudentIn",
    },
    "procure": {
        "create_requisition": "RequisitionIn",
        "create_bid": "BidIn",
        "award_bid": "AwardIn",
        "create_contract": "ContractIn",
        "review_contract": "ContractReviewIn",
        "create_payment_plan": "PaymentPlanIn",
        "payment_callback": "PaymentCallbackIn",
    },
    "asset": {
        "create_asset": "AssetIn",
        "create_from_receipt": "FromReceiptIn",
        "run_depreciation": "DepreciationRunIn",
        "voucher_callback": "VoucherCallbackIn",
        "submit_inventory": "InventoryIn",
        "issue_asset": "IssueIn",
        "transfer_asset": "TransferIn",
        "create_disposal": "DisposalIn",
        "stock_in": "StockInIn",
        "stock_out": "StockOutIn",
    },
    "confsec": {
        "upsert_entity": "EntityUpsertIn",
        "publish_policy": "PolicyPublishIn",
        "grant_access": "GrantIn",
        "revoke_access": "RevokeIn",
        "create_export_apply": "ExportApplyIn",
        "approve_export": "ExportApproveIn",
        "release_export": "ExportReleaseIn",
        "submit_classify": "ClassifyIn",
        "write_sec_log": "SecLogIn",
        "personnel_review": "PersonnelReviewIn",
    },
}


def insert_imports(lines: list[str], domain: str, schema_names: list[str]) -> list[str]:
    """在 import 区末尾插入 validate_body 与域 schemas 导入。"""
    validate_imp = "from core.reqschema import validate_body\n"
    schema_imp = f"from apps.{domain}.schemas import {', '.join(schema_names)}\n"
    # 找最后一个顶层 import 行
    last_imp = -1
    for i, ln in enumerate(lines):
        if re.match(r"^(from |import )", ln):
            last_imp = i
    if validate_imp in lines and schema_imp in lines:
        return lines
    out: list[str] = []
    for i, ln in enumerate(lines):
        out.append(ln)
        if i == last_imp:
            if validate_imp not in lines:
                out.append(validate_imp)
            if schema_imp not in lines:
                out.append(schema_imp)
    return out


def decorate_file(domain: str, handlers: dict[str, str]) -> list[str]:
    path = BASE / "apps" / domain / "api.py"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    report: list[str] = []

    schema_names = list(handlers.values())
    lines = insert_imports(lines, domain, schema_names)

    for handler, schema in handlers.items():
        # 幂等：已装饰则跳过
        already = any(
            f"@validate_body({schema})" in ln for ln in lines
        ) and any(
            lines[i].startswith(f"def {handler}(") for i in range(len(lines))
        )
        # 定位 def 行
        def_idx = None
        for i, ln in enumerate(lines):
            if re.match(rf"^def {handler}\(", ln):
                def_idx = i
                break
        if def_idx is None:
            report.append(f"  [MISS] {handler} 未找到 def")
            continue
        # 检查 def 上方的装饰器块
        block_start = def_idx
        j = def_idx - 1
        while j >= 0 and lines[j].startswith("@"):
            block_start = j
            j -= 1
        dec_line = f"@validate_body({schema})\n"
        block = lines[block_start:def_idx]
        if any("validate_body" in b for b in block):
            report.append(f"  [SKIP] {handler} 已有 validate_body")
            continue
        lines.insert(block_start, dec_line)
        report.append(f"  [OK]   {handler} <- {schema}")

    path.write_text("".join(lines), encoding="utf-8")
    return report


def main():
    total = 0
    for domain, handlers in MAPPING.items():
        print(f"== {domain} ==")
        reps = decorate_file(domain, handlers)
        for r in reps:
            print(r)
        total += sum(1 for r in reps if r.strip().startswith("[OK]"))
    print(f"共装饰 {total} 个 handler")


if __name__ == "__main__":
    main()
