"""
Admin Agent E2E Tests - 符合 2026-02-15 审计标准

测试 Admin Agent v2.1.0 功能：
1. Fast-path 命令（不需要 LLM）
2. Admin Agent 工具（需要 LLM）
3. CLI 集成测试

运行：
    uv run pytest tests/e2e/test_admin_agent.py -v -s
    uv run pytest tests/e2e/test_admin_agent.py::TestAdminFastPath -v
    uv run pytest tests/e2e/test_admin_agent.py::TestAdminAgentWithLLM -v
    uv run pytest tests/e2e/test_admin_agent.py::TestAdminCLI -v
"""

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
ADMIN_TIMEOUT = 5  # Fast-path commands should be < 1s
LLM_TIMEOUT = 60  # LLM commands can take longer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# Test 1: Fast-Path Commands (No LLM Required) ⚡
# ============================================================================

class TestAdminFastPath:
    """测试 Admin fast-path 命令（<100ms，无 LLM）"""

    @pytest.mark.asyncio
    async def test_admin_status(self):
        """测试 /admin status 命令"""
        from olav.cli.admin import admin_handler
        
        result = await admin_handler("/admin status")
        
        assert result["status"] == "success"
        assert "data" in result
        assert "timestamp" in result["data"]
        assert "databases" in result["data"]
        assert "skills_count" in result["data"]
        assert "tools_count" in result["data"]
        
        logger.info(f"✓ Admin status: {result['data']['skills_count']} skills, {result['data']['tools_count']} tools")

    @pytest.mark.asyncio
    async def test_admin_backup(self):
        """测试 /admin backup 命令"""
        from olav.cli.admin import admin_handler
        
        result = await admin_handler("/admin backup")
        
        assert result["status"] == "success"
        assert "backup_file" in result
        assert "size_mb" in result
        
        # Verify backup file exists
        backup_file = Path(result["backup_file"])
        assert backup_file.exists()
        assert backup_file.suffix == ".gz"
        
        logger.info(f"✓ Backup created: {backup_file.name} ({result['size_mb']} MB)")
        
        # Cleanup
        backup_file.unlink()

    @pytest.mark.asyncio
    async def test_admin_db_info(self):
        """测试 /admin db-info 命令"""
        from olav.cli.admin import admin_handler
        
        result = await admin_handler("/admin db-info")
        
        assert result["status"] == "success"
        assert "databases" in result
        
        # Should have at least main.duckdb
        databases = result["databases"]
        assert len(databases) > 0
        
        logger.info(f"✓ Found {len(databases)} databases")
        for db_name, db_info in databases.items():
            logger.info(f"  - {db_name}: {db_info['size_mb']} MB")

    @pytest.mark.asyncio
    async def test_admin_skill_list(self):
        """测试 /admin skill-list 命令"""
        from olav.cli.admin import admin_handler
        
        result = await admin_handler("/admin skill-list")
        
        assert result["status"] == "success"
        assert "skills" in result
        assert "count" in result
        assert result["count"] > 0
        
        # Should have olav-admin skill
        skill_names = [skill["name"] for skill in result["skills"]]
        assert "olav-admin" in skill_names
        
        logger.info(f"✓ Found {result['count']} skills: {', '.join(skill_names)}")

    @pytest.mark.asyncio
    async def test_admin_restore_error(self):
        """测试 /admin restore 命令（错误情况）"""
        from olav.cli.admin import admin_handler
        
        result = await admin_handler("/admin restore nonexistent.tar.gz")
        
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()
        
        logger.info("✓ Restore error handling works")


# ============================================================================
# Test 2: Admin Agent Tools (LLM Required) 🤖
# ============================================================================

@pytest.fixture
def llm_api_key():
    """检查 LLM API Key 是否存在"""
    key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY")
    if not key:
        pytest.skip("未配置 LLM_API_KEY - 跳过 LLM 测试")
    return key


@pytest.fixture
async def admin_agent(llm_api_key):
    """初始化 Admin Agent"""
    from olav.agents.admin_agent import AdminAgent
    from config.settings import settings
    
    logger.info(f"初始化 Admin Agent: provider={settings.llm_provider}, model={settings.llm_model_name}")
    
    agent = AdminAgent()
    yield agent


class TestAdminAgentWithLLM:
    """测试 Admin Agent 的 LLM 能力"""

    @pytest.mark.asyncio
    @pytest.mark.llm
    async def test_admin_agent_tools_loaded(self, admin_agent):
        """测试 Admin Agent 是否正确加载了 4 个工具"""
        assert len(admin_agent.tools) == 4
        
        tool_names = [tool.name for tool in admin_agent.tools]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "execute_command" in tool_names
        assert "execute_olav" in tool_names
        
        logger.info(f"✓ Admin Agent loaded 4 tools: {', '.join(tool_names)}")

    @pytest.mark.asyncio
    @pytest.mark.llm
    async def test_admin_agent_read_file(self, admin_agent):
        """测试 Admin Agent 能否读取文件"""
        # Ask agent to read a file
        query = "Read the file .olav/OLAV.md and tell me what it says"
        
        response = await admin_agent.ainvoke(query)
        
        assert response is not None
        assert len(response) > 0
        # Should mention OLAV or network automation
        assert ("OLAV" in response or "network" in response.lower())
        
        logger.info(f"✓ Admin Agent read file successfully")

    @pytest.mark.asyncio
    @pytest.mark.llm
    async def test_admin_agent_execute_command(self, admin_agent):
        """测试 Admin Agent 能否执行命令"""
        # Ask agent to list Python files
        query = "Use execute_command to find and count Python files in .olav/tools directory"
        
        response = await admin_agent.ainvoke(query)
        
        assert response is not None
        assert len(response) > 0
        # Should mention files or numbers
        assert any(word in response.lower() for word in ["file", "found", "python", ".py"])
        
        logger.info(f"✓ Admin Agent executed command successfully")

    @pytest.mark.asyncio
    @pytest.mark.llm
    async def test_admin_agent_execute_olav(self, admin_agent):
        """测试 Admin Agent 能否执行 OLAV 命令"""
        # Ask agent to check OLAV status
        query = "Use execute_olav to run 'skills' command and tell me how many skills are available"
        
        response = await admin_agent.ainvoke(query)
        
        assert response is not None
        assert len(response) > 0
        # Should mention skills or numbers
        assert any(word in response.lower() for word in ["skill", "found", "available"])
        
        logger.info(f"✓ Admin Agent executed OLAV command successfully")

    @pytest.mark.asyncio
    @pytest.mark.llm
    async def test_admin_agent_conversation_state(self, admin_agent):
        """测试 Admin Agent 对话状态持久化"""
        thread_id = "test_thread_123"
        
        # First message
        response1 = await admin_agent.ainvoke(
            "Remember this number: 42. What is it?",
            thread_id=thread_id
        )
        assert "42" in response1
        
        # Second message (should remember)
        response2 = await admin_agent.ainvoke(
            "What number did I just tell you to remember?",
            thread_id=thread_id
        )
        assert "42" in response2
        
        logger.info("✓ Admin Agent conversation state works")


# ============================================================================
# Test 3: CLI Integration (Subprocess) 🖥️
# ============================================================================

class TestAdminCLI:
    """测试 Admin CLI 命令（subprocess）"""

    def run_cli(self, *args, timeout=ADMIN_TIMEOUT):
        """运行 uv run olav admin 命令"""
        cmd = ["uv", "run", "olav", "admin"] + list(args)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=PROJECT_ROOT
        )
        return result

    def test_cli_admin_status(self):
        """测试 CLI: olav admin status"""
        result = self.run_cli("status")
        
        assert result.returncode == 0
        assert "timestamp" in result.stdout
        assert "databases" in result.stdout
        assert "skills_count" in result.stdout
        
        logger.info("✓ CLI: olav admin status works")

    def test_cli_admin_backup(self):
        """测试 CLI: olav admin backup"""
        result = self.run_cli("backup", timeout=15)  # Backup needs more time
        
        assert result.returncode == 0
        assert "backup_" in result.stdout
        assert ".tar.gz" in result.stdout
        
        # Find and cleanup backup file
        import re
        match = re.search(r'backup_\d{8}_\d{6}\.tar\.gz', result.stdout)
        if match:
            backup_file = Path(".olav/backups") / match.group(0)
            if backup_file.exists():
                backup_file.unlink()
        
        logger.info("✓ CLI: olav admin backup works")

    def test_cli_admin_db_info(self):
        """测试 CLI: olav admin db-info"""
        result = self.run_cli("db-info")
        
        assert result.returncode == 0
        assert "databases" in result.stdout
        assert "main.duckdb" in result.stdout
        
        logger.info("✓ CLI: olav admin db-info works")

    def test_cli_admin_skill_list(self):
        """测试 CLI: olav admin skill-list"""
        result = self.run_cli("skill-list")
        
        assert result.returncode == 0
        assert "skills" in result.stdout
        assert "olav-admin" in result.stdout
        
        logger.info("✓ CLI: olav admin skill-list works")

    def test_cli_admin_help(self):
        """测试 CLI: olav admin --help"""
        result = self.run_cli("--help")
        
        # Should show help or run admin command
        assert result.returncode in [0, 2]  # 0 for success, 2 for help shown
        
        logger.info("✓ CLI: olav admin --help works")


# ============================================================================
# Test 4: Admin Tools Direct Testing 🔧
# ============================================================================

class TestAdminToolsDirect:
    """直接测试 Admin 工具（不通过 Agent）"""

    def test_tool_read_file(self):
        """测试 read_file 工具"""
        from importlib import import_module
        import sys
        
        # Add admin tools to path
        admin_tools_path = PROJECT_ROOT / ".olav/skills/olav-admin/tools"
        sys.path.insert(0, str(admin_tools_path))
        
        read_file_module = import_module("read_file")
        read_file = read_file_module.read_file
        
        # Test reading OLAV.md (invoke with dict for LangChain tools)
        result = read_file.invoke({"path": ".olav/OLAV.md"})
        
        assert result is not None
        assert "OLAV" in result or "network" in result.lower()
        
        logger.info("✓ Tool: read_file works")

    def test_tool_execute_command(self):
        """测试 execute_command 工具"""
        from importlib import import_module
        import sys
        
        # Add admin tools to path
        admin_tools_path = PROJECT_ROOT / ".olav/skills/olav-admin/tools"
        sys.path.insert(0, str(admin_tools_path))
        
        command_executor_module = import_module("command_executor")
        execute_command = command_executor_module.execute_command
        
        # Test listing files (invoke with dict for LangChain tools)
        result = execute_command.invoke({"command": "ls .olav/"})
        
        assert result is not None
        assert result["success"] is True
        assert "skills" in result["stdout"]
        
        logger.info("✓ Tool: execute_command works")

    def test_tool_execute_olav(self):
        """测试 execute_olav 工具"""
        from importlib import import_module
        import sys
        
        # Add admin tools to path
        admin_tools_path = PROJECT_ROOT / ".olav/skills/olav-admin/tools"
        sys.path.insert(0, str(admin_tools_path))
        
        olav_executor_module = import_module("olav_executor")
        execute_olav = olav_executor_module.execute_olav
        
        # Test running olav skills (invoke with dict for LangChain tools)
        result = execute_olav.invoke({"command": "skills"})
        
        assert result is not None
        assert result["success"] is True
        assert "skill" in result["stdout"].lower()
        
        logger.info("✓ Tool: execute_olav works")

    def test_tool_write_file_temp(self):
        """测试 write_file 工具（临时文件）"""
        from importlib import import_module
        import sys
        
        # Add admin tools to path
        admin_tools_path = PROJECT_ROOT / ".olav/skills/olav-admin/tools"
        sys.path.insert(0, str(admin_tools_path))
        
        write_file_module = import_module("write_file")
        write_file = write_file_module.write_file
        
        # Test writing to temp file (invoke with dict for LangChain tools)
        temp_file = ".olav/.test_write_file.tmp"
        test_content = "# Test Content\nThis is a test file."
        
        result = write_file.invoke({"path": temp_file, "content": test_content})
        
        assert result is not None
        assert "✅" in result or "Created" in result or "Modified" in result
        
        # Verify file exists
        temp_path = PROJECT_ROOT / temp_file
        assert temp_path.exists()
        
        # Cleanup
        temp_path.unlink()
        
        logger.info("✓ Tool: write_file works")


# ============================================================================
# Test 5: Performance & Reliability 📊
# ============================================================================

class TestAdminPerformance:
    """测试 Admin Agent 性能和可靠性"""

    @pytest.mark.asyncio
    async def test_fast_path_performance(self):
        """测试 fast-path 命令性能（应该 < 1s）"""
        import time
        from olav.cli.admin import admin_handler
        
        start = time.time()
        result = await admin_handler("/admin status")
        elapsed = time.time() - start
        
        assert result["status"] == "success"
        assert elapsed < 1.0  # Should be < 1 second
        
        logger.info(f"✓ Fast-path performance: {elapsed:.3f}s (target: <1s)")

    @pytest.mark.asyncio
    async def test_multiple_fast_path_commands(self):
        """测试多次调用 fast-path 命令"""
        from olav.cli.admin import admin_handler
        
        commands = [
            "/admin status",
            "/admin db-info",
            "/admin skill-list",
        ]
        
        for cmd in commands:
            result = await admin_handler(cmd)
            assert result["status"] == "success"
        
        logger.info(f"✓ Multiple fast-path commands succeeded")

    def test_cli_command_reliability(self):
        """测试 CLI 命令可靠性（重复运行）"""
        for i in range(3):
            cmd = ["uv", "run", "olav", "admin", "status"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=ADMIN_TIMEOUT,
                cwd=PROJECT_ROOT
            )
            assert result.returncode == 0
        
        logger.info("✓ CLI reliability: 3/3 runs succeeded")


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "-s"])
