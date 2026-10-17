"""集中路由注册：公开（login/healthz）+ 受保护（auth=ark_auth）。"""
from core.auth.api import login as login_view
from core.auth.deps import ark_auth
from core.ninja import api
from apps.notify import api as notify_api
from apps.sysadmin import api as sysadmin_api

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
