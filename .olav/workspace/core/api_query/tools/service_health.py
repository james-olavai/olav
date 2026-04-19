"""service_health — Check health status of registered API services.

Uses the platform ServiceRegistry and LifecycleManager to check if
registered services are reachable and responding.
"""
from __future__ import annotations

from langchain_core.tools import tool


@tool
def service_health(service: str = "") -> dict:
    """Check health status of registered API services.

    Args:
        service: Service name to check. If empty, checks ALL registered services.

    Returns:
        Dict with service name(s), status (healthy/unhealthy/unknown), and details.

    Examples:
        >>> service_health()                    # Check all services
        >>> service_health(service="netbox")    # Check specific service
    """
    from olav.platform.services.registry import ServiceRegistry

    registry = ServiceRegistry.get_instance()
    services_to_check = []

    if service:
        try:
            svc = registry.get(service)
            services_to_check = [svc]
        except KeyError:
            available = sorted(s.name for s in registry.list())
            return {
                "status": "error",
                "reason": f"Service '{service}' not registered.",
                "available": available,
            }
    else:
        services_to_check = registry.list()

    if not services_to_check:
        return {"status": "no_services", "message": "No services registered. Use 'olav registry register <url>' to add one."}

    results = []
    for svc in services_to_check:
        entry = {"name": svc.name, "endpoint": svc.endpoint}
        try:
            import httpx
            resp = httpx.get(
                f"{svc.endpoint.rstrip('/')}/health",
                timeout=5,
                follow_redirects=True,
            )
            entry["status"] = "healthy" if resp.status_code < 400 else "unhealthy"
            entry["http_status"] = resp.status_code
        except Exception as exc:
            # Try base URL if /health doesn't work
            try:
                resp = httpx.get(svc.endpoint, timeout=5, follow_redirects=True)
                entry["status"] = "reachable" if resp.status_code < 500 else "unhealthy"
                entry["http_status"] = resp.status_code
            except Exception:
                entry["status"] = "unreachable"
                entry["error"] = str(exc)[:100]
        results.append(entry)

    if len(results) == 1:
        return results[0]
    return {"services": results, "total": len(results),
            "healthy": sum(1 for r in results if r.get("status") in ("healthy", "reachable"))}
