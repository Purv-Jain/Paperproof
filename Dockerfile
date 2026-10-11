# syntax=docker/dockerfile:1

# Paperproof production image for Render (and any OCI host).
#
# Two stages:
#   builder  - Python 3.13 + Node 22 (>= 22.22 for React Router 8.4) + uv.
#              Compiles the backend and builds the static frontend.
#   runtime  - Python 3.13 + tesseract + Caddy. No Node, no build toolchain.
#
# Node is deliberately kept out of the runtime image: `reflex run --env prod
# --backend-only` skips the frontend build, and Caddy serves the exported
# bundle from /srv instead. See the Caddyfile.
#
# Render terminates TLS and forwards plain HTTP to $PORT, so Caddy listens on
# http://:$PORT only and never attempts ACME.

ARG PORT=10000


FROM python:3.13-slim AS builder

# Node 22 for the React Router build. Copied file-by-file rather than whole
# /usr/local so the Python toolchain underneath is left untouched.
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && apt-get update -y \
 && apt-get install -y --no-install-recommends libstdc++6 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

# REFLEX_USE_NPM=1 because there is no .env in the image, and this project is
# npm-managed (reflex.lock/package-lock.json is committed). Without it Reflex
# drives the frontend with its bundled Bun.
ENV UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    REFLEX_USE_NPM=1 \
    npm_config_update_notifier=false \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Requirements first so source edits do not reinstall the dependency tree.
COPY requirements.txt ./
RUN uv venv && uv pip install -r requirements.txt

COPY . ./

# api_url is intentionally left at its localhost default. The compiled frontend
# rewrites a localhost backend URL to the origin it was served from and upgrades
# it to wss://, which is what makes this single-origin deployment work with no
# REFLEX_API_URL and no CORS configuration.
RUN reflex export --frontend-only --no-zip


FROM python:3.13-slim AS runtime

# tesseract-ocr-eng is listed explicitly: pytesseract calls the tesseract binary
# with lang="eng", and --no-install-recommends would otherwise skip the English
# language pack, silently breaking OCR of scanned PDFs.
# libcap2-bin provides setcap, used below to strip Caddy's file capability.
RUN apt-get update -y \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      libcap2-bin \
      tesseract-ocr \
      tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*

# The official Caddy image ships the binary with
# `setcap cap_net_bind_service=+ep /usr/bin/caddy`. The +e (effective) bit makes
# the kernel refuse to exec the binary unless the process can actually obtain
# that capability, and Render does not put CAP_NET_BIND_SERVICE in the
# container's bounding set. The result is `caddy: Operation not permitted` and
# exit 126 before Caddy ever starts.
#
# The capability is unnecessary here: Caddy binds :{$PORT}, and Render sets PORT
# to 10000, far above the privileged range. Strip it.
#
# The `test -z` is the real guard. BuildKit's own build containers do have
# CAP_NET_BIND_SERVICE in their bounding set, so merely running `caddy version`
# would succeed even with the capability still attached; asserting that getcap
# comes back empty is what actually catches a regression at build time.
COPY --from=caddy:2 /usr/bin/caddy /usr/bin/caddy
RUN setcap -r /usr/bin/caddy \
 && test -z "$(getcap /usr/bin/caddy)" \
 && /usr/bin/caddy version

ARG PORT
ENV PATH="/app/.venv/bin:$PATH" \
    PORT=$PORT \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    REFLEX_USE_NPM=1

WORKDIR /app

# Reflex writes .states/ and uploaded_files/ at runtime, so the app user must own
# /app itself.
RUN adduser --disabled-password --gecos "" --home /app reflex && chown reflex /app

COPY --chown=reflex --from=builder /app/.venv .venv
COPY --chown=reflex --from=builder /app/.web/backend .web/backend
COPY --from=builder /app/.web/build/client /srv
COPY --chown=reflex . ./

USER reflex
EXPOSE $PORT

# Caddy daemonises and owns the public port; reflex runs as PID 1 so a backend
# crash ends the container and Render restarts it. Render's health check hits
# /_health, which Caddy proxies to the backend, so that also fails closed.
CMD caddy start --config /app/Caddyfile --adapter caddyfile && \
    exec reflex run --env prod --backend-only --backend-port 8000
