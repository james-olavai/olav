# OLAV Main Application Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Copy project files
COPY pyproject.toml uv.lock* ./
COPY README.md ./
COPY src ./src
COPY config ./config

# Install dependencies using uv
RUN uv sync --frozen

# Expose port for web service
EXPOSE 8000

# Default command (can be overridden)
CMD ["uv", "run", "python", "-m", "olav.main", "serve"]
