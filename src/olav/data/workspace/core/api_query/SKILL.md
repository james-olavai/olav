---
name: api-query
description: "API service queries — HTTP requests to registered services (NetBox, Grafana, Jira, etc.), health checks, web search, report export"
tools:
  - web_search
  - format_and_export
scripts:
  - name: api_request
    description: "Make HTTP requests to a registered service"
    file: api_request.py
  - name: service_health
    description: "Check health and reachability of a registered service"
    file: service_health.py
---
