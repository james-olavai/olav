"""DockerComposeBackend — docker compose lifecycle operations.

Part of M5 Service Lifecycle Management.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class DockerComposeBackend:
    """Execute docker compose lifecycle operations for a given compose file."""

    def __init__(self, compose_file: str) -> None:
        self.compose_file = Path(compose_file)
        self._cwd = str(self.compose_file.parent) if self.compose_file.parent != Path(".") else None

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        cmd = ["docker", "compose", "-f", str(self.compose_file), *args]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=self._cwd,
        )

    def start(self) -> subprocess.CompletedProcess:
        """Run docker compose up -d."""
        return self._run("up", "-d")

    def stop(self) -> subprocess.CompletedProcess:
        """Run docker compose down."""
        return self._run("down")

    def is_healthy(self) -> bool:
        """Return True when all services are running (no exited/restarting)."""
        result = self._run("ps", "--format", "table {{.Name}}\t{{.Status}}")
        if result.returncode != 0:
            return False
        output = result.stdout.lower()
        if not output.strip():
            return False
        bad = ("exited", "restarting", "error", "dead", "unhealthy")
        return not any(b in output for b in bad)

    def get_logs(self, service: str = "", tail: int = 50) -> str:
        """Return recent log output from compose services."""
        extra = ["--tail", str(tail)]
        if service:
            extra.append(service)
        result = self._run("logs", *extra)
        return result.stdout or result.stderr
