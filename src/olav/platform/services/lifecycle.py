"""LifecycleManager — service health, start, and wait_healthy.

Part of M5 Service Lifecycle Management (dev_docs/16 §7).

State machine:
  UNKNOWN → health_check() → HEALTHY | STOPPED
  STOPPED → start()        → STARTING
  STARTING → health_check() → HEALTHY | DEGRADED
  HEALTHY  → health_check() → HEALTHY | DEGRADED
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ServiceState(str, Enum):
    UNKNOWN = "unknown"
    STOPPED = "stopped"
    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"


@dataclass
class LifecycleManager:
    """Manage a service's container lifecycle via a backend.

    Parameters
    ----------
    service_name:
        Human-readable name used in log messages.
    compose_file:
        Path to docker-compose.yml — used to auto-create a
        DockerComposeBackend when no explicit ``backend`` is given.
    backend:
        Any object with ``start()``, ``stop()``, ``is_healthy()``,
        ``get_logs()`` methods. Defaults to DockerComposeBackend.
    """

    service_name: str
    compose_file: str | None = None
    backend: Any = field(default=None, repr=False)
    state: ServiceState = field(default=ServiceState.UNKNOWN, init=False)

    def __post_init__(self) -> None:
        if self.backend is None:
            if self.compose_file is None:
                raise ValueError("Either compose_file or backend must be provided.")
            from olav.platform.execution.docker_compose import DockerComposeBackend
            self.backend = DockerComposeBackend(self.compose_file)

    # ── state transitions ─────────────────────────────────────────────────────

    def health_check(self) -> ServiceState:
        """Check backend health and update state."""
        try:
            healthy = self.backend.is_healthy()
        except Exception as exc:
            logger.warning("%s health_check failed: %s", self.service_name, exc)
            self.state = ServiceState.DEGRADED
            return self.state

        self.state = ServiceState.HEALTHY if healthy else ServiceState.STOPPED
        return self.state

    def start(self) -> None:
        """Start the service backend and transition to STARTING."""
        logger.info("Starting service: %s", self.service_name)
        try:
            self.backend.start()
            self.state = ServiceState.STARTING
        except Exception as exc:
            logger.error("Failed to start %s: %s", self.service_name, exc)
            self.state = ServiceState.DEGRADED

    def stop(self) -> None:
        """Stop the service backend."""
        logger.info("Stopping service: %s", self.service_name)
        self.backend.stop()
        self.state = ServiceState.STOPPED

    def get_logs(self, tail: int = 50) -> str:
        """Return recent log output."""
        try:
            return self.backend.get_logs(tail=tail)
        except Exception as exc:
            return f"Could not retrieve logs: {exc}"

    # ── wait_healthy ──────────────────────────────────────────────────────────

    def wait_healthy(
        self,
        timeout: float = 120,
        poll_interval: float = 5,
    ) -> dict[str, Any]:
        """Wait until the service is healthy, auto-starting if stopped.

        Parameters
        ----------
        timeout:
            Maximum seconds to wait.
        poll_interval:
            Seconds between health checks.

        Returns
        -------
        dict with keys:
          healthy (bool), state (str), elapsed (float), message (str)
        """
        deadline = time.monotonic() + timeout
        started = False

        while time.monotonic() < deadline:
            current = self.health_check()

            if current == ServiceState.HEALTHY:
                elapsed = timeout - (deadline - time.monotonic())
                return {
                    "healthy": True,
                    "state": current.value,
                    "elapsed": round(elapsed, 1),
                    "message": f"{self.service_name} is healthy",
                }

            if current == ServiceState.STOPPED and not started:
                self.start()
                started = True

            time.sleep(poll_interval)

        # Timed out
        return {
            "healthy": False,
            "state": self.state.value,
            "elapsed": timeout,
            "message": (
                f"{self.service_name} did not become healthy within {timeout}s. "
                f"Last state: {self.state.value}. "
                "Check logs with get_logs()."
            ),
        }
