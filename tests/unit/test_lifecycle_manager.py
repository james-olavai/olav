"""TDD — GAP-03 DockerComposeBackend + GAP-08 registry register retry.

(LifecycleManager tests removed 2026-06-12 with the dead
olav.platform.services.lifecycle module.)
"""
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
            from olav.platform.services.registry import ServiceRegistry, ServiceConfig, ReferenceGenerationConfig

            mock_svc = MagicMock(spec=ServiceConfig)
            mock_svc.name = "testservice"
            mock_svc.schema_url = "http://localhost:8000/api/schema/"
            mock_svc.tool_generation = MagicMock()
            mock_svc.tool_generation.groups = []
            mock_svc.reference_generation = ReferenceGenerationConfig()
            mock_svc.reference_generation.groups = []

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
