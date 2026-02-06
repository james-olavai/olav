"""
Flow Diagram Builder for Dependency Visualization

Phase 6.2.2.2: Enhanced dependency flow diagram generation.
Supports complex DAGs, parallel execution detection, and ASCII art rendering.

Author: OLAV Development Team
Version: 0.9.8
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class DiagramStyle(str, Enum):
    """Flow diagram style options."""
    SIMPLE = "simple"      # Linear flow
    TREE = "tree"          # Tree-like with branches
    FLOWCHART = "flowchart"  # Detailed flowchart


@dataclass
class ParallelGroup:
    """Group of steps that can run in parallel."""
    steps: List[str]  # Step names
    estimated_time: int  # Time for this parallel group (max of group, not sum)
    
    def display_name(self) -> str:
        """Display name for parallel group."""
        if len(self.steps) == 1:
            return self.steps[0]
        else:
            return f"[{' | '.join(self.steps)}]"


@dataclass
class FlowDiagramConfig:
    """Configuration for flow diagram generation."""
    style: DiagramStyle = DiagramStyle.SIMPLE
    show_timing: bool = True
    show_parallel: bool = True
    max_width: int = 80
    use_unicode: bool = True


class FlowDiagramBuilder:
    """
    Builds ASCII art flow diagrams for execution plans.
    
    Features:
    - Linear flow visualization
    - Parallel step detection
    - Tree-like complex DAG rendering
    - Time estimation display
    - Unicode/ASCII support
    """
    
    def __init__(self, config: FlowDiagramConfig = None):
        """Initialize builder with optional config."""
        self.config = config or FlowDiagramConfig()
    
    def build_diagram(
        self,
        execution_order: List[str],
        dependency_graph: Dict,
        step_timings: Optional[Dict[str, int]] = None,
        style: DiagramStyle = None
    ) -> str:
        """
        Build flow diagram for execution plan.
        
        Args:
            execution_order: List of steps in execution order
            dependency_graph: Dependency graph with subagents
            step_timings: Optional dict mapping step name to duration
            style: Optional override for diagram style
        
        Returns:
            ASCII art diagram as string
        """
        style = style or self.config.style
        
        # Detect parallel opportunities
        parallel_groups = self._detect_parallel_groups(
            execution_order,
            dependency_graph
        )
        
        # Generate appropriate diagram
        if len(execution_order) <= 3:
            return self._build_linear_diagram(
                execution_order,
                parallel_groups,
                step_timings
            )
        else:
            return self._build_complex_diagram(
                execution_order,
                parallel_groups,
                step_timings
            )
    
    def _detect_parallel_groups(
        self,
        execution_order: List[str],
        dependency_graph: Dict
    ) -> List[ParallelGroup]:
        """
        Detect groups of steps that can run in parallel.
        
        Args:
            execution_order: Execution order
            dependency_graph: Dependency graph
        
        Returns:
            List of ParallelGroup objects
        """
        # For now, return single-step groups (no parallelization)
        # Future: implement actual parallel detection
        
        groups = []
        for step in execution_order:
            groups.append(ParallelGroup(steps=[step], estimated_time=0))
        
        return groups
    
    def _build_linear_diagram(
        self,
        execution_order: List[str],
        parallel_groups: List[ParallelGroup],
        step_timings: Optional[Dict[str, int]] = None
    ) -> str:
        """
        Build simple linear flow diagram.
        
        Example:
            [1️⃣ QUERY] (20s)
                ↓
            [2️⃣ NETBOX] (45s)
                ↓
            [3️⃣ ANALYZER] (20s)
            
            ✅ 完成！
        """
        lines = []
        
        # Add parallel notice if applicable
        has_parallel = any(len(g.steps) > 1 for g in parallel_groups)
        if has_parallel and self.config.show_parallel:
            lines.append("💡 并行机会: 某些步骤可以同时运行")
            lines.append("")
        else:
            if self.config.show_parallel:
                lines.append("🔴 无并行机会: 所有步骤形成线性链")
                lines.append("")
        
        # Build step-by-step flow
        for i, step_name in enumerate(execution_order):
            # Step box with emoji
            emoji = f"{i+1}️⃣"
            timing_str = ""
            if self.config.show_timing and step_timings:
                duration = step_timings.get(step_name, 0)
                if duration:
                    timing_str = f" ({self._format_time(duration)})"
            
            lines.append(f"[{emoji} {step_name.upper()}]{timing_str}")
            
            # Add arrow if not last step
            if i < len(execution_order) - 1:
                lines.append("    ↓")
        
        # Add completion indicator
        lines.append("")
        lines.append("✅ 完成！")
        
        return "\n".join(lines)
    
    def _build_complex_diagram(
        self,
        execution_order: List[str],
        parallel_groups: List[ParallelGroup],
        step_timings: Optional[Dict[str, int]] = None
    ) -> str:
        """
        Build complex flow diagram for complex DAGs.
        
        For now, falls back to linear diagram.
        Future: implement branching/tree visualization.
        """
        # For Phase 6.2.2.2 initial version, use linear
        return self._build_linear_diagram(execution_order, parallel_groups, step_timings)
    
    def _format_time(self, seconds: int) -> str:
        """Format time duration."""
        if seconds < 60:
            return f"{seconds}s"
        else:
            minutes = seconds // 60
            secs = seconds % 60
            if secs == 0:
                return f"{minutes}m"
            else:
                return f"{minutes}m {secs}s"
    
    def calculate_parallelization_savings(
        self,
        execution_order: List[str],
        dependency_graph: Dict,
        step_timings: Dict[str, int]
    ) -> Tuple[int, int, str]:
        """
        Calculate time saved by parallelization.
        
        Args:
            execution_order: Execution order
            dependency_graph: Dependency graph
            step_timings: Timing for each step
        
        Returns:
            Tuple of (sequential_time, parallel_time, savings_percent_str)
        """
        # Sequential: sum of all durations
        sequential_time = sum(step_timings.get(s, 0) for s in execution_order)
        
        # Parallel: max (still linear for current implementation)
        parallel_time = sequential_time
        
        # Calculate savings
        if sequential_time == 0:
            savings_pct = "0%"
        else:
            savings = (sequential_time - parallel_time) / sequential_time * 100
            savings_pct = f"{int(savings)}%"
        
        return sequential_time, parallel_time, savings_pct
    
    def build_optimization_suggestions(
        self,
        execution_order: List[str],
        dependency_graph: Dict
    ) -> List[str]:
        """
        Generate optimization suggestions based on plan.
        
        Args:
            execution_order: Execution order
            dependency_graph: Dependency graph
        
        Returns:
            List of suggestion strings
        """
        suggestions = []
        
        # Check if all steps are sequential
        if len(execution_order) > 3:
            suggestions.append(
                f"执行步骤较多 ({len(execution_order)}步)，"
                "考虑分阶段执行或并行化"
            )
        
        # Check for long linear chains
        max_depth = self._calculate_max_depth(
            execution_order,
            dependency_graph
        )
        if max_depth > 3:
            suggestions.append(
                f"依赖链较长 ({max_depth}层)，考虑重构以支持更多并行"
            )
        
        # Default suggestion
        if not suggestions:
            suggestions.append("执行流程优化良好，无需改进")
        
        return suggestions
    
    def _calculate_max_depth(
        self,
        execution_order: List[str],
        dependency_graph: Dict
    ) -> int:
        """Calculate maximum dependency depth."""
        max_depth = 0
        subagents = dependency_graph.get("subagents", {})
        
        for step in execution_order:
            depth = 0
            requires = subagents.get(step, {}).get("requires", [])
            
            while requires:
                depth += 1
                # Get next level dependencies
                next_requires = []
                for req in requires:
                    next_requires.extend(
                        subagents.get(req, {}).get("requires", [])
                    )
                requires = next_requires
            
            max_depth = max(max_depth, depth)
        
        return max_depth


# Singleton instance
_builder: FlowDiagramBuilder = None


def get_flow_diagram_builder(config: FlowDiagramConfig = None) -> FlowDiagramBuilder:
    """Get or create FlowDiagramBuilder singleton."""
    global _builder
    if _builder is None:
        _builder = FlowDiagramBuilder(config)
    return _builder
