# =============================================================================
# Solana Intel Engine - Dockerfile
# =============================================================================
# Simplified build that uses pre-built wheels
# Includes: API Server, Ingestion, Logic Engine
# =============================================================================

FROM python:3.11-slim

WORKDIR /app

# Install minimal runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy all application code
COPY . .

# Install Python dependencies from pyproject.toml
# Using --prefer-binary to use pre-built wheels
RUN pip install --no-cache-dir --prefer-binary \
    asyncpg==0.29.0 \
    redis==5.0.1 \
    neo4j==5.15.0 \
    aiohttp==3.9.1 \
    python-dotenv==1.0.0 \
    websockets==12.0 \
    backoff==2.2.1 \
    grpcio==1.60.0 \
    fastapi==0.109.0 \
    uvicorn==0.27.0 \
    python-socketio==5.11.0 \
    cryptography==42.0.0

# Create non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Environment defaults
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Expose API port
EXPOSE 8000

# Default command: run all services
CMD ["python", "run_dev.py"]
