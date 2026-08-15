# Multi-stage build: compile the Vite/React app, then serve the built
# `dist/` output from a minimal nginx image. nginx is more production-
# representative than `vite preview` (which is documented upstream as a
# dev-only convenience, not a production server).
FROM node:20-alpine AS build
WORKDIR /app

COPY package*.json ./
# --legacy-peer-deps: eslint-plugin-jsx-a11y@6.10.2 declares an eslint peer
# range that stops at ^9 (no v10 support tag yet), but this project is on
# eslint@^10.8.0. See .github/workflows/ci.yml for the same rationale.
# Remove this flag once jsx-a11y publishes a release with eslint v10 in its
# peerDependencies range.
RUN npm ci --legacy-peer-deps

COPY . .
# VITE_API_URL is baked into the JS bundle at build time (Vite inlines
# import.meta.env.* at build, not at container start) — pass it as a build
# arg so different environments (dev/staging/prod) can each build their own
# image pointed at the right API.
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

# --- Runtime stage --------------------------------------------------------
# nginx:alpine already runs its worker processes as an unprivileged `nginx`
# user by default, but the master process still starts as root (needed to
# bind port 80 and read the config) unless we move both the listen port
# and file ownership out of root's territory. Rather than relying on the
# base image's default (which can change across tags), pin the ownership
# and switch USER explicitly so this Dockerfile is self-documenting about
# its own security posture instead of inheriting an implicit one.
FROM nginx:alpine AS serve

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Listen on an unprivileged port (>1024) so the whole process — master
# included — can run as a non-root user; binding :80 directly would require
# root or CAP_NET_BIND_SERVICE. The published/mapped host port is unrelated
# to this (see docker-compose*.yml), so this is transparent to callers.
RUN sed -i 's/listen\s*80;/listen 8080;/' /etc/nginx/conf.d/default.conf \
    # nginx needs to write its pid file, and its worker processes need to
    # write cache/temp dirs — all normally root-owned by default. Rehome
    # them under a directory the `nginx` user (already created by the base
    # image) actually owns.
    && sed -i 's#^pid\s\+.*#pid /tmp/nginx.pid;#' /etc/nginx/nginx.conf \
    && touch /tmp/nginx.pid \
    && chown -R nginx:nginx /usr/share/nginx/html /etc/nginx/conf.d /tmp/nginx.pid \
    && chown -R nginx:nginx /var/cache/nginx /var/log/nginx

USER nginx
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://localhost:8080/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
