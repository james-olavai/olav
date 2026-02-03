"""OLAV HTTP API Server - Phase 5 Day 1-2.

Provides HTTP endpoints for health checks, metrics, and API access.

Endpoints:
- GET /health - Health check endpoint
- GET /metrics - Prometheus metrics (Phase 5 Day 3-5)
- POST /api/v1/query - Query endpoint (future)
"""

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config.paths import CACHE_DIR
from config.settings import settings
from olav.core.query_cache import get_query_cache
from olav.core.unified_database import UnifiedDatabase

logger = logging.getLogger(__name__)


# Health check response model
class HealthStatus(BaseModel):
    """Health check status response."""

    status: str = Field(description="Overall status: healthy, degraded, unhealthy")
    timestamp: str = Field(description="Check timestamp (ISO 8601)")
    version: str = Field(description="OLAV version")
    checks: dict[str, Any] = Field(description="Individual component health checks")
    uptime_seconds: float = Field(description="API server uptime in seconds")


# Global startup time for uptime calculation
_startup_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting OLAV API server")
    global _startup_time
    _startup_time = time.time()
    
    yield
    
    # Shutdown
    logger.info("Shutting down OLAV API server")


# Create FastAPI app
app = FastAPI(
    title="OLAV API",
    description="Network Operations AI Assistant API",
    version="0.9.8",
    lifespan=lifespan,
)


async def check_database() -> dict[str, Any]:
    """Check database connectivity and basic query."""
    try:
        with UnifiedDatabase() as db:
            # Simple query to verify database is accessible
            result = db.conn.execute("SELECT COUNT(*) as count FROM v_device_status").fetchone()
            device_count = result[0] if result else 0
            
            return {
                "status": "healthy",
                "message": "Database accessible",
                "device_count": device_count,
            }
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {
            "status": "unhealthy",
            "message": f"Database error: {str(e)}",
            "error": type(e).__name__,
        }


async def check_cache() -> dict[str, Any]:
    """Check query cache status."""
    try:
        cache = get_query_cache()
        stats = cache.stats()
        
        # Cache is healthy if it's accessible
        return {
            "status": "healthy",
            "message": "Cache accessible",
            "l1_size": stats.get("l1_size", 0),
            "l2_entries": stats.get("l2_total_entries", 0),
            "cache_dir": str(CACHE_DIR),
        }
    except Exception as e:
        logger.error(f"Cache health check failed: {e}")
        return {
            "status": "unhealthy",
            "message": f"Cache error: {str(e)}",
            "error": type(e).__name__,
        }


async def check_llm() -> dict[str, Any]:
    """Check LLM configuration (not actual connectivity)."""
    try:
        # Check if API key is configured
        api_key = settings.llm_api_key
        has_api_key = bool(api_key and len(api_key) > 0)
        
        # Check base URL if using third-party provider
        base_url = settings.llm_base_url
        
        if has_api_key:
            return {
                "status": "healthy",
                "message": "LLM configured",
                "provider": settings.llm_model_provider or "openai",
                "model": settings.llm_model_name,
                "base_url": base_url if base_url else "default",
            }
        else:
            return {
                "status": "degraded",
                "message": "LLM API key not configured",
                "provider": settings.llm_model_provider or "openai",
            }
    except Exception as e:
        logger.error(f"LLM health check failed: {e}")
        return {
            "status": "unhealthy",
            "message": f"LLM config error: {str(e)}",
            "error": type(e).__name__,
        }


@app.get("/health", response_model=HealthStatus, status_code=status.HTTP_200_OK)
async def health_check() -> HealthStatus:
    """Health check endpoint for monitoring and load balancers.
    
    Returns:
        HealthStatus: Comprehensive health status of all components
        
    Status Codes:
        - 200: All components healthy or degraded (service operational)
        - 503: One or more critical components unhealthy (service degraded)
    """
    # Perform all health checks
    checks = {
        "database": await check_database(),
        "cache": await check_cache(),
        "llm": await check_llm(),
    }
    
    # Determine overall status
    unhealthy_count = sum(1 for check in checks.values() if check["status"] == "unhealthy")
    degraded_count = sum(1 for check in checks.values() if check["status"] == "degraded")
    
    if unhealthy_count > 0:
        overall_status = "unhealthy"
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    elif degraded_count > 0:
        overall_status = "degraded"
        http_status = status.HTTP_200_OK
    else:
        overall_status = "healthy"
        http_status = status.HTTP_200_OK
    
    # Calculate uptime
    uptime = time.time() - _startup_time
    
    # Build response
    health_status = HealthStatus(
        status=overall_status,
        timestamp=datetime.utcnow().isoformat() + "Z",
        version="0.9.8",
        checks=checks,
        uptime_seconds=round(uptime, 2),
    )
    
    # Return with appropriate status code
    if http_status != status.HTTP_200_OK:
        return JSONResponse(
            status_code=http_status,
            content=health_status.model_dump(),
        )
    
    return health_status


@app.get("/", include_in_schema=False)
async def root():
    """Root endpoint redirect to health check."""
    return {"message": "OLAV API Server", "health": "/health", "metrics": "/metrics"}


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "olav.api.server:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=settings.debug if hasattr(settings, 'debug') else False,
    )
