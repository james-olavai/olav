"""Normalizer for cross-vendor network data standardization.

This module provides the core normalization processor that converts vendor-specific
command output data into standardized Pydantic models.

Architecture:
    Raw TextFSM Output → Normalizer → Normalized Pydantic Model → DuckDB View

Usage:
    from olav.core.normalizer import Normalizer

    normalizer = Normalizer()

    # Normalize single record
    bgp_neighbor = normalizer.normalize(
        platform="cisco_ios",
        command="show_ip_bgp_summary",
        raw_data={"BGP_NEIGHBOR": "10.0.0.1", "AS": "65001", "STATE_PFXRCD": "100"}
    )

    # Normalize batch of records
    results = normalizer.normalize_batch(
        platform="cisco_ios",
        command="show_ip_bgp_summary",
        raw_records=[
            {"BGP_NEIGHBOR": "10.0.0.1", "AS": "65001"},
            {"BGP_NEIGHBOR": "10.0.0.2", "AS": "65002"},
        ]
    )
"""

import logging
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from olav.core.field_mappings import (
    apply_mapping,
    get_mapping,
    get_supported_commands,
    get_supported_platforms,
    infer_command_from_raw_fields,
)
from olav.core.normalized_models import (
    NORMALIZED_MODELS,
    get_model_by_name,
)

logger = logging.getLogger(__name__)


T = TypeVar("T", bound=BaseModel)


# =============================================================================
# Normalization Result Types
# =============================================================================


@dataclass
class NormalizationResult:
    """Result of a normalization attempt."""

    success: bool
    data: BaseModel | None = None
    model_name: str | None = None
    raw_data: dict[str, Any] | None = None
    errors: list[str] | None = None
    warnings: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result = {
            "success": self.success,
            "model_name": self.model_name,
            "errors": self.errors,
            "warnings": self.warnings,
        }
        if self.data:
            result["data"] = self.data.model_dump()
        if self.raw_data:
            result["raw_data"] = self.raw_data
        return result


@dataclass
class BatchNormalizationResult:
    """Result of batch normalization."""

    total_count: int
    success_count: int
    failure_count: int
    results: list[NormalizationResult]

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total_count == 0:
            return 0.0
        return (self.success_count / self.total_count) * 100

    def get_successful_models(self) -> list[BaseModel]:
        """Get list of successfully normalized models."""
        return [r.data for r in self.results if r.success and r.data]

    def get_failed_records(self) -> list[dict[str, Any]]:
        """Get list of records that failed normalization."""
        return [{"raw_data": r.raw_data, "errors": r.errors} for r in self.results if not r.success]


# =============================================================================
# Normalizer Class
# =============================================================================


class Normalizer:
    """Cross-vendor data normalizer.

    The Normalizer handles conversion from vendor-specific field names to
    standardized Pydantic models. It supports:

    1. Explicit normalization (platform + command known)
    2. Auto-detection (infer command from field names)
    3. Fuzzy matching (handle field name variations)
    4. Batch processing (normalize multiple records efficiently)

    Attributes:
        strict_mode: If True, fail on any validation error. If False, try to
                     normalize as much as possible and report warnings.
    """

    def __init__(self, strict_mode: bool = False) -> None:
        """Initialize normalizer.

        Args:
            strict_mode: If True, fail on any validation error.
        """
        self.strict_mode = strict_mode
        self._stats = {
            "total_normalized": 0,
            "total_failed": 0,
            "by_model": {},
            "by_platform": {},
        }

    def normalize(
        self,
        platform: str,
        command: str,
        raw_data: dict[str, Any],
    ) -> NormalizationResult:
        """Normalize a single raw data record.

        Args:
            platform: Platform identifier (e.g., "cisco_ios")
            command: Command name (e.g., "show_ip_bgp_summary")
            raw_data: Raw data dict from TextFSM parsing

        Returns:
            NormalizationResult with normalized model or errors

        Example:
            >>> result = normalizer.normalize(
            ...     platform="cisco_ios",
            ...     command="show_ip_bgp_summary",
            ...     raw_data={"BGP_NEIGHBOR": "10.0.0.1", "AS": "65001"}
            ... )
            >>> if result.success:
            ...     print(result.data.neighbor_ip)
        """
        warnings: list[str] = []
        errors: list[str] = []

        # Get field mapping for this platform/command
        mapping = get_mapping(platform, command)

        if not mapping:
            # Try fuzzy matching or auto-detection
            detected_command = infer_command_from_raw_fields(platform, list(raw_data.keys()))
            if detected_command:
                mapping = get_mapping(platform, detected_command)
                warnings.append(f"Command auto-detected as '{detected_command}'")

        if not mapping:
            error_msg = f"No mapping found for platform='{platform}', command='{command}'"
            errors.append(error_msg)
            self._stats["total_failed"] += 1
            return NormalizationResult(
                success=False,
                raw_data=raw_data,
                errors=errors,
                warnings=warnings,
            )

        # Apply field mapping
        normalized_dict = apply_mapping(raw_data, mapping)

        # Get target model
        model_name = mapping.get("model")
        if not model_name:
            errors.append(f"No model specified in mapping for {command}")
            self._stats["total_failed"] += 1
            return NormalizationResult(
                success=False,
                raw_data=raw_data,
                model_name=model_name,
                errors=errors,
                warnings=warnings,
            )

        try:
            model_class = get_model_by_name(model_name)
        except KeyError:
            errors.append(f"Unknown model: {model_name}")
            self._stats["total_failed"] += 1
            return NormalizationResult(
                success=False,
                raw_data=raw_data,
                model_name=model_name,
                errors=errors,
                warnings=warnings,
            )

        # Validate and create model instance
        try:
            model_instance = model_class(**normalized_dict)
            self._stats["total_normalized"] += 1
            self._update_stats(model_name, platform)
            return NormalizationResult(
                success=True,
                data=model_instance,
                model_name=model_name,
                raw_data=raw_data,
                warnings=warnings if warnings else None,
            )
        except ValidationError as e:
            for error in e.errors():
                field = ".".join(str(loc) for loc in error["loc"])
                msg = error["msg"]
                errors.append(f"Validation error for '{field}': {msg}")

            if self.strict_mode:
                self._stats["total_failed"] += 1
                return NormalizationResult(
                    success=False,
                    raw_data=raw_data,
                    model_name=model_name,
                    errors=errors,
                    warnings=warnings,
                )

            # Non-strict mode: try partial normalization
            partial_data = self._try_partial_normalization(normalized_dict, model_class, warnings)
            if partial_data:
                self._stats["total_normalized"] += 1
                self._update_stats(model_name, platform)
                return NormalizationResult(
                    success=True,
                    data=partial_data,
                    model_name=model_name,
                    raw_data=raw_data,
                    warnings=warnings,
                )

            self._stats["total_failed"] += 1
            return NormalizationResult(
                success=False,
                raw_data=raw_data,
                model_name=model_name,
                errors=errors,
                warnings=warnings,
            )

    def normalize_batch(
        self,
        platform: str,
        command: str,
        raw_records: list[dict[str, Any]],
    ) -> BatchNormalizationResult:
        """Normalize a batch of raw data records.

        Args:
            platform: Platform identifier
            command: Command name
            raw_records: List of raw data dictionaries

        Returns:
            BatchNormalizationResult with aggregated statistics

        Example:
            >>> result = normalizer.normalize_batch(
            ...     platform="cisco_ios",
            ...     command="show_ip_bgp_summary",
            ...     raw_records=[
            ...         {"BGP_NEIGHBOR": "10.0.0.1", "AS": "65001"},
            ...         {"BGP_NEIGHBOR": "10.0.0.2", "AS": "65002"},
            ...     ]
            ... )
            >>> print(f"Success rate: {result.success_rate}%")
        """
        results: list[NormalizationResult] = []
        success_count = 0
        failure_count = 0

        for raw_data in raw_records:
            result = self.normalize(platform, command, raw_data)
            results.append(result)
            if result.success:
                success_count += 1
            else:
                failure_count += 1

        return BatchNormalizationResult(
            total_count=len(raw_records),
            success_count=success_count,
            failure_count=failure_count,
            results=results,
        )

    def normalize_auto(
        self,
        platform: str,
        raw_data: dict[str, Any],
    ) -> NormalizationResult:
        """Normalize data with automatic command detection.

        Attempts to infer the command type from field names in the raw data.

        Args:
            platform: Platform identifier
            raw_data: Raw data dict from TextFSM parsing

        Returns:
            NormalizationResult with normalized model or errors
        """
        detected_command = infer_command_from_raw_fields(platform, list(raw_data.keys()))

        if not detected_command:
            return NormalizationResult(
                success=False,
                raw_data=raw_data,
                errors=[f"Could not detect command for platform '{platform}'"],
            )

        return self.normalize(platform, detected_command, raw_data)

    def normalize_from_json_column(
        self,
        platform: str,
        command: str,
        json_data: dict[str, Any],
    ) -> BatchNormalizationResult:
        """Normalize data from DuckDB JSON column format.

        Handles the standard JSON structure used in command_outputs table:
        {"metadata": {...}, "data": [...]}

        Args:
            platform: Platform identifier
            command: Command name
            json_data: JSON dict with "metadata" and "data" keys

        Returns:
            BatchNormalizationResult for all records in data array

        Example:
            >>> json_data = {
            ...     "metadata": {"device": "R1", "timestamp": "..."},
            ...     "data": [
            ...         {"BGP_NEIGHBOR": "10.0.0.1", "AS": "65001"},
            ...         {"BGP_NEIGHBOR": "10.0.0.2", "AS": "65002"},
            ...     ]
            ... }
            >>> result = normalizer.normalize_from_json_column(
            ...     "cisco_ios", "show_ip_bgp_summary", json_data
            ... )
        """
        data_array = json_data.get("data", [])

        if not isinstance(data_array, list):
            return BatchNormalizationResult(
                total_count=0,
                success_count=0,
                failure_count=0,
                results=[
                    NormalizationResult(
                        success=False,
                        errors=["'data' field is not a list"],
                    )
                ],
            )

        return self.normalize_batch(platform, command, data_array)

    def get_stats(self) -> dict[str, Any]:
        """Get normalization statistics.

        Returns:
            Dictionary with normalization statistics
        """
        return {
            "total_normalized": self._stats["total_normalized"],
            "total_failed": self._stats["total_failed"],
            "success_rate": (
                self._stats["total_normalized"]
                / (self._stats["total_normalized"] + self._stats["total_failed"])
                * 100
                if (self._stats["total_normalized"] + self._stats["total_failed"]) > 0
                else 0
            ),
            "by_model": dict(self._stats["by_model"]),
            "by_platform": dict(self._stats["by_platform"]),
        }

    def reset_stats(self) -> None:
        """Reset normalization statistics."""
        self._stats = {
            "total_normalized": 0,
            "total_failed": 0,
            "by_model": {},
            "by_platform": {},
        }

    def _update_stats(self, model_name: str, platform: str) -> None:
        """Update internal statistics."""
        self._stats["by_model"][model_name] = self._stats["by_model"].get(model_name, 0) + 1
        self._stats["by_platform"][platform] = self._stats["by_platform"].get(platform, 0) + 1

    def _try_partial_normalization(
        self,
        normalized_dict: dict[str, Any],
        model_class: type[BaseModel],
        warnings: list[str],
    ) -> BaseModel | None:
        """Try to create model with partial data.

        Removes invalid fields and tries to create model with required fields only.
        """
        # Get required fields
        required_fields = set()
        for field_name, field_info in model_class.model_fields.items():
            if field_info.is_required():
                required_fields.add(field_name)

        # Try with required fields only
        partial_dict = {k: v for k, v in normalized_dict.items() if k in required_fields}

        try:
            model = model_class(**partial_dict)
            warnings.append("Partial normalization: some optional fields omitted")
            return model
        except ValidationError:
            return None


# =============================================================================
# Convenience Functions
# =============================================================================


def normalize(
    platform: str,
    command: str,
    raw_data: dict[str, Any],
    strict: bool = False,
) -> NormalizationResult:
    """Normalize a single record (convenience function).

    Args:
        platform: Platform identifier
        command: Command name
        raw_data: Raw data from TextFSM parsing
        strict: If True, fail on any validation error

    Returns:
        NormalizationResult

    Example:
        >>> from olav.core.normalizer import normalize
        >>> result = normalize(
        ...     "cisco_ios",
        ...     "show_ip_bgp_summary",
        ...     {"BGP_NEIGHBOR": "10.0.0.1", "AS": "65001"}
        ... )
    """
    normalizer = Normalizer(strict_mode=strict)
    return normalizer.normalize(platform, command, raw_data)


def normalize_batch(
    platform: str,
    command: str,
    raw_records: list[dict[str, Any]],
    strict: bool = False,
) -> BatchNormalizationResult:
    """Normalize multiple records (convenience function).

    Args:
        platform: Platform identifier
        command: Command name
        raw_records: List of raw data dictionaries
        strict: If True, fail on any validation error

    Returns:
        BatchNormalizationResult
    """
    normalizer = Normalizer(strict_mode=strict)
    return normalizer.normalize_batch(platform, command, raw_records)


def get_normalizer_info() -> dict[str, Any]:
    """Get information about the normalizer capabilities.

    Returns:
        Dictionary with supported platforms, commands, and models
    """
    return {
        "supported_platforms": get_supported_platforms(),
        "supported_commands": {
            platform: get_supported_commands(platform) for platform in get_supported_platforms()
        },
        "available_models": list(NORMALIZED_MODELS.keys()),
    }
