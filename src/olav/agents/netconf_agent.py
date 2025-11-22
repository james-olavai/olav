"""
NETCONF Agent - 通过 NETCONF/YANG 执行设备操作（优先使用的标准方案）
"""
from deepagents import SubAgent
from olav.core.prompt_manager import prompt_manager


def create_netconf_subagent() -> SubAgent:
    """
    创建 NETCONF 执行 SubAgent（专注于 NETCONF 协议）
    
    职责:
    - 通过 NETCONF over SSH (Port 830) 执行设备操作
    - 使用 OpenConfig YANG 模型构造 RPC 请求
    - 配置操作触发 HITL 审批
    - ✅ 优势: 原子回滚、数据验证、Candidate Datastore
    
    错误处理:
    - 连接失败时返回明确错误: "NETCONF connection failed: {原因}"
    - **不自己尝试降级** - 让 Root Agent 决定是否切换到 CLI
    
    Returns:
        SubAgent: NETCONF 执行代理
    """
    # 加载 NETCONF Agent 专用 Prompt
    netconf_prompt = prompt_manager.load_agent_prompt("netconf_agent")
    
    # 导入工具（延迟导入避免循环依赖）
    from olav.tools.nornir_tool import netconf_tool
    
    return SubAgent(
        name="netconf-executor",
        description="通过 NETCONF/YANG 执行设备操作（优先使用）",
        system_prompt=netconf_prompt,
        tools=[netconf_tool],
        interrupt_on={
            "netconf_tool": {
                # 仅 edit-config 操作触发 HITL
                "condition": lambda args: args.get("operation") == "edit-config",
                "allowed_decisions": ["approve", "edit", "reject"]
            }
        }
    )


# 导出
__all__ = ["create_netconf_subagent"]
