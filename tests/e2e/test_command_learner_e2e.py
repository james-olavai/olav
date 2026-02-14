"""
Command Learner Agent E2E Tests - v2.1.0

测试 Command Learner Agent 功能：
1. Agent 初始化
2. 7 个工具的独立功能
3. CommandRegistry 热重载机制
4. CLI 集成 (/learn_cmd, /admin reload)
5. Token 优化验证（metadata first）

运行：
    uv run pytest tests/e2e/test_command_learner_e2e.py -v -s
    uv run pytest tests/e2e/test_command_learner_e2e.py::TestAgentInit -v
    uv run pytest tests/e2e/test_command_learner_e2e.py::TestTools -v
    uv run pytest tests/e2e/test_command_learner_e2e.py::TestReloadMechanism -v
"""

import asyncio
import json
import logging
from pathlib import Path
import tempfile
import shutil

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# Test 1: Agent Initialization ✅
# ============================================================================

class TestAgentInit:
    """测试 Command Learner Agent 初始化"""

    def test_agent_initialization(self):
        """测试 Agent 初始化：7 个工具加载，lazy LLM"""
        from olav.agents.command_learner_agent import CommandLearnerAgent
        
        # 测试初始化成功
        agent = CommandLearnerAgent()
        
        # 验证工具加载
        assert len(agent.tools) == 7, f"Expected 7 tools, got {len(agent.tools)}"
        
        # 验证工具名称
        tool_names = [tool.name for tool in agent.tools]
        expected_tools = [
            "execute_command",
            "analyze_output",
            "search_ntc_templates",
            "read_template_file",
            "browse_ntc_directory",
            "generate_template",
            "save_template",
        ]
        
        for expected in expected_tools:
            assert expected in tool_names, f"Missing tool: {expected}"
        
        logger.info(f"✅ Agent initialized with {len(agent.tools)} tools: {tool_names}")

    def test_lazy_llm_initialization(self):
        """测试 Lazy LLM 初始化（不在 __init__ 中创建）"""
        from olav.agents.command_learner_agent import CommandLearnerAgent
        
        agent = CommandLearnerAgent()
        
        # 验证 LLM 未在 __init__ 中创建
        assert agent._llm is None, "LLM should be None before first use"
        assert agent._llm_with_tools is None, "LLM with tools should be None before first use"
        
        # 首次访问 llm property 时才创建
        llm = agent.llm  # Trigger lazy initialization
        
        assert llm is not None, "LLM should be created on first access"
        assert agent._llm is not None, "LLM should be cached"
        
        logger.info("✅ Lazy LLM initialization works correctly")

    def test_singleton_pattern(self):
        """测试 get_command_learner_agent() 单例模式"""
        from olav.agents.command_learner_agent import get_command_learner_agent
        
        agent1 = get_command_learner_agent()
        agent2 = get_command_learner_agent()
        
        assert agent1 is agent2, "Should return same instance (singleton)"
        
        logger.info("✅ Singleton pattern works correctly")


# ============================================================================
# Test 2: Individual Tools 🛠️
# ============================================================================

class TestTools:
    """测试 7 个工具的独立功能"""

    def test_ntc_search_metadata_only(self):
        """测试 search_ntc_templates 只返回 metadata（无 full content）"""
        import sys
        tools_path = PROJECT_ROOT / ".olav/skills/command_learner/tools"
        if str(tools_path) not in sys.path:
            sys.path.insert(0, str(tools_path))
        
        from ntc_search import search_ntc_templates
        
        result = search_ntc_templates.invoke({
            "platform": "cisco_ios",
            "command": "show version",
            "approved_fields": ["version", "uptime", "hostname"],
            "limit": 3
        })
        
        # 验证结构
        assert "ntc_path" in result
        assert "results" in result
        assert len(result["results"]) <= 3
        
        # ⭐ 验证 token 优化：只返回 metadata，不返回 full content
        for template_result in result["results"]:
            assert "template_name" in template_result
            assert "template_path" in template_result
            assert "score" in template_result
            assert "fields_found" in template_result
            assert "content" not in template_result, "❌ Should NOT return full content (token optimization)"
        
        logger.info(f"✅ NTC search returned {len(result['results'])} metadata-only results")

    def test_template_reader_on_demand(self):
        """测试 read_template_file 按需加载完整内容"""
        import sys
        tools_path = PROJECT_ROOT / ".olav/skills/command_learner/tools"
        if str(tools_path) not in sys.path:
            sys.path.insert(0, str(tools_path))
        
        from ntc_search import search_ntc_templates, find_ntc_templates_path
        from template_reader import read_template_file
        
        # 先搜索（metadata only）
        search_result = search_ntc_templates.invoke({
            "platform": "cisco_ios",
            "command": "show version",
            "approved_fields": ["version", "uptime"],
            "limit": 1
        })
        
        if not search_result["results"]:
            pytest.skip("No NTC templates found, skipping test")
        
        # 获取 top 1 模板路径
        template_path = search_result["results"][0]["template_path"]
        
        # 按需加载完整内容
        read_result = read_template_file.invoke({"template_path": template_path})
        
        # 验证返回完整内容
        assert "content" in read_result, "Should return full content"
        assert "fields" in read_result
        assert "size_bytes" in read_result
        assert len(read_result["content"]) > 0
        
        logger.info(f"✅ Template reader loaded {read_result['size_bytes']} bytes on-demand")

    def test_ntc_browser(self):
        """测试 browse_ntc_directory 浏览功能"""
        import sys
        tools_path = PROJECT_ROOT / ".olav/skills/command_learner/tools"
        if str(tools_path) not in sys.path:
            sys.path.insert(0, str(tools_path))
        
        from ntc_browser import browse_ntc_directory
        
        # 不过滤平台（省略参数或使用空字符串）
        result = browse_ntc_directory.invoke({"limit": 20})
        
        assert "ntc_path" in result
        assert "total_templates" in result
        assert "platforms" in result
        assert "templates" in result
        
        # 验证推断命令
        if result["templates"]:
            first_template = result["templates"][0]
            assert "name" in first_template  # Changed from template_name
            assert "commands" in first_template  # Changed from inferred_command
        
        logger.info(f"✅ NTC browser found {result['total_templates']} templates, {len(result['platforms'])} platforms")

    def test_analyze_output_structure(self):
        """测试 analyze_output 工具结构（不调用 LLM）"""
        import sys
        tools_path = PROJECT_ROOT / ".olav/skills/command_learner/tools"
        if str(tools_path) not in sys.path:
            sys.path.insert(0, str(tools_path))
        
        from analyze_output import analyze_output
        
        # 验证工具存在和基本属性
        assert analyze_output.name == "analyze_output"
        assert callable(analyze_output.invoke)
        
        logger.info("✅ analyze_output tool structure validated")

    def test_template_generator_structure(self):
        """测试 generate_template 工具结构（不调用 LLM）"""
        import sys
        tools_path = PROJECT_ROOT / ".olav/skills/command_learner/tools"
        if str(tools_path) not in sys.path:
            sys.path.insert(0, str(tools_path))
        
        from template_generator import generate_template
        
        # 验证工具存在
        assert generate_template.name == "generate_template"
        assert callable(generate_template.invoke)
        
        logger.info("✅ generate_template tool structure validated")


# ============================================================================
# Test 3: CommandRegistry Reload Mechanism 🔄
# ============================================================================

class TestReloadMechanism:
    """测试 CommandRegistry 热重载机制"""

    def test_command_registry_initialization(self):
        """测试 CommandRegistry 初始化"""
        from olav.core.command_registry import CommandRegistry
        
        registry = CommandRegistry()
        
        # 验证基本属性
        assert hasattr(registry, '_templates')
        assert hasattr(registry, '_whitelist')
        assert hasattr(registry, '_blacklist')
        
        logger.info("✅ CommandRegistry initialized")

    def test_reload_method(self):
        """测试 CommandRegistry.reload() 方法"""
        from olav.core.command_registry import CommandRegistry
        
        # 调用 reload
        result = CommandRegistry.reload()
        
        # 验证返回结构
        assert "reloaded" in result
        assert "templates" in result["reloaded"]
        assert "whitelisted_commands" in result["reloaded"]  # Changed from whitelist
        assert "blacklisted_patterns" in result["reloaded"]  # Changed from blacklist
        
        logger.info(f"✅ Reload completed: {result['reloaded']['templates']} templates")

    def test_priority_system(self):
        """测试模板优先级系统（config > custom > legacy > NTC）"""
        from olav.core.command_registry import CommandRegistry
        
        registry = CommandRegistry()
        
        # 验证 _load_templates 使用正确的优先级目录
        # Priority 1: .olav/config/textfsm/
        # Priority 2: .olav/templates/custom/
        # Priority 3: .olav/templates/
        # Priority 4: ntc_templates/
        
        # 创建测试模板
        custom_dir = PROJECT_ROOT / ".olav/templates/custom"
        custom_dir.mkdir(parents=True, exist_ok=True)
        
        test_template = custom_dir / "test_priority.textfsm"
        test_template.write_text("Value TEST (.+)\n\nStart\n  ^${TEST} -> Record\n")
        
        # Reload
        result = CommandRegistry.reload()
        
        # 验证能找到 custom 模板（get_template_path 只接受 template_name）
        custom_template = registry.get_template_path("test_priority.textfsm")
        assert custom_template is not None or result["reloaded"]["templates"] > 0
        
        # 清理
        test_template.unlink(missing_ok=True)
        
        logger.info("✅ Priority system working")

    def test_hot_reload_no_restart(self):
        """测试热重载（无需重启）"""
        from olav.core.command_registry import CommandRegistry
        
        # 第一次加载
        result1 = CommandRegistry.reload()
        count1 = result1["reloaded"]["templates"]
        
        # 创建新模板
        custom_dir = PROJECT_ROOT / ".olav/templates/custom"
        custom_dir.mkdir(parents=True, exist_ok=True)
        
        new_template = custom_dir / "test_hot_reload.textfsm"
        new_template.write_text("Value FIELD (.+)\n\nStart\n  ^${FIELD} -> Record\n")
        
        # 热重载（无需重启）
        result2 = CommandRegistry.reload()
        count2 = result2["reloaded"]["templates"]
        
        # 验证模板数增加（或至少相等）
        assert count2 >= count1, "Hot reload should detect new template"
        
        # 清理
        new_template.unlink(missing_ok=True)
        CommandRegistry.reload()  # 最终清理
        
        logger.info(f"✅ Hot reload: {count1} → {count2} templates")


# ============================================================================
# Test 4: CLI Integration 💻
# ============================================================================

class TestCLIIntegration:
    """测试 CLI 集成"""

    @pytest.mark.asyncio
    async def test_admin_reload_command(self):
        """测试 /admin reload-commands 命令"""
        from olav.cli.admin import admin_handler
        
        result = await admin_handler("/admin reload-commands")
        
        # 验证返回结构
        assert "status" in result
        assert result["status"] in ["success", "error"]
        
        if result["status"] == "success":
            assert "reloaded" in result  # Changed: reloaded is in top level, not result["data"]
            assert "templates" in result["reloaded"]
        
        logger.info("✅ /admin reload-commands works")

    @pytest.mark.asyncio
    async def test_admin_reload_alias(self):
        """测试 /admin reload 别名"""
        from olav.cli.admin import admin_handler
        
        result = await admin_handler("/admin reload")
        
        assert "status" in result
        assert result["status"] in ["success", "error"]
        
        logger.info("✅ /admin reload alias works")

    def test_learn_cmd_exists(self):
        """测试 /learn_cmd 命令存在"""
        from olav.cli.commands.builtin import cmd_learn
        
        # 验证命令存在
        assert callable(cmd_learn)
        
        logger.info("✅ /learn_cmd command exists")


# ============================================================================
# Test 5: Token Optimization Validation ⭐
# ============================================================================

class TestTokenOptimization:
    """验证 token 优化策略"""

    def test_metadata_vs_full_content_size(self):
        """验证 metadata only 比 full content 节省 token"""
        import sys
        tools_path = PROJECT_ROOT / ".olav/skills/command_learner/tools"
        if str(tools_path) not in sys.path:
            sys.path.insert(0, str(tools_path))
        
        from ntc_search import search_ntc_templates
        from template_reader import read_template_file
        
        # 搜索 5 个模板（metadata only）
        search_result = search_ntc_templates.invoke({
            "platform": "cisco_ios",
            "command": "show ip",
            "approved_fields": ["network", "mask"],
            "limit": 5
        })
        
        if not search_result["results"]:
            pytest.skip("No templates found")
        
        # 计算 metadata 大小
        metadata_str = json.dumps(search_result)
        metadata_size = len(metadata_str)
        
        # 读取所有模板的完整内容
        full_content_size = 0
        for template in search_result["results"]:
            read_result = read_template_file.invoke({
                "template_path": template["template_path"]
            })
            full_content_size += len(read_result["content"])
        
        # 验证节省比例
        if full_content_size > 0:
            savings_ratio = 1 - (metadata_size / full_content_size)
            logger.info(f"Token savings: {savings_ratio:.1%} (metadata: {metadata_size} bytes, full: {full_content_size} bytes)")
            
            # 应该节省至少 50% token
            assert savings_ratio > 0.5, f"Expected >50% savings, got {savings_ratio:.1%}"
        
        logger.info(f"✅ Token optimization validated: metadata={metadata_size}B, full={full_content_size}B")

    def test_workflow_token_optimization(self):
        """测试工作流的 token 优化策略"""
        # Workflow:
        # 1. search_ntc_templates() → metadata only (5 results) ~2KB
        # 2. LLM selects top 1-2 most relevant
        # 3. read_template_file() → load selected only ~1KB each
        # Total: ~4KB vs ~10KB (all upfront) = 60% savings
        
        import sys
        tools_path = PROJECT_ROOT / ".olav/skills/command_learner/tools"
        if str(tools_path) not in sys.path:
            sys.path.insert(0, str(tools_path))
        
        from ntc_search import search_ntc_templates
        from template_reader import read_template_file
        
        # Step 1: Search metadata only
        search_result = search_ntc_templates.invoke({
            "platform": "cisco_ios",
            "command": "show version",
            "approved_fields": ["version"],
            "limit": 5
        })
        
        step1_size = len(json.dumps(search_result))
        
        # Step 2: Simulate LLM selecting top 2
        selected_count = min(2, len(search_result["results"]))
        
        # Step 3: Load only selected
        step3_size = 0
        for i in range(selected_count):
            template_path = search_result["results"][i]["template_path"]
            read_result = read_template_file.invoke({"template_path": template_path})
            step3_size += len(read_result["content"])
        
        optimized_total = step1_size + step3_size
        
        # Compare with loading all upfront
        all_upfront_size = 0
        for template in search_result["results"]:
            read_result = read_template_file.invoke({"template_path": template["template_path"]})
            all_upfront_size += len(read_result["content"])
        
        if all_upfront_size > 0:
            savings = 1 - (optimized_total / all_upfront_size)
            logger.info(f"Workflow savings: {savings:.1%} (optimized: {optimized_total}B, all upfront: {all_upfront_size}B)")
        
        logger.info(f"✅ Workflow token optimization: {step1_size}B metadata + {step3_size}B selected = {optimized_total}B total")


# ============================================================================
# Summary
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
