"""Query Router - 统一查询路由器.

分离架构:
- Guard (guard_rules.yaml): 安全检查 (规则 + LLM意图)
- Router (routing_rules.yaml): 查询路由 (斜杠命令 + 模式匹配 + LLM fallback)

P2优化: 路由决策缓存
- Guard检查结果缓存 (确定性结果)
- 白名单匹配缓存 (快速路径)
- 模式匹配缓存 (规则驱动)
"""

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from config.paths import GUARD_RULES_PATH, ROUTING_RULES_PATH

logger = logging.getLogger(__name__)


@dataclass
class RoutingDecision:
    """路由决策结果."""

    expert: str | None  # database, cli, analysis, None表示拒绝或需要审批
    action: str  # route, reject, require_approval
    tool: str | None = None  # 具体调用的工具
    params: dict[str, Any] | None = None  # 提取的参数
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

        # P2优化: 启动时缓存白名单配置 (避免每次route()都读YAML)
        self._whitelist_config = None
        self._load_whitelist_config()

    def _load_whitelist_config(self) -> None:
        """启动时加载白名单配置到内存.

        P2优化: 避免每次route()调用都从磁盘读取YAML文件
        """
        whitelist_file = Path(".olav/skills/guard/whitelist.yaml")
        if whitelist_file.exists():
            try:
                with open(whitelist_file) as f:
                    self._whitelist_config = yaml.safe_load(f) or {}
                logger.debug(
                    f"QueryRouter白名单已缓存 "
                    f"({len(self._whitelist_config.get('command_whitelist', {}))}条规则)"
                )
            except Exception as e:
                logger.warning(f"Failed to load whitelist config: {e}")
                self._whitelist_config = {}
        else:
            self._whitelist_config = {}

    def _get_routing_cache_key(self, user_input: str) -> str:
        """生成路由缓存键 (基于用户输入的hash).

        P2优化: 用于缓存相同输入的路由决策
        """
        import hashlib

        return hashlib.md5(user_input.strip().encode()).hexdigest()  # noqa: S324

    def _get_routing_cache(self, cache_key: str) -> RoutingDecision | None:
        """获取缓存的路由决策."""
        if not hasattr(self, "_routing_cache"):
            self._routing_cache = {}
        return self._routing_cache.get(cache_key)

    def _set_routing_cache(self, cache_key: str, decision: RoutingDecision) -> None:
        """缓存路由决策 (LRU: 最多缓存1000条).

        P2优化: 避免重复分析相同的输入
        """
        if not hasattr(self, "_routing_cache"):
            self._routing_cache = {}

        # 简单LRU实现: 超过1000条时清空
        if len(self._routing_cache) >= 1000:
            self._routing_cache.clear()
            logger.debug("QueryRouter缓存已满, 清空重置")

        self._routing_cache[cache_key] = decision

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

        timings = {}

        # P2优化: 检查路由缓存 (如果命中，跳过所有分析步骤)
        cache_key = self._get_routing_cache_key(user_input)
        cached_decision = self._get_routing_cache(cache_key)
        if cached_decision is not None:
            timings["cache_hit"] = 0.0001  # 缓存命中时间近乎为0
            cached_decision.timings = timings
            return cached_decision

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

        # Step 1.5: 命令白名单检查 (Tier 0.5 - 快速路径，最高优先级)
        # P2优化: 使用启动时缓存的白名单配置（避免每次都读YAML）
        start = time.time()
        if self._whitelist_config:
            try:
                command_whitelist = self._whitelist_config.get("command_whitelist", {})
                mode = self._whitelist_config.get("mode", "simple_match")

                if mode == "simple_match" and user_input.strip():
                    for pattern, sql_query in command_whitelist.items():
                        if re.match(pattern, user_input.strip()):
                            device = self._extract_device_from_pattern(pattern, user_input)
                            params = {"sql": sql_query, "device": device}

                            decision = RoutingDecision(
                                expert="database",
                                action="route",
                                tool="query_database",
                                params=params,
                                message=f"Whitelist match: {pattern}",
                            )
                            timings["whitelist"] = time.time() - start
                            decision.timings = timings
                            self._set_routing_cache(cache_key, decision)  # P2优化: 缓存决策
                            return decision
            except Exception as e:
                logger.debug(f"Whitelist check failed: {e}")  # 白名单检查失败不影响其他路径

        timings["whitelist"] = time.time() - start

        # Step 2: 斜杠命令检查
        if user_input.strip().startswith("/"):
            start = time.time()
            decision = self._handle_slash_command(user_input)
            timings["slash_command"] = time.time() - start
            decision.timings = timings
            self._set_routing_cache(cache_key, decision)  # P2优化: 缓存决策
            return decision

        # Step 3: 模式匹配 (规则驱动)
        start = time.time()
        pattern_match = self._match_patterns(user_input)
        timings["pattern_match"] = time.time() - start
        if pattern_match:
            pattern_match.timings = timings
            self._set_routing_cache(cache_key, pattern_match)  # P2优化: 缓存决策
            return pattern_match

        # Step 4: LLM意图分类 (fallback)
        start = time.time()
        llm_decision = self._classify_intent_with_llm(user_input)
        timings["llm_fallback"] = time.time() - start
        if llm_decision:
            llm_decision.timings = timings
            self._set_routing_cache(cache_key, llm_decision)  # P2优化: 缓存决策
            return llm_decision

        decision = RoutingDecision(
            expert="database",
            action="route",
            message="No pattern matched, defaulting to database expert",
            timings=timings,
        )
        self._set_routing_cache(cache_key, decision)  # P2优化: 缓存决策
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
            valid_experts = [
                "database",
                "cli",
                "analysis",
                "security-expert",
                "routing-expert",
                "switching-expert",
                "bgp-expert",
            ]
            if expert not in valid_experts:
                expert = "database"

            return RoutingDecision(
                expert=expert,
                action="route",
                intent=expert,
                message=f"LLM classified intent as {expert}",
            )
        except Exception:
            return None

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
                    protocol=protocol,
                    message=f"Pattern matched: {pattern_rule.get('tool', 'database')}",
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
