-- U 域 · 页面可见性矩阵仓储（PRD 2.9：白名单制，全量替换保存）。
-- role_code='*' 表示所有已登录角色；R-ADMIN 恒可见由前端硬编码兜底，不入库。

-- name: ListPageGrants :many
SELECT page_name, role_code FROM sys_page_grant
WHERE tenant_id = @tenant_id
ORDER BY page_name, role_code;

-- name: DeleteAllPageGrants :execrows
DELETE FROM sys_page_grant WHERE tenant_id = @tenant_id;

-- name: InsertPageGrant :exec
INSERT INTO sys_page_grant (tenant_id, page_name, role_code)
VALUES (@tenant_id, @page_name, @role_code);
