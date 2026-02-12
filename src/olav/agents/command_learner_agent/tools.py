"""
Tool Functions for TextFSM Interactive Agent

All tools that the DeepAgents agent can call.

NOTE: Phase 1-3 implementations are MOCK/PLACEHOLDER only.
Real implementations will be completed in Phase 4.
"""

import json
import logging
from pathlib import Path
from typing import Any
from datetime import datetime

logger = logging.getLogger(__name__)


# ============================================================================
# Tool 1: Execute Command
# ============================================================================

async def execute_command_tool(
    host: str,
    command: str,
    timeout: int = 30
) -> dict[str, Any]:
    """
    Execute command on target host and capture output.
    
    Args:
        host: Target host (e.g., "R1.cisco.ios")
        command: Command to execute (e.g., "show bgp summary")
        timeout: Command timeout in seconds
        
    Returns:
        {
            "success": bool,
            "output": str (raw command output),
            "error": str (if failed),
            "execution_time": float
        }
    """
    # Phase 4 TODO: Implement with actual network client
    # - Initialize connection to host
    # - Execute command
    # - Capture raw output
    # Phase 1-3: Using mock for testing workflow
    logger.info(f"Executing '{command}' on {host} (MOCK)")
    
    return {
        "success": True,
        "output": "Mock output - Phase 4: implement actual network execution",
        "error": None,
        "execution_time": 1.5
    }


# ============================================================================
# Tool 2: Analyze Required Fields
# ============================================================================

async def analyze_fields_tool(
    raw_output: str,
    command_name: str,
    platform: str
) -> dict[str, Any]:
    """
    Analyze output structure and identify fields to extract.
    
    Args:
        raw_output: Raw command output
        command_name: Command name (e.g., "show bgp summary")
        platform: Platform (e.g., "cisco_ios")
        
    Returns:
        {
            "fields": [
                {
                    "name": "Router ID",
                    "type": "string",
                    "mandatory": True,
                    "description": "..."
                },
                ...
            ],
            "strategy": "column-based" | "regex-based" | "hybrid",
            "confidence": float (0-1),
            "relationships": {"Neighbors": "1-N with State"}
        }
    """
    # Phase 4 TODO: Implement with LLM analysis
    # - Send output to LLM
    # - Request field extraction and type inference
    # - Parse response into AnalysisResult
    # Phase 1-3: Using mock for testing workflow
    
    from .models import FieldDefinition, AnalysisResult
    
    logger.info(f"Analyzing fields for '{command_name}' on {platform} (MOCK)")
    
    # Mock response - simulates what LLM analysis would produce
    detected_fields = [
        FieldDefinition(name="Router ID", type="string", mandatory=True),
        FieldDefinition(name="Neighbors", type="list", mandatory=True),
        FieldDefinition(name="State", type="string", mandatory=True),
    ]
    
    analysis = AnalysisResult(
        command_name=command_name,
        platform=platform,
        raw_output=raw_output,
        detected_fields=detected_fields,
        field_relationships={"Neighbors": "1-N with State"},
        extraction_strategy="column-based",
        confidence=0.85
    )
    
    return {
        "fields": [
            {
                "name": f.name,
                "type": f.type,
                "mandatory": f.mandatory,
                "description": f.description
            }
            for f in detected_fields
        ],
        "strategy": analysis.extraction_strategy,
        "confidence": analysis.confidence,
        "relationships": analysis.field_relationships
    }


# ============================================================================
# Tool 3: Get NTC References
# ============================================================================

async def get_ntc_references_tool(
    platform: str,
    command: str,
    approved_fields: list[str],
    limit: int = 2
) -> dict[str, Any]:
    """
    Retrieve NTC template references for the command and fields.
    
    Uses local NTC-Templates search (no internet required).
    
    Delegates to: .olav/skills/command_learner/scripts/ntc_search.py
    
    Args:
        platform: Device platform (e.g., "cisco_ios", "juniper_junos")
        command: Command name (e.g., "show bgp summary")
        approved_fields: User-approved fields to extract
        limit: Number of templates to return
        
    Returns:
        {
            "references": [
                {
                    "template_name": "cisco_ios_show_bgp_summary.textfsm",
                    "path": "/path/to/template",
                    "relevance_score": 0.92,
                    "field_coverage": ["Router ID", "Neighbors"],
                    "source": "local_ntc_package"
                },
                ...
            ],
            "source": "local_ntc_package" | "none"
        }
    """
    try:
        # Import from skill's local script
        # This allows the script to be independent and testable
        import sys
        from pathlib import Path
        
        # Add skill scripts to path
        skill_scripts_path = Path(__file__).parent.parent.parent.parent / "skills" / "command_learner" / "scripts"
        if skill_scripts_path not in sys.path:
            sys.path.insert(0, str(skill_scripts_path))
        
        # Import search function from local script
        from ntc_search import search_ntc_templates
        
        logger.info(f"Searching local NTC templates for '{command}' on {platform}")
        
        # Call the local search function (no internet needed)
        result = search_ntc_templates(
            platform=platform,
            command=command,
            approved_fields=approved_fields,
            limit=limit
        )
        
        logger.info(f"NTC search completed: {result['total_found']} matches found")
        
        return result
        
    except ImportError as e:
        logger.warning(f"Could not import ntc_search script: {e}")
        logger.info("Attempting fallback: direct ntc-templates search")
        
        # Fallback: direct implementation if script not available
        try:
            from pathlib import Path
            import ntc_templates
            
            ntc_path = Path(ntc_templates.__file__).parent / "templates"
            
            if not ntc_path.exists():
                logger.warning(f"NTC templates path not found: {ntc_path}")
                return {
                    "references": [],
                    "source": "none",
                    "error": "NTC templates not installed"
                }
            
            matches = []
            cmd_keywords = command.lower().replace(" ", "_")
            platform_dir = ntc_path / platform
            
            if platform_dir.exists():
                for template_file in platform_dir.glob("*.textfsm"):
                    keyword_matches = sum(1 for kw in cmd_keywords.split("_") if kw in template_file.stem)
                    
                    if keyword_matches > 0:
                        try:
                            with open(template_file, encoding="utf-8") as f:
                                content = f.read()
                            
                            field_coverage = []
                            for field in approved_fields:
                                if f"Value {field}" in content or f"${{{field}}}" in content:
                                    field_coverage.append(field)
                            
                            relevance = (keyword_matches + len(field_coverage)) / max(len(approved_fields), 1)
                            relevance = min(0.99, max(0.5, relevance))
                            
                            matches.append({
                                "template_name": template_file.name,
                                "path": str(template_file),
                                "relevance_score": relevance,
                                "field_coverage": field_coverage,
                                "source": "local_ntc_package"
                            })
                        except Exception as e:
                            logger.debug(f"Error reading template {template_file}: {e}")
                            continue
            
            matches.sort(key=lambda x: x["relevance_score"], reverse=True)
            
            return {
                "references": matches[:limit],
                "source": "local_ntc_package",
                "total_found": len(matches)
            }
            
        except ImportError:
            logger.error("ntc-templates package not installed")
            return {
                "references": [],
                "source": "none",
                "error": "ntc-templates not installed. Install with: pip install ntc-templates"
            }
        
    except Exception as e:
        logger.error(f"Error searching NTC templates: {e}")
        return {
            "references": [],
            "source": "none",
            "error": f"Error searching templates: {str(e)}"
        }


# ============================================================================
# Tool 4: Generate Template
# ============================================================================

async def generate_template_tool(
    raw_output: str,
    approved_fields: list[str],
    ntc_references: list[str],
    previous_errors: list[str] = None,
    iteration: int = 1
) -> dict[str, Any]:
    """
    Generate TextFSM template using LLM with guidance.
    
    Args:
        raw_output: Raw command output
        approved_fields: User-approved fields
        ntc_references: NTC template examples
        previous_errors: Errors from previous attempts
        iteration: Iteration number
        
    Returns:
        {
            "template": str (TextFSM content),
            "success": bool,
            "error_message": str
        }
    """
    # Phase 4 TODO: Implement LLM template generation
    # - Format approved fields and NTC references into prompt
    # - Call LLM to generate template
    # - Parse and validate output
    # Phase 1-3: Using mock for testing workflow
    
    logger.info(f"Generating template (iteration {iteration}) (MOCK)")
    
    return {
        "template": "Mock TextFSM template content",
        "success": True,
        "error_message": None
    }


# ============================================================================
# Tool 5: Test Template
# ============================================================================

async def test_template_tool(
    template: str,
    sample_outputs: list[str]
) -> dict[str, Any]:
    """
    Test template against sample outputs.
    
    Args:
        template: TextFSM template
        sample_outputs: Sample outputs to test against
        
    Returns:
        {
            "success_rate": float (0-1),
            "parse_results": [
                {"output_idx": 0, "success": True, "extracted": {...}},
                ...
            ],
            "errors": [str],
            "metrics": {
                "value_coverage": float,
                "regex_accuracy": float,
                "state_completeness": float
            }
        }
    """
    # Phase 4 TODO: Implement TextFSM testing
    # - Parse template syntax
    # - Test against each sample output
    # - Calculate coverage and accuracy metrics
    # Phase 1-3: Using mock for testing workflow
    
    logger.info(f"Testing template against {len(sample_outputs)} samples (MOCK)")
    
    return {
        "success_rate": 0.85,
        "parse_results": [
            {"output_idx": 0, "success": True, "extracted": {"Router ID": "1.1.1.1"}},
            {"output_idx": 1, "success": True, "extracted": {"Router ID": "2.2.2.2"}},
        ],
        "errors": [],
        "metrics": {
            "value_coverage": 0.90,
            "regex_accuracy": 0.85,
            "state_completeness": 0.80
        }
    }


# ============================================================================
# Tool 6: Save Template
# ============================================================================

async def save_template_tool(
    template: str,
    command_name: str,
    platform: str,
    metadata: dict[str, Any]
) -> dict[str, Any]:
    """
    Save template to TextFSM templates directory.
    
    Implements Phase 4: Real template saving with metadata indexing.
    
    Args:
        template: TextFSM content
        command_name: Command name (e.g., "show bgp summary")
        platform: Platform (e.g., "cisco_ios")
        metadata: Template metadata with fields, coverage info, etc.
        
    Returns:
        {
            "success": bool,
            "file_path": str (absolute path),
            "metadata_path": str,
            "error": str (if failed)
        }
    """
    try:
        # Get template directory from settings
        from config.settings import settings
        
        # Get template directory - resolve to absolute path
        template_dir = Path(settings.execution.textfsm_template_dir).resolve()
        
        # Create directory if it doesn't exist
        template_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate filename
        template_filename = f"{platform}_{command_name.replace(' ', '_').replace('/', '_')}.textfsm"
        template_path = template_dir / template_filename
        
        # Write template file
        with open(template_path, 'w', encoding='utf-8') as f:
            f.write(template)
        logger.info(f"✓ Template saved: {template_path}")
        
        # Save metadata JSON alongside template
        metadata_filename = f"{template_filename[:-8]}.metadata.json"  # Remove .textfsm, add .metadata.json
        metadata_path = template_dir / metadata_filename
        
        # Add metadata headers
        full_metadata = {
            "template_file": template_filename,
            "command": command_name,
            "platform": platform,
            "created_at": datetime.now().isoformat(),
            "fields": metadata.get("fields", []),
            "field_coverage": metadata.get("field_coverage", 0),
            "success_rate": metadata.get("success_rate", 0.0),
            "notes": metadata.get("notes", ""),
            "source": "command_learner_auto_generated"
        }
        
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(full_metadata, f, indent=2, ensure_ascii=False)
        logger.info(f"✓ Metadata saved: {metadata_path}")
        
        # Update/create index file
        index_path = template_dir / "index"
        index_entry = f"{template_filename}, {platform}, {command_name.lower()}"
        
        # Read existing index or create new one
        existing_entries = []
        if index_path.exists():
            with open(index_path, 'r', encoding='utf-8') as f:
                existing_entries = [line.strip() for line in f if line.strip()]
        
        # Add new entry if not already present
        if index_entry not in existing_entries:
            existing_entries.append(index_entry)
            with open(index_path, 'w', encoding='utf-8') as f:
                for entry in sorted(existing_entries):
                    f.write(entry + '\n')
            logger.info(f"✓ Index updated: {index_path}")
        
        return {
            "success": True,
            "file_path": str(template_path),
            "metadata_path": str(metadata_path),
            "error": None
        }
        
    except Exception as e:
        error_msg = f"Failed to save template: {str(e)}"
        logger.error(error_msg)
        return {
            "success": False,
            "file_path": "",
            "metadata_path": "",
            "error": error_msg
        }
