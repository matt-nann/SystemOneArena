# The arena service: dependencies installed with uv in a build stage, then a slim runtime image.
# --- Build stage: install Python deps with uv ---
FROM python:3.12-slim AS builder

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# --- Dependency layer (cache-stable) ---
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# --- Runtime stage ---
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY arena/ arena/
COPY mock_openrouter/ mock_openrouter/
COPY web/ web/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# The mock can run from the same image: CMD ["python", "-m", "mock_openrouter"]
CMD ["python", "-m", "arena"]
