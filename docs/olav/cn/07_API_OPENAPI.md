# OLAV API 与 OpenAPI

本文档说明当前平台层 API 的维护方式，以及 OpenAPI 在现状下如何更新。

这里描述的是当前已经实现的模型，不预设未来的 router 拆分形态。

## 1. 当前权威来源

当前 FastAPI 应用的权威入口在 `src/olav/api/server.py`。

当前实现事实：

1. 平台只在这个模块里创建了一个共享的 `FastAPI(...)` 应用。
2. 当前代码没有自定义 `app.openapi()`。
3. 当前代码没有设置自定义的 `docs_url`、`redoc_url` 或 `openapi_url`。
4. 因此，FastAPI 默认生成的 schema 就是当前权威来源。

落到实际行为上就是：

- `GET /docs` 是交互式 Swagger UI。
- `GET /openapi.json` 由 FastAPI 自动生成。
- 当前没有单独维护的手写 OpenAPI 文件。

## 2. 当前路由结构

当前会进入 schema 的 API 路由包括：

- `GET /health`
- `POST /threads`
- `GET /threads/search`
- `POST /threads/{thread_id}/runs/stream`
- `POST /runs/stream`

像 `/` 和 `/login` 这样的浏览器入口路由，当前明确使用了 `include_in_schema=False`，因此不会进入公开 API schema。

如果没有静态首页，根路由会回退重定向到 `/docs`。

## 3. OpenAPI 如何更新

OLAV 当前使用的是 FastAPI 自动生成 schema 的模式。

这意味着 OpenAPI 的更新来自 API Python 代码本身：

1. 新增或修改请求/响应模型。
2. 在共享 `app` 对象上新增或修改路由装饰器。
3. 重启 API 服务。
4. 重新检查 `/docs` 和 `/openapi.json`。

当前不存在单独的“重新生成 spec 文件”步骤。

## 4. 维护规则

当你修改 API 层时，建议遵循以下规则：

### 规则 1：共享 app 仍然是唯一权威

如果未来把路由拆到多个模块，仍应统一挂载到同一个 FastAPI 应用上，避免出现多份 OpenAPI 真相。

### 规则 2：公开接口尽量使用显式类型模型

如果某个接口属于公开 API 面，优先使用明确的 Pydantic 请求模型和类型化响应，这样生成出来的 schema 更稳定、更可读。

### 规则 3：浏览器/会话辅助接口不要默认暴露到 schema

只用于本地浏览器登录、session 建立或 UI 引导的路由，应继续使用 `include_in_schema=False`，除非平台明确决定把它们纳入公开 API。

### 规则 4：鉴权行为要和 schema 一致

进入 schema 的 API 路由应继续保持 Bearer token 依赖；浏览器登录与 session 辅助路由仍然保持本地 WebUI 语义。

### 规则 5：把 `/openapi.json` 当成生成结果，不是手写资产

除非未来平台引入专门的 export/build 流程，否则不要再维护一份独立提交的 OpenAPI 文件。

## 5. 实际变更检查单

当你新增一个 API endpoint 时：

1. 先在 `server.py` 或未来的 API 模块里补充 Pydantic 模型。
2. 把路由注册到共享 FastAPI app。
3. 明确判断这个路由是否应该进入 schema。
4. 检查鉴权依赖是否正确。
5. 启动 API 服务并确认 `/docs` 可以正常渲染。
6. 检查 `/openapi.json` 中是否出现了正确的新接口定义。

## 6. 本文档不宣称的内容

本文档不宣称 OLAV 现在已经具备：

1. 多文件 router 包与正式 API 版本化体系。
2. 单独提交和发布的 OpenAPI 制品。
3. 完整的外部 API 兼容性承诺。

这些都可以是后续能力，但不是当前的维护模型。

## 7. 相关文档

- [02_QUICK_START.md](./02_QUICK_START.md)
- [03_CORE_CONCEPTS.md](./03_CORE_CONCEPTS.md)
- [08_AGENT_SKILL_REGISTRATION.md](./08_AGENT_SKILL_REGISTRATION.md)
- [09_EXTENSION_LIFECYCLE.md](./09_EXTENSION_LIFECYCLE.md)