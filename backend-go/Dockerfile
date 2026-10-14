# syntax=docker/dockerfile:1
# 科研管理 Go 后端镜像。构建上下文 = 仓库根：
#   docker build -f backend-go/Dockerfile -t eplugger-ark-go:0.1.0 .
# 阶段 1：静态编译（pgx 纯 Go，无需 CGO）
FROM golang:1.22-alpine AS build
WORKDIR /src

# 先拷依赖清单，命中层缓存
COPY backend-go/go.mod backend-go/go.sum ./
RUN go mod download

# 再拷源码 + 契约（oapi.LoadDir 运行时读 /srv/design；生成期也可用）
COPY backend-go/ ./
COPY design/ /srv/design/

RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" \
    -o /out/ark-server ./cmd/server

# 阶段 2：极简运行层
FROM alpine:3.20
RUN adduser -D -u 10001 ark && apk add --no-cache ca-certificates wget
WORKDIR /srv/app

COPY --from=build /out/ark-server ./ark-server
# 运行时资产：契约目录、Casbin 模型/策略、迁移脚本
COPY --from=build /srv/design/ /srv/design/
COPY --from=build /src/internal/platform/auth/model.conf  /srv/auth/model.conf
COPY --from=build /src/internal/platform/auth/policy.csv  /srv/auth/policy.csv
COPY --from=build /src/migrations/ /srv/migrations/

ENV ARK_ENV=production \
    ARK_HTTP_PORT=8787 \
    DESIGN_DIR=/srv/design \
    ARK_MIGRATIONS_DIR=/srv/migrations \
    ARK_AUTH_MODEL_PATH=/srv/auth/model.conf \
    ARK_AUTH_POLICY_PATH=/srv/auth/policy.csv

EXPOSE 8787
USER ark
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
  CMD wget -qO- http://127.0.0.1:8787/healthz >/dev/null || exit 1

ENTRYPOINT ["./ark-server"]
