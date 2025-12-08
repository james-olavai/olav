"""Expert Mode Guard: Two-Layer Filtering Mechanism

Layer 1: Relevance Filter - Determine if this is a fault diagnosis request
Layer 2: Sufficiency Check - Extract and validate required diagnostic information
"""

import logging
from enum import Enum
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class QueryType(str, Enum):
    """User input type classification"""
    FAULT_DIAGNOSIS = "fault_diagnosis"     # Fault diagnosis -> Expert Mode
    SIMPLE_QUERY = "simple_query"           # Simple query -> Standard Mode
    CONFIG_CHANGE = "config_change"         # Config change -> Standard Mode
    OFF_TOPIC = "off_topic"                 # Non-network topic -> Reject


class SymptomType(str, Enum):
    """Fault symptom types"""
    CONNECTIVITY = "connectivity"           # Connectivity issues (ping/traceroute)
    PERFORMANCE = "performance"             # Performance issues (latency/packet loss)
    ROUTING = "routing"                     # Routing issues (route missing/flapping)
    PROTOCOL = "protocol"                   # Protocol issues (BGP down/OSPF neighbor)
    HARDWARE = "hardware"                   # Hardware issues (interface down/CRC)
    UNKNOWN = "unknown"                     # Unable to determine


class DiagnosisContext(BaseModel):
    """Diagnosis context - Structured information extracted from user input"""
    symptom: str = Field(description="Symptom description, e.g., 'unreachable', 'BGP neighbor down'")
    symptom_type: SymptomType = Field(default=SymptomType.UNKNOWN, description="Symptom classification")
    source_device: str | None = Field(default=None, description="Source device, e.g., 'R3'")
    target_device: str | None = Field(default=None, description="Target device/IP, e.g., '10.0.100.100'")
    protocol_hint: str | None = Field(default=None, description="Protocol hint, e.g., 'BGP', 'OSPF'")
    layer_hint: Literal["L1", "L2", "L3", "L4"] | None = Field(default=None, description="Layer hint")


class ExpertModeGuardResult(BaseModel):
    """Expert Mode Guard output"""
    query_type: QueryType = Field(description="Input type classification")
    is_fault_diagnosis: bool = Field(description="Whether this is a fault diagnosis request")
    is_sufficient: bool = Field(description="Whether information is sufficient to start diagnosis")
    missing_info: list[str] = Field(default_factory=list, description="List of missing information")
    clarification_prompt: str | None = Field(default=None, description="Prompt to ask user for clarification")
    context: DiagnosisContext | None = Field(default=None, description="Extracted diagnosis context")
    redirect_mode: Literal["standard"] | None = Field(default=None, description="Redirect target mode")


class LLMGuardDecision(BaseModel):
    """LLM structured decision output - Single call completes both layer checks"""

    # Layer 1: Relevance check
    query_type: QueryType = Field(description="User input type classification")
    query_type_reasoning: str = Field(description="Reasoning for classification")

    # Layer 2: Information extraction (only valid when query_type == fault_diagnosis)
    symptom: str | None = Field(default=None, description="Symptom description")
    symptom_type: SymptomType | None = Field(default=None, description="Symptom type")
    source_device: str | None = Field(default=None, description="Source device")
    target_device: str | None = Field(default=None, description="Target device/IP")
    protocol_hint: str | None = Field(default=None, description="Protocol hint")
    layer_hint: Literal["L1", "L2", "L3", "L4"] | None = Field(default=None, description="Layer hint")

    # Sufficiency check
    is_sufficient: bool = Field(default=False, description="Whether information is sufficient to start diagnosis")
    missing_info: list[str] = Field(default_factory=list, description="Missing required information")
    clarification_prompt: str | None = Field(default=None, description="Prompt to ask user")


GUARD_PROMPT_TEMPLATE = """You are a network fault diagnosis expert. Analyze user input to determine:
1. Is this a fault diagnosis request?
2. If yes, is the information sufficient to start diagnosis?

## Input Type Classification

- fault_diagnosis: Describes network fault symptoms, requires root cause diagnosis
  Examples: "R3 cannot reach 10.0.100.100", "BGP neighbor down", "interface errors", "route missing"

- simple_query: Query network status, no deep diagnosis needed
  Examples: "query R1 interface", "show all BGP neighbors", "what routes does R2 have"

- config_change: Configuration change request
  Examples: "configure OSPF area 0", "modify BGP neighbor", "add ACL"

- off_topic: Non-network related topic
  Examples: "what's the weather today", "write a poem"

## Symptom Type Classification

- connectivity: Connectivity issues (unreachable, ping fails, packet loss)
- performance: Performance issues (high latency, insufficient bandwidth)
- routing: Routing issues (route missing, route flapping, suboptimal path)
- protocol: Protocol issues (BGP down, OSPF neighbor lost)
- hardware: Hardware issues (interface down, CRC errors)
- unknown: Unable to determine

## Sufficiency Requirements

Fault diagnosis requires at minimum:
- symptom: Symptom description (required)
- source_device or target_device: At least one device/IP (required)

Optional but helpful for diagnosis:
- protocol_hint: Protocol type (BGP, OSPF, etc.)
- layer_hint: Possible layer of the problem (L1/L2/L3/L4)

## User Input

{user_query}

Please analyze and return a structured JSON decision."""


class ExpertModeGuard:
    """Expert Mode entry filter - Two-layer filtering mechanism

    Layer 1: Relevance Filter
        - fault_diagnosis -> Continue to Layer 2
        - simple_query/config_change -> Redirect to Standard Mode
        - off_topic -> Reject

    Layer 2: Sufficiency Check
        - Extract diagnosis context (symptom, devices, protocol)
        - Validate if required information is sufficient
        - Generate clarification prompt if insufficient
    """

    def __init__(self, llm: BaseChatModel) -> None:
        """Initialize Guard

        Args:
            llm: LangChain Chat Model instance
        """
        self.llm = llm.with_structured_output(LLMGuardDecision)
        self.prompt = ChatPromptTemplate.from_template(GUARD_PROMPT_TEMPLATE)

    async def check(self, user_query: str) -> ExpertModeGuardResult:
        """Check if user input is suitable for Expert Mode

        Args:
            user_query: User input query

        Returns:
            ExpertModeGuardResult:
                - is_fault_diagnosis=True, is_sufficient=True -> Start diagnosis
                - is_fault_diagnosis=True, is_sufficient=False -> Ask for clarification
                - is_fault_diagnosis=False -> Redirect to Standard Mode or reject
        """
        logger.info(f"[ExpertModeGuard] Checking query: {user_query[:50]}...")

        try:
            # Single LLM call completes both layer checks
            messages = self.prompt.format_messages(user_query=user_query)
            decision: LLMGuardDecision = await self.llm.ainvoke(messages)

            logger.info(f"[ExpertModeGuard] Decision: type={decision.query_type}, "
                       f"sufficient={decision.is_sufficient}")

            return self._build_result(decision)

        except Exception as e:
            logger.error(f"[ExpertModeGuard] LLM call failed: {e}")
            # Fail-open: Assume fault diagnosis with sufficient info
            return ExpertModeGuardResult(
                query_type=QueryType.FAULT_DIAGNOSIS,
                is_fault_diagnosis=True,
                is_sufficient=True,
                context=DiagnosisContext(
                    symptom=user_query,
                    symptom_type=SymptomType.UNKNOWN,
                ),
            )

    def check_sync(self, user_query: str) -> ExpertModeGuardResult:
        """Synchronous version of check method"""
        import asyncio
        return asyncio.run(self.check(user_query))

    def _build_result(self, decision: LLMGuardDecision) -> ExpertModeGuardResult:
        """Build result from LLM decision"""

        # Non-fault-diagnosis request -> Redirect or reject
        if decision.query_type != QueryType.FAULT_DIAGNOSIS:
            redirect_mode = None
            if decision.query_type in [QueryType.SIMPLE_QUERY, QueryType.CONFIG_CHANGE]:
                redirect_mode = "standard"

            return ExpertModeGuardResult(
                query_type=decision.query_type,
                is_fault_diagnosis=False,
                is_sufficient=False,
                redirect_mode=redirect_mode,
            )

        # Fault diagnosis request -> Build diagnosis context
        context = DiagnosisContext(
            symptom=decision.symptom or "Unknown fault",
            symptom_type=decision.symptom_type or SymptomType.UNKNOWN,
            source_device=decision.source_device,
            target_device=decision.target_device,
            protocol_hint=decision.protocol_hint,
            layer_hint=decision.layer_hint,
        )

        return ExpertModeGuardResult(
            query_type=QueryType.FAULT_DIAGNOSIS,
            is_fault_diagnosis=True,
            is_sufficient=decision.is_sufficient,
            missing_info=decision.missing_info,
            clarification_prompt=decision.clarification_prompt,
            context=context,
        )

    @staticmethod
    def get_redirect_message(query_type: QueryType) -> str:
        """Get redirect message"""
        messages = {
            QueryType.SIMPLE_QUERY: "This is a simple query request, will be handled by standard mode.",
            QueryType.CONFIG_CHANGE: "This is a configuration change request, will be handled by standard mode.",
            QueryType.OFF_TOPIC: "Sorry, this is not a network-related request.",
        }
        return messages.get(query_type, "Request type not recognized.")
