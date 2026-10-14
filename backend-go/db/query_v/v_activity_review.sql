-- name: ListReviews :many
SELECT id, activity_id, review_level, reviewer_id, action, opinion, acted_at, tenant_id
FROM v_activity_review
WHERE activity_id = $1 AND tenant_id = $2
ORDER BY review_level, acted_at;

-- name: InsertReview :one
INSERT INTO v_activity_review (activity_id, review_level, reviewer_id, action, opinion, tenant_id)
VALUES ($1, $2, $3, $4, $5, $6)
RETURNING id, activity_id, review_level, reviewer_id, action, opinion, acted_at, tenant_id;
