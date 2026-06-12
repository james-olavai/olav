"""Unit tests for olav.platform.execution backends."""

import pytest

from olav.platform.execution import (
    ExecutionBackend,
    ExecutionConfig,
    ExecutionResult,
    LocalBackend,
    SSHBackend,
)


# ── ExecutionResult ───────────────────────────────────────────────────────────

class TestExecutionResult:
    def test_ok_true_on_zero_returncode(self):
        r = ExecutionResult(returncode=0, stdout="hello", stderr="")
        assert r.ok is True

    def test_ok_false_on_nonzero(self):
        r = ExecutionResult(returncode=1, stdout="", stderr="error")
        assert r.ok is False

    def test_output_returns_stdout_on_success(self):
        r = ExecutionResult(returncode=0, stdout="hi", stderr="noise")
        assert r.output == "hi"

    def test_output_returns_stderr_on_failure(self):
        r = ExecutionResult(returncode=1, stdout="", stderr="err msg")
        assert r.output == "err msg"

    def test_str_representation(self):
        r = ExecutionResult(returncode=0, stdout="hello world", stderr="")
        assert "ok" in str(r)
        assert "hello" in str(r)


# ── ExecutionBackend protocol ─────────────────────────────────────────────────

class TestExecutionBackendProtocol:
    def test_local_is_backend(self):
        assert isinstance(LocalBackend(), ExecutionBackend)

    def test_ssh_is_backend(self):
        assert isinstance(SSHBackend(host="localhost"), ExecutionBackend)


# ── LocalBackend ──────────────────────────────────────────────────────────────

class TestLocalBackend:
    def setup_method(self):
        self.backend = LocalBackend()

    def test_is_available(self):
        assert self.backend.is_available() is True

    def test_execute_echo(self):
        result = self.backend.execute("echo hello")
        assert result.ok
        assert "hello" in result.stdout

    def test_execute_with_config(self):
        cfg = ExecutionConfig(timeout=5)
        result = self.backend.execute("echo configured", cfg)
        assert result.ok
        assert "configured" in result.stdout

    def test_execute_failing_command(self):
        result = self.backend.execute("false")
        assert not result.ok
        assert result.returncode != 0

    def test_execute_env_injection(self):
        cfg = ExecutionConfig(env={"MY_TEST_VAR": "hello_from_env"}, shell=True)
        result = self.backend.execute("echo $MY_TEST_VAR", cfg)
        assert result.ok
        assert "hello_from_env" in result.stdout

    def test_execute_timeout(self):
        cfg = ExecutionConfig(timeout=1)
        result = self.backend.execute("sleep 10", cfg)
        assert not result.ok
        assert result.returncode == 124
        assert "timed out" in result.stderr

    def test_execute_nonexistent_command(self):
        result = self.backend.execute("__nonexistent_command_xyz__")
        assert not result.ok
        assert result.returncode == 127

    def test_execute_multiline_output(self):
        result = self.backend.execute("printf 'line1\nline2\nline3'")
        assert result.ok
        assert "line1" in result.stdout
        assert "line3" in result.stdout


# ── SSHBackend (unit, no real SSH) ────────────────────────────────────────────

class TestSSHBackendConstruction:
    def test_default_port(self):
        b = SSHBackend(host="10.0.0.1")
        assert b.port == 22

    def test_custom_port(self):
        b = SSHBackend(host="10.0.0.1", port=2222)
        assert b.port == 2222

    def test_repr_with_user(self):
        b = SSHBackend(host="myhost", user="admin", port=22)
        assert "admin@myhost" in repr(b)

    def test_repr_without_user(self):
        b = SSHBackend(host="myhost")
        assert "myhost" in repr(b)
        assert "@" not in repr(b)

    def test_build_ssh_cmd_basic(self):
        b = SSHBackend(host="192.168.1.1", user="olav")
        cfg = ExecutionConfig()
        cmd = b._build_ssh_cmd("docker ps", cfg)
        assert "ssh" in cmd[0]
        assert "olav@192.168.1.1" in cmd
        assert "docker ps" in cmd

    def test_build_ssh_cmd_with_cwd(self):
        b = SSHBackend(host="10.0.0.1")
        cfg = ExecutionConfig(cwd="/tmp/lab")
        cmd = b._build_ssh_cmd("ls", cfg)
        # Remote command should include cd prefix
        remote_cmd = cmd[-1]
        assert "cd" in remote_cmd
        assert "/tmp/lab" in remote_cmd
        assert "ls" in remote_cmd

    def test_build_ssh_cmd_with_custom_port(self):
        b = SSHBackend(host="10.0.0.1", port=2222)
        cfg = ExecutionConfig()
        cmd = b._build_ssh_cmd("ls", cfg)
        assert "-p" in cmd
        assert "2222" in cmd

    def test_build_ssh_cmd_with_key_file(self):
        b = SSHBackend(host="10.0.0.1", key_file="/home/user/.ssh/id_rsa")
        cfg = ExecutionConfig()
        cmd = b._build_ssh_cmd("ls", cfg)
        assert "-i" in cmd
        assert "/home/user/.ssh/id_rsa" in cmd

    def test_unavailable_on_unreachable_host(self):
        """SSHBackend.is_available() should return False for unreachable hosts."""
        b = SSHBackend(host="192.0.2.1", port=22222)  # TEST-NET, unreachable
        # Should not raise — just return False
        result = b.is_available()
        assert result is False
