"""
Admin Agent - System Configuration Manager

Core class for handling user requests related to system configuration.

Design: See dev_doc/ADMIN_AGENT_SIMPLIFIED_DESIGN.md (v3.0)
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .admin_file_manager import AdminFileManager
from .knowledge_manager import KnowledgeManager
from .exceptions import IntentError, ValidationError
from .validators import (
    validate_device_ip,
    validate_device_name,
    validate_not_empty,
    validate_username,
)

logger = logging.getLogger(__name__)


class AdminAgent:
    """
    Admin Agent for OLAV System Configuration Management.

    Handles:
      - Device management (add/delete/update/list)
      - Cron task management
      - Knowledge base management
      - System monitoring

    Not handling (delegated to Orchestrator Agent):
      - Business queries
      - Data analysis
      - Complex reasoning
    """

    # Safe intents that Agent can handle
    ALLOWED_INTENTS = {
        "add_device",
        "delete_device",
        "update_device",
        "list_devices",
        "add_cron",
        "remove_cron",
        "list_cron",
        "explain_cron",
        "add_knowledge",
        "delete_knowledge",
        "search_knowledge",
        "system_status",
        "cleanup_logs",
        "clear_cache",
    }

    # Forbidden intents (security policy)
    FORBIDDEN_INTENTS = {
        "modify_database",
        "delete_backup",
        "execute_shell",
        "modify_skill_code",
        "modify_api_key",
        "execute_arbitrary_command",
    }

    def __init__(self):
        """Initialize Admin Agent."""
        self.file_manager = AdminFileManager()
        self.knowledge_manager = KnowledgeManager()
        self.crontab_file = Path(".olav/config/crontab")
        logger.info("AdminAgent initialized")

    async def handle_request(self, user_input: str) -> str:
        """
        Main entry point for handling user requests.

        Three-layer security check:
          1. Intent identification and classification
          2. Parameter validation
          3. Operation safety verification

        Args:
            user_input: Natural language input from user

        Returns:
            Operation result message

        Raises:
            IntentError: If intent cannot be identified
            ValidationError: If parameters are invalid
        """
        logger.info(f"Processing request: {user_input[:100]}...")

        try:
            # Layer 1: Identify intent
            intent = await self.identify_intent(user_input)
            logger.debug(f"Identified intent: {intent}")

            # Layer 1b: Security classification
            if intent in self.FORBIDDEN_INTENTS:
                logger.warning(f"Forbidden intent attempted: {intent}")
                return "❌ This operation is not allowed"

            if intent not in self.ALLOWED_INTENTS:
                logger.warning(f"Unknown intent: {intent}")
                raise IntentError(f"Cannot understand request: {intent}")

            # Layer 2: Extract and validate parameters
            params = await self.extract_parameters(user_input, intent)
            logger.debug(f"Extracted parameters: {params}")

            # Layer 3: Route to appropriate handler
            handler = getattr(self, f"handle_{intent}", None)
            if not handler:
                raise IntentError(f"Handler not implemented for intent: {intent}")

            result = await handler(**params)
            logger.info(f"Request succeeded: {intent}")
            return result

        except (IntentError, ValidationError) as e:
            logger.warning(f"Request failed: {e.message}")
            return f"❌ {e.message}"
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return f"❌ An unexpected error occurred: {str(e)}"

    async def identify_intent(self, user_input: str) -> str:
        """
        Identify user intent from natural language input.

        Keywords for intent detection:
          - add/create device → add_device
          - delete/remove device → delete_device
          - modify/update device → update_device
          - list/show devices → list_devices
          - add/create knowledge → add_knowledge
          - delete/remove knowledge → delete_knowledge
          - search/find knowledge → search_knowledge
          - add/create cron → add_cron
          - delete/remove cron → remove_cron
          - list/show cron → list_cron
          - explain cron → explain_cron
          - etc.

        Args:
            user_input: Natural language input

        Returns:
            Intent string

        Raises:
            IntentError: If intent cannot be identified
        """
        user_lower = user_input.lower()

        # Check for Knowledge keywords FIRST (very specific)
        has_knowledge_keywords = any(word in user_lower for word in ["knowledge", "knowledge base", "kb"])

        if has_knowledge_keywords:
            # Knowledge intents (highest priority)
            
            if any(word in user_lower for word in ["add", "create", "store", "save"]):
                return "add_knowledge"
            
            if any(word in user_lower for word in ["delete", "remove", "drop"]):
                return "delete_knowledge"
            
            if any(word in user_lower for word in ["search", "find", "query", "lookup"]):
                return "search_knowledge"
            
            if any(word in user_lower for word in ["list", "show", "display"]):
                return "search_knowledge"

        # Check for Cron/Task/Job keywords SECOND (before device operations)
        # This prevents confusion with device operations
        has_cron_keywords = any(word in user_lower for word in ["cron", "task", "job"])
        has_scheduled_keywords = "scheduled" in user_lower
        has_schedule_action = "schedule" in user_lower and "device" not in user_lower  # "schedule a cron" but not "schedule a device"

        if has_cron_keywords or (has_scheduled_keywords and not "device" in user_lower):
            # Cron task intents (high priority)
            
            # Check for explain FIRST
            if any(word in user_lower for word in ["explain", "what", "meaning", "mean"]) and has_cron_keywords:
                return "explain_cron"

            if any(word in user_lower for word in ["create", "add"]) and (has_cron_keywords or has_scheduled_keywords):
                return "add_cron"
            
            # "schedule a cron task" should create a cron
            if has_schedule_action and has_cron_keywords:
                return "add_cron"

            if any(word in user_lower for word in ["delete", "remove"]) and has_cron_keywords:
                return "remove_cron"

            if any(word in user_lower for word in ["list", "show", "display"]) and has_cron_keywords:
                return "list_cron"

        # Device management intents (lower priority)
        if any(word in user_lower for word in ["add", "create", "register"]) and "device" in user_lower:
            return "add_device"

        if any(word in user_lower for word in ["delete", "remove", "drop"]) and "device" in user_lower:
            return "delete_device"

        if any(word in user_lower for word in ["modify", "update", "change"]) and "device" in user_lower:
            return "update_device"

        if any(word in user_lower for word in ["list", "show", "display"]) and "device" in user_lower:
            return "list_devices"

        # System monitoring intents
        if any(word in user_lower for word in ["status", "health", "info"]) and "system" in user_lower:
            return "system_status"

        if any(word in user_lower for word in ["cleanup", "clean", "clear"]) and "log" in user_lower:
            return "cleanup_logs"

        if any(word in user_lower for word in ["clear", "reset"]) and "cache" in user_lower:
            return "clear_cache"

        raise IntentError(f"Cannot understand your request: {user_input}")

    async def extract_parameters(self, user_input: str, intent: str) -> Dict[str, Any]:
        """
        Extract parameters from natural language input.

        Args:
            user_input: Natural language input
            intent: Identified intent

        Returns:
            Dictionary of extracted parameters

        Raises:
            ValidationError: If required parameters are missing
        """
        params = {}
        import re

        # For knowledge operations, try to extract knowledge-related info
        if "knowledge" in intent:
            # Try to extract knowledge topic/title
            # Pattern: words in quotes or after specific keywords, including special characters
            title_match = re.search(r'(?:knowledge|topic)\s+(?:about|regarding|for)?\s*(?:"([^"]+)"|([A-Za-z][A-Za-z0-9\s\-/._]+?)(?:\s+(?:with|using|for|tags?|description|about|content)|\s*$))', user_input, re.IGNORECASE)
            if title_match:
                title = title_match.group(1) or title_match.group(2)
                if title:
                    params["title"] = title.strip()
            
            # For delete knowledge, also try more direct title extraction
            if "delete" in intent and "title" not in params:
                # Pattern like "delete knowledge <title>"
                delete_match = re.search(r"delete\s+knowledge\s+(.+?)(?:\s*$)", user_input, re.IGNORECASE)
                if delete_match:
                    potential_title = delete_match.group(1).strip()
                    if potential_title:
                        params["title"] = potential_title

            # Try to extract topic category
            topic_match = re.search(r"(?:topic|category):\s*([a-z_]+)", user_input, re.IGNORECASE)
            if topic_match:
                params["topic"] = topic_match.group(1)

            # Try to extract tags
            tags_match = re.search(r"(?:tags?|with\s+tags?):\s*([^,\n]+(?:,\s*[^,\n]+)*)", user_input, re.IGNORECASE)
            if tags_match:
                tags_str = tags_match.group(1)
                tags = [t.strip() for t in tags_str.split(",")]
                params["tags"] = tags

            # Try to extract description
            desc_match = re.search(r"(?:description|desc):\s*(.+?)(?:\s+(?:tags?|topic|with|content)|\s*$)", user_input, re.IGNORECASE)
            if desc_match:
                params["description"] = desc_match.group(1).strip()

            # For add_knowledge, try to extract content from various patterns
            if "add" in intent:
                # Look for content after "content:" or "is:" or "details:"
                content_match = re.search(r"(?:content|details|info|is):\s*(.+?)(?:\s+(?:topic|tags?|description)|\s*$)", user_input, re.IGNORECASE | re.DOTALL)
                if content_match:
                    params["content"] = content_match.group(1).strip()
                else:
                    # If no explicit content keyword, use the main description as content
                    # For "add knowledge about X with tags: ..." use X as both title and content
                    if "title" in params and "content" not in params:
                        params["content"] = f"Information about {params['title']}"

            # For search_knowledge, the query is the main parameter
            if "search" in intent:
                # Extract query as everything after "search for" or "find" or "search knowledge"
                # Try multiple patterns
                query_match = re.search(r"(?:search|find|query|lookup)(?:\s+knowledge)?\s+(?:for\s+)?(.+?)(?:\s+(?:in|with|by)|\s*$)", user_input, re.IGNORECASE)
                if query_match:
                    params["query"] = query_match.group(1).strip()

        # For device operations, try to extract device-related info
        elif "device" in intent:
            # Try to extract device name (common patterns: "device X", "R1", "SW2", etc)
            # Simple heuristic: look for capital letters followed by numbers
            device_match = re.search(r"\b([A-Z][A-Z0-9]*)\b", user_input)
            if device_match:
                params["name"] = device_match.group(1)

            # Try to extract IP address
            ip_match = re.search(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", user_input)
            if ip_match:
                params["ip"] = ip_match.group(1)

            # Try to extract username
            if "username" in user_input.lower():
                # Extract what comes after "username"
                user_match = re.search(r"(?:username|user)\s+(?:is\s+)?([a-zA-Z0-9_-]+)", user_input, re.I)
                if user_match:
                    params["username"] = user_match.group(1)

        # For cron operations, try to extract cron-related info
        elif "cron" in intent or "task" in intent or "schedule" in intent:
            # Try to extract cron schedule (5-field format: min hour day month dow)
            # Pattern: numbers/wildcards separated by spaces
            schedule_match = re.search(
                r"(?:schedule|cron|at|time)?\s+([*0-9,-/]+(?:\s+[*0-9,-/]+){4})",
                user_input,
                re.IGNORECASE
            )
            if schedule_match:
                params["schedule"] = schedule_match.group(1).strip()

            # Try to extract command description
            if "command" in user_input.lower():
                cmd_match = re.search(r"command\s+(?:is\s+)?(.+?)(?:\s+on\s+devices?|$)", user_input, re.IGNORECASE)
                if cmd_match:
                    params["command"] = cmd_match.group(1).strip()

        return params

    # Device management handlers

    async def handle_add_device(self, name: str = None, ip: str = None, username: str = None, **kwargs) -> str:
        """Add a new device to inventory."""
        # Validate parameters
        if not name:
            raise ValidationError("Device name is required (e.g., 'R1', 'SW1')")
        validate_device_name(name)

        if not ip:
            raise ValidationError("Device IP is required (e.g., '10.0.0.1')")
        validate_device_ip(ip)

        if not username:
            raise ValidationError("Username is required")
        validate_username(username)

        # Load current inventory
        config = self.file_manager.load_yaml(".olav/config/hosts.yaml")

        # Check if device already exists
        if name in config:
            raise ValidationError(f"Device {name} already exists")

        # Add new device
        config[name] = {
            "hostname": ip,
            "username": username,
            "password": f"${{PASSWORD_{name}}}",  # From environment
            "platform": kwargs.get("platform", "cisco_ios"),
            "added_at": datetime.now().isoformat(),
        }

        # Save updated inventory
        self.file_manager.save_yaml(".olav/config/hosts.yaml", config)

        # Log operation
        logger.info(f"Device {name} ({ip}) added by Admin Agent")

        return f"✓ Device {name} has been added to inventory\n  IP: {ip}\n  Username: {username}\n  Platform: {kwargs.get('platform', 'cisco_ios')}"

    async def handle_delete_device(self, name: str = None, **kwargs) -> str:
        """Delete a device from inventory."""
        if not name:
            raise ValidationError("Device name is required")

        validate_device_name(name)

        # Load inventory
        config = self.file_manager.load_yaml(".olav/config/hosts.yaml")

        # Check if device exists
        if name not in config:
            raise ValidationError(f"Device {name} does not exist in inventory")

        # Delete device
        deleted_info = config.pop(name)

        # Save updated inventory
        self.file_manager.save_yaml(".olav/config/hosts.yaml", config)

        logger.info(f"Device {name} deleted by Admin Agent")

        return f"✓ Device {name} has been deleted from inventory"

    async def handle_update_device(self, name: str = None, **kwargs) -> str:
        """Update device parameters."""
        if not name:
            raise ValidationError("Device name is required")

        validate_device_name(name)

        # Load inventory
        config = self.file_manager.load_yaml(".olav/config/hosts.yaml")

        # Check if device exists
        if name not in config:
            raise ValidationError(f"Device {name} does not exist in inventory")

        # Update allowed fields
        allowed_fields = ["ip", "hostname", "username", "platform"]
        updated_fields = {}

        for field in allowed_fields:
            if field in kwargs and kwargs[field]:
                if field == "ip":
                    validate_device_ip(kwargs[field])
                    config[name]["hostname"] = kwargs[field]
                    updated_fields["IP"] = kwargs[field]
                elif field == "hostname":
                    config[name]["hostname"] = kwargs[field]
                    updated_fields["Hostname"] = kwargs[field]
                elif field == "username":
                    validate_username(kwargs[field])
                    config[name]["username"] = kwargs[field]
                    updated_fields["Username"] = kwargs[field]
                elif field == "platform":
                    config[name]["platform"] = kwargs[field]
                    updated_fields["Platform"] = kwargs[field]

        if not updated_fields:
            return f"✓ Device {name} updated (no changes made)"

        # Save updated inventory
        self.file_manager.save_yaml(".olav/config/hosts.yaml", config)

        logger.info(f"Device {name} updated by Admin Agent: {updated_fields}")

        changes = "\n  ".join([f"{k}: {v}" for k, v in updated_fields.items()])
        return f"✓ Device {name} has been updated\n  {changes}"

    async def handle_list_devices(self, **kwargs) -> str:
        """List all devices in inventory."""
        config = self.file_manager.load_yaml(".olav/config/hosts.yaml")

        if not config:
            return "ℹ️  No devices in inventory"

        # Format output
        lines = [f"📋 Devices in inventory ({len(config)} total):\n"]

        for name, info in config.items():
            ip = info.get("hostname", "N/A")
            username = info.get("username", "N/A")
            platform = info.get("platform", "N/A")
            lines.append(f"  • {name:15} IP: {ip:15} User: {username:10} Platform: {platform}")

        return "\n".join(lines)

    # Cron task management handlers

    async def handle_add_cron(self, schedule: str = None, command: str = None, **kwargs) -> str:
        """Add a new cron task to .olav/config/crontab."""
        if not schedule:
            raise ValidationError("Schedule is required (e.g., '0 20 * * *' for 8 PM daily)")
        if not command:
            raise ValidationError("Command is required (e.g., 'backup running-config')")
        
        validate_not_empty(schedule, "Schedule")
        validate_not_empty(command, "Command")

        # Validate cron format
        if not self._is_valid_cron(schedule):
            raise ValidationError(f"Invalid cron schedule: {schedule}")

        # Ensure file exists
        self.crontab_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.crontab_file.exists():
            self.crontab_file.write_text("# OLAV Cron Jobs\n")

        # Append new job
        cwd = Path.cwd()
        line = f"{schedule} cd {cwd} && {command}\n"
        self.crontab_file.write_text(self.crontab_file.read_text() + line)

        explanation = self._explain_schedule(schedule)
        logger.info(f"Cron job added: {explanation}")

        return f"✓ Cron job added\n  {explanation}\n  Command: {command}"

    async def handle_remove_cron(self, command: str = None, **kwargs) -> str:
        """Remove a cron task from crontab by command keyword."""
        if not command:
            raise ValidationError("Command keyword is required for removal")
        
        validate_not_empty(command, "Command keyword")

        if not self.crontab_file.exists():
            raise ValidationError("No cron jobs configured")

        content = self.crontab_file.read_text()
        lines = content.split("\n")

        # Remove matching lines
        new_lines = [l for l in lines if command not in l or l.startswith("#")]

        if len(new_lines) == len(lines):
            raise ValidationError(f"No job found matching: {command}")

        self.crontab_file.write_text("\n".join(new_lines))

        logger.info(f"Cron job removed: {command}")
        return f"✓ Cron job removed\n  Removed jobs matching: {command}"

    async def handle_list_cron(self, **kwargs) -> str:
        """List all cron tasks."""
        if not self.crontab_file.exists():
            return "📋 No cron jobs configured"

        content = self.crontab_file.read_text()
        lines = [line.strip() for line in content.split("\n") if line.strip() and not line.startswith("#")]

        if not lines:
            return "📋 No cron jobs configured"

        result = ["🕐 Current Cron Jobs:\n"]
        for i, line in enumerate(lines, 1):
            parts = line.split(maxsplit=5)
            if len(parts) >= 6:
                schedule = " ".join(parts[:5])
                command = parts[5]
                explanation = self._explain_schedule(schedule)
                result.append(f"  {i}. {explanation}")
                result.append(f"     Schedule: {schedule}")
                result.append(f"     Command: {command}\n")

        return "\n".join(result)

    async def handle_explain_cron(self, schedule: str = None, **kwargs) -> str:
        """Explain what a cron expression means."""
        if not schedule:
            raise ValidationError("Cron expression is required (e.g., '0 20 * * *')")
        
        return self._explain_schedule(schedule)

    async def handle_add_knowledge(self, title: str = None, content: str = None, **kwargs) -> str:
        """Add knowledge to knowledge base."""
        if not title:
            raise ValidationError("Knowledge title is required")
        if not content:
            raise ValidationError("Knowledge content is required")

        topic = kwargs.get("topic", "")
        tags = kwargs.get("tags", [])
        description = kwargs.get("description", "")

        return await self.knowledge_manager.add_knowledge(
            title=title,
            content=content,
            topic=topic,
            tags=tags,
            description=description,
        )

    async def handle_delete_knowledge(self, title: str = None, **kwargs) -> str:
        """Delete knowledge from knowledge base."""
        if not title:
            raise ValidationError("Knowledge title is required")

        return await self.knowledge_manager.delete_knowledge(title)

    async def handle_search_knowledge(self, query: str = None, **kwargs) -> str:
        """Search knowledge base."""
        if query:
            return await self.knowledge_manager.search_knowledge(query)
        else:
            # If no query, list all knowledge
            return await self.knowledge_manager.list_knowledge()

    async def handle_system_status(self, **kwargs) -> str:
        """Get system status (Phase 2)."""
        raise ValidationError("System monitoring is not yet implemented. Coming in Phase 2.")

    async def handle_cleanup_logs(self, **kwargs) -> str:
        """Clean up old logs (Phase 2)."""
        raise ValidationError("Log cleanup is not yet implemented. Coming in Phase 2.")

    async def handle_clear_cache(self, **kwargs) -> str:
        """Clear cache (Phase 2)."""
        raise ValidationError("Cache clearing is not yet implemented. Coming in Phase 2.")

    # Private helper methods for cron management

    @staticmethod
    def _is_valid_cron(schedule: str) -> bool:
        """Check if cron expression is valid (5 fields)."""
        parts = schedule.split()
        if len(parts) != 5:
            return False

        # Simple validation - each field should be *, number, or */number
        for field in parts:
            if not re.match(r"^(\*|[0-9]+|\*/[0-9]+)$", field):
                return False

        return True

    @staticmethod
    def _explain_schedule(schedule: str) -> str:
        """Convert cron schedule to human-readable format."""
        parts = schedule.split()
        if len(parts) != 5:
            return f"Invalid cron: {schedule}"

        minute, hour, day, month, weekday = parts

        # Build explanation
        explanation = []

        if hour == "*":
            if minute == "*":
                explanation.append("Every minute")
            else:
                explanation.append(f"Every hour at minute {minute}")
        else:
            if minute == "*":
                explanation.append(f"Every {hour}:{minute} hour")
            else:
                explanation.append(f"At {hour}:{minute.zfill(2)}")

        if weekday != "*" and weekday != "?":
            days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            day_num = int(weekday) if weekday.isdigit() else -1
            if 0 <= day_num <= 6:
                explanation[0] += f" on {days[day_num]}"

        elif day != "*" and day != "?":
            explanation[0] += f" on day {day}"

        if month != "*" and month != "?":
            months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            month_num = int(month) if month.isdigit() else -1
            if 1 <= month_num <= 12:
                explanation[0] += f" of {months[month_num]}"

        return " ".join(explanation)

