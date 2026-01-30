"""Query Router - 统一查询路由器.

分离架构:
- Guard (guard_rules.yaml): 安全检查 (规则 + LLM意图)
- Router (routing_rules.yaml): 查询路由 (斜杠命令 + 模式匹配 + LLM fallback)
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from config.paths import GUARD_RULES_PATH, ROUTING_RULES_PATH
from olav.core.unified_database import UnifiedDatabase


@dataclass
class RoutingDecision:
    """路由决策结果."""

    expert: str | None  # database, cli, analysis, None表示拒绝或需要审批
    action: str  # route, reject, require_approval
    tool: str | None = None  # 具体调用的工具
    params: dict[str, Any] | None = None  # 提取的参数
    fallback: str | None = None  # 回落策略 (cli, None)
    message: str | None = None  # 提示消息
    intent: str | None = None  # LLM分类的意图 (query, analysis, etc.)
    protocol: str | None = None  # Phase 15: 意图遮罩 (ospf, bgp, interface)
    timings: dict[str, float] | None = None  # 性能监控：各步骤耗时（秒）


@dataclass
class GuardResult:
    """Guard检查结果."""

    action: str  # pass, reject, require_approval, warn
    message: str | None = None
    matched_pattern: str | None = None
    severity: str | None = None  # critical, high, medium, low
    intent: str | None = None  # LLM分类的意图


class Guard:
    """安全守卫 - 规则检查 + LLM意图分类."""

    def __init__(self, config_path: str | Path | None = None, language: str = "zh") -> None:
        """初始化Guard.

        Args:
            config_path: guard_rules.yaml路径
            language: 消息语言 ("zh" or "en")
        """
        if config_path is None:
            config_path = GUARD_RULES_PATH
        else:
            config_path = Path(config_path)

        self.rules: dict[str, Any] = {}
        self.language = language
        if config_path.exists():
            with open(config_path) as f:
                self.rules = yaml.safe_load(f) or {}

    def _get_message(self, message_dict: str | dict[str, str], **kwargs: str) -> str:
        """获取本地化消息.

        Args:
            message_dict: 消息字符串或字典 {"en": "...", "zh": "..."}
            **kwargs: 格式化参数

        Returns:
            格式化后的消息
        """
        if isinstance(message_dict, str):
            return message_dict.format(**kwargs)

        # 支持中英文
        msg = message_dict.get(self.language, message_dict.get("en", ""))
        return msg.format(**kwargs)

    def check(self, user_input: str) -> GuardResult:
        """检查用户输入是否安全.

        Args:
            user_input: 用户输入

        Returns:
            GuardResult: 检查结果
        """
        # Step 1: 白名单检查 - 快速放行
        if self._is_whitelisted(user_input):
            return GuardResult(action="pass")

        # Step 2: 正则规则检查 - 快速确定性检查
        pattern_result = self._check_patterns(user_input)
        if pattern_result.action != "pass":
            return pattern_result

        # Step 3: LLM意图分类 (可选, 复杂场景)
        llm_config = self.rules.get("llm_classification", {})
        if llm_config.get("enabled", False) and not llm_config.get("fallback_only", True):
            # TODO: 实现LLM意图分类
            pass

        return GuardResult(action="pass")

    def _is_whitelisted(self, user_input: str) -> bool:
        """检查是否在白名单中."""
        whitelist = self.rules.get("whitelist", {})
        prefixes = whitelist.get("command_prefixes", [])

        # 检查命令前缀
        input_lower = user_input.lower().strip()
        for prefix in prefixes:
            if input_lower.startswith(prefix.lower()):
                return True

        return False

    def _check_patterns(self, user_input: str) -> GuardResult:
        """检查正则规则."""
        patterns = self.rules.get("patterns", {})

        # 检查所有规则类别
        for _category, rules in patterns.items():
            for rule in rules:
                pattern = rule.get("pattern", "")
                if re.search(pattern, user_input, re.IGNORECASE):
                    message = self._get_message(rule.get("message", ""), matched=user_input)
                    return GuardResult(
                        action=rule.get("action", "reject"),
                        message=message,
                        matched_pattern=pattern,
                        severity=rule.get("severity"),
                    )

        return GuardResult(action="pass")


class QueryRouter:
    """问题路由器 - 查询路由 (不含Guard)."""

    def __init__(
        self,
        config_path: str | Path | None = None,
        guard: Guard | None = None,
    ) -> None:
        """初始化路由器.

        Args:
            config_path: routing_rules.yaml路径
            guard: Guard实例，如果为None则自动创建
        """
        if config_path is None:
            config_path = ROUTING_RULES_PATH
        else:
            config_path = Path(config_path)

        if not config_path.exists():
            raise FileNotFoundError(
                f"Routing rules not found: {config_path}\n"
                "Please ensure .olav/config/routing_rules.yaml exists"
            )

        with open(config_path) as f:
            self.rules = yaml.safe_load(f)

        # 初始化Guard (独立的安全检查)
        self.guard = guard if guard is not None else Guard()

        # Lazy initialization for semantic components
        self.embedder = None
        self.expert_index = None
        self.semantic_threshold = self.rules.get("semantic_cache", {}).get("threshold", 0.9)

    def check_guard(self, user_input: str) -> GuardResult:
        """检查用户输入是否安全.

        Args:
            user_input: 用户输入

        Returns:
            GuardResult: 检查结果
        """
        return self.guard.check(user_input)

    def route(self, user_input: str) -> RoutingDecision:
        """路由用户输入到合适的专家.

        Args:
            user_input: 用户输入的问题或命令

        Returns:
            RoutingDecision: 路由决策结果
        """
        import time
        timings = {}

        # Step 1: Guard检查 (最高优先级, 使用独立Guard)
        start = time.time()
        guard_result = self.guard.check(user_input)
        timings["guard"] = time.time() - start

        if guard_result.action == "reject":
            decision = RoutingDecision(
                expert=None,
                action="reject",
                message=guard_result.message,
                timings=timings,
            )
            return decision
        if guard_result.action == "require_approval":
            decision = RoutingDecision(
                expert=None,
                action="require_approval",
                message=guard_result.message,
                timings=timings,
            )
            return decision

        # Step 2: 斜杠命令检查
        if user_input.strip().startswith("/"):
            start = time.time()
            decision = self._handle_slash_command(user_input)
            timings["slash_command"] = time.time() - start
            decision.timings = timings
            return decision

        # Tier 0: Semantic Cache (向量匹配历史成功查询)
        start = time.time()
        semantic_decision = self._check_semantic_cache(user_input)
        timings["semantic_cache"] = time.time() - start
        if semantic_decision:
            semantic_decision.timings = timings
            return semantic_decision

        # Step 3: 模式匹配 (规则驱动)
        start = time.time()
        pattern_match = self._match_patterns(user_input)
        timings["pattern_match"] = time.time() - start
        if pattern_match:
            pattern_match.timings = timings
            return pattern_match

        # Tier 1: Neural Router (向量匹配专家描述)
        start = time.time()
        neural_decision = self._check_neural_router(user_input)
        timings["neural_router"] = time.time() - start
        if neural_decision:
            neural_decision.timings = timings
            return neural_decision

        # Step 4: LLM意图分类 (fallback)
        start = time.time()
        llm_decision = self._classify_intent_with_llm(user_input)
        timings["llm_fallback"] = time.time() - start
        if llm_decision:
            llm_decision.timings = timings
            return llm_decision

        decision = RoutingDecision(
            expert="database",
            action="route",
            message="No pattern matched, defaulting to database expert",
            timings=timings,
        )
        return decision

    def _classify_intent_with_llm(self, user_input: str) -> RoutingDecision | None:
        """Use LLM to classify intent if patterns fail."""
        try:
            from olav.core.llm import LLMFactory

            model = LLMFactory.get_chat_model()
            prompt = f"""Classify the user intent for a network assistant.
Available experts: database, cli, analysis, security-expert, routing-expert, switching-expert, bgp-expert.

User Input: "{user_input}"

Return only the expert name as a single word. If unsure, return 'database'."""

            response = model.invoke(prompt)
            expert = str(response.content).strip().lower()

            # Basic validation
            valid_experts = ["database", "cli", "analysis", "security-expert", "routing-expert", "switching-expert", "bgp-expert"]
            if expert not in valid_experts:
                expert = "database"

            return RoutingDecision(
                expert=expert,
                action="route",
                intent=expert,
                message=f"LLM classified intent as {expert}"
            )
        except Exception:
            return None

    def _check_semantic_cache(self, user_input: str) -> RoutingDecision | None:
        """Check if query exists in vector semantic cache (Tier 0)."""
        if not self.embedder:
            # Lazy init
            from olav.core.embeddings import get_embedder
            self.embedder = get_embedder()

        embedding = self.embedder.embed_query(user_input)
        if not embedding:
            return None

        try:
            with UnifiedDatabase() as db:
                # Search for similar queries using vector distance (cosine similarity)
                # DuckDB array_cosine_similarity returns -1 to 1. We want > threshold.
                # Optimized: Added WHERE clause to enable early termination
                sql = f"""
                    SELECT
                        query_text,
                        action_json,
                        array_cosine_similarity(query_embedding::FLOAT[{len(embedding)}], ?::FLOAT[{len(embedding)}]) as similarity
                    FROM commands.main.semantic_cache
                    WHERE array_cosine_similarity(query_embedding::FLOAT[{len(embedding)}], ?::FLOAT[{len(embedding)}]) >= ?
                    ORDER BY similarity DESC
                    LIMIT 1
                """
                # Handle empty table gracefully via try/except in execution or result check
                try:
                    result = db.query(sql, [embedding, embedding, self.semantic_threshold])
                except Exception:
                    # Table might not exist or be empty
                    return None

                if result:
                    query_text, action_json, similarity = result[0]
                    # Note: similarity already >= threshold due to WHERE clause
                    import json
                    action = json.loads(action_json) if isinstance(action_json, str) else action_json
                    return RoutingDecision(
                        expert=action.get("expert"),
                        action="route",
                        tool=action.get("tool"),
                        params=action.get("params"),
                        message="Semantic cache hit! (Tier 0)",
                        intent=action.get("intent")
                    )
        except Exception:
            pass

        return None

    def _check_neural_router(self, user_input: str) -> RoutingDecision | None:
        """Tier 1: Semantic matching against expert capabilities."""
        try:
            from olav.core.embeddings import get_embedder

            if self.embedder is None:
                self.embedder = get_embedder()

            # Build expert index if not exists
            if self.expert_index is None:
                self._build_expert_index()

            if not self.expert_index:
                return None

            query_vec = self.embedder.embed_query(user_input)

            # Match
            best_score = -1.0
            best_expert = None

            for expert_name, expert_vec in self.expert_index.items():
                score = self._cosine_similarity(query_vec, expert_vec)
                if score > best_score:
                    best_score = score
                    best_expert = expert_name

            # Threshold for Tier 1 matching (0.8)
            if best_score > 0.8:
                return RoutingDecision(
                    expert=best_expert,
                    action="route",
                    intent=best_expert,
                    message=f"Neural router matched expert: {best_expert} (Tier 1, score: {best_score:.2f})"
                )
        except Exception:
            pass
        return None

    def _build_expert_index(self) -> None:
        """Build vector index for all available experts."""
        try:
            experts = self.rules.get("experts", {})
            self.expert_index = {}

            texts_to_embed = []
            expert_names = []

            for name, cfg in experts.items():
                desc = cfg.get("description", "")
                tools = ", ".join(cfg.get("tools", []))
                # Add descriptive context for embedding
                full_desc = f"Expert: {name}. Matches queries about: {desc}. Tools available: {tools}."
                texts_to_embed.append(full_desc)
                expert_names.append(name)

            if texts_to_embed:
                embeddings = self.embedder.embed_documents(texts_to_embed) # type: ignore
                self.expert_index = dict(zip(expert_names, embeddings))
        except Exception:
            self.expert_index = {}

    def _cosine_similarity(self, v1: list[float], v2: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        dot_product = sum(a * b for a, b in zip(v1, v2))
        magnitude1 = sum(a * a for a in v1) ** 0.5
        magnitude2 = sum(b * b for b in v2) ** 0.5
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
        return dot_product / (magnitude1 * magnitude2)

    def _handle_slash_command(self, user_input: str) -> RoutingDecision:
        """处理斜杠命令.

        Args:
            user_input: 用户输入的斜杠命令

        Returns:
            RoutingDecision: 路由决策
        """
        command = user_input.split()[0]  # 提取命令部分
        slash_commands = self.rules.get("slash_commands", {})

        if command == "/analyze":
            cmd_config = slash_commands.get("/analyze", {})
            return RoutingDecision(
                expert=cmd_config.get("expert", "analysis"),
                action="route",
                tool="analyze",  # 将路由到/analyze命令处理器
                params={"command_text": user_input},
            )

        # 其他系统命令由CLI原生处理
        return RoutingDecision(
            expert=None,
            action="system_command",
            tool=command,
            message=f"System command: {command}",
        )

    def _match_patterns(self, user_input: str) -> RoutingDecision | None:
        """模式匹配 (Enhanced with Protocol Detection).

        Args:
            user_input: 用户输入

        Returns:
            RoutingDecision | None: 匹配结果，无匹配返回None
        """
        patterns = self.rules.get("patterns", {})

        # Phase 17: Zero-Hardcode (Protocol detection is handled dynamically by SQL-Graph)
        protocol = None

        # 检查CLI必需模式
        for pattern_rule in patterns.get("cli_required", []):
            pattern = pattern_rule["pattern"]
            if re.search(pattern, user_input, re.IGNORECASE):
                return RoutingDecision(
                    expert="cli",
                    action="route",
                    message=pattern_rule.get("reason"),
                    protocol=protocol,
                )

        # 检查DB优先模式
        for pattern_rule in patterns.get("database_first", []):
            pattern = pattern_rule["pattern"]
            match = re.search(pattern, user_input, re.IGNORECASE)
            if match:
                # 提取参数
                params: dict[str, Any] | None = None
                if "extract" in pattern_rule:
                    # Prefer first capturing group if available, otherwise full match
                    extract_key = pattern_rule["extract"]
                    if match.groups():
                        params = {extract_key: match.group(1)}
                    else:
                        params = {extract_key: match.group(0)}

                # Phase 2.2: Support precompiled SQL for fast execution
                if "precompiled_sql" in pattern_rule:
                    if params is None:
                        params = {}
                    # Replace ? with extracted parameter value
                    precompiled_sql = pattern_rule["precompiled_sql"]
                    if params and "?" in precompiled_sql:
                        # Get the first (and should be only) parameter value
                        param_value = list(params.values())[0]
                        params["sql"] = precompiled_sql.replace("?", f"'{param_value}'")

                return RoutingDecision(
                    expert="database",
                    action="route",
                    tool=pattern_rule.get("tool"),
                    params=params,
                    fallback=pattern_rule.get("fallback"),
                    protocol=protocol,
                    message=f"Pattern matched: {pattern_rule.get('tool', 'database')}"
                )

        return None

    def get_expert_config(self, expert_name: str) -> dict[str, Any]:
        """获取专家配置.

        Args:
            expert_name: 专家名称 (database, cli, analysis)

        Returns:
            dict: 专家配置
        """
        experts = self.rules.get("experts", {})
        return experts.get(expert_name, {})

    def should_fallback_to_cli(
        self, db_result: list | dict | None, completeness_threshold: float = 0.7
    ) -> tuple[bool, str]:
        """检查是否应该回落到CLI.

        Args:
            db_result: 数据库查询结果
            completeness_threshold: 数据完整性阈值

        Returns:
            tuple[bool, str]: (是否回落, 原因)
        """
        # 如果结果为空，回落到CLI
        if not db_result or (isinstance(db_result, (list, dict)) and len(db_result) == 0):
            return True, "Database returned no results"

        # 检查数据完整性 (简单实现: 检查None值比例)
        if isinstance(db_result, list):
            total_fields = 0
            none_fields = 0
            for item in db_result:
                if isinstance(item, dict):
                    for value in item.values():
                        total_fields += 1
                        if value is None:
                            none_fields += 1

            if total_fields > 0:
                completeness = 1 - (none_fields / total_fields)
                if completeness < completeness_threshold:
                    return (
                        True,
                        f"Data incomplete ({completeness:.1%} < {completeness_threshold:.1%})",
                    )

        return False, "Data is complete"

    def get_fallback_strategy(self) -> dict[str, Any]:
        """获取回落策略配置.

        Returns:
            dict: 回落策略配置
        """
        return self.rules.get("fallback", {})
