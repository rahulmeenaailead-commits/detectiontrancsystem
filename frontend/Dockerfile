FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
# The dashboard authenticates to the backend with X-API-Key, so the key must be
# baked in at build time (NEXT_PUBLIC_* is inlined during `next build`). It must
# match the backend's SENTINEL_API_KEY or every request 401s.
ARG NEXT_PUBLIC_SENTINEL_API_KEY=sentinel-dev-key
ENV NEXT_PUBLIC_SENTINEL_API_KEY=$NEXT_PUBLIC_SENTINEL_API_KEY
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
EXPOSE 3000
CMD ["npm", "start"]
