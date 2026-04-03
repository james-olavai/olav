# 后台服务

OLAV 提供三个可选的后台服务，分别解决不同场景的需求。CLI 本身无需后台服务即可工作，但这些服务能大幅提升团队协作和使用体验。

!!! abstract "功能声明"
    | ID | 声明 | 状态 |
    |----|------|------|
    | C-L2-16 | `olav service web start` 启动 Web 界面 + REST API | ✅ v0.10.0 |
    | C-L2-17 | `olav service daemon start` 常驻进程加速 CLI | ✅ v0.10.0 |
    | C-L2-18 | `olav service logs start` 接收 Syslog 并存入 DuckDB | ✅ v0.10.0 |
    | C-L2-41 | `olav service status/start --all/stop --all` 批量管理 | ✅ v0.10.0 |

---

## 三个服务概览

| 服务 | 功能 | 默认端口 | 典型场景 |
|------|------|---------|---------|
| `web` | Web 界面 + REST API | `2280` | 浏览器访问、团队共享、CI/CD 集成 |
| `daemon` | 常驻进程，加速 CLI 响应 | Unix socket | 频繁使用 CLI、开发测试 |
| `logs` | Syslog 接收器 | `5514` UDP | 接收网络设备日志 |

---

## 服务管理

所有服务通过统一的命令管理：

```bash
# 启动
olav service web start
olav service daemon start
olav service logs start
olav service start --all          # 全部启动

# 停止
olav service web stop
olav service stop --all           # 全部停止

# 查看状态
olav service status

# 查看日志
olav service web logs
olav service logs logs --tail 100
```

---

## Web 服务

启动后提供浏览器可访问的 Web 界面和 REST API：

```bash
olav service web start                              # 默认 0.0.0.0:2280
olav service web start --host 127.0.0.1 --port 8080 # 自定义地址
```

浏览器访问 `http://localhost:2280` 即可使用与 CLI 完全相同的 Agent 能力，支持实时流式响应（SSE）。

### 适用场景

| 场景 | 说明 |
|------|------|
| **团队共享** | 一个 OLAV 实例，全团队通过浏览器使用 |
| **CI/CD 集成** | 从流水线通过 REST API 调用 OLAV（详见 [HTTP API 参考](../reference/http-api.md)） |
| **自定义前端** | 基于 SSE 流式 API 构建你自己的 UI |

---

## Daemon 服务（加速 CLI）

每次运行 `olav "..."` 都会启动一个新进程、加载 Agent——这需要 3-5 秒冷启动。Daemon 服务将 Agent 预加载到内存中，通过 Unix socket 通信，后续查询近乎即时响应。

```bash
olav service daemon start
```

启动后，CLI 会自动检测 daemon 并通过它处理查询，你不需要改变任何使用习惯。

### 什么时候该用 Daemon？

- 你频繁使用 CLI，每次 3-5 秒的等待影响效率
- OLAV 部署在长期运行的服务器上
- 你在开发和调试过程中需要快速迭代

---

## Syslog 接收服务

接收网络设备发送的 Syslog 消息（支持 RFC 3164 和 RFC 5424），存入 DuckDB 供查询：

```bash
olav service logs start                    # 默认 UDP 5514
olav service logs start --port 5514        # 自定义端口
olav service logs start --flush-interval 30 # 刷新间隔（秒，默认 60）
```

将网络设备的 Syslog 目标配置为 `<olav-host>:5514`，日志即可自动入库。

入库后用自然语言查询：

```bash
olav "最近一小时有哪些 syslog 错误？"
olav "今天哪些设备发送了最多的 syslog 消息？"
```

!!! note "搭配 olav-netops 效果更佳"
    Syslog 接收器搭配 `olav-netops` 扩展使用时，能提供更丰富的网络设备日志解析和关联分析。

---

## 运行时文件

| 服务 | PID 文件 | 日志文件 |
|------|---------|---------|
| `web` | `.olav/run/web.pid` | `.olav/logs/web.log` |
| `daemon` | `.olav/run/daemon.pid` | `.olav/logs/daemon.log` |
| `logs` | `.olav/run/syslog_receiver.pid` | `.olav/logs/syslog_receiver.log` |

---

## 生产环境部署

在生产环境中，建议使用 systemd 或 supervisor 管理服务，而不是 `olav service start`：

```bash
# 直接运行 Web 服务
uvicorn olav.api.server:app --host 0.0.0.0 --port 2280
```

环境变量：

```bash
OLAV_WEB_PORT=2280
OLAV_WEB_HOST=0.0.0.0
```
