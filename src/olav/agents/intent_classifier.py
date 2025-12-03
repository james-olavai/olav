"""Intent Classifier for Multi-Agent Routing.

Uses LLM with structured output to classify user intents into:
- query: Information retrieval, read-only operations
- diagnose: Problem analysis, root cause identification
- config: Configuration changes, HITL-required operations

Replaces keyword-based matching with intelligent classification.
"""

from enum import Enum
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from olav.core.llm import LLMFactory
from olav.core.prompt_manager import prompt_manager


class IntentType(str, Enum):
    """Supported intent types for routing."""

    QUERY = "query"
    DIAGNOSE = "diagnose"
    CONFIG = "config"


class Intent(BaseModel):
    """Structured output for intent classification."""

    primary: Literal["query", "diagnose", "config"] = Field(
        description="Primary intent type: query (read-only), diagnose (analysis), config (changes)"
    )
    secondary: Literal["query", "diagnose", "config", "none"] = Field(
        default="none",
        description="Secondary intent if compound request (e.g., diagnose then fix)",
    )
    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Confidence score for the classification",
    )
    reasoning: str = Field(
        description="Brief explanation for the classification decision"
    )
    requires_hitl: bool = Field(
        default=False,
        description="Whether this request requires Human-in-the-Loop approval",
    )


class IntentClassifier:
    """LLM-based intent classifier for multi-agent routing.

    Uses structured output to ensure consistent classification results.
    Supports compound intents (e.g., "diagnose and fix").
    """

    def __init__(self):
        """Initialize the classifier with LLM."""
        self.llm = LLMFactory.get_chat_model(json_mode=True)

    async def classify(self, user_query: str) -> Intent:
        """Classify user query into intent type.

        Args:
            user_query: The user's natural language query

        Returns:
            Intent object with primary/secondary intent, confidence, and reasoning
        """
        # Load prompt from config
        try:
            system_prompt = prompt_manager.load_prompt(
                "agents/intent_classifier", "system"
            )
        except Exception:
            # Fallback prompt if config not found
            system_prompt = self._get_fallback_prompt()

        # Use structured output
        llm_with_structure = self.llm.with_structured_output(Intent)

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_query),
        ]

        result = await llm_with_structure.ainvoke(messages)
        return result

    def classify_sync(self, user_query: str) -> Intent:
        """Synchronous version of classify for non-async contexts."""
        import asyncio

        return asyncio.run(self.classify(user_query))

    def _get_fallback_prompt(self) -> str:
        """Get fallback prompt if config not available."""
        return """你是一个意图分类器，负责将用户请求分类到以下三种类型之一：

## 意图类型

### 1. query (查询)
- 信息检索、列表获取、状态检查
- 只读操作，不需要修改任何配置
- 关键词：列出、查询、显示、获取、show、list、get

**示例：**
- "列出所有设备的接口状态"
- "查询 R1 的 BGP 邻居"
- "显示 VLAN 100 的成员端口"

### 2. diagnose (诊断)
- 故障分析、问题排查、根因定位
- 需要分析多个数据源来确定问题原因
- 关键词：为什么、原因、诊断、排查、分析、why、troubleshoot

**示例：**
- "为什么 BGP 邻居建不起来？"
- "分析 OSPF 邻居中断的原因"
- "排查 R2 到 R3 的连接问题"

### 3. config (配置)
- 配置变更、创建删除、修改设置
- 需要 HITL (Human-in-the-Loop) 审批
- 关键词：配置、创建、删除、修改、添加、设置、configure、create、delete、modify

**示例：**
- "在 R1 上创建 Loopback0 接口"
- "删除 VLAN 100"
- "修改 BGP 邻居的 AS 号"

## 复合意图

如果用户请求包含多个意图（例如"诊断并修复"），则：
- primary: 第一个要执行的意图
- secondary: 后续要执行的意图

**示例：**
- "诊断 BGP 问题并修复配置" → primary: diagnose, secondary: config

## 输出格式

返回 JSON 格式，包含：
- primary: 主要意图 (query/diagnose/config)
- secondary: 次要意图 (query/diagnose/config/none)
- confidence: 置信度 (0.0-1.0)
- reasoning: 分类理由
- requires_hitl: 是否需要人工审批 (config 操作总是 true)

## 规则

1. config 操作始终需要 requires_hitl=true
2. 如果不确定，优先分类为 query（最安全）
3. 诊断通常需要后续配置操作，考虑设置 secondary=config
"""


# Singleton instance for easy import
_classifier: IntentClassifier | None = None


def get_intent_classifier() -> IntentClassifier:
    """Get or create the singleton intent classifier instance."""
    global _classifier
    if _classifier is None:
        _classifier = IntentClassifier()
    return _classifier


__all__ = ["Intent", "IntentType", "IntentClassifier", "get_intent_classifier"]
