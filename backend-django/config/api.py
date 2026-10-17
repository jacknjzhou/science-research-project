"""集中路由注册：公开（login/healthz）+ 受保护（auth=ark_auth）。"""
from core.auth.api import login as login_view
from core.auth.deps import ark_auth
from core.ninja import api
from apps.funding import api as funding_api
from apps.notify import api as notify_api
from apps.p import api as p_api
from apps.project import api as project_api
from apps.sysadmin import api as sysadmin_api
from core import dataio_api

# —— 公开：登录（不进鉴权中间件，对齐 Go）——
api.post("/auth/login", tags=["auth"])(login_view)

# —— auth/me（所有已认证角色）——
api.get("/auth/me", auth=ark_auth, tags=["auth"])(sysadmin_api.get_me)

# —— 用户管理 ——
api.get("/admin/users", auth=ark_auth, tags=["admin"])(sysadmin_api.list_users)
api.post("/admin/users", auth=ark_auth, tags=["admin"])(sysadmin_api.create_user)
api.get("/admin/users/{id}", auth=ark_auth, tags=["admin"])(sysadmin_api.get_user)
api.put("/admin/users/{id}", auth=ark_auth, tags=["admin"])(sysadmin_api.update_user)
api.delete("/admin/users/{id}", auth=ark_auth, tags=["admin"])(sysadmin_api.delete_user)
api.post("/admin/users/{id}/roles", auth=ark_auth, tags=["admin"])(sysadmin_api.assign_role)
api.delete(
    "/admin/users/{id}/roles/{role_id}", auth=ark_auth, tags=["admin"]
)(sysadmin_api.revoke_role)

# —— 角色目录 ——
api.get("/admin/roles", auth=ark_auth, tags=["admin"])(sysadmin_api.list_roles)
api.post("/admin/roles", auth=ark_auth, tags=["admin"])(sysadmin_api.create_role)
api.put("/admin/roles/{role_id}", auth=ark_auth, tags=["admin"])(sysadmin_api.update_role)
api.delete("/admin/roles/{role_id}", auth=ark_auth, tags=["admin"])(sysadmin_api.delete_role)

# —— 数据字典 ——
api.get("/admin/dicts", auth=ark_auth, tags=["dicts"])(sysadmin_api.list_dicts)
api.post("/admin/dicts", auth=ark_auth, tags=["dicts"])(sysadmin_api.upsert_dict)
api.get("/admin/dicts/{dict_id}", auth=ark_auth, tags=["dicts"])(sysadmin_api.get_dict)
api.delete("/admin/dicts/{dict_id}", auth=ark_auth, tags=["dicts"])(sysadmin_api.delete_dict)
api.post(
    "/admin/dicts/{dict_id}/items", auth=ark_auth, tags=["dicts"]
)(sysadmin_api.upsert_dict_item)
api.put(
    "/admin/dicts/{dict_id}/items/{item_id}", auth=ark_auth, tags=["dicts"]
)(sysadmin_api.update_dict_item)
api.delete(
    "/admin/dicts/{dict_id}/items/{item_id}", auth=ark_auth, tags=["dicts"]
)(sysadmin_api.delete_dict_item)
api.get("/dicts/{code}", auth=ark_auth, tags=["dicts"])(sysadmin_api.get_dict_by_code)

# —— 页面可见性矩阵 ——
api.get("/page-grants", auth=ark_auth, tags=["admin"])(sysadmin_api.list_page_grants)
api.put("/admin/page-grants", auth=ark_auth, tags=["admin"])(sysadmin_api.save_page_grants)

# —— 通知中心 ——
api.get("/notifications", auth=ark_auth, tags=["notify"])(notify_api.list_notifications)
api.get("/notifications/unread-count", auth=ark_auth, tags=["notify"])(notify_api.unread_count)
api.post("/notifications/read-all", auth=ark_auth, tags=["notify"])(notify_api.mark_all_read)
api.post("/notifications/{id}/read", auth=ark_auth, tags=["notify"])(notify_api.mark_read)

# —— P 申报指南 ——
api.get("/apply/guidelines", auth=ark_auth, tags=["p"])(p_api.list_guidelines)
api.post("/apply/guidelines", auth=ark_auth, tags=["p"])(p_api.upsert_guideline)
api.get("/apply/guidelines/{id}", auth=ark_auth, tags=["p"])(p_api.get_guideline)

# —— P 申报书（p 模块直建，DRAFT）——
api.get("/apply/applications", auth=ark_auth, tags=["p"])(p_api.list_applications)
api.post("/apply/applications", auth=ark_auth, tags=["p"])(p_api.create_application)
# 注意：{id}:withdraw/:terminate 带冒号后缀，必须先于 {id} 注册，
# 否则 {id} 的 [^/]+ 正则会先吞掉 "1:withdraw" 导致 405。
api.post(
    "/apply/applications/{id}:withdraw", auth=ark_auth, tags=["p"]
)(p_api.withdraw_application)
api.post(
    "/apply/applications/{id}:terminate", auth=ark_auth, tags=["p"]
)(p_api.terminate_application)
api.get("/apply/applications/{id}", auth=ark_auth, tags=["p"])(p_api.get_application)

# —— E 项目：静态路由必须先于 {id} 注册 ——
api.get("/project/mine", auth=ark_auth, tags=["project"])(project_api.list_my_projects)
api.get("/project/{id}", auth=ark_auth, tags=["project"])(project_api.get_project)
api.get("/project/{id}/tasks", auth=ark_auth, tags=["project"])(project_api.list_tasks)
api.get("/project/{id}/milestones", auth=ark_auth, tags=["project"])(project_api.list_milestones)
api.put(
    "/project/{id}/tasks/{task_id}", auth=ark_auth, tags=["project"]
)(project_api.update_task)
api.post(
    "/project/{id}/progress-report", auth=ark_auth, tags=["project"]
)(project_api.create_progress_report)
api.post(
    "/project/{id}/mid-check", auth=ark_auth, tags=["project"]
)(project_api.create_mid_check)
api.post(
    "/project/{id}/change-request", auth=ark_auth, tags=["project"]
)(project_api.create_change_request)
api.post(
    "/project/{id}/change-request/{change_id}/approve", auth=ark_auth, tags=["project"]
)(project_api.approve_change_request)
api.post(
    "/project/{id}/final-accept", auth=ark_auth, tags=["project"]
)(project_api.create_final_accept)

# —— E 变更批量审批 / 任务书提取（静态，先于 /projects/{id}/...）——
api.post(
    "/projects/approve-batch", auth=ark_auth, tags=["project"]
)(project_api.approve_change_batch)
api.post(
    "/projects/extract-taskbook", auth=ark_auth, tags=["project"]
)(project_api.extract_taskbook)
api.post(
    "/projects/{id}/category", auth=ark_auth, tags=["project"]
)(project_api.attach_project_category)

# —— E 项目分类 ——
api.get(
    "/project-categories", auth=ark_auth, tags=["project"]
)(project_api.list_project_categories)
api.post(
    "/project-categories", auth=ark_auth, tags=["project"]
)(project_api.create_project_category)
api.post(
    "/project-categories/scan-warnings", auth=ark_auth, tags=["project"]
)(project_api.scan_warnings)
api.put(
    "/project-categories/{id}", auth=ark_auth, tags=["project"]
)(project_api.update_project_category)
api.delete(
    "/project-categories/{id}", auth=ark_auth, tags=["project"]
)(project_api.delete_project_category)

# —— E 申报计划与申报审批 ——
api.get("/apply-plans", auth=ark_auth, tags=["project"])(project_api.list_apply_plans)
api.post("/apply-plans", auth=ark_auth, tags=["project"])(project_api.create_apply_plan)
api.post(
    "/apply-plans/auto-stop", auth=ark_auth, tags=["project"]
)(project_api.auto_stop_plans)
api.post(
    "/apply-plans/{id}/start", auth=ark_auth, tags=["project"]
)(project_api.start_apply_plan)
api.post(
    "/apply-plans/{id}/stop", auth=ark_auth, tags=["project"]
)(project_api.stop_apply_plan)
api.post(
    "/apply-plans/{id}/applications", auth=ark_auth, tags=["project"]
)(project_api.create_plan_application)
api.get(
    "/apply-plans/{id}/applications", auth=ark_auth, tags=["project"]
)(project_api.list_plan_applications)
api.post(
    "/applications/{id}/approve", auth=ark_auth, tags=["project"]
)(project_api.approve_application)
api.post(
    "/applications/{id}/to-project", auth=ark_auth, tags=["project"]
)(project_api.application_to_project)

# —— dataio Excel 导入导出底座 ——
api.get("/dataio/template", auth=ark_auth, tags=["dataio"])(dataio_api.template)
api.post("/dataio/import", auth=ark_auth, tags=["dataio"])(dataio_api.import_rows)
api.get("/dataio/imports", auth=ark_auth, tags=["dataio"])(dataio_api.list_imports)
api.post(
    "/dataio/imports/{id}/undo", auth=ark_auth, tags=["dataio"]
)(dataio_api.undo_import)
api.post("/dataio/export", auth=ark_auth, tags=["dataio"])(dataio_api.export)

# —— F 经费域：科目 ——
api.get("/subjects", auth=ark_auth, tags=["funding"])(funding_api.list_subjects)
api.get("/subjects/tree", auth=ark_auth, tags=["funding"])(funding_api.subjects_tree)
api.post("/subjects", auth=ark_auth, tags=["funding"])(funding_api.create_subject)
api.put("/subjects/{id}", auth=ark_auth, tags=["funding"])(funding_api.update_subject)
api.delete("/subjects/{id}", auth=ark_auth, tags=["funding"])(funding_api.delete_subject)

# —— F 预算 ——
api.post("/budgets", auth=ark_auth, tags=["funding"])(funding_api.create_budget)
api.get("/budgets", auth=ark_auth, tags=["funding"])(funding_api.list_budgets)
api.get("/budgets/{id}", auth=ark_auth, tags=["funding"])(funding_api.get_budget)
api.get("/budgets/{id}/lines", auth=ark_auth, tags=["funding"])(funding_api.list_budget_lines)
api.post("/budgets/{id}/submit", auth=ark_auth, tags=["funding"])(funding_api.submit_budget)
api.post("/budgets/{id}/approve", auth=ark_auth, tags=["funding"])(funding_api.approve_budget)
api.post("/budgets/{id}/adjust", auth=ark_auth, tags=["funding"])(funding_api.adjust_budget)
api.post("/budgets/{id}/append", auth=ark_auth, tags=["funding"])(funding_api.append_budget)
api.post("/budgets/{id}/append/approve", auth=ark_auth, tags=["funding"])(funding_api.approve_budget_append)
api.get("/budget-lines/{lineId}/balance", auth=ark_auth, tags=["funding"])(funding_api.line_balance)

# —— F 到款 ——
api.post("/incomes", auth=ark_auth, tags=["funding"])(funding_api.create_income)
api.get("/incomes", auth=ark_auth, tags=["funding"])(funding_api.list_incomes)
api.post("/incomes/{id}/claim", auth=ark_auth, tags=["funding"])(funding_api.claim_income)
api.post(
    "/incomes/import-bank-flow", auth=ark_auth, tags=["funding"]
)(funding_api.import_bank_flow)

# —— F 报销（静态 approval-batch 必须先于 {id} 注册，避免 [^/]+ 吞噬 → 405）——
api.post("/expenses", auth=ark_auth, tags=["funding"])(funding_api.create_expense)
api.get("/expenses", auth=ark_auth, tags=["funding"])(funding_api.list_expenses)
api.post(
    "/expenses/approval-batch", auth=ark_auth, tags=["funding"]
)(funding_api.approval_batch)
api.get("/expenses/{id}", auth=ark_auth, tags=["funding"])(funding_api.get_expense)
api.post("/expenses/{id}/submit", auth=ark_auth, tags=["funding"])(funding_api.submit_expense)
api.post("/expenses/{id}/approval", auth=ark_auth, tags=["funding"])(funding_api.approval_action)
api.post(
    "/expense/ai-invoice-review", auth=ark_auth, tags=["funding"]
)(funding_api.ai_invoice_review)

# —— F 执行/预警/间接费 ——
api.get("/funding/execution", auth=ark_auth, tags=["funding"])(funding_api.funding_execution)
api.get("/funding/warnings", auth=ark_auth, tags=["funding"])(funding_api.funding_warnings)
api.post(
    "/indirect-fees/calculate", auth=ark_auth, tags=["funding"]
)(funding_api.calculate_indirect_fee)
api.get(
    "/indirect-fees/calculate", auth=ark_auth, tags=["funding"]
)(funding_api.page_indirect_fees)
api.get("/indirect-fees", auth=ark_auth, tags=["funding"])(funding_api.list_indirect_fees)

# —— F 外拨/结转 ——
api.post("/outwards", auth=ark_auth, tags=["funding"])(funding_api.create_outward)
api.get("/outwards", auth=ark_auth, tags=["funding"])(funding_api.list_outwards)
api.post("/outwards/{id}/approval", auth=ark_auth, tags=["funding"])(funding_api.outward_action)
api.post("/carryovers", auth=ark_auth, tags=["funding"])(funding_api.create_carryover)
api.get("/carryovers", auth=ark_auth, tags=["funding"])(funding_api.list_carryovers)
api.post(
    "/carryovers/{id}/approval", auth=ark_auth, tags=["funding"]
)(funding_api.carryover_action)

# —— F 预警配置 ——
api.get("/funding/warn-configs", auth=ark_auth, tags=["funding"])(funding_api.list_warn_configs)
api.post("/funding/warn-configs", auth=ark_auth, tags=["funding"])(funding_api.create_warn_config)
api.put(
    "/funding/warn-configs/{id}", auth=ark_auth, tags=["funding"]
)(funding_api.update_warn_config)
api.delete(
    "/funding/warn-configs/{id}", auth=ark_auth, tags=["funding"]
)(funding_api.delete_warn_config)

# ==================== Phase 3：R/N/V/O/M/D 域 ====================
from apps.output import api as output_api
from apps.expertreview import api as expertreview_api
from apps.activity import api as activity_api
from apps.archive import api as archive_api
from apps.performance import api as performance_api
from apps.dataops import api as dataops_api
from core.stub import stub_view

# —— R 成果：静态段（mine/pending-claim/claim/reject/mark-not-mine）先于 {id} ——
# 契约 passthrough 端点（AI/导出/专利目录）也须先于 {id} 注册，否则被 [^/]+ 吞噬 → 405/422
api.post("/output/ai-fill", auth=ark_auth, tags=["output"])(stub_view)
api.post("/output/ai-dedup", auth=ark_auth, tags=["output"])(stub_view)
api.post("/output/export", auth=ark_auth, tags=["output"])(stub_view)
api.get("/output/patents", auth=ark_auth, tags=["output"])(stub_view)
api.get("/output", auth=ark_auth, tags=["output"])(output_api.list_outputs)
api.post("/output", auth=ark_auth, tags=["output"])(output_api.create_output)
api.get("/output/mine", auth=ark_auth, tags=["output"])(output_api.list_my_outputs)
api.get("/output/pending-claim", auth=ark_auth, tags=["output"])(output_api.list_pending_claim)
api.post("/output/claim", auth=ark_auth, tags=["output"])(output_api.claim_outputs)
api.post("/output/reject", auth=ark_auth, tags=["output"])(output_api.reject_outputs)
api.post("/output/mark-not-mine", auth=ark_auth, tags=["output"])(output_api.mark_not_mine)
api.put(
    "/output/{id}/projects", auth=ark_auth, tags=["output"]
)(output_api.link_projects)
api.get("/output/{id}", auth=ark_auth, tags=["output"])(output_api.get_output)

# —— P5 治理：期刊（resolve 静态先于 {id}/sources）/转载/网推/专利/代理 ——
api.get("/journal-sources", auth=ark_auth, tags=["output"])(output_api.list_journal_sources)
api.post("/journal-sources", auth=ark_auth, tags=["output"])(output_api.create_journal_source)
api.get("/journal-levels", auth=ark_auth, tags=["output"])(output_api.list_journal_levels)
api.post("/journal-levels", auth=ark_auth, tags=["output"])(output_api.create_journal_level)
api.get(
    "/journal-levels/resolve", auth=ark_auth, tags=["output"]
)(output_api.resolve_journal_level)
api.post(
    "/journal-levels/{id}/sources", auth=ark_auth, tags=["output"]
)(output_api.attach_level_source)
api.post("/papers/{id}/reprints", auth=ark_auth, tags=["output"])(output_api.create_reprint)
api.get("/papers/{id}/reprints", auth=ark_auth, tags=["output"])(output_api.list_reprints)
api.get("/push-items", auth=ark_auth, tags=["output"])(output_api.list_push_items)
api.post(
    "/push-items/{id}/import", auth=ark_auth, tags=["output"]
)(output_api.import_push_item)
api.post(
    "/push-items/{id}/ignore", auth=ark_auth, tags=["output"]
)(output_api.ignore_push_item)
api.post("/patents/{id}/stage", auth=ark_auth, tags=["output"])(output_api.set_patent_stage)
api.post("/patents/{id}/fees", auth=ark_auth, tags=["output"])(output_api.create_patent_fee)
api.get("/patents/{id}/fees", auth=ark_auth, tags=["output"])(output_api.list_patent_fees)
api.get("/agencies", auth=ark_auth, tags=["output"])(output_api.list_agencies)
api.post("/agencies", auth=ark_auth, tags=["output"])(output_api.create_agency)

# —— N 专家评审 ——
api.get("/experts", auth=ark_auth, tags=["expertreview"])(expertreview_api.list_experts)
api.post("/experts", auth=ark_auth, tags=["expertreview"])(expertreview_api.create_expert)
api.get("/experts/{id}", auth=ark_auth, tags=["expertreview"])(expertreview_api.get_expert)
api.put("/experts/{id}", auth=ark_auth, tags=["expertreview"])(expertreview_api.update_expert)
api.delete("/experts/{id}", auth=ark_auth, tags=["expertreview"])(expertreview_api.delete_expert)
api.post(
    "/experts/{id}/status", auth=ark_auth, tags=["expertreview"]
)(expertreview_api.set_expert_status)

api.get("/reviews", auth=ark_auth, tags=["expertreview"])(expertreview_api.list_reviews)
api.post("/reviews", auth=ark_auth, tags=["expertreview"])(expertreview_api.create_review)
# {id}/detail 静态段先于 {id}（GET 同方法避免吞噬）
api.get(
    "/reviews/{id}/detail", auth=ark_auth, tags=["expertreview"]
)(expertreview_api.get_review_detail)
api.get("/reviews/{id}", auth=ark_auth, tags=["expertreview"])(expertreview_api.get_review)
api.delete("/reviews/{id}", auth=ark_auth, tags=["expertreview"])(expertreview_api.cancel_review)
api.post("/reviews/{id}/draw", auth=ark_auth, tags=["expertreview"])(expertreview_api.draw_experts)
api.post("/reviews/{id}/invite", auth=ark_auth, tags=["expertreview"])(expertreview_api.invite_experts)
api.post("/reviews/{id}/accept", auth=ark_auth, tags=["expertreview"])(expertreview_api.accept_invitation)
api.post("/reviews/{id}/decline", auth=ark_auth, tags=["expertreview"])(expertreview_api.decline_invitation)
api.post("/reviews/{id}/start", auth=ark_auth, tags=["expertreview"])(expertreview_api.start_review)
api.post("/reviews/{id}/scores", auth=ark_auth, tags=["expertreview"])(expertreview_api.submit_score)
api.post("/reviews/{id}/conclude", auth=ark_auth, tags=["expertreview"])(expertreview_api.conclude_review)
api.post("/reviews/{id}/fees", auth=ark_auth, tags=["expertreview"])(expertreview_api.generate_fees)

# —— V 学术活动：calendar/stats 静态先于 {id} ——
api.get("/activities", auth=ark_auth, tags=["activity"])(activity_api.list_activities)
api.post("/activities", auth=ark_auth, tags=["activity"])(activity_api.create_activity)
api.get(
    "/activities/calendar", auth=ark_auth, tags=["activity"]
)(activity_api.activity_calendar)
api.get("/activities/stats", auth=ark_auth, tags=["activity"])(activity_api.activity_stats)
api.get("/activities/{id}", auth=ark_auth, tags=["activity"])(activity_api.get_activity)
api.put("/activities/{id}", auth=ark_auth, tags=["activity"])(activity_api.update_activity)
api.delete("/activities/{id}", auth=ark_auth, tags=["activity"])(activity_api.delete_activity)
api.post("/activities/{id}/submit", auth=ark_auth, tags=["activity"])(activity_api.submit_activity)
api.post("/activities/{id}/approve", auth=ark_auth, tags=["activity"])(activity_api.approve_activity)
api.post("/activities/{id}/hold", auth=ark_auth, tags=["activity"])(activity_api.hold_activity)
api.post("/activities/{id}/archive", auth=ark_auth, tags=["activity"])(activity_api.archive_activity)
api.post("/activities/{id}/cancel", auth=ark_auth, tags=["activity"])(activity_api.cancel_activity)
api.get(
    "/activities/{id}/participants", auth=ark_auth, tags=["activity"]
)(activity_api.list_participants)
api.post(
    "/activities/{id}/participants", auth=ark_auth, tags=["activity"]
)(activity_api.add_participant)
api.delete(
    "/activities/{id}/participants/{pid}", auth=ark_auth, tags=["activity"]
)(activity_api.remove_participant)

# —— O 档案：documents/search 静态先于 {id} ——
api.post("/documents", auth=ark_auth, tags=["archive"])(archive_api.upload_document)
api.get(
    "/documents/search", auth=ark_auth, tags=["archive"]
)(archive_api.search_documents)
api.get("/documents/{id}", auth=ark_auth, tags=["archive"])(archive_api.get_document)
api.delete("/documents/{id}", auth=ark_auth, tags=["archive"])(archive_api.delete_document)
api.get(
    "/documents/{id}/download", auth=ark_auth, tags=["archive"]
)(archive_api.download_document)

api.get("/archives", auth=ark_auth, tags=["archive"])(archive_api.list_archives)
api.post("/archives", auth=ark_auth, tags=["archive"])(archive_api.create_archive)
api.get("/archives/{id}", auth=ark_auth, tags=["archive"])(archive_api.get_archive)
api.put("/archives/{id}", auth=ark_auth, tags=["archive"])(archive_api.update_archive)
api.delete("/archives/{id}", auth=ark_auth, tags=["archive"])(archive_api.delete_archive)
api.get("/archives/{id}/items", auth=ark_auth, tags=["archive"])(archive_api.list_items)
api.post("/archives/{id}/items", auth=ark_auth, tags=["archive"])(archive_api.add_item)
api.put(
    "/archives/{id}/items/{item_id}", auth=ark_auth, tags=["archive"]
)(archive_api.fill_item)
api.delete(
    "/archives/{id}/items/{item_id}", auth=ark_auth, tags=["archive"]
)(archive_api.delete_item)
api.post("/archives/{id}/ingest", auth=ark_auth, tags=["archive"])(archive_api.ingest_source)
api.post("/archives/{id}/submit", auth=ark_auth, tags=["archive"])(archive_api.submit_archive)
api.post("/archives/{id}/check", auth=ark_auth, tags=["archive"])(archive_api.check_archive)
api.post("/archives/{id}/file", auth=ark_auth, tags=["archive"])(archive_api.file_archive)
api.post("/archives/{id}/destroy", auth=ark_auth, tags=["archive"])(archive_api.destroy_archive)

api.get("/borrows", auth=ark_auth, tags=["archive"])(archive_api.list_borrows)
api.post("/borrows", auth=ark_auth, tags=["archive"])(archive_api.create_borrow)
api.post("/borrows/{id}/approve", auth=ark_auth, tags=["archive"])(archive_api.approve_borrow)
api.post("/borrows/{id}/reject", auth=ark_auth, tags=["archive"])(archive_api.reject_borrow)
api.post("/borrows/{id}/return", auth=ark_auth, tags=["archive"])(archive_api.return_borrow)

# —— M 绩效：portrait 独立前缀；perf 嵌套无吞噬冲突 ——
api.get("/portrait/{user_id}", auth=ark_auth, tags=["performance"])(performance_api.portrait)
api.get("/perf/schemes", auth=ark_auth, tags=["performance"])(performance_api.list_schemes)
api.post("/perf/schemes", auth=ark_auth, tags=["performance"])(performance_api.create_scheme)
api.get("/perf/schemes/{id}", auth=ark_auth, tags=["performance"])(performance_api.get_scheme)
api.put("/perf/schemes/{id}", auth=ark_auth, tags=["performance"])(performance_api.update_scheme)
api.delete("/perf/schemes/{id}", auth=ark_auth, tags=["performance"])(performance_api.delete_scheme)
api.post(
    "/perf/schemes/{id}/activate", auth=ark_auth, tags=["performance"]
)(performance_api.activate_scheme)
api.post(
    "/perf/schemes/{id}/calculate", auth=ark_auth, tags=["performance"]
)(performance_api.calculate_performance)
api.get(
    "/perf/schemes/{id}/factors", auth=ark_auth, tags=["performance"]
)(performance_api.list_factors)
api.post(
    "/perf/schemes/{id}/factors", auth=ark_auth, tags=["performance"]
)(performance_api.upsert_factor)
api.put(
    "/perf/schemes/{id}/factors/{factor_id}", auth=ark_auth, tags=["performance"]
)(performance_api.update_factor)
api.delete(
    "/perf/schemes/{id}/factors/{factor_id}", auth=ark_auth, tags=["performance"]
)(performance_api.delete_factor)
api.get("/perf/records", auth=ark_auth, tags=["performance"])(performance_api.list_records)
api.get(
    "/perf/records/{id}/detail", auth=ark_auth, tags=["performance"]
)(performance_api.get_record_detail)
api.get("/perf/records/{id}", auth=ark_auth, tags=["performance"])(performance_api.get_record)
api.post(
    "/perf/records/{id}/confirm", auth=ark_auth, tags=["performance"]
)(performance_api.confirm_record)
api.post(
    "/perf/records/{id}/appeal", auth=ark_auth, tags=["performance"]
)(performance_api.appeal_record)
api.post(
    "/perf/records/{id}/approve", auth=ark_auth, tags=["performance"]
)(performance_api.approve_record)
api.post(
    "/perf/records/{id}/void", auth=ark_auth, tags=["performance"]
)(performance_api.void_record)
api.get("/perf/payouts", auth=ark_auth, tags=["performance"])(performance_api.list_payouts)
api.post("/perf/payouts", auth=ark_auth, tags=["performance"])(performance_api.create_payout)
api.get("/perf/payouts/{id}", auth=ark_auth, tags=["performance"])(performance_api.get_payout)
api.post(
    "/perf/payouts/{id}/approve", auth=ark_auth, tags=["performance"]
)(performance_api.approve_payout)
api.post("/perf/payouts/{id}/pay", auth=ark_auth, tags=["performance"])(performance_api.pay_payout)
api.post(
    "/perf/payouts/{id}/reject", auth=ark_auth, tags=["performance"]
)(performance_api.reject_payout)
api.get("/perf/me", auth=ark_auth, tags=["performance"])(performance_api.my_performance)
api.get("/perf/ranking", auth=ark_auth, tags=["performance"])(performance_api.perf_ranking)

# —— D 数据决策大屏 ——
api.get(
    "/dashboard/funding", auth=ark_auth, tags=["dataops"]
)(dataops_api.funding_dashboard)
