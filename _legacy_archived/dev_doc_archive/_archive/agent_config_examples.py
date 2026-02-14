"""Agent配置使用示例 - v0.9.8+

展示如何在代码中使用新的Agent配置系统。
"""

from config.settings import settings


def example_1_basic_usage():
    """示例1: 基础用法 - 直接访问配置"""
    print("=== Example 1: Basic Usage ===\n")
    
    # 访问Orchestrator配置
    print(f"Orchestrator Model: {settings.agent.orchestrator_model}")
    print(f"Orchestrator Base URL: {settings.agent.orchestrator_base_url or '(use global)'}")
    print(f"Orchestrator API Key: {'Set' if settings.agent.orchestrator_api_key else '(use global)'}")
    
    # Fallback逻辑
    base_url = settings.agent.orchestrator_base_url or settings.llm_base_url
    api_key = settings.agent.orchestrator_api_key or settings.llm_api_key
    
    print(f"\nActual Base URL: {base_url}")
    print(f"Actual API Key: {'***' if api_key else 'Not set'}")


def example_2_helper_method():
    """示例2: 使用辅助方法 - 推荐方式"""
    print("\n=== Example 2: Using Helper Method ===\n")
    
    # 使用get_agent_config自动处理fallback
    for agent_name in ["orchestrator", "analyzer", "guard", "textfsm"]:
        config = settings.agent.get_agent_config(agent_name, settings)
        
        print(f"{agent_name.upper()}")
        print(f"  Model: {config['model']}")
        print(f"  Base URL: {config['base_url']}")
        print(f"  API Key: {'Set' if config['api_key'] else 'Not set'}")
        print()


def example_3_create_llm():
    """示例3: 创建LLM实例"""
    print("\n=== Example 3: Create LLM Instance ===\n")
    
    # 获取Orchestrator配置
    config = settings.agent.get_agent_config("orchestrator", settings)
    
    # 模拟创建ChatOpenAI实例（需要导入langchain_openai）
    print("Creating LLM with config:")
    print(f"  model={config['model']}")
    print(f"  openai_api_base={config['base_url']}")
    print(f"  openai_api_key={'***' if config['api_key'] else 'None'}")
    
    # 实际代码示例：
    # from langchain_openai import ChatOpenAI
    # llm = ChatOpenAI(
    #     model=config["model"],
    #     openai_api_base=config["base_url"],
    #     openai_api_key=config["api_key"],
    # )


def example_4_multi_provider():
    """示例4: 多API提供商场景"""
    print("\n=== Example 4: Multi-Provider Setup ===\n")
    
    print("Scenario: Using different providers for different agents")
    print("- Global: OpenRouter (grok-4.1-fast)")
    print("- Analyzer: OpenAI Official (gpt-4o)")
    print("- Guard: OpenRouter (gpt-4o-mini, cheaper)")
    print("- LLM Interface: Anthropic (claude-sonnet-4)")
    print()
    
    # .env配置示例
    print("Required .env configuration:")
    print("""
# Global (OpenRouter)
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=sk-or-v1-xxx
LLM_MODEL_NAME=x-ai/grok-4.1-fast

# Analyzer (OpenAI Official)
AGENT__ANALYZER_MODEL=gpt-4o
AGENT__ANALYZER_BASE_URL=https://api.openai.com/v1
AGENT__ANALYZER_API_KEY=sk-proj-xxx

# Guard (cheaper model, same provider)
AGENT__GUARD_MODEL=gpt-4o-mini
# BASE_URL and API_KEY will fallback to global

# LLM Interface (Anthropic)
AGENT__LLM_INTERFACE_MODEL=claude-sonnet-4-20250514
AGENT__LLM_INTERFACE_BASE_URL=https://api.anthropic.com/v1
AGENT__LLM_INTERFACE_API_KEY=sk-ant-xxx
    """)
    
    # 验证配置
    print("\nActual configuration after fallback:")
    for agent in ["orchestrator", "analyzer", "guard", "llm_interface"]:
        config = settings.agent.get_agent_config(agent, settings)
        provider = "Unknown"
        if "openrouter" in config["base_url"]:
            provider = "OpenRouter"
        elif "openai.com" in config["base_url"]:
            provider = "OpenAI"
        elif "anthropic.com" in config["base_url"]:
            provider = "Anthropic"
        
        print(f"{agent:15} -> {config['model']:30} @ {provider}")


def example_5_environment_override():
    """示例5: 环境变量覆盖"""
    print("\n=== Example 5: Environment Variable Override ===\n")
    
    import os
    
    print("Original Orchestrator Model:", settings.agent.orchestrator_model)
    
    # 临时覆盖（仅演示，实际应在.env中配置）
    print("\nSetting AGENT__ORCHESTRATOR_MODEL=test-model...")
    os.environ["AGENT__ORCHESTRATOR_MODEL"] = "test-model"
    
    # 重新加载settings（实际使用中settings是单例，需要重启应用）
    from config.settings import Settings
    new_settings = Settings()
    
    print("New Orchestrator Model:", new_settings.agent.orchestrator_model)
    print("✅ Environment variable override works!")


if __name__ == "__main__":
    example_1_basic_usage()
    example_2_helper_method()
    example_3_create_llm()
    example_4_multi_provider()
    example_5_environment_override()
    
    print("\n" + "="*60)
    print("✅ All examples completed!")
    print("="*60)
