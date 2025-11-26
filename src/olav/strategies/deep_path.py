"""
Deep Path Strategy - Hypothesis-driven reasoning for complex diagnostics.

This strategy implements an iterative reasoning loop for "why" questions
and multi-step troubleshooting scenarios that cannot be answered by a
single tool invocation.

Execution Flow (max 5 iterations):
1. ObservationCollect: Gather initial data with tools
2. HypothesisGenerate: LLM analyzes data and forms hypotheses
3. Verification: Execute tools to test hypothesis
4. Refinement: Update understanding based on results
5. Repeat until answer found or max iterations

Example Queries:
- "为什么 R1 无法建立 BGP 邻居？" → Multi-step: BGP status → config check → neighbor reachability
- "诊断为什么路由表不完整" → Hypothesis loop: OSPF adjacency → route filtering → redistribution
- "排查网络丢包问题" → Iterative: interface errors → QoS policies → path MTU

Key Difference from Fast Path:
- Fast Path: Single tool call, deterministic
- Deep Path: Iterative reasoning, hypothesis-driven, adaptive
"""

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from pydantic import BaseModel, Field

from olav.tools.base import ToolOutput, ToolRegistry

logger = logging.getLogger(__name__)


class Hypothesis(BaseModel):
    """
    A hypothesis about the root cause of a problem.

    LLM generates hypotheses based on observed data.
    """

    description: str = Field(description="What this hypothesis proposes")
    reasoning: str = Field(description="Why this hypothesis is plausible")
    verification_plan: str = Field(
        description="What tool to use and what to check to verify/reject this hypothesis"
    )
    confidence: float = Field(description="Confidence in this hypothesis (0.0-1.0)", ge=0.0, le=1.0)


class ObservationStep(BaseModel):
    """
    A single observation step in the reasoning loop.

    Contains the tool used, data collected, and LLM's interpretation.
    """

    step_number: int
    tool: str
    parameters: dict[str, Any]
    tool_output: ToolOutput | None = None
    interpretation: str = Field(description="LLM's interpretation of what the data means")


class ReasoningState(BaseModel):
    """
    State of the deep path reasoning process.

    Tracks observations, hypotheses, and current understanding.
    """

    original_query: str
    observations: list[ObservationStep] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    current_hypothesis: Hypothesis | None = None
    iteration: int = 0
    conclusion: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class DeepPathStrategy:
    """
    Deep Path execution strategy for complex, multi-step diagnostics.

    Implements hypothesis-driven reasoning:
    1. Collect initial observations
    2. Generate hypotheses about root cause
    3. Verify hypothesis with targeted tool calls
    4. Refine understanding and iterate

    Attributes:
        llm: Language model for reasoning
        tool_registry: Registry of available tools
        max_iterations: Maximum reasoning loops (default: 5)
        confidence_threshold: Min confidence to conclude (default: 0.8)
    """

    def __init__(
        self,
        llm: BaseChatModel,
        tool_registry: "ToolRegistry",
        max_iterations: int = 5,
        confidence_threshold: float = 0.8,
    ) -> None:
        """
        Initialize Deep Path strategy.

        Args:
            llm: Language model for reasoning
            tool_registry: ToolRegistry instance (required for tool discovery)
            max_iterations: Max reasoning iterations
            confidence_threshold: Min confidence to conclude
        """
        self.llm = llm
        self.tool_registry = tool_registry
        self.max_iterations = max_iterations
        self.confidence_threshold = confidence_threshold

        # Load tool capability guides (cached at init)
        self._tool_guides = self._load_tool_capability_guides()

        # Validate tool registry
        if not self.tool_registry:
            msg = "ToolRegistry is required for DeepPathStrategy"
            raise ValueError(msg)

        logger.info(
            f"DeepPathStrategy initialized with max_iterations={max_iterations}, "
            f"confidence_threshold={confidence_threshold}, "
            f"available tools: {len(self.tool_registry.list_tools())}"
        )

    def _load_tool_capability_guides(self) -> dict[str, str]:
        """Load tool capability guides from config/prompts/tools/.
        
        Returns:
            Dict mapping tool prefix to capability guide content
        """
        from olav.core.prompt_manager import prompt_manager
        
        guides = {}
        for tool_prefix in ["suzieq", "netbox", "cli", "netconf"]:
            guide = prompt_manager.load_tool_capability_guide(tool_prefix)
            if guide:
                guides[tool_prefix] = guide
                logger.debug(f"Loaded capability guide for: {tool_prefix}")
        
        return guides

    async def execute(
        self, user_query: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Execute Deep Path strategy for a complex query.

        Args:
            user_query: User's diagnostic question
            context: Optional context (network topology, device info, etc.)

        Returns:
            Dict with 'success', 'conclusion', 'reasoning_trace', 'metadata'
        """
        state = ReasoningState(original_query=user_query)

        try:
            # Step 1: Initial observation collection
            logger.info(f"Deep Path iteration {state.iteration}: Initial observation")
            await self._collect_initial_observations(state, context)

            # Reasoning loop
            while state.iteration < self.max_iterations:
                state.iteration += 1
                logger.info(f"Deep Path iteration {state.iteration}/{self.max_iterations}")

                # Step 2: Generate hypotheses
                await self._generate_hypotheses(state)

                if not state.hypotheses:
                    logger.warning("No hypotheses generated, concluding with current data")
                    break

                # Step 3: Select and verify best hypothesis
                state.current_hypothesis = state.hypotheses[0]  # Highest confidence

                logger.info(
                    f"Testing hypothesis: {state.current_hypothesis.description} "
                    f"(confidence: {state.current_hypothesis.confidence:.2f})"
                )

                await self._verify_hypothesis(state)

                # Step 4: Check if we can conclude
                if state.current_hypothesis.confidence >= self.confidence_threshold:
                    logger.info(
                        f"Hypothesis confidence {state.current_hypothesis.confidence:.2f} "
                        f"exceeds threshold {self.confidence_threshold}, concluding"
                    )
                    break

                # Step 5: Refine understanding (implicit in next iteration)

            # Synthesize final conclusion
            await self._synthesize_conclusion(state)

            return {
                "success": True,
                "conclusion": state.conclusion,
                "reasoning_trace": [
                    {
                        "step": obs.step_number,
                        "tool": obs.tool,
                        "interpretation": obs.interpretation,
                    }
                    for obs in state.observations
                ],
                "hypotheses_tested": [
                    {
                        "description": h.description,
                        "confidence": h.confidence,
                        "reasoning": h.reasoning,
                    }
                    for h in state.hypotheses
                ],
                "metadata": {
                    "strategy": "deep_path",
                    "iterations": state.iteration,
                    "final_confidence": state.confidence,
                    "total_observations": len(state.observations),
                },
            }

        except Exception as e:
            logger.exception(f"Deep Path execution failed: {e}")
            return {
                "success": False,
                "reason": "exception",
                "error": str(e),
                "reasoning_trace": [
                    {"step": obs.step_number, "interpretation": obs.interpretation}
                    for obs in state.observations
                ],
            }

    async def _discover_schema(self, user_query: str) -> dict[str, Any] | None:
        """
        Schema-Aware discovery: search schema to find correct tables/fields.
        
        This is CRITICAL for avoiding table name guessing errors.
        
        Args:
            user_query: User's natural language query
            
        Returns:
            Dict mapping table names to their schema info, or None if not applicable
        """
        try:
            schema_tool = self.tool_registry.get_tool("suzieq_schema_search")
            if not schema_tool:
                logger.debug("suzieq_schema_search tool not available")
                return None
            
            from olav.tools.base import ToolOutput
            result = await schema_tool.execute(query=user_query)
            
            if isinstance(result, ToolOutput) and result.data:
                schema_context = {}
                data = result.data
                
                if isinstance(data, dict):
                    tables = data.get('tables', [])
                    for table in tables:
                        if table in data:
                            schema_context[table] = data[table]
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and 'table' in item:
                            schema_context[item['table']] = item
                
                if schema_context:
                    logger.info(f"DeepPath schema discovery found: {list(schema_context.keys())}")
                    return schema_context
                    
            return None
            
        except Exception as e:
            logger.warning(f"Schema discovery failed: {e}")
            return None

    async def _collect_initial_observations(
        self, state: ReasoningState, context: dict[str, Any] | None = None
    ) -> None:
        """
        Collect initial observations to understand the problem.

        Uses Schema-Aware pattern: first discover available tables,
        then LLM decides what tools to call.
        """
        # Schema-Aware: discover correct table names first
        schema_context = await self._discover_schema(state.original_query)
        
        schema_section = ""
        if schema_context:
            schema_tables = "\n".join([
                f"    - {table}: {info.get('description', '')} (fields: {', '.join(info.get('fields', [])[:5])}...)"
                for table, info in schema_context.items()
            ])
            schema_section = f"""
## 🎯 Schema Discovery 结果（必须使用这些表名）
{schema_tables}
⚠️ 重要：请使用上述发现的表名，不要猜测或使用其他表名！
"""
        
        # Build capability guide section
        capability_guide = ""
        if self._tool_guides:
            guides_text = "\n\n".join([
                f"### {name.upper()} 工具\n{guide[:500]}..."  # Truncate for token efficiency
                for name, guide in self._tool_guides.items()
            ])
            capability_guide = f"""
## 工具能力指南
{guides_text}
"""
        
        context_str = ""
        if context:
            context_str = f"\n\n可用上下文: {context}"

        prompt = f"""你是 OLAV 网络诊断专家。用户提出了复杂的诊断问题，需要多步推理。

## 用户问题
{state.original_query}
{context_str}
{schema_section}
{capability_guide}
## 第一步：初始观察
确定需要收集哪些初始数据来理解问题。选择 1-2 个工具调用。

可用工具：
- suzieq_query: 查询网络状态（必须使用 Schema Discovery 中发现的表名）
- netbox_api_call: 查询设备信息、IP、配置
- cli_tool: 执行 CLI 命令
- netconf_tool: NETCONF get-config

返回 JSON 列表：
[
  {{"tool": "<工具名>", "parameters": {{"<参数名>": "<参数值>"}}, "reasoning": "<使用该工具的理由>"}}
]

⚠️ 如果使用 suzieq_query，必须使用 Schema Discovery 中发现的表名！
"""

        response = await self.llm.ainvoke([SystemMessage(content=prompt)])

        try:
            import json

            tool_calls = json.loads(response.content)

            for _i, call in enumerate(tool_calls):
                observation = ObservationStep(
                    step_number=len(state.observations) + 1,
                    tool=call["tool"],
                    parameters=call["parameters"],
                    interpretation=call.get("reasoning", ""),
                )

                # Execute tool
                tool_output = await self._execute_tool(call["tool"], call["parameters"])
                observation.tool_output = tool_output

                state.observations.append(observation)

        except Exception as e:
            logger.error(f"Failed to parse initial observation plan: {e}")
            # Fallback: use schema search to discover available tables
            observation = ObservationStep(
                step_number=1,
                tool="suzieq_schema_search",
                parameters={"query": state.original_query},
                interpretation="Fallback: discovering available tables via schema search",
            )
            state.observations.append(observation)

    async def _generate_hypotheses(self, state: ReasoningState) -> None:
        """
        Generate hypotheses based on observations.

        LLM analyzes collected data and proposes possible root causes.
        """
        # Serialize observations
        observations_text = "\n\n".join(
            [
                f"**观察 {obs.step_number}**: {obs.tool} → {obs.interpretation}\n"
                f"数据: {obs.tool_output.data[:3] if obs.tool_output and obs.tool_output.data else 'No data'}"
                for obs in state.observations
            ]
        )

        prompt = f"""你是 OLAV 网络诊断专家。基于观察到的数据，提出可能的根本原因假设。

## 原始问题
{state.original_query}

## 已收集的观察
{observations_text}

## 任务
分析数据，提出 2-3 个关于根本原因的假设。按置信度排序（最可能的在前）。

返回 JSON 列表：
[
  {{
    "description": "简洁的假设描述",
    "reasoning": "为什么这个假设合理（基于观察到的数据）",
    "verification_plan": "如何验证这个假设（需要什么工具和数据）",
    "confidence": 0.85
  }}
]
"""

        response = await self.llm.ainvoke([SystemMessage(content=prompt)])

        try:
            import json

            hypotheses_data = json.loads(response.content)

            state.hypotheses = [Hypothesis(**h) for h in hypotheses_data]

            # Sort by confidence
            state.hypotheses.sort(key=lambda h: h.confidence, reverse=True)

        except Exception as e:
            logger.error(f"Failed to parse hypotheses: {e}")
            # Fallback hypothesis
            state.hypotheses = [
                Hypothesis(
                    description="需要更多数据来确定根本原因",
                    reasoning="当前观察不足以形成确定性假设",
                    verification_plan="收集更多诊断数据",
                    confidence=0.3,
                )
            ]

    async def _verify_hypothesis(self, state: ReasoningState) -> None:
        """
        Verify the current hypothesis by executing verification plan.

        Uses Schema-Aware pattern to discover correct table names.
        """
        if not state.current_hypothesis:
            return

        # Schema-Aware: discover correct table names
        schema_context = await self._discover_schema(state.current_hypothesis.verification_plan)
        
        schema_section = ""
        if schema_context:
            schema_tables = "\n".join([
                f"    - {table}: {info.get('description', '')}"
                for table, info in schema_context.items()
            ])
            schema_section = f"""
## 🎯 Schema Discovery 结果（必须使用这些表名）
{schema_tables}
"""

        prompt = f"""你是 OLAV 网络诊断专家。现在需要验证一个假设。

## 假设
{state.current_hypothesis.description}

## 验证计划
{state.current_hypothesis.verification_plan}
{schema_section}

## 任务
根据验证计划，决定需要执行的工具调用。如果有 Schema Discovery 结果，使用发现的表名。

返回 JSON：
{{
  "tool": "<工具名>",
  "parameters": {{"<参数名>": "<参数值>"}},
  "reasoning": "<验证理由>"
}}

⚠️ 如果使用 suzieq_query，必须使用 Schema Discovery 中发现的表名！
"""

        response = await self.llm.ainvoke([SystemMessage(content=prompt)])

        try:
            import json

            verification = json.loads(response.content)

            observation = ObservationStep(
                step_number=len(state.observations) + 1,
                tool=verification["tool"],
                parameters=verification["parameters"],
                interpretation=verification.get("reasoning", ""),
            )

            # Execute tool
            tool_output = await self._execute_tool(verification["tool"], verification["parameters"])
            observation.tool_output = tool_output

            state.observations.append(observation)

            # Update hypothesis confidence based on results
            await self._update_hypothesis_confidence(state)

        except Exception as e:
            logger.error(f"Failed to verify hypothesis: {e}")

    async def _update_hypothesis_confidence(self, state: ReasoningState) -> None:
        """
        Update hypothesis confidence based on verification results.

        LLM analyzes whether verification supports or refutes hypothesis.
        """
        if not state.current_hypothesis:
            return

        latest_obs = state.observations[-1]

        prompt = f"""你是 OLAV 网络诊断专家。评估验证结果是否支持假设。

## 假设
{state.current_hypothesis.description}

## 验证结果
工具: {latest_obs.tool}
数据: {latest_obs.tool_output.data[:5] if latest_obs.tool_output and latest_obs.tool_output.data else "No data"}

## 任务
分析验证结果是否支持假设。更新置信度。

返回 JSON：
{{
  "supports_hypothesis": true,
  "updated_confidence": 0.9,
  "reasoning": "验证结果与假设一致，增加置信度"
}}
"""

        response = await self.llm.ainvoke([SystemMessage(content=prompt)])

        try:
            import json

            update = json.loads(response.content)

            if update.get("supports_hypothesis"):
                state.current_hypothesis.confidence = update["updated_confidence"]
            else:
                state.current_hypothesis.confidence *= 0.5  # Reduce confidence

            logger.info(
                f"Updated hypothesis confidence to {state.current_hypothesis.confidence:.2f}"
            )

        except Exception as e:
            logger.error(f"Failed to update hypothesis confidence: {e}")

    async def _synthesize_conclusion(self, state: ReasoningState) -> None:
        """
        Synthesize final conclusion from reasoning process.

        LLM creates human-readable answer based on all observations and hypotheses.
        """
        observations_text = "\n".join(
            [f"{obs.step_number}. {obs.tool}: {obs.interpretation}" for obs in state.observations]
        )

        hypotheses_text = "\n".join(
            [f"- {h.description} (置信度: {h.confidence:.2f})" for h in state.hypotheses]
        )

        prompt = f"""你是 OLAV 网络诊断专家。基于推理过程，回答用户的问题。

## 原始问题
{state.original_query}

## 推理过程
{observations_text}

## 测试的假设
{hypotheses_text}

## 任务
综合所有信息，回答用户问题。包括：
1. 根本原因（如果找到）
2. 支持证据
3. 建议的解决方案（如果适用）

返回 JSON：
{{
  "conclusion": "简洁明确的结论（2-3 段话）",
  "confidence": 0.9
}}
"""

        response = await self.llm.ainvoke([SystemMessage(content=prompt)])

        try:
            import json

            result = json.loads(response.content)

            state.conclusion = result["conclusion"]
            state.confidence = result["confidence"]

        except Exception as e:
            logger.error(f"Failed to synthesize conclusion: {e}")
            state.conclusion = f"基于 {len(state.observations)} 次观察，问题分析尚未完成。"
            state.confidence = 0.5

    async def _execute_tool(self, tool_name: str, parameters: dict[str, Any]) -> ToolOutput:
        """
        Execute a tool and return standardized output.

        Args:
            tool_name: Tool identifier (must be registered in ToolRegistry)
            parameters: Tool parameters

        Returns:
            ToolOutput from tool execution
        """
        if not self.tool_registry:
            logger.error("ToolRegistry not configured in DeepPathStrategy")
            return ToolOutput(
                source=tool_name,
                device="unknown",
                data=[],
                error="ToolRegistry not configured - cannot execute tools",
            )

        # Get tool from registry
        tool = self.tool_registry.get_tool(tool_name)
        if not tool:
            logger.error(f"Tool '{tool_name}' not found in ToolRegistry")
            available_tools = [t.name for t in self.tool_registry.list_tools()]
            return ToolOutput(
                source=tool_name,
                device="unknown",
                data=[],
                error=f"Tool '{tool_name}' not registered. Available: {', '.join(available_tools)}",
            )

        # Execute tool
        logger.debug(f"Executing tool '{tool_name}' with parameters: {parameters}")
        return await tool.execute(**parameters)

    def is_suitable(self, user_query: str) -> bool:
        """
        Check if query is suitable for Deep Path strategy.

        Args:
            user_query: User's query

        Returns:
            True if suitable for Deep Path, False otherwise
        """
        # Deep Path suitable for:
        # - "Why" questions (为什么)
        # - Diagnostic queries (诊断, troubleshoot)
        # - Multi-step analysis

        suitable_patterns = [
            "为什么",
            "why",
            "诊断",
            "diagnose",
            "排查",
            "troubleshoot",
            "分析",
            "analyze",
            "investigate",
            "调查",
        ]

        query_lower = user_query.lower()
        return any(pattern in query_lower for pattern in suitable_patterns)
