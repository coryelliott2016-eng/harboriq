# Multi-stage build: compile the Vite/React app, then serve the static
# `dist/` output from a minimal nginx image. nginx is more production-
# representative than `vite preview` (which is documented upstream as a
# dev-only convenience, not a production server).
FROM node:20-alpine AS build
WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
# VITE_API_URL is baked into the JS bundle at build time (Vite inlines
# import.meta.env.* at build, not at container start) — pass it as a build
# arg so different environments (dev/staging/prod) can each build their own
# image pointed at the right API.
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

FROM nginx:alpine AS serve
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
