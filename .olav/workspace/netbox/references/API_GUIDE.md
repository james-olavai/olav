# NetBox REST API Guide

    ## Authentication
    Bearer Token: Authorization: Token <key>

    ## Key Endpoints
    - GET /api/dcim/sites/ — sites
    - GET /api/dcim/devices/?site_id=1 — devices
    - GET /api/ipam/prefixes/?site_id=1 — prefixes
    - GET /api/ipam/ip-addresses/?within=10.0.0.0/24 — IPs
    - GET /api/dcim/cables/ — cables

    Use ?limit=0 for count, ?limit=20 for list.

    Full OpenAPI schema at /api/schema/swagger/
    