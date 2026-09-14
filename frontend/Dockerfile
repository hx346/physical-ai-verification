# 前端：node 构建 + nginx 托管（/api 反代到 backend 容器）
# build context = 仓库根（compose: context: .., dockerfile: frontend/Dockerfile）
FROM node:22-alpine AS build
WORKDIR /build

ENV NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html
EXPOSE 80
