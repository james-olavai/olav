"""
Security Tools Unit Tests (TDD - Phase 1.1)
测试安全扫描工具的基础功能
"""

import pytest
from unittest.mock import AsyncMock, patch


class TestSecurityScanBasic:
    """基础安全扫描测试"""

    @pytest.mark.asyncio
    async def test_security_scan_vulnerability(self):
        """测试漏洞扫描功能 - RED状态 (未实现)"""
        # 这个测试会失败，因为security_scan还未实现
        from olav.tools.security import security_scan

        result = await security_scan(target="R1", scan_type="vulnerability")

        assert "vulnerabilities" in result, "结果应包含vulnerabilities字段"
        assert isinstance(result["vulnerabilities"], list), "vulnerabilities应为列表"

    @pytest.mark.asyncio
    async def test_security_scan_compliance(self):
        """测试合规性检查 - RED状态 (未实现)"""
        from olav.tools.security import security_scan

        result = await security_scan(target="R1", scan_type="compliance")

        assert "compliance_score" in result, "结果应包含compliance_score"
        assert 0 <= result["compliance_score"] <= 100, "合规分数应在0-100之间"

    @pytest.mark.asyncio
    async def test_security_scan_default_type(self):
        """测试默认扫描类型"""
        from olav.tools.security import security_scan

        result = await security_scan(target="R1")

        # 默认应该是漏洞扫描
        assert "vulnerabilities" in result


class TestSecurityScanAdvanced:
    """高级安全扫描测试"""

    @pytest.mark.asyncio
    async def test_vulnerability_severity_classification(self):
        """测试漏洞严重性分类"""
        from olav.tools.security import security_scan

        result = await security_scan(target="VULNERABLE_DEVICE", scan_type="vulnerability")

        if len(result["vulnerabilities"]) > 0:
            vuln = result["vulnerabilities"][0]
            assert "severity" in vuln
            assert vuln["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

    @pytest.mark.asyncio
    async def test_compliance_detailed_report(self):
        """测试合规性详细报告"""
        from olav.tools.security import security_scan

        result = await security_scan(target="R1", scan_type="compliance")

        assert "compliance_score" in result
        assert "issues" in result  # 应该列出不合规项
        assert isinstance(result["issues"], list)

    @pytest.mark.asyncio
    async def test_security_scan_performance(self):
        """测试扫描性能 - 应在5秒内完成"""
        import time
        from olav.tools.security import security_scan

        start = time.time()
        await security_scan(target="R1")
        duration = time.time() - start

        assert duration < 5.0, f"安全扫描耗时{duration:.2f}秒，超过5秒阈值"

    @pytest.mark.asyncio
    async def test_invalid_scan_type(self):
        """测试无效扫描类型"""
        from olav.tools.security import security_scan

        with pytest.raises(ValueError, match="Invalid scan_type"):
            await security_scan(target="R1", scan_type="invalid_type")


class TestSecurityToolIntegration:
    """安全工具集成测试"""

    @pytest.mark.asyncio
    async def test_security_subagent_routing(self):
        """测试安全SubAgent路由 - 需要在orchestrator中添加安全SubAgent后测试"""
        pytest.skip("需要先在orchestrator.py中添加security SubAgent")

        from olav.agents.orchestrator import create_orchestrator
        from langchain_core.messages import HumanMessage

        orchestrator = create_orchestrator()

        result = await orchestrator.ainvoke({
            "messages": [HumanMessage(content="扫描R1的安全漏洞")]
        })

        # 应该路由到security SubAgent
        agent_path = result.get("agent_path", [])
        assert "security" in agent_path, "应该调用security SubAgent"
