"""Two OLAV deployments on one machine must not share a compose project.

`deploy_service` runs ``docker compose`` with ``<OLAV_HOME>/.olav/services/<name>``
as the cwd, so compose derives the project from the directory basename: every
deployment gets project ``batfish`` and container ``batfish-batfish-1``. Observed
on the test VM (dev_docs/115 §1i) — ``docker compose up -d`` from ``~/olav-test``
restarted the container owned by ``~/olav``.

The naming has to be adaptive, not unconditional: renaming the project of an
already-running service orphans its containers (``down`` misses them, ``up``
fights them for host ports). These tests pin both halves.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from olav.platform.services import compose_project as cp


@pytest.fixture(autouse=True)
def _clear_cache():
    cp._CACHE.clear()
    yield
    cp._CACHE.clear()


class TestDefaultProjectName:
    """Must match what docker itself would derive, or the ownership check
    looks for the wrong project."""

    def test_plain_name(self):
        assert cp.default_project_name(Path("/home/u/.olav/services/batfish")) == "batfish"

    def test_lowercased_and_stripped_of_invalid_chars(self):
        assert cp.default_project_name(Path("/a/My_Svc.1")) == "my_svc1"

    def test_leading_non_alphanumerics_dropped(self):
        assert cp.default_project_name(Path("/a/_-weird")) == "weird"

    def test_unusable_name_falls_back(self):
        assert cp.default_project_name(Path("/a/...")) == "default"


class TestAdaptiveNaming:
    def test_namespaces_when_legacy_project_is_not_ours(self, monkeypatch):
        monkeypatch.setattr(cp, "_default_project_is_ours", lambda d, l: False)
        name = cp.compose_project_name(Path("/tmp/depA/.olav/services/batfish"))
        assert name is not None and name.startswith("batfish-")

    def test_distinct_deployments_get_distinct_projects(self, monkeypatch):
        monkeypatch.setattr(cp, "_default_project_is_ours", lambda d, l: False)
        a = cp.compose_project_name(Path("/tmp/depA/.olav/services/batfish"))
        b = cp.compose_project_name(Path("/tmp/depB/.olav/services/batfish"))
        assert a != b, "this collision is the whole defect"

    def test_same_deployment_and_service_is_stable(self, monkeypatch):
        monkeypatch.setattr(cp, "_default_project_is_ours", lambda d, l: False)
        p = Path("/tmp/depA/.olav/services/batfish")
        first = cp.compose_project_name(p)
        cp._CACHE.clear()
        assert cp.compose_project_name(p) == first, (
            "an unstable name would strand containers between up and down"
        )

    def test_services_in_one_deployment_stay_separate(self, monkeypatch):
        monkeypatch.setattr(cp, "_default_project_is_ours", lambda d, l: False)
        bf = cp.compose_project_name(Path("/tmp/dep/.olav/services/batfish"))
        nb = cp.compose_project_name(Path("/tmp/dep/.olav/services/netbox"))
        assert bf != nb

    def test_keeps_legacy_when_the_containers_are_already_ours(self, monkeypatch):
        """Existing installs must not have their project renamed underneath them."""
        monkeypatch.setattr(cp, "_default_project_is_ours", lambda d, l: True)
        assert cp.compose_project_name(Path("/tmp/dep/.olav/services/batfish")) is None

    def test_docker_unavailable_changes_nothing(self, monkeypatch):
        """None from the probe means "cannot tell" — never rename on a guess."""
        monkeypatch.setattr(cp, "_default_project_is_ours", lambda d, l: None)
        p = Path("/tmp/dep/.olav/services/batfish")
        assert cp.compose_project_name(p) is None
        assert cp.compose_argv(p) == ["docker", "compose"]

    def test_argv_carries_the_project_flag(self, monkeypatch):
        monkeypatch.setattr(cp, "_default_project_is_ours", lambda d, l: False)
        argv = cp.compose_argv(Path("/tmp/dep/.olav/services/batfish"))
        assert argv[:3] == ["docker", "compose", "-p"]
        assert argv[3].startswith("batfish-")


class TestOwnershipProbe:
    """The probe decides whether renaming is safe, so its parsing matters."""

    @staticmethod
    def _fake_run(stdout: str, returncode: int = 0):
        class _P:
            pass

        p = _P()
        p.stdout = stdout
        p.returncode = returncode
        return lambda *a, **k: p

    def test_no_containers_means_safe_to_namespace(self, monkeypatch):
        monkeypatch.setattr(cp.subprocess, "run", self._fake_run(""))
        assert cp._default_project_is_ours(Path("/tmp/dep/.olav/services/batfish"), "batfish") is False

    def test_containers_owned_by_another_deployment(self, monkeypatch):
        monkeypatch.setattr(
            cp.subprocess, "run", self._fake_run("/home/olav/olav/.olav/services/batfish\n")
        )
        assert (
            cp._default_project_is_ours(Path("/home/olav/olav-test/.olav/services/batfish"), "batfish")
            is False
        ), "the VM case — must not adopt another deployment's project"

    def test_containers_owned_by_us(self, monkeypatch):
        mine = "/home/olav/olav/.olav/services/batfish"
        monkeypatch.setattr(cp.subprocess, "run", self._fake_run(mine + "\n"))
        assert cp._default_project_is_ours(Path(mine), "batfish") is True

    def test_docker_failure_is_inconclusive(self, monkeypatch):
        monkeypatch.setattr(cp.subprocess, "run", self._fake_run("", returncode=1))
        assert cp._default_project_is_ours(Path("/tmp/x"), "batfish") is None

    def test_docker_missing_is_inconclusive(self, monkeypatch):
        def _boom(*a, **k):
            raise FileNotFoundError("docker")

        monkeypatch.setattr(cp.subprocess, "run", _boom)
        assert cp._default_project_is_ours(Path("/tmp/x"), "batfish") is None
