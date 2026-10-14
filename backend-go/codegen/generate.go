package codegen

// 本包仅承载 go:generate 指令：从 design 的 P 契约生成 DTO 模型（供 M1 handler 复用）。
// 单独运行：cd backend-go && go run github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@v2.4.1 -config codegen/p.cfg.yaml "../design/01-项目申报与立项-P.openapi.yaml"

//go:generate go run github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@v2.4.1 -config p.cfg.yaml ../../design/01-项目申报与立项-P.openapi.yaml
