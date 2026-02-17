#!/usr/bin/env python3
"""
Intelligent Inspection Command Resolver (v3.0)
===============================================

Intent-based command selection - Agent自动从SKILL.md读取检查项

New Architecture (v3.0):
1. User defines inspection_items in SKILL.md (WHAT to check)
2. Agent reads SKILL.md, infers keywords from item names
3. Query NTC templates database for best command
4. Return platform-specific commands automatically

NO HARDCODED COMMANDS! NO COMPLEX YAML CONFIGS!

Usage:
    resolver = InspectionCommandResolver()
    
    # Get commands for template
    commands = resolver.resolve_template("standard", device_platform="cisco_ios")
    # Returns: ["show version", "show processes cpu", "show interfaces", ...]
    
    # Get commands for specific items
    commands = resolver.resolve_items(
        items=["cpu_utilization", "interface_status"],
        device_platform="cisco_nxos"
    )
"""

import logging
import yaml
import frontmatter
from pathlib import Path
from typing import Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ResolvedCommand:
    """Resolved command with metadata"""
    command: str
    intent: str
    platform: str
    source: str  # "ntc" or "fallback"
    template_name: str | None = None
    confidence: float = 0.0  # 0.0-1.0


class InspectionCommandResolver:
    """
    Intelligent command resolver using NTC templates database.
    
    New in v3.0:
    - Reads inspection_items from SKILL.md (not inspection_intents.yaml)
    - Auto-infers keywords from item names
    - Simpler configuration, more automation
    
    Workflow:
    1. Load SKILL.md → Parse inspection_items
    2. For each item, infer keywords from name/description
    3. Search NTC templates by platform + keywords
    4. Return best matching command
    5. Fallback to common commands if NTC fails
    """
    
    def __init__(self):
        self.skill_path = Path(".olav/skills/network-inspection/SKILL.md")
        self.thresholds_path = Path(".olav/skills/network-inspection/config/thresholds.yaml")
        self.config = self._load_skill_config()
        self.ntc_path = self._find_ntc_path()
        
    def _load_skill_config(self) -> dict:
        """Load inspection_items from SKILL.md"""
        if not self.skill_path.exists():
            logger.error(f"SKILL.md not found: {self.skill_path}")
            return {"inspection_items": [], "templates": {}}
            
        with open(self.skill_path, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)
            
        return {
            "inspection_items": post.metadata.get("inspection_items", []),
            "templates": post.metadata.get("templates", {})
        }
    
    def _infer_keywords_from_name(self, item_name: str) -> list[str]:
        """
        Infer NTC search keywords from item name.
        
        Examples:
            "cpu_utilization" → ["cpu", "processes"]
            "interface_status" → ["interface", "status"]
            "ospf_neighbors" → ["ospf", "neighbor"]
        """
        # Common keyword mappings
        KEYWORD_MAP = {
            "cpu_utilization": ["cpu", "processes"],
            "memory_utilization": ["memory"],
            "environment": ["environment", "temperature"],
            "interface_status": ["interface", "status"],
            "interface_errors": ["interface", "error"],
            "neighbor_discovery": ["cdp", "lldp", "neighbor"],
            "mac_address_table": ["mac", "address-table"],
            "routing_table": ["route", "routing"],
            "ospf_neighbors": ["ospf", "neighbor"],
            "bgp_neighbors": ["bgp", "neighbor"],
            "arp_table": ["arp"],
            "device_info": ["version", "inventory"],
        }
        
        # Return mapped keywords or parse from name
        if item_name in KEYWORD_MAP:
            return KEYWORD_MAP[item_name]
        
        # Fallback: split by underscore
        return item_name.replace("_", " ").split()
    
    def _infer_required_fields(self, item_name: str) -> list[str]:
        """
        Infer required output fields from item name.
        
        Examples:
            "cpu_utilization" → ["cpu_percent", "cpu_5min"]
            "interface_status" → ["interface", "status"]
        """
        FIELD_MAP = {
            "cpu_utilization": ["cpu_percent", "cpu_5sec", "cpu_1min", "cpu_5min"],
            "memory_utilization": ["memory_percent", "memory_used", "memory_free"],
            "interface_status": ["interface", "status", "protocol"],
            "interface_errors": ["interface", "in_errors", "out_errors", "crc_errors"],
            "ospf_neighbors": ["neighbor_id", "state", "interface"],
            "bgp_neighbors": ["neighbor", "as_number", "state"],
            "routing_table": ["network", "mask", "next_hop"],
            "device_info": ["vendor", "model", "version", "serial"],
        }
        
        return FIELD_MAP.get(item_name, [item_name])

    
    def _find_ntc_path(self) -> Path | None:
        """Locate NTC templates directory"""
        try:
            import ntc_templates
            return Path(ntc_templates.__file__).parent / "templates"
        except ImportError:
            logger.warning("ntc-templates not installed, using fallback commands only")
            return None
    
    def _search_ntc_command(
        self,
        platform: str,
        keywords: list[str],
        required_fields: list[str]
    ) -> ResolvedCommand | None:
        """
        Search NTC templates for best matching command.
        
        Args:
            platform: Device platform (cisco_ios, cisco_nxos, etc.)
            keywords: Command keywords from intent (["cpu", "processes"])
            required_fields: Required output fields (["cpu_percent", "cpu_5min"])
            
        Returns:
            ResolvedCommand or None if not found
        """
        if not self.ntc_path or not self.ntc_path.exists():
            return None
        
        # Search templates matching platform
        platform_templates = list(self.ntc_path.glob(f"{platform}_*.textfsm"))
        
        if not platform_templates:
            logger.debug(f"No NTC templates found for platform: {platform}")
            return None
        
        best_match = None
        best_score = 0.0
        
        for template_path in platform_templates:
            template_name = template_path.name
            
            # Extract command from filename
            # Example: cisco_ios_show_processes_cpu.textfsm → "show processes cpu"
            command_parts = template_name.replace(f"{platform}_", "").replace(".textfsm", "").split("_")
            command = " ".join(command_parts)
            
            # Calculate score
            score = 0.0
            
            # Keyword matching (70% weight)
            matched_keywords = sum(1 for kw in keywords if kw.lower() in command.lower())
            if keywords:
                keyword_score = matched_keywords / len(keywords)
                score += keyword_score * 0.7
            
            # Field matching (30% weight) - would need to parse template
            # For now, use simple heuristic: if command contains field name
            matched_fields = sum(1 for field in required_fields if any(part in field.lower() for part in command.lower().split()))
            if required_fields:
                field_score = min(matched_fields / len(required_fields), 1.0)
                score += field_score * 0.3
            
            if score > best_score:
                best_score = score
                best_match = ResolvedCommand(
                    command=command,
                    intent="",  # Will be set by caller
                    platform=platform,
                    source="ntc",
                    template_name=template_name,
                    confidence=score
                )
        
        return best_match if best_score >= 0.3 else None  # Minimum threshold
    
    def _get_fallback_command(
        self,
        platform: str,
        item_name: str
    ) -> ResolvedCommand | None:
        """
        Get fallback command (v3.0: simplified, no complex config).
        
        Common fallback commands for popular items.
        """
        # Common fallback mappings (platform-agnostic where possible)
        FALLBACKS = {
            "cisco_ios": {
                "device_info": "show version",
                "cpu_utilization": "show processes cpu",
                "memory_utilization": "show processes memory",
                "environment": "show environment",
                "interface_status": "show interfaces",
                "interface_errors": "show interfaces",
                "neighbor_discovery": "show cdp neighbors",
                "mac_address_table": "show mac address-table",
                "routing_table": "show ip route",
                "ospf_neighbors": "show ip ospf neighbor",
                "bgp_neighbors": "show ip bgp summary",
                "arp_table": "show arp",
            },
            "cisco_nxos": {
                "device_info": "show version",
                "cpu_utilization": "show processes cpu",
                "interface_status": "show interface",
                "ospf_neighbors": "show ip ospf neighbor",
                "bgp_neighbors": "show ip bgp summary",
            },
            "juniper_junos": {
                "device_info": "show version",
                "cpu_utilization": "show chassis routing-engine",
                "interface_status": "show interfaces terse",
                "ospf_neighbors": "show ospf neighbor",
                "bgp_neighbors": "show bgp summary",
            }
        }
        
        fallback_cmd = FALLBACKS.get(platform, {}).get(item_name)
        
        if not fallback_cmd:
            logger.debug(f"No fallback for '{item_name}' on {platform}")
            return None
        
        return ResolvedCommand(
            command=fallback_cmd,
            intent=item_name,
            platform=platform,
            source="fallback",
            template_name=None,
            confidence=0.5  # Lower confidence for fallbacks
        )
    
    def resolve_item(
        self,
        item_name: str,
        device_platform: str
    ) -> ResolvedCommand | None:
        """
        Resolve inspection item to command (New in v3.0).
        
        Args:
            item_name: Inspection item name from SKILL.md (e.g., "cpu_utilization")
            device_platform: Device platform (e.g., "cisco_ios")
            
        Returns:
            ResolvedCommand or None if cannot resolve
            
        Example:
            >>> resolver.resolve_item("cpu_utilization", "cisco_ios")
            ResolvedCommand(command="show processes cpu", source="ntc", confidence=0.85)
        """
        # Check if item exists in SKILL.md
        items = self.config.get("inspection_items", [])
        item_config = next((item for item in items if item["name"] == item_name), None)
        
        if not item_config:
            logger.error(f"Unknown inspection item: {item_name}")
            return None
        
        # Infer keywords and fields from item name
        keywords = self._infer_keywords_from_name(item_name)
        required_fields = self._infer_required_fields(item_name)
        
        logger.debug(f"Item '{item_name}': keywords={keywords}, fields={required_fields}")
        
        # Try NTC search first
        resolved = self._search_ntc_command(device_platform, keywords, required_fields)
        
        if resolved:
            resolved.intent = item_name
            logger.info(f"✓ Resolved '{item_name}' on {device_platform}: {resolved.command} (confidence: {resolved.confidence:.2f}, source: NTC)")
            return resolved
        
        # Fallback to common commands
        resolved = self._get_fallback_command(device_platform, item_name)
        
        if resolved:
            resolved.intent = item_name
            logger.info(f"✓ Resolved '{item_name}' on {device_platform}: {resolved.command} (source: fallback)")
            return resolved
        
        logger.warning(f"✗ Cannot resolve '{item_name}' on {device_platform}")
        return None
    
    # Alias for backward compatibility
    def resolve_intent(self, intent_name: str, device_platform: str) -> ResolvedCommand | None:
        """Backward compatibility alias for resolve_item"""
        return self.resolve_item(intent_name, device_platform)
    
    def resolve_items(
        self,
        items: list[str],
        device_platform: str
    ) -> list[ResolvedCommand]:
        """
        Resolve multiple inspection items to commands (v3.0).
        
        Args:
            items: List of inspection item names from SKILL.md
            device_platform: Device platform
            
        Returns:
            List of ResolvedCommand objects
            
        Example:
            >>> resolver.resolve_items(["cpu_utilization", "interface_status"], "cisco_ios")
            [ResolvedCommand(...), ResolvedCommand(...)]
        """
        resolved_commands = []
        
        for item_name in items:
            resolved = self.resolve_item(item_name, device_platform)
            if resolved:
                resolved_commands.append(resolved)
        
        return resolved_commands
    
    # Backward compatibility alias
    def resolve_intents(self, intents: list[str], device_platform: str) -> list[ResolvedCommand]:
        """Backward compatibility alias for resolve_items"""
        return self.resolve_items(intents, device_platform)
    
    def resolve_template(
        self,
        template_name: str,
        device_platform: str
    ) -> list[ResolvedCommand]:
        """
        Resolve inspection template to commands (v3.0: from SKILL.md).
        
        Args:
            template_name: Template name (quick, basic, standard, full, etc.)
            device_platform: Device platform
            
        Returns:
            List of ResolvedCommand objects
            
        Example:
            >>> resolver.resolve_template("standard", "cisco_ios")
            [ResolvedCommand(...), ...]  # ~15 commands
        """
        templates = self.config.get("templates", {})
        
        if template_name not in templates:
            logger.error(f"Unknown template: {template_name}")
            return []
        
        template_config = templates[template_name]
        
        # Support both 'items' (v3.0) and 'intents' (backward compat)
        items = template_config.get("items", template_config.get("intents", []))
        
        # Handle "all" - expand to all inspection_items
        if items == "all":
            all_items = self.config.get("inspection_items", [])
            items = [item["name"] for item in all_items]
        
        logger.info(f"Resolving template '{template_name}' for {device_platform}...")
        logger.info(f"  Description: {template_config.get('description')}")
        logger.info(f"  Estimated time: {template_config.get('estimated_time')}")
        logger.info(f"  Items: {len(items)}")
        
        return self.resolve_items(items, device_platform)
    
    def get_command_strings(
        self,
        template_name: str,
        device_platform: str
    ) -> list[str]:
        """
        Convenience method: Get plain command strings.
        
        Args:
            template_name: Template name
            device_platform: Device platform
            
        Returns:
            List of command strings
            
        Example:
            >>> resolver.get_command_strings("quick", "cisco_ios")
            ["show version", "show processes cpu", "show interfaces", ...]
        """
        resolved = self.resolve_template(template_name, device_platform)
        return [cmd.command for cmd in resolved]
    
    def get_template_info(self, template_name: str) -> dict[str, Any]:
        """Get template metadata (v3.0: from SKILL.md)"""
        templates = self.config.get("templates", {})
        
        if template_name not in templates:
            return {}
        
        template_config = templates[template_name]
        items_list = template_config.get("items", template_config.get("intents", []))
        
        # Handle "all"
        if items_list == "all":
            all_items = self.config.get("inspection_items", [])
            items_list = [item["name"] for item in all_items]
        
        # Get inspection_items as list
        inspection_items = self.config.get("inspection_items", [])
        
        # Calculate layer distribution
        layer_counts = {}
        for item_name in items_list:
            item_config = next((item for item in inspection_items if item["name"] == item_name), None)
            if item_config:
                layer = item_config.get("layer", "Unknown")
                layer_counts[layer] = layer_counts.get(layer, 0) + 1
        
        return {
            "name": template_name,
            "description": template_config.get("description"),
            "estimated_time": template_config.get("estimated_time"),
            "item_count": len(items_list),
            "layer_distribution": layer_counts
        }


# ========================================================================
# CLI Test Interface
# ========================================================================

if __name__ == "__main__":
    """
    Test the resolver:
    
    uv run python3 .olav/skills/network-inspection/config/command_resolver.py
    """
    import sys
    
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    print("=" * 80)
    print("🧪 Inspection Command Resolver Test")
    print("=" * 80)
    
    resolver = InspectionCommandResolver()
    
    # Test 1: Resolve single intent
    print("\n📋 Test 1: Resolve single intent")
    print("-" * 80)
    resolved = resolver.resolve_intent("cpu_utilization", "cisco_ios")
    if resolved:
        print(f"Intent: {resolved.intent}")
        print(f"Platform: {resolved.platform}")
        print(f"Command: {resolved.command}")
        print(f"Source: {resolved.source}")
        print(f"Confidence: {resolved.confidence:.2%}")
    
    # Test 2: Resolve template
    print("\n📋 Test 2: Resolve 'quick' template for cisco_ios")
    print("-" * 80)
    commands = resolver.resolve_template("quick", "cisco_ios")
    for i, cmd in enumerate(commands, 1):
        print(f"{i}. {cmd.command:40s} (intent: {cmd.intent}, source: {cmd.source})")
    
    # Test 3: Different platform
    print("\n📋 Test 3: Resolve 'quick' template for juniper_junos")
    print("-" * 80)
    commands = resolver.resolve_template("quick", "juniper_junos")
    for i, cmd in enumerate(commands, 1):
        print(f"{i}. {cmd.command:40s} (source: {cmd.source})")
    
    # Test 4: Template info
    print("\n📋 Test 4: Template metadata")
    print("-" * 80)
    for template_name in ["quick", "standard"]:  # Test only available templates
        info = resolver.get_template_info(template_name)
        if info:
            print(f"{template_name:12s}: {info['item_count']:2d} items, {info['estimated_time']:10s}, {info['description']}")
    
    print("\n" + "=" * 80)
    print("✅ Test complete - v3.0 (SKILL.md-driven)")
    print("=" * 80)
