"""Agent Architecture Enhancement - Phase 3 Legacy (Task: Agent Architecture).

Implements advanced agent features:
1. QueryAgent tool access
2. IntentAgent intent extraction
3. SubAgent collaboration and pooling
4. Agent error recovery
"""

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QueryAgentTool:
    """Tool definition for QueryAgent."""

    name: str
    description: str = ""
    execute: Callable | None = None
    params: dict[str, str] = field(default_factory=dict)


class QueryAgent:
    """QueryAgent with tool access and execution."""

    def __init__(self) -> None:
        """Initialize QueryAgent."""
        self.tools: dict[str, QueryAgentTool] = {}
        self._executor = ThreadPoolExecutor(max_workers=5)

    def register_tool(self, tool: QueryAgentTool | Any) -> None:
        """Register a tool.

        Args:
            tool: Tool to register (QueryAgentTool or object with name/execute)
        """
        if isinstance(tool, QueryAgentTool):
            self.tools[tool.name] = tool
        elif hasattr(tool, "name"):
            self.tools[tool.name] = QueryAgentTool(
                name=tool.name,
                execute=getattr(tool, "execute", None),
            )
        else:
            logger.warning(f"Tool {tool} does not have required attributes")

    def get_available_tools(self) -> list[dict[str, Any]]:
        """Get all available tools.

        Returns:
            List of tool information dictionaries
        """
        return [
            {
                "name": name,
                "description": tool.description,
                "params": tool.params,
            }
            for name, tool in self.tools.items()
        ]

    def execute_query(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Execute query with specified tool.

        Args:
            tool_name: Name of tool to execute
            params: Tool parameters

        Returns:
            Query result
        """
        if tool_name not in self.tools:
            logger.warning(f"Tool not found: {tool_name}")
            return None

        tool = self.tools[tool_name]

        try:
            if tool.execute is None:
                logger.warning(f"Tool {tool_name} has no execute method")
                return None

            result = tool.execute(**params) if callable(tool.execute) else None
            logger.debug(f"Tool {tool_name} executed successfully")
            return result
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return None

    async def execute_query_async(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Execute query asynchronously.

        Args:
            tool_name: Name of tool to execute
            params: Tool parameters

        Returns:
            Query result
        """
        loop = asyncio.get_event_loop()

        try:
            result = await loop.run_in_executor(
                self._executor,
                lambda: self.execute_query(tool_name, params),
            )
            return result
        except Exception as e:
            logger.error(f"Async tool execution failed: {e}")
            return None

    def close(self) -> None:
        """Close executor."""
        self._executor.shutdown(wait=True)


@dataclass
class Intent:
    """Extracted intent from user input."""

    action: str
    intent_type: str = ""
    entities: list[dict[str, Any]] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


class IntentAgent:
    """IntentAgent for intent extraction."""

    def __init__(self) -> None:
        """Initialize IntentAgent."""
        self.intent_keywords = {
            "query": ["show", "list", "get", "find", "display", "what", "where"],
            "command": ["configure", "set", "enable", "disable", "reset", "create", "delete"],
            "help": ["help", "explain", "how", "describe"],
        }

    def extract_intent(self, user_input: str) -> dict[str, Any]:
        """Extract intent from user input.

        Args:
            user_input: User input string

        Returns:
            Intent information dictionary
        """
        user_input = user_input.lower().strip()

        # Detect intent type
        intent_type = self._detect_intent_type(user_input)

        # Extract action
        action = self._extract_action(user_input, intent_type)

        # Extract entities
        entities = self._extract_entities(user_input)

        # Calculate confidence
        confidence = self._calculate_confidence(user_input, intent_type)

        return {
            "action": action,
            "type": intent_type,
            "entities": entities,
            "confidence": confidence,
        }

    def _detect_intent_type(self, user_input: str) -> str:
        """Detect intent type from user input.

        Args:
            user_input: User input string

        Returns:
            Intent type (query, command, help, etc.)
        """
        words = user_input.split()

        for intent_type, keywords in self.intent_keywords.items():
            for keyword in keywords:
                if keyword in words:
                    return intent_type

        return "unknown"

    def _extract_action(self, user_input: str, intent_type: str) -> str:
        """Extract action from user input.

        Args:
            user_input: User input string
            intent_type: Detected intent type

        Returns:
            Action string
        """
        words = user_input.split()

        # First word is usually the action
        if len(words) > 0:
            return words[0]

        return "unknown"

    def _extract_entities(self, user_input: str) -> list[dict[str, Any]]:
        """Extract entities from user input.

        Args:
            user_input: User input string

        Returns:
            List of entity dictionaries
        """
        entities = []

        # Simple entity extraction (could be enhanced with NER)
        location_keywords = ["datacenter", "location", "site", "region"]
        device_keywords = ["device", "router", "switch", "interface"]

        words = user_input.split()

        for i, word in enumerate(words):
            for location_kw in location_keywords:
                if location_kw in word.lower():
                    entities.append(
                        {
                            "type": "location",
                            "value": word,
                            "position": i,
                        }
                    )

            for device_kw in device_keywords:
                if device_kw in word.lower():
                    entities.append(
                        {
                            "type": "device",
                            "value": word,
                            "position": i,
                        }
                    )

        return entities

    def _calculate_confidence(self, user_input: str, intent_type: str) -> float:
        """Calculate confidence score for extracted intent.

        Args:
            user_input: User input string
            intent_type: Detected intent type

        Returns:
            Confidence score (0.0-1.0)
        """
        # Simple confidence calculation
        if intent_type == "unknown":
            return 0.3

        # More words = more confidence (up to 1.0)
        word_count = len(user_input.split())
        confidence = min(0.5 + (word_count * 0.05), 0.95)

        return confidence


class SubAgentPool:
    """Pool of SubAgents for parallel task execution."""

    def __init__(self, max_agents: int = 5) -> None:
        """Initialize SubAgent pool.

        Args:
            max_agents: Maximum number of agents in pool
        """
        self.max_agents = max_agents
        self.agents: dict[str, Any] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_agents)
        self._available_agents: asyncio.Queue | None = None
        self._is_shutdown = False

    def create_agent(self, agent_id: str) -> Any:
        """Create agent in pool.

        Args:
            agent_id: Unique agent identifier

        Returns:
            Created agent
        """
        if len(self.agents) >= self.max_agents:
            logger.warning(f"Agent pool at capacity ({self.max_agents})")
            return None

        agent = {"id": agent_id, "state": "idle", "tasks": []}
        self.agents[agent_id] = agent
        logger.debug(f"Agent created: {agent_id}")
        return agent

    def get_agent(self, agent_id: str) -> Any | None:
        """Get agent by ID.

        Args:
            agent_id: Agent identifier

        Returns:
            Agent or None if not found
        """
        return self.agents.get(agent_id)

    def get_all_agents(self) -> list[Any]:
        """Get all agents in pool.

        Returns:
            List of agents
        """
        return list(self.agents.values())

    def acquire_agent(self) -> Any:
        """Acquire an agent from pool.

        Returns:
            Available agent or None if pool exhausted
        """
        for agent in self.agents.values():
            if agent["state"] == "idle":
                agent["state"] = "busy"
                return agent

        # If no idle agents, create new if room
        if len(self.agents) < self.max_agents:
            agent_id = f"agent_{len(self.agents)}"
            return self.create_agent(agent_id)

        return None

    def release_agent(self, agent: Any) -> None:
        """Release agent back to pool.

        Args:
            agent: Agent to release
        """
        if agent and "state" in agent:
            agent["state"] = "idle"
            agent["tasks"] = []

    def submit_task(self, task: Callable, *args) -> Future:
        """Submit task to pool.

        Args:
            task: Task function
            *args: Task arguments

        Returns:
            Future for task result
        """
        try:
            future = self._executor.submit(task, *args)
            return future
        except Exception as e:
            logger.error(f"Failed to submit task: {e}")
            return None

    async def submit_async_task(self, task: Coroutine, *args) -> Any:
        """Submit async task to pool.

        Args:
            task: Async task
            *args: Task arguments

        Returns:
            Task result
        """
        try:
            if asyncio.iscoroutinefunction(task):
                result = await task(*args)
            else:
                result = task(*args)
            return result
        except Exception as e:
            logger.error(f"Failed to execute async task: {e}")
            return None

    def shutdown(self) -> None:
        """Shutdown pool."""
        self._executor.shutdown(wait=True)
        self._is_shutdown = True
        logger.debug("Agent pool shutdown complete")

    @property
    def is_shutdown(self) -> bool:
        """Check if pool is shutdown.

        Returns:
            True if shutdown
        """
        return self._is_shutdown


class AgentErrorHandler:
    """Error handling and recovery for agents."""

    def __init__(self, max_failures: int = 5) -> None:
        """Initialize error handler.

        Args:
            max_failures: Max failures before circuit breaks
        """
        self.max_failures = max_failures
        self.error_count = 0
        self.failure_count = 0
        self._circuit_open = False
        self._last_error: Exception | None = None
        self._last_recovery: dict[str, Any] | None = None

    def handle_error(self, error: Exception, context: str | dict[str, Any] | None = None) -> None:
        """Handle error with context.

        Args:
            error: Exception that occurred
            context: Error context (string or dict)
        """
        self.error_count += 1
        self._last_error = error

        logger.error(f"Error handled: {error}, Context: {context}")

        # Update failure count
        self.failure_count += 1
        if self.failure_count >= self.max_failures:
            self._circuit_open = True
            logger.warning("Circuit breaker opened due to repeated failures")

    def create_recovery_plan(self, error: Exception) -> dict[str, Any]:
        """Create recovery plan for error.

        Args:
            error: Exception to recover from

        Returns:
            Recovery plan dictionary
        """
        recovery = {
            "action": "retry",
            "delay": 1.0,
            "max_retries": 3,
        }

        # Customize based on error type
        if isinstance(error, TimeoutError):
            recovery["action"] = "timeout_recovery"
            recovery["delay"] = 2.0
        elif isinstance(error, RuntimeError):
            recovery["action"] = "reset_state"
            recovery["delay"] = 0.5

        self._last_recovery = recovery
        return recovery

    def execute_with_retry(self, func: Callable, max_retries: int = 3) -> Any:
        """Execute function with retry logic.

        Args:
            func: Function to execute
            max_retries: Maximum retry attempts

        Returns:
            Function result or None on failure
        """
        for attempt in range(max_retries):
            try:
                result = func()
                self.failure_count = 0  # Reset on success
                return result
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                self.handle_error(e, f"retry_attempt_{attempt + 1}")

                if attempt < max_retries - 1:
                    time.sleep(0.5)

        return None

    def execute_with_timeout(self, func: Callable, timeout: float) -> Any:
        """Execute function with timeout.

        Args:
            func: Function to execute
            timeout: Timeout in seconds

        Returns:
            Function result or None on timeout
        """
        import threading

        result = [None]

        def wrapper() -> None:
            try:
                result[0] = func()
            except Exception as e:
                logger.error(f"Function failed: {e}")
                self.handle_error(e, "timeout_execution")

        thread = threading.Thread(target=wrapper, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            logger.warning(f"Function timed out after {timeout}s")
            self.handle_error(TimeoutError(f"Timeout after {timeout}s"), "timeout")
            return None

        return result[0]

    def execute_with_circuit_breaker(self, func: Callable) -> Any:
        """Execute function with circuit breaker pattern.

        Args:
            func: Function to execute

        Returns:
            Function result or None if circuit open
        """
        if self._circuit_open:
            logger.warning("Circuit breaker is open, rejecting call")
            return None

        try:
            result = func()
            self.failure_count = 0  # Reset on success
            return result
        except Exception as e:
            self.handle_error(e, "circuit_breaker")
            return None

    def is_circuit_open(self) -> bool:
        """Check if circuit is open.

        Returns:
            True if circuit is open
        """
        return self._circuit_open

    def get_last_recovery_plan(self) -> dict[str, Any] | None:
        """Get last recovery plan.

        Returns:
            Last recovery plan or None
        """
        return self._last_recovery


@dataclass
class AgentContext:
    """Execution context for agents."""

    agent_id: str
    state: str = "idle"
    timeout: float = 30.0
    _data: dict[str, Any] = field(default_factory=dict)
    _history: list[dict[str, Any]] = field(default_factory=list)
    _start_time: float = field(default_factory=time.time)

    def set_state(self, state: str) -> None:
        """Set agent state.

        Args:
            state: New state
        """
        self.state = state
        logger.debug(f"Agent {self.agent_id} state: {state}")

    def get_state(self) -> str:
        """Get current state.

        Returns:
            Current state
        """
        return self.state

    def store(self, key: str, value: Any) -> None:
        """Store data in context.

        Args:
            key: Data key
            value: Data value
        """
        self._data[key] = value

    def retrieve(self, key: str) -> Any | None:
        """Retrieve data from context.

        Args:
            key: Data key

        Returns:
            Data value or None
        """
        return self._data.get(key)

    def add_history_entry(self, event: str, details: dict[str, Any] | None = None) -> None:
        """Add history entry.

        Args:
            event: Event description
            details: Event details
        """
        entry = {
            "event": event,
            "timestamp": time.time(),
            "details": details or {},
        }
        self._history.append(entry)

    def get_history(self) -> list[dict[str, Any]]:
        """Get execution history.

        Returns:
            List of history entries
        """
        return self._history.copy()

    def is_expired(self) -> bool:
        """Check if context is expired.

        Returns:
            True if timeout exceeded
        """
        elapsed = time.time() - self._start_time
        return elapsed > self.timeout

    def cleanup(self) -> None:
        """Clean up context."""
        self._data.clear()
        self._history.clear()
        self.state = "idle"
        logger.debug(f"Agent {self.agent_id} context cleaned up")
