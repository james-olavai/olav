"""Field Mapping Learner - Intelligent field mapping using LLM semantic matching.

This module implements automatic field mapping between vendor-specific outputs
and normalized schemas using Large Language Model (LLM) semantic understanding.

Architecture:
    1. LLM Semantic Matching: Use LLM to understand field meanings
    2. Confidence Scoring: Score mapping quality based on context
    3. Caching Strategy: Cache learned mappings for reuse
    4. Multi-vendor Support: Handle different vendor formats

Integration:
    - normalizer.py: Uses field mapper when no manual mapping exists
    - knowledge_embedder.py: Stores learned mappings in vector DB
    - template_generator.py: Complements template generation

Example:
    >>> mapper = FieldMapper(llm=ChatAnthropic(model="claude-sonnet-4"))
    >>> result = mapper.map_fields(
    ...     source_fields=["Neighbor ID", "Pri", "State"],
    ...     target_schema=OSPFNeighbor,
    ...     command="show ip ospf neighbor",
    ...     platform="cisco_ios"
    ... )
    >>> print(result.mappings)
    {'Neighbor ID': 'neighbor_id', 'Pri': 'priority', 'State': 'state'}
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from olav.core.normalized_models import (
    BGPNeighbor,
    CDPNeighbor,
    InterfaceInfo,
    OSPFNeighbor,
    RouteEntry,
)


@dataclass
class FieldMapping:
    """Single field mapping result.

    Attributes:
        source_field: Original field name from vendor output
        target_field: Normalized field name in schema
        confidence: Confidence score (0.0-1.0)
        reasoning: Explanation for the mapping decision
    """

    source_field: str
    target_field: str
    confidence: float
    reasoning: str


@dataclass
class MappingResult:
    """Complete mapping result for a set of fields.

    Attributes:
        mappings: Dictionary of source -> target field mappings
        field_details: List of detailed mapping information
        overall_confidence: Average confidence across all mappings
        unmapped_fields: Source fields that couldn't be mapped
        platform: Device platform (e.g., 'cisco_ios')
        command: Command that generated the output
    """

    mappings: dict[str, str]
    field_details: list[FieldMapping]
    overall_confidence: float
    unmapped_fields: list[str]
    platform: str
    command: str


class FieldMapper:
    """Intelligent field mapper using LLM semantic understanding.

    The mapper uses an LLM to understand the semantic meaning of field names
    and map them to normalized schema fields. It considers:
    - Field name semantics
    - Command context
    - Platform-specific conventions
    - Schema field descriptions

    Attributes:
        llm: Language model for semantic matching
        min_confidence: Minimum confidence threshold (default: 0.7)
        cache_mappings: Whether to cache learned mappings (default: True)
        _mapping_cache: Internal cache of learned mappings
    """

    def __init__(
        self,
        llm: BaseChatModel,
        min_confidence: float = 0.7,
        cache_mappings: bool = True,
    ) -> None:
        """Initialize field mapper.

        Args:
            llm: Language model for semantic matching
            min_confidence: Minimum confidence threshold (0.0-1.0)
            cache_mappings: Whether to cache learned mappings
        """
        self.llm = llm
        self.min_confidence = min_confidence
        self.cache_mappings = cache_mappings
        self._mapping_cache: dict[str, MappingResult] = {}

    def map_fields(
        self,
        source_fields: list[str],
        target_schema: type[BaseModel],
        command: str,
        platform: str,
        sample_values: dict[str, str] | None = None,
    ) -> MappingResult:
        """Map source fields to target schema fields using LLM.

        Args:
            source_fields: List of field names from vendor output
            target_schema: Pydantic model representing target schema
            command: Command that generated the output
            platform: Device platform (e.g., 'cisco_ios')
            sample_values: Optional sample values for each field

        Returns:
            MappingResult containing field mappings and metadata

        Example:
            >>> result = mapper.map_fields(
            ...     source_fields=["BGP router identifier", "local AS number"],
            ...     target_schema=BGPNeighbor,
            ...     command="show ip bgp summary",
            ...     platform="cisco_ios"
            ... )
        """
        # Check cache first
        cache_key = self._get_cache_key(source_fields, target_schema, command, platform)
        if self.cache_mappings and cache_key in self._mapping_cache:
            return self._mapping_cache[cache_key]

        # Get target schema fields and their descriptions
        target_fields = self._extract_schema_fields(target_schema)

        # Create mapping prompt
        prompt = self._create_mapping_prompt(
            source_fields=source_fields,
            target_fields=target_fields,
            command=command,
            platform=platform,
            sample_values=sample_values,
        )

        # Get LLM response
        response = self.llm.invoke(prompt)
        response_text = response.content if hasattr(response, "content") else str(response)
        # Ensure response_text is a string
        if not isinstance(response_text, str):
            response_text = str(response_text)

        # Parse LLM response
        field_mappings = self._parse_mapping_response(response_text, source_fields, target_fields)

        # Build result
        mappings = {
            fm.source_field: fm.target_field
            for fm in field_mappings
            if fm.confidence >= self.min_confidence
        }

        unmapped_fields = [f for f in source_fields if f not in mappings]

        overall_confidence = (
            sum(fm.confidence for fm in field_mappings) / len(field_mappings)
            if field_mappings
            else 0.0
        )

        result = MappingResult(
            mappings=mappings,
            field_details=field_mappings,
            overall_confidence=overall_confidence,
            unmapped_fields=unmapped_fields,
            platform=platform,
            command=command,
        )

        # Cache result
        if self.cache_mappings:
            self._mapping_cache[cache_key] = result

        return result

    def _extract_schema_fields(self, schema: type[BaseModel]) -> dict[str, str]:
        """Extract field names and descriptions from Pydantic schema.

        Args:
            schema: Pydantic model class

        Returns:
            Dictionary mapping field names to their descriptions
        """
        fields = {}
        for field_name, field_info in schema.model_fields.items():
            description = field_info.description or f"Field: {field_name}"
            fields[field_name] = description
        return fields

    def _create_mapping_prompt(
        self,
        source_fields: list[str],
        target_fields: dict[str, str],
        command: str,
        platform: str,
        sample_values: dict[str, str] | None = None,
    ) -> str:
        """Create prompt for LLM field mapping.

        Args:
            source_fields: List of source field names
            target_fields: Dictionary of target field names and descriptions
            command: Command that generated the output
            platform: Device platform
            sample_values: Optional sample values for context

        Returns:
            Formatted prompt string
        """
        sample_info = ""
        if sample_values:
            sample_info = "\n\nSample Values:\n"
            for field_name, value in sample_values.items():
                sample_info += f"- {field_name}: {value}\n"

        target_fields_str = "\n".join([f"- {name}: {desc}" for name, desc in target_fields.items()])

        prompt = f"""You are a network data normalization expert. Map vendor-specific field names to normalized schema fields.

Context:
- Command: {command}
- Platform: {platform}
- Task: Map source fields to target schema fields based on semantic meaning

Source Fields (from vendor output):
{", ".join(source_fields)}
{sample_info}
Target Schema Fields (normalized):
{target_fields_str}

Instructions:
1. For each source field, determine the best matching target field
2. Consider field semantics, command context, and platform conventions
3. Assign a confidence score (0.0-1.0) based on match quality
4. Provide reasoning for each mapping decision
5. If no good match exists, assign confidence < 0.5

Output Format (JSON):
{{
    "mappings": [
        {{
            "source_field": "source field name",
            "target_field": "target field name",
            "confidence": 0.95,
            "reasoning": "explanation"
        }}
    ]
}}

Provide only the JSON response, no additional text."""

        return prompt

    def _parse_mapping_response(
        self,
        response: str,
        source_fields: list[str],
        target_fields: dict[str, str],
    ) -> list[FieldMapping]:
        """Parse LLM response into FieldMapping objects.

        Args:
            response: LLM response string
            source_fields: List of source field names
            target_fields: Dictionary of target field names

        Returns:
            List of FieldMapping objects
        """
        try:
            # Extract JSON from response (handle code blocks)
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            data = json.loads(json_str)
            mappings = []

            for mapping_data in data.get("mappings", []):
                source_field = mapping_data.get("source_field", "")
                target_field = mapping_data.get("target_field", "")
                confidence = mapping_data.get("confidence", 0.0)
                reasoning = mapping_data.get("reasoning", "")

                # Validate fields
                if source_field not in source_fields:
                    continue
                if target_field not in target_fields:
                    confidence = 0.0  # Invalid target field

                mappings.append(
                    FieldMapping(
                        source_field=source_field,
                        target_field=target_field,
                        confidence=confidence,
                        reasoning=reasoning,
                    )
                )

            return mappings

        except (json.JSONDecodeError, KeyError) as e:
            # Return empty mappings on parse error
            return [
                FieldMapping(
                    source_field=field,
                    target_field="",
                    confidence=0.0,
                    reasoning=f"Failed to parse LLM response: {e!s}",
                )
                for field in source_fields
            ]

    def _get_cache_key(
        self,
        source_fields: list[str],
        target_schema: type[BaseModel],
        command: str,
        platform: str,
    ) -> str:
        """Generate cache key for mapping result.

        Args:
            source_fields: List of source field names
            target_schema: Target Pydantic model
            command: Command string
            platform: Platform string

        Returns:
            Cache key string
        """
        fields_str = ",".join(sorted(source_fields))
        schema_name = target_schema.__name__
        return f"{platform}:{command}:{schema_name}:{fields_str}"

    def clear_cache(self) -> None:
        """Clear the mapping cache."""
        self._mapping_cache.clear()

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary containing cache size and keys
        """
        return {
            "cache_size": len(self._mapping_cache),
            "cached_keys": list(self._mapping_cache.keys()),
        }


# Convenience function for one-off mapping
def map_fields(
    source_fields: list[str],
    target_schema: type[BaseModel],
    command: str,
    platform: str,
    llm: BaseChatModel,
    min_confidence: float = 0.7,
    sample_values: dict[str, str] | None = None,
) -> MappingResult:
    """Convenience function for one-off field mapping.

    Args:
        source_fields: List of field names from vendor output
        target_schema: Pydantic model representing target schema
        command: Command that generated the output
        platform: Device platform
        llm: Language model for semantic matching
        min_confidence: Minimum confidence threshold
        sample_values: Optional sample values for context

    Returns:
        MappingResult containing field mappings and metadata

    Example:
        >>> from langchain_anthropic import ChatAnthropic
        >>> result = map_fields(
        ...     source_fields=["Neighbor", "V", "AS", "State/PfxRcd"],
        ...     target_schema=BGPNeighbor,
        ...     command="show ip bgp summary",
        ...     platform="cisco_ios",
        ...     llm=ChatAnthropic(model="claude-sonnet-4")
        ... )
    """
    mapper = FieldMapper(llm=llm, min_confidence=min_confidence)
    return mapper.map_fields(
        source_fields=source_fields,
        target_schema=target_schema,
        command=command,
        platform=platform,
        sample_values=sample_values,
    )


def get_schema_for_command(command: str) -> type[BaseModel] | None:
    """Get appropriate normalized schema for a command.

    Args:
        command: Network command string

    Returns:
        Pydantic model class or None if no match

    Example:
        >>> schema = get_schema_for_command("show ip bgp summary")
        >>> print(schema.__name__)
        'BGPNeighbor'
    """
    command_lower = command.lower()

    if "bgp" in command_lower:
        return BGPNeighbor
    elif "ospf neighbor" in command_lower:
        return OSPFNeighbor
    elif "route" in command_lower or "routing" in command_lower:
        return RouteEntry
    elif "cdp" in command_lower:
        return CDPNeighbor
    elif "interface" in command_lower or "int " in command_lower:
        return InterfaceInfo

    return None
