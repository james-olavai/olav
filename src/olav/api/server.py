"""FastAPI Web Server - REST API wrapper for Phase 1 programmatic API.

Provides RESTful endpoints for:
- Schema discovery (/api/v1/schema/*)
- Data querying (/api/v1/data/*)
- Cache management (/api/v1/cache/*)
- System health and stats (/api/v1/system/*)
- Device management (/api/v1/devices/*)
- Query execution (/api/v1/query/*)

Security:
- Input validation via Pydantic
- SQL injection prevention (parameterized queries)
- CORS configuration
- OpenAPI documentation
"""

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Import Phase 1 API functions
from olav.api.v1 import cache, data, devices, query, schema, system

logger = logging.getLogger(__name__)

# Global startup time for uptime calculation
_startup_time = time.time()


# Pydantic models for request/response validation
class HealthStatus(BaseModel):
    """Health check status response."""

    status: str = Field(description="Overall status: healthy, degraded, unhealthy")
    timestamp: str = Field(description="Check timestamp (ISO 8601)")
    version: str = Field(description="OLAV version")
    checks: dict[str, Any] = Field(description="Individual component health checks")
    uptime_seconds: float = Field(description="API server uptime in seconds")


class SchemaResponse(BaseModel):
    """Schema endpoint response."""

    tables: list[str] = []
    columns: list[dict[str, Any]] = []
    success: bool = True


class DataQueryRequest(BaseModel):
    """Data query request body."""

    where: dict[str, Any] | None = None
    order_by: str | None = None
    limit: int = 100
    offset: int = 0


class DataQueryResponse(BaseModel):
    """Data query response."""

    rows: list[dict[str, Any]] = []
    total_count: int = 0
    columns: list[str] = []
    success: bool = True
    cached: bool = False


class CacheRequest(BaseModel):
    """Cache management request."""

    cache_type: str = "query"
    expired_only: bool = False


class QueryRequest(BaseModel):
    """Query execution request."""

    query: str
    context: dict[str, Any] | None = None


class QueryResponse(BaseModel):
    """Query execution response."""

    success: bool
    result: dict[str, Any] | None = None
    error: str | None = None


class FormatRequest(BaseModel):
    """Format request model."""

    rows: list[dict[str, Any]]
    format_type: str = "json"


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
    title="OLAV Network Assistant API",
    description="REST API for network device querying and management",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure based on security requirements
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# HEALTH CHECK ENDPOINTS
# ============================================================================


async def check_database() -> dict[str, Any]:
    """Check database connectivity and basic query."""
    try:
        # Quick check using UnifiedDatabase
        from olav.core.unified_database import UnifiedDatabase

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
        from olav.core.query_cache import get_query_cache

        cache = get_query_cache()
        stats = cache.stats()

        # Cache is healthy if it's accessible
        return {
            "status": "healthy",
            "message": "Cache accessible",
            "l1_size": stats.get("l1_size", 0),
            "l2_entries": stats.get("l2_total_entries", 0),
        }
    except Exception as e:
        logger.error(f"Cache health check failed: {e}")
        return {
            "status": "unhealthy",
            "message": f"Cache error: {str(e)}",
            "error": type(e).__name__,
        }


@app.get("/health", response_model=HealthStatus, status_code=status.HTTP_200_OK)
async def health_check() -> HealthStatus:
    """Health check endpoint for monitoring and load balancers.

    Returns:
        HealthStatus: Comprehensive health status of all components
    """
    # Perform all health checks
    checks = {
        "database": await check_database(),
        "cache": await check_cache(),
    }

    # Determine overall status
    unhealthy_count = sum(1 for check in checks.values() if check["status"] == "unhealthy")
    degraded_count = sum(1 for check in checks.values() if check["status"] == "degraded")

    if unhealthy_count > 0:
        overall_status = "unhealthy"
    elif degraded_count > 0:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    # Calculate uptime
    uptime = time.time() - _startup_time

    # Build response
    health_status = HealthStatus(
        status=overall_status,
        timestamp=datetime.utcnow().isoformat() + "Z",
        version="1.0.0",
        checks=checks,
        uptime_seconds=round(uptime, 2),
    )

    return health_status


# ============================================================================
# SCHEMA ENDPOINTS
# ============================================================================


@app.get("/api/v1/schema/tables", response_model=SchemaResponse)
async def get_tables():
    """Discover all available tables in the database.

    Returns:
        List of table names
    """
    try:
        result = schema.list_tables()  # Correct Phase 1.1 function name
        tables = [t.name for t in result.tables] + [v.name for v in result.views]
        return SchemaResponse(tables=tables, success=True)
    except Exception as e:
        logger.error(f"Error getting tables: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/schema/{table_name}")
async def get_table_schema(table_name: str):
    """Get schema for a specific table.

    Args:
        table_name: Name of the table

    Returns:
        Table schema with columns
    """
    try:
        table_schema = schema.get_table_schema(table_name)
        return table_schema
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Table not found: {table_name}")
    except Exception as e:
        logger.error(f"Error getting schema for {table_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/schema/{table_name}/sample")
async def get_sample_data(table_name: str, limit: int = Query(5, ge=1, le=100)):
    """Get sample data from a table.

    Args:
        table_name: Name of the table
        limit: Number of rows to return (max 100)

    Returns:
        Sample rows from the table
    """
    try:
        sample = schema.get_sample_data(table_name, limit)  # Correct module
        return {"table": table_name, "rows": sample, "count": len(sample), "success": True}
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Table not found: {table_name}")
    except Exception as e:
        logger.error(f"Error getting sample data for {table_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# DATA ENDPOINTS
# ============================================================================


@app.get("/api/v1/data/{table_name}", response_model=DataQueryResponse)
async def query_table(
    table_name: str,
    limit: int = Query(100, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    order_by: str | None = None,
):
    """Query data from a table with optional filters, pagination, and ordering.

    Args:
        table_name: Name of the table to query
        limit: Max rows to return (default 100, max 10000)
        offset: Pagination offset
        order_by: Column name to order by

    Returns:
        Paginated query results
    """
    try:
        # Phase 1.2 query_table returns QueryResult dataclass
        result = data.query_table(
            table_name, where=None, order_by=order_by, limit=limit, offset=offset
        )

        return DataQueryResponse(
            rows=result.rows,
            total_count=result.total_count,
            columns=result.columns,
            success=True,
            cached=False,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Table not found: {table_name}")
    except Exception as e:
        logger.error(f"Error querying {table_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/data/{table_name}")
async def query_table_post(table_name: str, request: DataQueryRequest):
    """Query table via POST with filters in request body.

    Args:
        table_name: Name of the table
        request: Query parameters (where, order_by, limit, offset)

    Returns:
        Paginated results
    """
    try:
        result = data.query_table(
            table_name,
            where=request.where,
            order_by=request.order_by,
            limit=request.limit,
            offset=request.offset,
        )

        return DataQueryResponse(
            rows=result.rows, total_count=result.total_count, columns=result.columns, success=True
        )
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Table not found: {table_name}")
    except Exception as e:
        logger.error(f"Error querying {table_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CACHE ENDPOINTS
# ============================================================================


@app.get("/api/v1/cache/stats")
async def get_cache_stats(cache_type: str = Query("query")):
    """Get cache statistics for a specific cache type.

    Args:
        cache_type: Type of cache (query, session, schema, diagnosis)

    Returns:
        Cache metrics (hit_rate, size, entries, etc.)
    """
    try:
        stats = cache.get_cache_stats(cache_type)
        return stats
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/cache/stats/all")
async def get_all_cache_stats():
    """Get statistics for all cache types.

    Returns:
        Combined cache metrics for all cache types
    """
    try:
        stats = {
            "query": cache.get_cache_stats("query"),
            "session": cache.get_cache_stats("session"),
            "schema": cache.get_cache_stats("schema"),
            "diagnosis": cache.get_cache_stats("diagnosis"),
        }
        return stats
    except Exception as e:
        logger.error(f"Error getting all cache stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/cache/entries")
async def list_cache_entries(
    cache_type: str = Query("query"), limit: int = Query(10, ge=1, le=100)
):
    """List cached entries for a cache type.

    Args:
        cache_type: Type of cache
        limit: Max entries to return

    Returns:
        List of cache entries with keys and metadata
    """
    try:
        entries = cache.list_cache_entries(cache_type, limit)
        return {
            "cache_type": cache_type,
            "entries": entries,
            "count": len(entries) if entries else 0,
            "success": True,
        }
    except Exception as e:
        logger.error(f"Error listing cache entries: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/cache/clear")
async def clear_cache(request: CacheRequest):
    """Clear cache entries.

    Args:
        request: Cache parameters (type, expired_only)

    Returns:
        Number of entries cleared
    """
    try:
        cleared = cache.clear_cache(request.cache_type, expired_only=request.expired_only)
        return {"success": True, "cleared": cleared, "cache_type": request.cache_type}
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# SYSTEM ENDPOINTS
# ============================================================================


@app.get("/api/v1/system/health")
async def system_health():
    """Get system health status.

    Returns:
        Health status (healthy/degraded/unhealthy) with component checks
    """
    try:
        health = system.get_system_health()  # Returns dict
        return health
    except Exception as e:
        logger.error(f"Error getting system health: {e}")
        return {"status": "unhealthy", "error": str(e), "success": False}


@app.get("/api/v1/system/stats")
async def system_stats():
    """Get system statistics.

    Returns:
        System metrics (CPU, memory, uptime, etc.)
    """
    try:
        stats = system.get_system_stats()  # Returns dict
        return stats
    except Exception as e:
        logger.error(f"Error getting system stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/system/database/stats")
async def database_stats():
    """Get database statistics.

    Returns:
        Database metrics (size, tables, indexes, etc.)
    """
    try:
        db_stats = system.get_database_stats()  # Returns dict
        return db_stats
    except Exception as e:
        logger.error(f"Error getting database stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/system/cache/performance")
async def cache_performance():
    """Get cache performance metrics.

    Returns:
        Cache hit rate, response times, etc.
    """
    try:
        # Phase 1.4 function returns dict
        perf = system.get_cache_performance()
        return perf
    except Exception as e:
        logger.error(f"Error getting cache performance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/system/version")
async def get_version():
    """Get system version information.

    Returns:
        Version strings for API, database, etc.
    """
    try:
        # Phase 1.4 get_version() returns a string, wrap in dict for API
        version_str = system.get_version()
        return {"success": True, "version": version_str, "api_version": "v1", "api_name": "OLAV"}
    except Exception as e:
        logger.error(f"Error getting version: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# DEVICE ENDPOINTS
# ============================================================================


@app.get("/api/v1/devices")
async def list_devices(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    """List devices with optional filters.

    Args:
        limit: Max devices to return
        offset: Pagination offset

    Returns:
        List of devices
    """
    try:
        # Phase 1.5 list_devices uses individual params instead of filters dict
        device_list = devices.list_devices(limit=limit, offset=offset)
        return {"devices": device_list, "count": len(device_list)}
    except Exception as e:
        logger.error(f"Error listing devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/devices/{device_id}")
async def get_device(device_id: str):
    """Get specific device details.

    Args:
        device_id: Device identifier (hostname or IP)

    Returns:
        Device information
    """
    try:
        device = devices.get_device(device_id)
        if not device:
            raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")
        return device
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting device {device_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/devices/{device_id}/interfaces")
async def get_device_interfaces(device_id: str):
    """Get interfaces for a device.

    Args:
        device_id: Device identifier

    Returns:
        List of interfaces
    """
    try:
        interfaces = devices.get_device_interfaces(device_id)
        return {"device_id": device_id, "interfaces": interfaces}
    except Exception as e:
        logger.error(f"Error getting interfaces for {device_id}: {e}")
        # Graceful degradation - might not exist
        return {"device_id": device_id, "interfaces": []}


@app.get("/api/v1/devices/{device_id}/capabilities")
async def get_device_capabilities(device_id: str):
    """Get device capabilities.

    Args:
        device_id: Device identifier

    Returns:
        Device capabilities
    """
    try:
        capabilities = devices.get_device_capabilities(device_id)
        return {"device_id": device_id, "capabilities": capabilities}
    except Exception as e:
        logger.error(f"Error getting capabilities for {device_id}: {e}")
        return {"device_id": device_id, "capabilities": {}}


@app.get("/api/v1/devices/{device_id}/status")
async def get_device_status(device_id: str):
    """Get device health/operational status.

    Args:
        device_id: Device identifier

    Returns:
        Device status information
    """
    try:
        status_info = devices.get_device_status(device_id)
        return {"device_id": device_id, "status": status_info}
    except Exception as e:
        logger.error(f"Error getting status for {device_id}: {e}")
        return {"device_id": device_id, "status": {}}


# ============================================================================
# QUERY ENDPOINTS
# ============================================================================


@app.post("/api/v1/query/execute", response_model=QueryResponse)
async def execute_query(request: QueryRequest):
    """Execute natural language query.

    Args:
        request: Query text and optional context

    Returns:
        Query results
    """
    try:
        result = query.execute_query(request.query)
        return QueryResponse(
            success=result.get("success", True), result=result, error=result.get("error")
        )
    except Exception as e:
        logger.error(f"Error executing query: {e}")
        return QueryResponse(success=False, result=None, error=str(e))


@app.post("/api/v1/query/optimize")
async def optimize_query(request: QueryRequest):
    """Get optimization suggestions for a query.

    Args:
        request: Query text

    Returns:
        Optimization analysis
    """
    try:
        optimization = query.optimize_query(request.query)
        return {"success": True, "optimization": optimization}
    except Exception as e:
        logger.error(f"Error optimizing query: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/query/parse")
async def parse_query(request: QueryRequest):
    """Parse natural language query to structured intent.

    Args:
        request: Query text

    Returns:
        Parsed intent with entities and filters
    """
    try:
        intent = query.parse_intent(request.query)
        return {"success": True, "intent": intent}
    except Exception as e:
        logger.error(f"Error parsing query: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/query/format")
async def format_results(request: FormatRequest):
    """Format query results in specified format.

    Args:
        request: Rows and format type

    Returns:
        Formatted results
    """
    try:
        formatted = query.format_results(request.rows, request.format_type)
        return {"success": True, "format": request.format_type, "result": formatted}
    except Exception as e:
        logger.error(f"Error formatting results: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ROOT ENDPOINTS
# ============================================================================


@app.get("/")
async def root():
    """API root endpoint."""
    return {
        "name": "OLAV Network Assistant API",
        "version": "1.0.0",
        "docs": "/docs",
        "api_v1": "/api/v1",
    }


@app.get("/api/v1")
async def api_root():
    """API v1 root endpoint."""
    return {
        "version": "1.0.0",
        "endpoints": {
            "schema": "/api/v1/schema",
            "data": "/api/v1/data",
            "cache": "/api/v1/cache",
            "system": "/api/v1/system",
            "devices": "/api/v1/devices",
            "query": "/api/v1/query",
        },
    }


# ============================================================================
# EXCEPTION HANDLERS
# ============================================================================


@app.exception_handler(ValueError)
async def value_error_handler(request, exc: ValueError):
    """Handle ValueError exceptions."""
    logger.error(f"Value error: {exc}")
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def general_exception_handler(request, exc: Exception):
    """Handle unexpected exceptions."""
    logger.error(f"Unexpected error: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "olav.api.server:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
