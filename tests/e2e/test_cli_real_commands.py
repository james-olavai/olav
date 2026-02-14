"""
真实 CLI 命令 E2E 测试 - 符合 2026-02-14 审计标准

这个测试文件测试用户实际使用的命令，不是 Python API。

测试方法：
- 使用 subprocess 调用真实的 CLI 命令
- 测试所有 pyproject.toml 中定义的入口点
- 验证输出正确性，不只是检查退出码

运行：
    uv run pytest tests/e2e/test_cli_real_commands.py -v -s

要求：
    - 必须在项目根目录运行
    - 需要 .env 配置（部分测试）
"""

import subprocess
import sys
import os
from pathlib import Path
import pytest
import time

PROJECT_ROOT = Path(__file__).parent.parent.parent
CLI_TIMEOUT = 30  # 30 seconds for LLM commands
ADMIN_TIMEOUT = 5  # 5 seconds for non-LLM commands


class TestCLIRealCommands:
    """测试真实的 CLI 命令（subprocess）"""

    def run_cli(self, *args, timeout=ADMIN_TIMEOUT, check=True):
        """运行 uv run olav 命令并返回结果"""
        cmd = ["uv", "run", "olav"] + list(args)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=PROJECT_ROOT
        )
        
        if check and result.returncode != 0:
            print(f"\n❌ Command failed: {' '.join(cmd)}")
            print(f"STDOUT:\n{result.stdout}")
            print(f"STDERR:\n{result.stderr}")
            
        return result

    def test_olav_no_args(self):
        """测试：olav 无参数应显示帮助"""
        result = self.run_cli(check=False)
        
        # Typer 在 no_args_is_help=True 时返回 2
        assert result.returncode in [0, 2], \
            f"olav without args failed unexpectedly: {result.stderr}"
        
        # 应显示 Usage 信息
        output = result.stdout + result.stderr
        assert "Usage:" in output, "Missing usage information"
        assert "Commands:" in output or "commands" in output.lower(), \
            "Missing commands list"
        
        # 应列出主要命令
        assert "ask" in output.lower(), "Missing 'ask' command"
        assert "admin" in output.lower(), "Missing 'admin' command"
        assert "devices" in output.lower(), "Missing 'devices' command"
        
        print(f"✅ olav (no args) 显示帮助正常")

    def test_olav_help(self):
        """测试：olav --help 显示帮助信息"""
        result = self.run_cli("--help")
        
        assert result.returncode == 0, f"olav --help failed: {result.stderr}"
        assert "OLAV" in result.stdout, "Missing OLAV in help"
        assert "ask" in result.stdout, "Missing 'ask' command"
        assert "admin" in result.stdout, "Missing 'admin' command"
        assert "devices" in result.stdout, "Missing 'devices' command"
        
        print(f"✅ olav --help 工作正常")

    def test_olav_version(self):
        """测试：olav --version 显示版本"""
        result = self.run_cli("--version")
        
        assert result.returncode == 0, f"olav --version failed: {result.stderr}"
        # Version info might be in stdout or stderr
        output = result.stdout + result.stderr
        assert "OLAV" in output or "v2" in output or "version" in output.lower()
        
        print(f"✅ olav --version 工作正常")

    def test_admin_status_no_llm(self):
        """测试：olav admin status（无需 LLM）"""
        result = self.run_cli("admin", "status")
        
        assert result.returncode == 0, f"admin status failed: {result.stderr}"
        
        # 验证输出包含关键信息
        output = result.stdout + result.stderr
        assert "databases" in output.lower() or "database" in output.lower(), \
            "Missing database info"
        
        print(f"✅ olav admin status 工作正常")
        print(f"输出预览:\n{result.stdout[:200]}")

    def test_devices_command(self):
        """测试：olav devices 列出设备"""
        result = self.run_cli("devices")
        
        assert result.returncode == 0, f"devices command failed: {result.stderr}"
        
        # 验证输出
        output = result.stdout + result.stderr
        # Should show device table or device info
        assert "device" in output.lower() or "Device" in output or "设备" in output, \
            "Missing device information"
        
        print(f"✅ olav devices 工作正常")
        print(f"输出预览:\n{result.stdout[:200]}")

    @pytest.mark.skipif(
        not os.getenv("LLM_API_KEY"),
        reason="需要 LLM_API_KEY 才能测试 ask 命令"
    )
    def test_ask_command_simple_query(self):
        """测试：olav ask 简单查询（需要 LLM API）"""
        result = self.run_cli(
            "ask", 
            "What is 2 plus 2?",
            timeout=CLI_TIMEOUT,
            check=False  # Don't raise on error, we want to see the output
        )
        
        # 如果失败，打印详细错误信息
        if result.returncode != 0:
            print(f"\n⚠️ olav ask 命令失败")
            print(f"STDERR:\n{result.stderr}")
            print(f"STDOUT:\n{result.stdout}")
            
            # 检查常见错误
            error_output = result.stderr + result.stdout
            
            if "No module named 'olav.tools'" in error_output:
                pytest.fail("❌ 工具加载路径错误：Agent 期望 'olav.tools' 但实际在 '.olav/tools/'")
            
            if "checkpoint_ns" in error_output:
                pytest.fail("❌ Checkpointer schema 错误：数据库缺少 'checkpoint_ns' 列")
            
            if "API" in error_output and "key" in error_output.lower():
                pytest.skip("API key 配置问题，跳过测试")
            
            # 未知错误
            pytest.fail(f"olav ask 命令失败: {error_output[:500]}")
        
        # 验证成功响应
        output = result.stdout + result.stderr
        # Should contain a response (any response is fine for now)
        assert len(result.stdout) > 10, "Response too short"
        
        print(f"✅ olav ask 工作正常")
        print(f"响应预览:\n{result.stdout[:300]}")

    def test_interactive_help(self):
        """测试：olav interactive --help"""
        result = self.run_cli("interactive", "--help")
        
        assert result.returncode == 0, f"interactive --help failed: {result.stderr}"
        assert "interactive" in result.stdout.lower(), "Missing interactive info"
        
        print(f"✅ olav interactive --help 工作正常")

    def test_all_command_entry_points(self):
        """测试：验证 pyproject.toml 中的所有命令入口点"""
        
        # 读取 pyproject.toml 获取所有脚本
        pyproject_path = PROJECT_ROOT / "pyproject.toml"
        assert pyproject_path.exists(), "pyproject.toml not found"
        
        # Parse scripts section
        scripts = []
        in_scripts = False
        with open(pyproject_path) as f:
            for line in f:
                if "[project.scripts]" in line:
                    in_scripts = True
                    continue
                if in_scripts:
                    if line.strip().startswith("["):
                        break
                    if "=" in line and not line.strip().startswith("#"):
                        script_name = line.split("=")[0].strip()
                        scripts.append(script_name)
        
        print(f"\n📋 发现 {len(scripts)} 个 CLI 入口点: {scripts}")
        
        # 测试每个脚本的 --help
        for script in scripts:
            print(f"\n测试 {script} --help...")
            result = subprocess.run(
                ["uv", "run", script, "--help"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=PROJECT_ROOT
            )
            
            assert result.returncode == 0, \
                f"{script} --help failed: {result.stderr}"
            
            print(f"✅ {script} --help 工作正常")


class TestCLIErrorHandling:
    """测试 CLI 错误处理"""
    
    def run_cli(self, *args, timeout=ADMIN_TIMEOUT):
        """运行命令，不检查返回码"""
        cmd = ["uv", "run", "olav"] + list(args)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=PROJECT_ROOT
        )
        return result

    def test_invalid_command(self):
        """测试：无效命令有友好错误提示"""
        result = self.run_cli("nonexistent-command")
        
        assert result.returncode != 0, "Should fail for invalid command"
        
        error_output = result.stderr + result.stdout
        # Should show error or help message
        assert len(error_output) > 0, "No error message shown"
        
        print(f"✅ 无效命令正确报错")
        print(f"错误提示:\n{error_output[:200]}")

    def test_ask_without_args(self):
        """测试：ask 命令缺少参数时的错误"""
        result = self.run_cli("ask")
        
        assert result.returncode != 0, "Should fail without query argument"
        
        error_output = result.stderr + result.stdout
        # Should show missing argument error
        assert "argument" in error_output.lower() or "required" in error_output.lower(), \
            "Missing argument error not clear"
        
        print(f"✅ ask 命令缺少参数时正确报错")


if __name__ == "__main__":
    # 允许直接运行此文件进行快速测试
    pytest.main([__file__, "-v", "-s"])
