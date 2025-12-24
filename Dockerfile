# syntax=docker/dockerfile:1

FROM python:3.13-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

# Install make
RUN apt-get update && apt-get install -y --no-install-recommends make \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set work directory
WORKDIR /app

# Copy dependency files and Makefile
COPY pyproject.toml uv.lock Makefile ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy application code
COPY app ./app

# Create directories for uploads and sessions
RUN mkdir -p /app/uploads /app/sessions

# Expose port
EXPOSE 8000

# Run the application using make
CMD ["make", "dev"]

