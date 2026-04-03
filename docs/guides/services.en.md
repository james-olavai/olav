# Background Services

OLAV provides three optional background services, each addressing different use cases. The CLI itself works without any background services, but these services can significantly improve team collaboration and the overall experience.

!!! abstract "Feature Claims"
    | ID | Claim | Status |
    |----|-------|--------|
    | C-L2-16 | `olav service web start` launches Web UI + REST API | ✅ v0.10.0 |
    | C-L2-17 | `olav service daemon start` resident process accelerates CLI | ✅ v0.10.0 |
    | C-L2-18 | `olav service logs start` receives Syslog and stores it in DuckDB | ✅ v0.10.0 |
    | C-L2-41 | `olav service status/start --all/stop --all` batch management | ✅ v0.10.0 |

---

## Three Services at a Glance

| Service | Function | Default Port | Typical Use Case |
|---------|----------|-------------|-----------------|
| `web` | Web UI + REST API | `2280` | Browser access, team sharing, CI/CD integration |
| `daemon` | Resident process, accelerates CLI responses | Unix socket | Frequent CLI usage, development and testing |
| `logs` | Syslog receiver | `5514` UDP | Receiving network device logs |

---

## Service Management

All services are managed through a unified command interface:

```bash
# Start
olav service web start
olav service daemon start
olav service logs start
olav service start --all          # Start all

# Stop
olav service web stop
olav service stop --all           # Stop all

# Check status
olav service status

# View logs
olav service web logs
olav service logs logs --tail 100
```

---

## Web Service

Once started, it provides a browser-accessible Web UI and REST API:

```bash
olav service web start                              # Default 0.0.0.0:2280
olav service web start --host 127.0.0.1 --port 8080 # Custom address
```

Open `http://localhost:2280` in your browser to access the same Agent capabilities as the CLI, with real-time streaming responses (SSE).

### Use Cases

| Scenario | Description |
|----------|-------------|
| **Team Sharing** | A single OLAV instance shared by the entire team via browser |
| **CI/CD Integration** | Call OLAV from pipelines via REST API (see [HTTP API Reference](../reference/http-api.md)) |
| **Custom Frontend** | Build your own UI on top of the SSE streaming API |

---

## Daemon Service (CLI Acceleration)

Each time you run `olav "..."`, a new process is started and the Agent is loaded — this requires a 3-5 second cold start. The daemon service pre-loads the Agent into memory and communicates via Unix socket, making subsequent queries respond almost instantly.

```bash
olav service daemon start
```

Once started, the CLI automatically detects the daemon and routes queries through it. You don't need to change any of your usage habits.

### When Should You Use the Daemon?

- You use the CLI frequently and the 3-5 second wait impacts your efficiency
- OLAV is deployed on a long-running server
- You need fast iteration during development and debugging

---

## Syslog Receiver Service

Receives Syslog messages sent by network devices (supports RFC 3164 and RFC 5424) and stores them in DuckDB for querying:

```bash
olav service logs start                    # Default UDP 5514
olav service logs start --port 5514        # Custom port
olav service logs start --flush-interval 30 # Flush interval (seconds, default 60)
```

Configure the Syslog destination on your network devices to `<olav-host>:5514`, and logs will be automatically ingested.

Once ingested, query with natural language:

```bash
olav "最近一小时有哪些 syslog 错误？"
olav "今天哪些设备发送了最多的 syslog 消息？"
```

!!! note "Works even better with olav-netops"
    When paired with the `olav-netops` extension, the Syslog receiver provides richer network device log parsing and correlation analysis.

---

## Runtime Files

| Service | PID File | Log File |
|---------|----------|----------|
| `web` | `.olav/run/web.pid` | `.olav/logs/web.log` |
| `daemon` | `.olav/run/daemon.pid` | `.olav/logs/daemon.log` |
| `logs` | `.olav/run/syslog_receiver.pid` | `.olav/logs/syslog_receiver.log` |

---

## Production Deployment

In production environments, it is recommended to use systemd or supervisor to manage services instead of `olav service start`:

```bash
# Run the Web service directly
uvicorn olav.api.server:app --host 0.0.0.0 --port 2280
```

Environment variables:

```bash
OLAV_WEB_PORT=2280
OLAV_WEB_HOST=0.0.0.0
```
