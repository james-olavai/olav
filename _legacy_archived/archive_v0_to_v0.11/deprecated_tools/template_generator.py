"""TextFSM template generator using ReAct iteration with Pydantic validation.

This module implements automatic TextFSM template generation through iterative
refinement (ReAct: Reasoning + Acting). It analyzes raw device command output,
generates TextFSM templates, validates against Pydantic constraints, and refines
until quality thresholds are met.

Architecture:
    Raw Output → Analyze Structure → Generate Template → Parse → Validate
                                           ↑                        ↓
                                           └────── Fix Issues ──────┘
                                           (ReAct Loop: max 5 iterations)

Example Usage:
    >>> generator = TemplateGenerator(llm=get_llm())
    >>> result = generator.generate_with_react(
    ...     raw_output=show_bgp_output,
    ...     command="show ip bgp summary",
    ...     platform="cisco_ios"
    ... )
    >>> if result.success:
    ...     print(f"Template generated with quality: {result.quality_score}")
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import textfsm
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from olav.core.template_constraints import (
    ValidationResult,
    get_constraint_model_for_command,
    validate_template_output,
)

# =============================================================================
# Result Models
# =============================================================================


@dataclass
class TemplateGenerationResult:
    """Result of template generation attempt."""

    success: bool
    template: str | None = None
    quality_score: float = 0.0
    iterations: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    validation_result: ValidationResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Template Generator
# =============================================================================


class TemplateGenerator:
    """TextFSM template generator using ReAct iteration.

    This class implements automatic TextFSM template generation through:
    1. Structural analysis of raw device output
    2. Initial template generation based on patterns
    3. Iterative refinement using ReAct (Reasoning + Acting)
    4. Pydantic constraint validation
    5. Quality scoring and metadata tracking

    Attributes:
        llm: Language model for template generation
        max_iterations: Maximum ReAct iterations (default: 5)
        min_quality_score: Minimum quality threshold (default: 0.75)
        constraint_validation: Enable Pydantic validation (default: True)
    """

    def __init__(
        self,
        llm: BaseChatModel,
        max_iterations: int = 5,
        min_quality_score: float = 0.75,
        constraint_validation: bool = True,
    ) -> None:
        """Initialize template generator.

        Args:
            llm: Language model for generation
            max_iterations: Maximum ReAct iterations
            min_quality_score: Minimum quality threshold
            constraint_validation: Enable constraint validation
        """
        self.llm = llm
        self.max_iterations = max_iterations
        self.min_quality_score = min_quality_score
        self.constraint_validation = constraint_validation

    def generate_with_react(
        self,
        raw_output: str,
        command: str,
        platform: str,
        constraint_model: type[BaseModel] | None = None,
    ) -> TemplateGenerationResult:
        """Generate TextFSM template using ReAct iteration loop.

        This is the main entry point for template generation. It implements
        the ReAct (Reasoning + Acting) pattern:

        1. Reasoning: Analyze output structure and errors
        2. Acting: Generate/modify template
        3. Validation: Parse and validate against constraints
        4. Repeat until success or max iterations

        Args:
            raw_output: Raw device command output
            command: Device command (e.g., "show ip bgp summary")
            platform: Device platform (e.g., "cisco_ios")
            constraint_model: Optional Pydantic model for validation

        Returns:
            TemplateGenerationResult with template and quality metrics

        Example:
            >>> generator = TemplateGenerator(llm)
            >>> result = generator.generate_with_react(
            ...     raw_output=bgp_output,
            ...     command="show ip bgp summary",
            ...     platform="cisco_ios"
            ... )
        """
        # Determine constraint model if not provided
        if constraint_model is None and self.constraint_validation:
            constraint_model = get_constraint_model_for_command(command, platform)

        # Analyze output structure
        structure_analysis = self._analyze_output_structure(raw_output)

        errors: list[str] = []
        warnings: list[str] = []
        current_template: str | None = None
        validation_result: ValidationResult | None = None

        # ReAct iteration loop
        for iteration in range(1, self.max_iterations + 1):
            # Step 1: Reasoning - Generate prompt based on current state
            if iteration == 1:
                # Initial generation
                prompt = self._create_initial_prompt(
                    raw_output=raw_output,
                    command=command,
                    platform=platform,
                    structure=structure_analysis,
                    constraint_model=constraint_model,
                )
            else:
                # Refinement based on errors
                prompt = self._create_refinement_prompt(
                    raw_output=raw_output,
                    current_template=current_template or "",
                    validation_result=validation_result,
                    constraint_model=constraint_model,
                    iteration=iteration,
                )

            # Step 2: Acting - Generate/modify template
            try:
                current_template = self._generate_template_from_llm(prompt)
            except Exception as e:
                errors.append(f"Iteration {iteration}: LLM generation failed: {e}")
                continue

            if not current_template:
                errors.append(f"Iteration {iteration}: Empty template generated")
                continue

            # Step 3: Validation - Parse and validate
            try:
                parsed_data = self._parse_with_template(current_template, raw_output)

                if constraint_model and self.constraint_validation:
                    validation_result = validate_template_output(
                        parsed_data=parsed_data,
                        constraint_model=constraint_model,
                    )

                    # Check if quality threshold met
                    if (
                        validation_result.success
                        and validation_result.quality_score >= self.min_quality_score
                    ):
                        return TemplateGenerationResult(
                            success=True,
                            template=current_template,
                            quality_score=validation_result.quality_score,
                            iterations=iteration,
                            validation_result=validation_result,
                            metadata={
                                "platform": platform,
                                "command": command,
                                "constraint_model": constraint_model.__name__,
                            },
                        )
                    else:
                        # Quality not sufficient, collect errors for next iteration
                        if validation_result.errors:
                            errors.extend(validation_result.errors)
                        if validation_result.warnings:
                            warnings.extend(validation_result.warnings)

                else:
                    # No constraint validation - just check if parsing worked
                    if parsed_data:
                        return TemplateGenerationResult(
                            success=True,
                            template=current_template,
                            quality_score=0.85,  # Default score without validation
                            iterations=iteration,
                            metadata={"platform": platform, "command": command},
                        )

            except Exception as e:
                errors.append(f"Iteration {iteration}: Parsing failed: {e}")
                continue

        # Max iterations reached without success
        return TemplateGenerationResult(
            success=False,
            template=current_template,
            quality_score=validation_result.quality_score if validation_result else 0.0,
            iterations=self.max_iterations,
            errors=errors,
            warnings=warnings,
            validation_result=validation_result,
            metadata={"platform": platform, "command": command},
        )

    def _analyze_output_structure(self, raw_output: str) -> dict[str, Any]:
        """Analyze raw output to identify structure patterns.

        Detects:
        - Table format (headers, separators, columns)
        - List format (bullets, numbering)
        - Key-value pairs
        - Hierarchical/nested structures

        Args:
            raw_output: Raw device output

        Returns:
            Dictionary with structure analysis
        """
        lines = raw_output.strip().split("\n")

        # Detect table structure
        has_header_separator = False
        potential_headers = []

        for i, line in enumerate(lines[:5]):  # Check first 5 lines
            # Look for separator lines (----, ====)
            if re.match(r"^[-=\s]+$", line):
                has_header_separator = True
                if i > 0:
                    potential_headers.append(lines[i - 1])

        # Detect columns by consistent spacing
        column_positions = self._detect_column_positions(lines[:10])

        return {
            "total_lines": len(lines),
            "has_header": bool(potential_headers),
            "has_separator": has_header_separator,
            "potential_headers": potential_headers,
            "column_count": len(column_positions),
            "column_positions": column_positions,
            "avg_line_length": sum(len(line) for line in lines) / len(lines) if lines else 0,
        }

    def _detect_column_positions(self, lines: list[str]) -> list[int]:
        """Detect column boundaries based on consistent whitespace.

        Args:
            lines: Sample lines from output

        Returns:
            List of column start positions
        """
        if not lines:
            return []

        # Find positions where all lines have spaces
        max_len = max(len(line) for line in lines)
        space_counts = [0] * max_len

        for line in lines:
            for i, char in enumerate(line):
                if char.isspace():
                    space_counts[i] += 1

        # Positions where >80% of lines have spaces are likely column boundaries
        threshold = len(lines) * 0.8
        column_positions = [i for i, count in enumerate(space_counts) if count >= threshold]

        return column_positions

    def _create_initial_prompt(
        self,
        raw_output: str,
        command: str,
        platform: str,
        structure: dict[str, Any],
        constraint_model: type[BaseModel] | None,
    ) -> str:
        """Create initial prompt for template generation.

        Args:
            raw_output: Raw device output
            command: Device command
            platform: Device platform
            structure: Structure analysis
            constraint_model: Pydantic constraint model

        Returns:
            Prompt string for LLM
        """
        constraint_info = ""
        if constraint_model:
            required_fields = [
                field_name
                for field_name, field_info in constraint_model.model_fields.items()
                if field_info.is_required()
            ]
            constraint_info = f"""
Required fields (must extract):
{chr(10).join(f"- {field}" for field in required_fields)}
"""

        prompt = f"""Generate a TextFSM template to parse the following device output.

Platform: {platform}
Command: {command}

Structure Analysis:
- Total lines: {structure["total_lines"]}
- Has header: {structure["has_header"]}
- Estimated columns: {structure["column_count"]}

{constraint_info}

Raw Output:
```
{raw_output[:2000]}
```

Requirements:
1. Extract all meaningful data fields
2. Use proper TextFSM syntax (Value, Start, Record, etc.)
3. Handle optional fields with Filldown if needed
4. Include clear field names (uppercase)

Output ONLY the TextFSM template, no explanations.
Start with Value definitions, then Start state with regex patterns.
"""
        return prompt

    def _create_refinement_prompt(
        self,
        raw_output: str,
        current_template: str,
        validation_result: ValidationResult | None,
        constraint_model: type[BaseModel] | None,
        iteration: int,
    ) -> str:
        """Create refinement prompt for failed validation.

        Args:
            raw_output: Raw device output
            current_template: Current template
            validation_result: Validation result
            constraint_model: Constraint model
            iteration: Current iteration number

        Returns:
            Refinement prompt for LLM
        """
        error_summary = ""
        if validation_result:
            if validation_result.missing_fields:
                error_summary += (
                    f"\nMissing required fields: {', '.join(validation_result.missing_fields)}"
                )
            if validation_result.errors:
                error_summary += "\nValidation errors:\n" + "\n".join(
                    f"  - {err}" for err in validation_result.errors[:5]
                )

        prompt = f"""The TextFSM template needs refinement (iteration {iteration}).

Current Template:
```
{current_template}
```

Issues Found:
{error_summary}

Quality Score: {validation_result.quality_score if validation_result else 0.0}

Raw Output (reference):
```
{raw_output[:1500]}
```

Fix the template to:
1. Extract all required fields
2. Fix regex patterns that fail to match
3. Ensure all records are captured

Output ONLY the FIXED template, no explanations.
"""
        return prompt

    def _generate_template_from_llm(self, prompt: str) -> str:
        """Generate template using LLM.

        Args:
            prompt: Generation prompt

        Returns:
            Generated template string
        """
        response = self.llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        # Ensure content is a string
        if not isinstance(content, str):
            content = str(content)

        # Extract template from markdown code blocks if present
        if "```" in content:
            match = re.search(r"```(?:textfsm)?\n(.*?)\n```", content, re.DOTALL)
            if match:
                content = match.group(1)

        return content.strip()

    def _parse_with_template(self, template: str, raw_output: str) -> list[dict[str, Any]]:
        """Parse raw output using TextFSM template.

        Args:
            template: TextFSM template string
            raw_output: Raw device output

        Returns:
            List of parsed records as dictionaries

        Raises:
            Exception: If parsing fails
        """
        from io import StringIO

        # Create TextFSM parser with StringIO
        template_io = StringIO(template)
        fsm = textfsm.TextFSM(template_io)

        # Parse output
        parsed = fsm.ParseText(raw_output)

        # Convert to list of dicts
        headers = [h.lower() for h in fsm.header]
        result = [dict(zip(headers, row, strict=False)) for row in parsed]

        return result

    def save_template_with_metadata(
        self,
        result: TemplateGenerationResult,
        output_dir: Path,
        platform: str,
        command: str,
    ) -> tuple[Path, Path]:
        """Save generated template and metadata to files.

        Args:
            result: Generation result
            output_dir: Output directory
            platform: Device platform
            command: Device command

        Returns:
            Tuple of (template_path, metadata_path)
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Create filename
        safe_command = re.sub(r"[^\w\-_]", "_", command)
        filename = f"{platform}_{safe_command}"

        # Save template
        template_path = output_dir / f"{filename}.textfsm"
        template_path.write_text(result.template or "", encoding="utf-8")

        # Save metadata
        metadata = {
            "generated_at": datetime.now().isoformat(),
            "generator": "llm-react",
            "model": getattr(self.llm, "model_name", "unknown"),
            "iterations": result.iterations,
            "quality_score": result.quality_score,
            "success": result.success,
            "platform": platform,
            "command": command,
            "validation": {
                "extraction_rate": result.validation_result.extraction_rate
                if result.validation_result
                else 0.0,
                "constraint_pass_rate": result.validation_result.constraint_pass_rate
                if result.validation_result
                else 0.0,
                "total_records": result.validation_result.total_records
                if result.validation_result
                else 0,
            }
            if result.validation_result
            else {},
            "errors": result.errors,
            "warnings": result.warnings,
            "reviewed": False,
            "status": "approved"
            if result.success and result.quality_score >= 0.85
            else "pending_review",
        }

        metadata_path = output_dir / f"{filename}.textfsm.meta"
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        return template_path, metadata_path


# =============================================================================
# Convenience Functions
# =============================================================================


def generate_template(
    raw_output: str,
    command: str,
    platform: str,
    llm: BaseChatModel,
    output_dir: Path | None = None,
    max_iterations: int = 5,
) -> TemplateGenerationResult:
    """Convenience function to generate TextFSM template.

    Args:
        raw_output: Raw device output
        command: Device command
        platform: Device platform
        llm: Language model
        output_dir: Optional output directory for saving
        max_iterations: Maximum ReAct iterations

    Returns:
        TemplateGenerationResult

    Example:
        >>> from olav.core.llm import get_llm
        >>> result = generate_template(
        ...     raw_output=bgp_output,
        ...     command="show ip bgp summary",
        ...     platform="cisco_ios",
        ...     llm=get_llm()
        ... )
    """
    generator = TemplateGenerator(llm=llm, max_iterations=max_iterations)

    result = generator.generate_with_react(
        raw_output=raw_output,
        command=command,
        platform=platform,
    )

    if output_dir and result.template:
        generator.save_template_with_metadata(
            result=result,
            output_dir=output_dir,
            platform=platform,
            command=command,
        )

    return result
