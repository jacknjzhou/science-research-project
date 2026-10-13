# 契约驱动参考后端镜像（Node 16 + Fastify）
# 构建上下文 = 仓库根，因为运行时需同时读取 backend/ 源码与 design/ 契约。
#   单独构建：docker build -f backend/Dockerfile -t eplugger-backend:0.1.0 .
# schema.js 里 DESIGN_DIR = resolve(__dirname,'..','..','design')
# 故容器内保留相对布局：/srv/app/backend/src 与 /srv/app/design
FROM node:16-alpine

WORKDIR /srv/app

# 先装依赖，利用镜像层缓存（改源码不触发重装）
COPY backend/package.json backend/package-lock.json ./backend/
RUN cd backend && npm ci --omit=dev && npm cache clean --force

# 再拷源码与契约（契约是唯一真源，随镜像只读分发）
COPY backend/ ./backend/
COPY design/ ./design/

# HOST=0.0.0.0 以便容器外/其它容器可访问
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=8787

EXPOSE 8787

# 轻量健康检查（server.js 暴露 /healthz）
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=5 \
  CMD wget -qO- http://127.0.0.1:8787/healthz >/dev/null || exit 1

# 以非 root 运行（应用为进程内存储，无需写盘）
USER node

CMD ["node", "backend/src/server.js"]
