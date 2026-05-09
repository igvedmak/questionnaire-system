FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install --prefer-offline
COPY . .
ARG VITE_API_URL=http://localhost:8000
RUN VITE_API_URL=$VITE_API_URL npm run build

# ── test stage ────────────────────────────────────────────────────────────────
# Used by: docker compose --profile test run --rm ui-test
FROM builder AS test
CMD ["npm", "test"]

# ── production stage ──────────────────────────────────────────────────────────
FROM nginx:alpine AS production
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
