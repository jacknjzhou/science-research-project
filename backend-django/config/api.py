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
