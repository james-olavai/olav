"""TDD — GAP-03: DockerComposeBackend + LifecycleManager."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ── DockerComposeBackend ──────────────────────────────────────────────────────


class TestDockerComposeBackend:
    def test_start_runs_docker_compose_up(self, tmp_path):
        """start() runs docker compose up -d in compose_file's directory."""
        from olav.platform.execution.docker_compose import DockerComposeBackend
        b = DockerComposeBackend(compose_file=str(tmp_path / "docker-compose.yml"))

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            b.start()

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "docker" in args
        assert "compose" in args
        assert "up" in args
        assert "-d" in args

    def test_stop_runs_docker_compose_down(self, tmp_path):
        """stop() runs docker compose down."""
        from olav.platform.execution.docker_compose import DockerComposeBackend
        b = DockerComposeBackend(compose_file=str(tmp_path / "docker-compose.yml"))

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            b.stop()

        args = mock_run.call_args[0][0]
        assert "down" in args

    def test_is_healthy_returns_true_when_all_containers_running(self, tmp_path):
        """is_healthy() returns True when docker compose ps shows all running."""
        from olav.platform.execution.docker_compose import DockerComposeBackend
        b = DockerComposeBackend(compose_file=str(tmp_path / "docker-compose.yml"))

        running_output = "NAME\tSTATUS\nnetbox\trunning\npostgres\trunning\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=running_output, stderr=""
            )
            result = b.is_healthy()

        assert result is True

    def test_is_healthy_returns_false_when_container_not_running(self, tmp_path):
        """is_healthy() returns False when any container is not running."""
        from olav.platform.execution.docker_compose import DockerComposeBackend
        b = DockerComposeBackend(compose_file=str(tmp_path / "docker-compose.yml"))

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
            result = b.is_healthy()

        assert result is False

    def test_is_healthy_returns_false_when_exited_in_output(self, tmp_path):
        """is_healthy() returns False when output contains 'exited'."""
        from olav.platform.execution.docker_compose import DockerComposeBackend
        b = DockerComposeBackend(compose_file=str(tmp_path / "docker-compose.yml"))

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="netbox\texited (1)\n", stderr=""
            )
            result = b.is_healthy()

        assert result is False


# ── LifecycleManager ──────────────────────────────────────────────────────────


class TestLifecycleManager:
    def test_initial_state_is_unknown(self, tmp_path):
        """Fresh LifecycleManager starts in UNKNOWN state."""
        from olav.platform.services.lifecycle import LifecycleManager, ServiceState
        mgr = LifecycleManager("netbox", compose_file=str(tmp_path / "docker-compose.yml"))
        assert mgr.state == ServiceState.UNKNOWN

    def test_health_check_sets_healthy_when_running(self, tmp_path):
        """health_check() transitions to HEALTHY when backend reports healthy."""
        from olav.platform.services.lifecycle import LifecycleManager, ServiceState
        from olav.platform.execution.docker_compose import DockerComposeBackend

        mock_backend = MagicMock(spec=DockerComposeBackend)
        mock_backend.is_healthy.return_value = True

        mgr = LifecycleManager("netbox", backend=mock_backend)
        mgr.health_check()

        assert mgr.state == ServiceState.HEALTHY

    def test_health_check_sets_stopped_when_not_running(self, tmp_path):
        """health_check() transitions to STOPPED when backend is not healthy."""
        from olav.platform.services.lifecycle import LifecycleManager, ServiceState
        from olav.platform.execution.docker_compose import DockerComposeBackend

        mock_backend = MagicMock(spec=DockerComposeBackend)
        mock_backend.is_healthy.return_value = False

        mgr = LifecycleManager("netbox", backend=mock_backend)
        mgr.health_check()

        assert mgr.state == ServiceState.STOPPED

    def test_start_calls_backend_start_and_transitions(self, tmp_path):
        """start() calls backend.start() and moves to STARTING."""
        from olav.platform.services.lifecycle import LifecycleManager, ServiceState
        from olav.platform.execution.docker_compose import DockerComposeBackend

        mock_backend = MagicMock(spec=DockerComposeBackend)
        mock_backend.is_healthy.return_value = False

        mgr = LifecycleManager("netbox", backend=mock_backend)
        mgr.start()

        mock_backend.start.assert_called_once()
        assert mgr.state in (ServiceState.STARTING, ServiceState.HEALTHY)

    def test_wait_healthy_returns_true_when_already_healthy(self, tmp_path):
        """wait_healthy() returns immediately if backend is already healthy."""
        from olav.platform.services.lifecycle import LifecycleManager, ServiceState
        from olav.platform.execution.docker_compose import DockerComposeBackend

        mock_backend = MagicMock(spec=DockerComposeBackend)
        mock_backend.is_healthy.return_value = True

        mgr = LifecycleManager("netbox", backend=mock_backend)
        result = mgr.wait_healthy(timeout=5, poll_interval=0.1)

        assert result["healthy"] is True
        assert result["state"] == ServiceState.HEALTHY.value

    def test_wait_healthy_starts_and_waits_when_stopped(self, tmp_path):
        """wait_healthy() auto-starts stopped service and polls until healthy."""
        from olav.platform.services.lifecycle import LifecycleManager, ServiceState
        from olav.platform.execution.docker_compose import DockerComposeBackend

        mock_backend = MagicMock(spec=DockerComposeBackend)
        # First 2 checks return False, then True
        mock_backend.is_healthy.side_effect = [False, False, True]

        mgr = LifecycleManager("netbox", backend=mock_backend)
        result = mgr.wait_healthy(timeout=10, poll_interval=0.01)

        assert result["healthy"] is True
        mock_backend.start.assert_called_once()

    def test_wait_healthy_returns_false_on_timeout(self, tmp_path):
        """wait_healthy() returns healthy=False if timeout expires."""
        from olav.platform.services.lifecycle import LifecycleManager, ServiceState
        from olav.platform.execution.docker_compose import DockerComposeBackend

        mock_backend = MagicMock(spec=DockerComposeBackend)
        mock_backend.is_healthy.return_value = False

        mgr = LifecycleManager("netbox", backend=mock_backend)
        result = mgr.wait_healthy(timeout=0.05, poll_interval=0.01)

        assert result["healthy"] is False

    def test_get_logs_returns_string(self, tmp_path):
        """get_logs() returns container log output as string."""
        from olav.platform.services.lifecycle import LifecycleManager
        from olav.platform.execution.docker_compose import DockerComposeBackend

        mock_backend = MagicMock(spec=DockerComposeBackend)
        mock_backend.get_logs.return_value = "Starting netbox...\nReady.\n"

        mgr = LifecycleManager("netbox", backend=mock_backend)
        logs = mgr.get_logs()

        assert "Starting netbox" in logs


# ── GAP-08: registry register retry ──────────────────────────────────────────


class TestRegistryRegisterRetry:
    def test_register_service_retries_on_schema_fetch_failure(self, tmp_path, monkeypatch):
        """GAP-08: register_service retries schema fetch when server returns 5xx."""
        monkeypatch.chdir(tmp_path)

        call_count = {"n": 0}

        def fake_fetch(url, **kwargs):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ConnectionError("server not ready")
            return {"openapi": "3.0", "paths": {}, "info": {"title": "t", "version": "1"}}

        with patch(
            "olav.platform.services.tool_generator._fetch_openapi_schema",
            side_effect=fake_fetch,
        ), patch(
            "olav.platform.services.tool_generator._discover_schema_url",
            return_value="http://localhost:8000/api/schema/",
        ):
            from olav.platform.services.tool_generator import register_service
            from olav.platform.services.registry import ServiceRegistry, ServiceConfig

            mock_svc = MagicMock(spec=ServiceConfig)
            mock_svc.schema_url = "http://localhost:8000/api/schema/"
            mock_svc.tool_generation = MagicMock()
            mock_svc.tool_generation.groups = []

            with patch.object(ServiceRegistry, "get", return_value=mock_svc):
                with patch("olav.platform.services.tool_generator._store_schema"):
                    result = register_service(
                        "testservice",
                        max_retries=3,
                        retry_delay=0.01,
                    )

        assert call_count["n"] == 3
        assert result.get("status") in ("ok", "success", "registered") or "error" not in str(result).lower()

    def test_register_service_fails_after_max_retries(self, tmp_path, monkeypatch):
        """GAP-08: register_service returns error after exhausting retries."""
        monkeypatch.chdir(tmp_path)

        with patch(
            "olav.platform.services.tool_generator._fetch_openapi_schema",
            side_effect=ConnectionError("always fails"),
        ):
            from olav.platform.services.tool_generator import register_service
            from olav.platform.services.registry import ServiceRegistry, ServiceConfig

            mock_svc = MagicMock(spec=ServiceConfig)
            mock_svc.schema_url = "http://localhost:8000/api/schema/"
            mock_svc.tool_generation = MagicMock()
            mock_svc.tool_generation.groups = []

            with patch.object(ServiceRegistry, "get", return_value=mock_svc):
                result = register_service(
                    "testservice",
                    max_retries=2,
                    retry_delay=0.01,
                )

        assert "error" in str(result).lower() or result.get("status") == "error"
