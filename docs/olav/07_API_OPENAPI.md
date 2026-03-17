# OLAV API And OpenAPI

This document describes the current platform-level API surface and how OpenAPI is maintained.

It focuses on the implementation that exists today, not on a future router split.

## 1. Current Source Of Truth

The authoritative FastAPI application lives in `src/olav/api/server.py`.

Current implementation facts:

1. A single shared `FastAPI(...)` app is created in that module.
2. The current code does not override `app.openapi()`.
3. The current code does not define custom `docs_url`, `redoc_url`, or `openapi_url`.
4. This means FastAPI's default schema generation is the current source of truth.

In practical terms:

- `GET /docs` is the interactive Swagger UI.
- `GET /openapi.json` is generated automatically by FastAPI.
- There is no separate handwritten OpenAPI file to update.

## 2. Current Route Shape

Schema-visible API routes currently include:

- `GET /health`
- `POST /threads`
- `GET /threads/search`
- `POST /threads/{thread_id}/runs/stream`
- `POST /runs/stream`

Browser-facing routes such as `/` and `/login` are intentionally marked with `include_in_schema=False`, so they do not appear in the public API schema.

If no static index page is present, the root handler redirects to `/docs`.

## 3. How OpenAPI Updates Happen

OLAV currently uses FastAPI's automatic schema generation model.

That means OpenAPI is updated by changing Python code in the API layer:

1. Add or modify request/response models.
2. Add or modify route decorators on the shared `app` object.
3. Restart the API server.
4. Re-check `/docs` and `/openapi.json`.

There is no separate "regenerate spec" step today.

## 4. Update Rules

When changing the API layer, follow these rules:

### Rule 1: Keep the shared app authoritative

If routes are later split across modules, they should still be mounted into the same shared FastAPI application so there is only one OpenAPI document.

### Rule 2: Use typed models for schema-visible endpoints

If an endpoint is part of the public API surface, prefer explicit Pydantic request models and typed responses so the generated schema is stable and readable.

### Rule 3: Hide browser/session endpoints from public schema

Routes that exist only for local browser login or UI bootstrap should continue to use `include_in_schema=False` unless there is a clear reason to expose them.

### Rule 4: Keep auth behavior aligned with the schema

Schema-visible API endpoints should continue to use the bearer-token dependency model, while login/session helpers remain browser-oriented.

### Rule 5: Treat `/openapi.json` as generated output

Do not hand-maintain a separate checked-in OpenAPI file unless the platform explicitly introduces an export/build step later.

## 5. Practical Change Checklist

When adding a new API endpoint:

1. Add or update the Pydantic models in `server.py` or the future API module.
2. Register the route on the shared FastAPI app.
3. Decide whether the route belongs in the schema.
4. Re-check auth dependency usage.
5. Start the API server and verify `/docs` renders correctly.
6. Confirm the new endpoint appears correctly in `/openapi.json`.

## 6. What This Document Does Not Claim

This document does not claim that OLAV already has:

1. A multi-file router package with formal API versioning.
2. A separate checked-in OpenAPI release artifact.
3. A full external API compatibility policy.

Those are valid future improvements, but they are not the current maintenance model.

## 7. Related Docs

- [02_QUICK_START.md](./02_QUICK_START.md)
- [03_CORE_CONCEPTS.md](./03_CORE_CONCEPTS.md)
- [08_AGENT_SKILL_REGISTRATION.md](./08_AGENT_SKILL_REGISTRATION.md)
- [09_EXTENSION_LIFECYCLE.md](./09_EXTENSION_LIFECYCLE.md)