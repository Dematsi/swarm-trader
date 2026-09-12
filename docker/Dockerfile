FROM python:3.11-slim

WORKDIR /app

# Set PYTHONPATH to include the app directory
ENV PYTHONPATH=/app

# Unprivileged runtime user
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --create-home --home-dir /home/app app

# Install Poetry
RUN pip install poetry==1.7.1

# Copy only dependency files first for better caching
COPY pyproject.toml poetry.lock* /app/

# Configure Poetry to not use a virtual environment
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi

# Copy rest of the source code (owned by the runtime user so caches/outputs are writable)
COPY --chown=app:app . /app/

USER app

# Default command (will be overridden by Docker Compose)
CMD ["python", "src/main.py"]
