# Production-ready Dockerfile for OLAV v2.0
FROM python:3.12-slim as builder

LABEL maintainer="OLAV Team"
LABEL version="2.0.0"
LABEL description="OLAV - Network Operations AI Assistant with DeepAgents"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    openssh-client \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

# Install uv (package installer)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:$PATH"

# Install dependencies using uv
RUN uv pip install --no-cache-dir -e .

# Production stage
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /app /app
COPY --from=builder /root/.cache /root/.cache

# Create non-root user for security
RUN useradd -m -u 1000 olav && chown -R olav:olav /app
USER olav

# Environment configuration
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV OLAV_ENV=production

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from src.olav.core.database import get_database; get_database()" || exit 1

# Expose ports
# 8000: REST API
# 5000: CLI interactive mode
EXPOSE 8000 5000

# Default command (help, can be overridden)
CMD ["python", "-m", "olav", "--help"]

# Alternative entrypoints for different modes:
# - API server: python -m uvicorn src.olav.api.server:app --host 0.0.0.0 --port 8000
# - CLI interactive: python -m olav interactive
# - CLI command: python -m olav ask "query"
