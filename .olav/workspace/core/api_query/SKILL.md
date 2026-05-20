---
name: api_query
description: "API service queries — HTTP requests to registered services (NetBox, Grafana, Jira, etc.), health checks, web search, report export"
tools:
  - web_search
  - format_and_export
scripts:
  - name: api_request
    description: "HTTP request to a registered service (GET/POST/PUT/DELETE). Resolves base URL from service registry."
    file: api_request.py
  - name: service_health
    description: "Check health / reachability of a registered service. Returns status and response time."
    file: service_health.py
---
