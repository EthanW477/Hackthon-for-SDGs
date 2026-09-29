FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_* values are inlined at build time.
ARG NEXT_PUBLIC_API_URL=http://localhost:43124
ARG NEXT_PUBLIC_CESIUM_ION_TOKEN=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_CESIUM_ION_TOKEN=$NEXT_PUBLIC_CESIUM_ION_TOKEN
RUN node scripts/copy-cesium-assets.mjs && npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app ./
EXPOSE 43123
CMD ["npx", "next", "start", "-p", "43123"]
