# Use the official uv image with Python 3.13 for building dependencies
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

# Enable bytecode compilation and copy mode for uv
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies first to cache the layer
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Copy source code and config files
COPY src /app/src
COPY pyproject.toml uv.lock /app/

# Sync again to install the project itself if applicable (non-dev dependencies)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Use a clean, slim python runtime for the final production image
FROM python:3.13-slim-bookworm

WORKDIR /app

# Copy the virtual environment and source code from the builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# Prepend the virtual environment bin directory to the PATH
ENV PATH="/app/.venv/bin:$PATH"

# Set environment variables for production execution
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Expose the default Cloud Run port (8080)
EXPOSE 8080

# Cloud Run sets the PORT env variable at runtime. Bind to it dynamically.
CMD ["sh", "-c", "fastapi run src/main.py --host 0.0.0.0 --port ${PORT:-8080}"]
