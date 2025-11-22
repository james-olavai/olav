"""
CLI Agent - 通过传统 CLI 命令执行设备操作（NETCONF 失败时的降级方案）
"""
from deepagents import SubAgent
from olav.core.prompt_manager import prompt_manager
from olav.core.llm import LLMFactory


def create_cli_subagent() -> SubAgent:
    """
    创建 CLI 执行 SubAgent（专注于传统 CLI 命令）
    
    职责:
    - 通过 SSH + Netmiko 执行 CLI 命令
    - 使用 TextFSM 解析输出为结构化数据
    - 配置操作触发 HITL 审批
    - ⚠️ 警告: 无原子回滚能力
    
    使用场景:
    - NETCONF 不可用的模拟器设备（GNS3/EVE-NG）
    - 传统设备不支持 NETCONF
    - Root Agent 检测到 NETCONF 连接失败后自动降级
    
    Returns:
        SubAgent: CLI 执行代理
    """
    # 加载 CLI Agent 专用 Prompt
    cli_prompt = prompt_manager.load_agent_prompt("cli_agent")
    
    # 导入工具（延迟导入避免循环依赖）
    from olav.tools.nornir_tool import cli_tool
    from olav.tools.ntc_tool import discover_commands, list_supported_platforms
    
    return SubAgent(
        name="cli-executor",
        description="通过 CLI 命令执行设备操作（NETCONF 失败时使用）",
        system_prompt=cli_prompt,
        tools=[
            discover_commands,  # Schema-first: 优先查询已验证命令
            cli_tool,
            list_supported_platforms,
        ],
        interrupt_on={
            "cli_tool": {
                # 仅配置命令触发 HITL
                "condition": lambda args: args.get("config_commands") is not None,
                "allowed_decisions": ["approve", "edit", "reject"]
            }
        }
    )


# 导出
__all__ = ["create_cli_subagent"]
