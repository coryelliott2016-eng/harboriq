# Multi-stage build. The `builder` stage has the compiler toolchain needed
# to build wheels for packages with C extensions (psycopg, argon2-cffi); the
# final `runtime` stage copies only the installed Python packages + app
# code, so no compiler, header files, or build cache ever ship in the image
# that actually runs in production.
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install into a dedicated prefix (not the system site-packages) so the
# runtime stage can copy exactly this directory and nothing else.
COPY pyproject.toml ./
COPY app ./app
# Deliberately `pip install .` (NOT `-e ".[dev]"`): a production image has
# no business running the test suite, and an editable install would depend
# on the source tree being present/writable at the same path at runtime,
# which conflicts with the read-only, code-baked-into-the-image model of a
# container. The `dev` extra (pytest, httpx, ruff) is test/lint tooling that
# only bloats the runtime image and widens its attack surface.
RUN pip install --upgrade pip \
    && pip install --prefix=/install .

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH=/usr/local/bin:$PATH \
    PYTHONPATH=/usr/local/lib/python3.12/site-packages

WORKDIR /app

# libpq5 is the runtime shared library psycopg needs; libpq-dev/build-essential
# (headers + compilers) are NOT installed here — those only existed in the
# builder stage. curl is kept only because the HEALTHCHECK below uses it;
# swap for a smaller tool if that becomes a concern.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /usr/sbin/nologin app

COPY --from=builder /install /usr/local
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

# Run as a dedicated non-root user. A container escape or an RCE in a
# dependency then lands as an unprivileged user rather than root, which is
# the difference between "contained to this process" and "trivially
# escalates to the host" in the common case.
RUN chown -R app:app /app
USER app

EXPOSE 8000

# Hits the real liveness route (see app/api/v1/routes/health.py, mounted
# under the /api/v1 prefix in app/api/v1/router.py) rather than a bespoke
# healthcheck script, so this always reflects the same signal the app
# itself exposes to callers/load balancers. `--start-period` gives
# migrations + first boot a grace window before failures count.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
