# syntax=docker/dockerfile:1
# Lab 2 reference Dockerfile (step 2.5). Use it only if your own api/Dockerfile doesn't build
# (Lab 5 guide, Part 0): cp lab05-ci-pipeline/reference/Dockerfile api/. It costs no points.
FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --omit=dev

FROM node:24-alpine AS runtime
ENV NODE_ENV=production PORT=5000
WORKDIR /app
COPY --from=deps --chown=node:node /app/node_modules ./node_modules
COPY --chown=node:node . .
USER node
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1:5000/healthz || exit 1
CMD ["node", "server.js"]
