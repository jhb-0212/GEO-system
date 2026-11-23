# 前端生产镜像（多阶段：依赖 → 构建 → 运行）
FROM node:24-alpine AS deps
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
# 允许覆盖 npm 源：国内构建时传 --build-arg NPM_REGISTRY=https://registry.npmmirror.com
ARG NPM_REGISTRY=https://registry.npmjs.org
RUN pnpm install --frozen-lockfile --registry=${NPM_REGISTRY}

FROM node:24-alpine AS build
WORKDIR /app
RUN corepack enable
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build

FROM node:24-alpine AS runner
WORKDIR /app
# 构建时注入固定 release commit；部署验收用此 label 与 RELEASE_COMMIT 比对。
ARG RELEASE_COMMIT=unknown
LABEL org.opencontainers.image.revision="${RELEASE_COMMIT}"
ENV NODE_ENV=production
RUN corepack enable
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/pnpm-lock.yaml ./pnpm-lock.yaml
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["pnpm", "start"]
