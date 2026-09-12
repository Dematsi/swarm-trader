FROM python:3.11-slim

WORKDIR /app

# Set PYTHONPATH to include the app directory
ENV PYTHONPATH=/app

# Unprivileged runtime user
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --create-home --home-dir /home/app app

# Install uv (pinned)
COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /uvx /bin/

# Dependencies live outside /app so the source COPY below never shadows them
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

# Copy only dependency files first for better caching
COPY pyproject.toml uv.lock /app/

# Scripts run from /app via PYTHONPATH, so the project itself isn't installed
RUN uv sync --frozen --no-dev --no-install-project

# Copy rest of the source code (owned by the runtime user so caches/outputs are writable)
COPY --chown=app:app . /app/

USER app

# Default command (will be overridden by Docker Compose)
CMD ["python", "src/main.py"]
