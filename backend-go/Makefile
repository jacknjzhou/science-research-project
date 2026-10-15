# Go 后端一键任务。均在本目录（backend-go）执行。
GO        ?= go
PKG       = ./...
BIN       = ark-server
DATABASE  = postgres://ark:ark@127.0.0.1:5432/ark?sslmode=disable

.PHONY: help fmt fmt-check vet tidy build run test test-integration cover \
        codegen gen-sqlc gen-oapi gen-migrations drift lint vuln ci

help: ## 列出可用目标
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n",$$1,$$2}'

fmt: ## 格式化
	$(GO) fmt $(PKG)

fmt-check: ## 检查未格式化文件（有则非零退出）
	@out=$$(gofmt -l .); if [ -n "$$out" ]; then echo "未格式化:\n$$out"; exit 1; fi

vet: ## go vet
	$(GO) vet $(PKG)

tidy: ## 整理依赖
	$(GO) mod tidy

build: ## 编译服务器
	CGO_ENABLED=0 $(GO) build -trimpath -o $(BIN) ./cmd/server

run: ## 本地起服务（需本地 Postgres/Redis 或用 compose 起依赖）
	ARK_DATABASE_URL=$(DATABASE) $(GO) run ./cmd/server

test: ## 单元测试（无 DB；集成测试因未设 ARK_TEST_DATABASE_URL 自动 skip）
	$(GO) test -race -count=1 $(PKG)

test-integration: ## 集成测试（需可达的 Postgres，见 CI services）
	ARK_TEST_DATABASE_URL=$(DATABASE) $(GO) test -race -count=1 -run 'Integration|UpDown|Store' -v $(PKG)

cover: ## 覆盖率汇总
	$(GO) test -coverprofile=coverage.out $(PKG) && $(GO) tool cover -func=coverage.out | tail -1

codegen: gen-sqlc gen-oapi gen-migrations ## 重新生成全部代码产物

# sqlc v1.27.0 的 wazero pg_query 解析器在自动工具链（go1.26/1.27）下会崩溃，
# 任务 5 实测仅能用钉死的 go1.23.4 稳定运行，故此目标必须固定 GOTOOLCHAIN。
# sqlc.yaml 位于 backend-go 根，schema 取裁剪后的 db/schema/p_schema.sql，
# 生成物输出到 internal/modules/p/store。
gen-sqlc: ## 由 db/query + schema 生成 DAL（sqlc，需钉住 go1.23.4 工具链）
	GOTOOLCHAIN=go1.23.4 $(GO) run github.com/sqlc-dev/sqlc/cmd/sqlc@v1.27.0 generate

# oapi-codegen 的调用与相对路径（-config p.cfg.yaml + 输入 design 契约 + output）
# 已由 codegen/generate.go 里的 //go:generate 指令按 codegen 目录工作路径正确装配，
# 因此这里统一走 `go generate`，避免在 Makefile 里重复一份易漂移的命令行/文件名。
# 真源文件名：codegen/p.cfg.yaml（注意非计划初稿写的 oapi-p.yaml）。
gen-oapi: ## 由 design 契约生成 DTO/模型（oapi-codegen，经 go:generate）
	$(GO) generate ./codegen/...

# migrations/gen.go 里 //go:generate go run ./cmd/gen（cmd/gen 调 migrations.WriteFiles，
# 读 design/ 拼出 000001_init.{up,down}.sql），故对 ./migrations/... 触发即可。
gen-migrations: ## 由 design/*.sql 生成 golang-migrate 脚本
	$(GO) generate ./migrations/...

drift: codegen ## 漂移守卫：重跑生成后若与已提交产物不一致则失败
	@$(GO) build ./... # 确保生成物可编译
	git diff --exit-code -- internal/modules/p/store internal/modules/sysadmin/store internal/modules/activity/store internal/modules/performance/store internal/modules/project/store internal/modules/output/store internal/modules/expertreview/store internal/modules/archive/store api/gen migrations/000001_init.up.sql migrations/000001_init.down.sql \
	  || (echo "codegen 产物与源不一致：请 make codegen 后提交"; exit 1)

lint: ## golangci-lint（govet/staticcheck/errcheck/ineffassign/unused + goimports）
	golangci-lint run --timeout=5m ./...

vuln: ## 漏洞扫描
	$(GO) run golang.org/x/vuln/cmd/govulncheck@latest ./...

ci: fmt-check vet lint test ## 无外部依赖的 CI 快路径（集成/漂移在专用 job 里跑）
