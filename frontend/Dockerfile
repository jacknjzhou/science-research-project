# 前端 SPA 镜像：多阶段。构建上下文 = frontend/。
#   单独构建：docker build -t eplugger-frontend:0.1.0 ./frontend
# 阶段 1：node 构建产物 dist/（关闭契约 mock，走真实后端）
FROM node:16-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# 关键：生产构建期把 VITE_USE_MOCK 设为 false，否则 main.ts 默认仍安装 fetch 拦截 mock
ENV VITE_USE_MOCK=false
RUN npm run build          # vue-tsc --noEmit && vite build → /app/dist

# 阶段 2：nginx 托管静态资源，并反代 /api/v1 → backend 服务
FROM nginx:1.25-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=5 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
