"""NTC Templates Schema-Aware CLI tool - discover validated commands."""

import logging
import os
from typing import Any, Literal

from langchain_core.tools import tool
from opensearchpy import AsyncOpenSearch

logger = logging.getLogger(__name__)


class NTCTool:
    """Schema-Aware CLI command discovery using NTC Templates index."""

    def __init__(self, opensearch_url: str | None = None):
        """Initialize NTC tool.

        Args:
            opensearch_url: OpenSearch URL
        """
        self.opensearch_url = opensearch_url or os.getenv(
            "OPENSEARCH_URL", "http://localhost:9200"
        )
        self.index_name = "ntc-templates-schema"
        self._client: AsyncOpenSearch | None = None

    @property
    async def client(self) -> AsyncOpenSearch:
        """Lazy-load OpenSearch client."""
        if self._client is None:
            self._client = AsyncOpenSearch(
                hosts=[self.opensearch_url],
                http_auth=None,
                use_ssl=False,
                verify_certs=False,
            )
        return self._client

    async def close(self):
        """Close OpenSearch client."""
        if self._client:
            await self._client.close()
            self._client = None


# Global instance
_ntc_tool_instance = NTCTool()


@tool
async def discover_commands(
    platform: Literal[
        "cisco_ios",
        "cisco_nxos",
        "cisco_iosxr",
        "arista_eos",
        "juniper_junos",
        "huawei_vrp",
        "h3c_comware",
    ],
    intent: str,
) -> dict[str, Any]:
    """Discover validated CLI commands for platform using NTC Templates schema.

    **优先使用此工具** before executing CLI commands to ensure:
    - Correct command syntax for target platform
    - TextFSM template availability (structured parsing guaranteed)
    - Safe, validated command execution

    Args:
        platform: Target device platform
        intent: User intent in Chinese (e.g., "查看接口状态", "查看BGP邻居")

    Returns:
        Dictionary with:
        - commands: List of validated commands with metadata
        - total: Number of matches
        - fallback_needed: Whether generic CLI fallback required

    Example:
        >>> await discover_commands(
        ...     platform="cisco_ios",
        ...     intent="查看接口状态"
        ... )
        {
            "commands": [
                {
                    "command": "show ip interface brief",
                    "category": "interface",
                    "has_textfsm": True,
                    "confidence": 0.95
                }
            ],
            "total": 1,
            "fallback_needed": False
        }
    """
    client = await _ntc_tool_instance.client

    # Search by platform + semantic match on intent
    query = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"platform": platform}},
                    {
                        "multi_match": {
                            "query": intent,
                            "fields": ["intent^2", "command"],
                            "type": "best_fields",
                        }
                    },
                ],
                "filter": [{"term": {"has_textfsm": True}}],
            }
        },
        "size": 5,
        "_source": ["command", "category", "has_textfsm", "template_name"],
    }

    try:
        response = await client.search(index=_ntc_tool_instance.index_name, body=query)
        hits = response["hits"]["hits"]

        if not hits:
            logger.warning(
                f"No NTC templates found for platform={platform}, intent={intent}"
            )
            return {
                "commands": [],
                "total": 0,
                "fallback_needed": True,
                "message": f"未找到 {platform} 平台的命令模板，请使用传统 CLI 工具",
            }

        commands = [
            {
                "command": hit["_source"]["command"],
                "category": hit["_source"]["category"],
                "has_textfsm": hit["_source"]["has_textfsm"],
                "template_name": hit["_source"]["template_name"],
                "confidence": hit["_score"],
            }
            for hit in hits
        ]

        return {
            "commands": commands,
            "total": len(commands),
            "fallback_needed": False,
        }

    except Exception as e:
        logger.error(f"NTC schema search failed: {e}")
        return {
            "commands": [],
            "total": 0,
            "fallback_needed": True,
            "error": str(e),
        }


@tool
async def list_supported_platforms() -> dict[str, Any]:
    """List all platforms with NTC Templates support.

    Returns:
        Dictionary with platform statistics
    """
    client = await _ntc_tool_instance.client

    query = {
        "size": 0,
        "aggs": {
            "platforms": {
                "terms": {"field": "platform", "size": 100},
                "aggs": {
                    "categories": {
                        "terms": {"field": "category", "size": 20}
                    }
                },
            }
        },
    }

    try:
        response = await client.search(index=_ntc_tool_instance.index_name, body=query)
        platform_buckets = response["aggregations"]["platforms"]["buckets"]

        platforms = [
            {
                "platform": bucket["key"],
                "template_count": bucket["doc_count"],
                "categories": [
                    cat["key"] for cat in bucket["categories"]["buckets"]
                ],
            }
            for bucket in platform_buckets
        ]

        return {
            "platforms": platforms,
            "total_platforms": len(platforms),
        }

    except Exception as e:
        logger.error(f"Platform listing failed: {e}")
        return {"platforms": [], "total_platforms": 0, "error": str(e)}
