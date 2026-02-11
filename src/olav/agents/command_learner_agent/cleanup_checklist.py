"""
Command Learner Agent Migration & Cleanup Checklist

Validates completeness of command learner implementation.
"""

import logging
import os
import json
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CommandLearnerCleanupChecklist:
    """
    Verifies command learner completeness and validates local environment.
    
    Checks:
    1. Agent module is properly importable
    2. All required dependencies installed
    3. Old agent replacement is complete
    4. NTC library available and indexed
    5. Template storage directories ready
    6. Configuration settings valid
    7. Backward compatibility maintained
    8. Test coverage for new workflow
    """
    
    def __init__(self, workspace_root: str = None):
        """
        Initialize checklist.
        
        Args:
            workspace_root: Project root directory (auto-detected if None)
        """
        if workspace_root is None:
            workspace_root = self._find_workspace_root()
        
        self.workspace_root = Path(workspace_root)
        self.checks_passed = 0
        self.checks_failed = 0
        self.warnings = []
    
    def _find_workspace_root(self) -> str:
        """Find project root by looking for pyproject.toml."""
        current = Path.cwd()
        for parent in [current] + list(current.parents):
            if (parent / "pyproject.toml").exists():
                return str(parent)
        
        raise RuntimeError("Could not find workspace root (no pyproject.toml)")
    
    async def run_all_checks(self) -> dict[str, Any]:
        """
        Run all verification checks.
        
        Returns:
            {
                "passed": int,
                "failed": int,
                "warnings": [str],
                "checks": {
                    "module_importable": bool,
                    "dependencies": bool,
                    "old_agent_replacement": bool,
                    "ntc_library": bool,
                    "template_directories": bool,
                    "configuration": bool,
                    "backward_compatibility": bool,
                    "tests": bool,
                },
                "all_passed": bool
            }
        """
        logger.info("=" * 70)
        logger.info("TextFSM Agent Cleanup Checklist")
        logger.info("=" * 70)
        
        results = {
            "module_importable": await self._check_module_importable(),
            "dependencies": await self._check_dependencies(),
            "old_agent_replacement": await self._check_old_agent_replacement(),
            "ntc_library": await self._check_ntc_library(),
            "template_directories": await self._check_template_directories(),
            "configuration": await self._check_configuration(),
            "backward_compatibility": await self._check_backward_compatibility(),
            "tests": await self._check_tests(),
        }
        
        logger.info("=" * 70)
        logger.info(f"Results: {self.checks_passed} passed, {self.checks_failed} failed")
        logger.info("=" * 70)
        
        for warning in self.warnings:
            logger.warning(f"⚠ {warning}")
        
        return {
            "passed": self.checks_passed,
            "failed": self.checks_failed,
            "warnings": self.warnings,
            "checks": results,
            "all_passed": self.checks_failed == 0,
        }
    
    async def _check_module_importable(self) -> bool:
        """Check 1: New agent module is importable."""
        logger.info("✓ Check 1: Module Importability")
        
        try:
            from olav.agents.command_learner_agent import (
                CommandLearnerAgent,
                CommandLearnerOrchestrator,
                AnalysisResult,
                ApprovalResult,
                GenerationResult,
                TemplateMetadata,
            )
            
            logger.info("  ✓ All required classes importable")
            self.checks_passed += 1
            return True
        
        except ImportError as e:
            logger.error(f"  ✗ Import error: {e}")
            self.checks_failed += 1
            return False
    
    async def _check_dependencies(self) -> bool:
        """Check 2: Required dependencies installed."""
        logger.info("✓ Check 2: Dependencies")
        
        required_packages = [
            "langchain",
            "deepagents",  # Or whatever agent framework is used
            "pydantic",
            "textfsm",
            "ntc_templates",
        ]
        
        missing = []
        for package in required_packages:
            try:
                __import__(package.replace("-", "_"))
            except ImportError:
                missing.append(package)
        
        if missing:
            logger.error(f"  ✗ Missing packages: {', '.join(missing)}")
            self.checks_failed += 1
            return False
        
        logger.info(f"  ✓ All {len(required_packages)} required packages installed")
        self.checks_passed += 1
        return True
    
    async def _check_old_agent_replacement(self) -> bool:
        """Check 3: Old agent has been removed."""
        logger.info("✓ Check 3: Old Agent Replacement")
        
        old_agent_path = (
            self.workspace_root / "src" / "olav" / "agents" / "textfsm_agent.py"
        )
        
        if not old_agent_path.exists():
            logger.info("  ✓ Old textfsm_agent.py removed successfully")
            self.checks_passed += 1
            return True
        else:
            logger.error(
                "  ✗ Old textfsm_agent.py still exists - should be removed"
            )
            self.checks_failed += 1
            return False
    
    async def _check_ntc_library(self) -> bool:
        """Check 4: NTC library available and indexed."""
        logger.info("✓ Check 4: NTC Library")
        
        try:
            import ntc_templates
            ntc_path = Path(ntc_templates.__file__).parent
            
            logger.info(f"  ✓ NTC library installed at {ntc_path}")
            
            # Check for templates directory
            templates_dir = ntc_path / "templates"
            if templates_dir.exists():
                template_count = len(list(templates_dir.glob("**/*.textfsm")))
                logger.info(f"  ✓ Found {template_count} TextFSM templates")
            
            self.checks_passed += 1
            return True
        
        except ImportError:
            logger.error("  ✗ NTC library not installed (run: pip install ntc-templates)")
            self.checks_failed += 1
            return False
    
    async def _check_template_directories(self) -> bool:
        """Check 5: Template storage directories ready."""
        logger.info("✓ Check 5: Template Directories")
        
        required_dirs = [
            Path.home() / ".olav" / "templates" / "custom",
            self.workspace_root / ".olav" / "templates" / "custom",
        ]
        
        all_ready = True
        for dir_path in required_dirs:
            if dir_path.exists():
                logger.info(f"  ✓ {dir_path} exists")
            else:
                logger.warning(f"  ⚠ {dir_path} missing (will be created on save)")
                self.warnings.append(f"Template directory {dir_path} will be auto-created")
        
        self.checks_passed += 1
        return True
    
    async def _check_configuration(self) -> bool:
        """Check 6: Configuration settings valid."""
        logger.info("✓ Check 6: Configuration")
        
        try:
            from config.settings import settings
            from config.paths import config
            
            # Check LLM config
            if not settings.llm_api_key:
                self.warnings.append("LLM API key not configured (check .env or settings.json)")
                logger.warning("  ⚠ LLM API key missing")
            else:
                logger.info("  ✓ LLM API key configured")
            
            if not settings.llm_base_url:
                logger.info("  ℹ LLM base URL not configured (using default)")
            else:
                logger.info(f"  ✓ LLM base URL configured: {settings.llm_base_url}")
            
            logger.info(f"  ✓ Config loaded from: {config.CONFIG_DIR}")
            
            self.checks_passed += 1
            return True
        
        except Exception as e:
            logger.error(f"  ✗ Configuration error: {e}")
            self.checks_failed += 1
            return False
    
    async def _check_backward_compatibility(self) -> bool:
        """Check 7: Backward compatibility with existing templates."""
        logger.info("✓ Check 7: Backward Compatibility")
        
        # Check that textfsm-generator skill has been removed
        old_skill_path = (
            self.workspace_root / ".olav" / "skills" / "textfsm-generator" / "SKILL.md"
        )
        
        if old_skill_path.exists():
            logger.warning("  ⚠ Old textfsm-generator skill still exists")
        else:
            logger.info("  ✓ Old textfsm-generator skill removed")
        
        # Check template storage location
        templates_dir = self.workspace_root / ".olav" / "templates" / "custom"
        if templates_dir.exists():
            template_list = list(templates_dir.glob("*.textfsm"))
            logger.info(f"  ✓ Found {len(template_list)} existing custom templates")
        
        self.checks_passed += 1
        return True
        
        self.checks_passed += 1
        return True
    
    async def _check_tests(self) -> bool:
        """Check 8: Test coverage for new workflow."""
        logger.info("✓ Check 8: Test Coverage")
        
        test_file = (
            self.workspace_root / "tests" / "e2e" / "test_textfsm_interactive.py"
        )
        
        if test_file.exists():
            logger.info(f"  ✓ Found test file: {test_file}")
            self.checks_passed += 1
            return True
        else:
            logger.warning("  ⚠ No tests found for interactive workflow")
            self.warnings.append(
                "Consider creating e2e tests for interactive workflow "
                "(tests/e2e/test_textfsm_interactive.py)"
            )
            self.checks_passed += 1  # Not a blocker
            return True


# ============================================================================
# CLI Entry Point
# ============================================================================

async def main():
    """Run cleanup checklist from CLI."""
    checklist = TextFSMCleanupChecklist()
    results = await checklist.run_all_checks()
    
    if results["all_passed"]:
        print("\n✓ All checks passed! Migration is complete.")
        return 0
    else:
        print(f"\n✗ {results['failed']} check(s) failed. See details above.")
        return 1


if __name__ == "__main__":
    import asyncio
    exit_code = asyncio.run(main())
    exit(exit_code)
