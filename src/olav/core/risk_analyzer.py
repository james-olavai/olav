"""
Risk Analyzer for SubAgent Execution Planning

Phase 6.2.2.3: Risk analysis for execution plans.
Calculates risk score based on dependency complexity, step count, etc.

Author: OLAV Development Team
Version: 0.9.8
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple
from enum import Enum


class RiskLevel(str, Enum):
    """Risk level enumeration."""
    LOW = "🟢 低"
    MEDIUM = "🟡 中"
    HIGH = "🔴 高"


@dataclass
class RiskFactors:
    """Individual risk factors."""
    step_count: int
    max_dependency_depth: int  # Max dependencies a step has
    dependency_complexity: int  # Total number of dependency edges
    circular_dependencies: bool = False
    
    @property
    def step_count_score(self) -> float:
        """Score based on number of steps (0-10)."""
        if self.step_count < 3:
            return 2.0
        elif self.step_count < 5:
            return 5.0
        else:
            return min(10.0, self.step_count)
    
    @property
    def dependency_depth_score(self) -> float:
        """Score based on max dependency depth (0-10)."""
        if self.max_dependency_depth == 0:
            return 1.0
        elif self.max_dependency_depth == 1:
            return 3.0
        elif self.max_dependency_depth == 2:
            return 6.0
        else:
            return min(10.0, self.max_dependency_depth * 2)
    
    @property
    def dependency_complexity_score(self) -> float:
        """Score based on total dependencies (0-10)."""
        if self.dependency_complexity == 0:
            return 1.0
        elif self.dependency_complexity < 3:
            return 3.0
        elif self.dependency_complexity < 5:
            return 6.0
        else:
            return 10.0
    
    @property
    def circular_dependency_score(self) -> float:
        """Score for circular dependencies."""
        return 10.0 if self.circular_dependencies else 0.0


@dataclass
class RiskAnalysis:
    """Risk analysis result."""
    level: RiskLevel
    score: float  # 0-10
    factors: RiskFactors
    recommendations: List[str]
    
    def format_for_markdown(self) -> str:
        """Format risk analysis for markdown display."""
        lines = [
            f"- **风险等级**: {self.level.value}",
            f"- **风险评分**: {self.score:.1f}/10.0",
            f"  - 步骤数: {self.factors.step_count} ({'低' if self.factors.step_count < 3 else '中' if self.factors.step_count < 5 else '高'})",
            f"  - 依赖深度: {self.factors.max_dependency_depth}层 ({'低' if self.factors.max_dependency_depth <= 1 else '中' if self.factors.max_dependency_depth == 2 else '高'})",
            f"  - 依赖复杂度: {self.factors.dependency_complexity}条边 ({'低' if self.factors.dependency_complexity == 0 else '中' if self.factors.dependency_complexity < 5 else '高'})",
        ]
        
        if self.factors.circular_dependencies:
            lines.append("  - ⚠️ **循环依赖**: 检测到循环！")
        
        if self.recommendations:
            lines.append("- **建议**:")
            for rec in self.recommendations:
                lines.append(f"  - {rec}")
        
        return "\n".join(lines)


class RiskAnalyzer:
    """
    Analyzes risk level of execution plans.
    
    Considers:
    - Number of steps
    - Dependency complexity
    - Circular dependency presence
    - Critical path length
    """
    
    def analyze(
        self,
        dependency_graph: Dict,
        execution_order: List[str],
        critical_path: List[str] = None
    ) -> RiskAnalysis:
        """
        Analyze risk of a plan.
        
        Args:
            dependency_graph: Dependency graph with subagents
            execution_order: Topologically sorted execution order
            critical_path: Critical path steps (optional)
        
        Returns:
            RiskAnalysis with score and recommendations
        """
        # Extract factors
        factors = self._extract_factors(dependency_graph, execution_order)
        
        # Calculate risk score
        score = self._calculate_score(factors)
        
        # Determine risk level
        if score < 3.5:
            level = RiskLevel.LOW
        elif score < 6.5:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.HIGH
        
        # Generate recommendations
        recommendations = self._generate_recommendations(
            factors, execution_order, critical_path or []
        )
        
        return RiskAnalysis(
            level=level,
            score=score,
            factors=factors,
            recommendations=recommendations
        )
    
    def _extract_factors(
        self,
        dependency_graph: Dict,
        execution_order: List[str]
    ) -> RiskFactors:
        """Extract risk factors from dependency graph."""
        subagents = dependency_graph.get("subagents", {})
        
        # Count steps
        step_count = len(execution_order)
        
        # Calculate max dependency depth
        max_depth = 0
        for subagent in subagents.values():
            depth = self._calculate_dependency_depth(
                subagent.get("requires", []),
                subagents,
                visited=set()
            )
            max_depth = max(max_depth, depth)
        
        # Count total dependencies (edges)
        dependency_complexity = sum(
            len(sa.get("requires", []))
            for sa in subagents.values()
        )
        
        # Check for circular dependencies
        # (Already detected in _build_dependency_graph, but check again)
        circular = self._has_circular_dependencies(subagents)
        
        return RiskFactors(
            step_count=step_count,
            max_dependency_depth=max_depth,
            dependency_complexity=dependency_complexity,
            circular_dependencies=circular
        )
    
    def _calculate_dependency_depth(
        self,
        requirements: List[str],
        all_subagents: Dict,
        visited: set
    ) -> int:
        """
        Calculate maximum dependency depth.
        
        Depth 0 = no dependencies
        Depth 1 = depends on steps with no dependencies
        Depth 2 = depends on steps that depend on steps with no dependencies
        etc.
        """
        if not requirements:
            return 0
        
        max_dep_depth = 0
        for req in requirements:
            if req in visited:
                continue  # Skip circular references
            
            visited.add(req)
            
            # Get dependencies of this requirement
            req_info = all_subagents.get(req, {})
            req_deps = req_info.get("requires", [])
            
            # Recursively calculate depth
            sub_depth = self._calculate_dependency_depth(
                req_deps, all_subagents, visited
            )
            max_dep_depth = max(max_dep_depth, 1 + sub_depth)
        
        return max_dep_depth
    
    def _has_circular_dependencies(self, subagents: Dict) -> bool:
        """Check if there are circular dependencies."""
        for name, info in subagents.items():
            if self._has_circular_path(name, info.get("requires", []), subagents, visited=set()):
                return True
        return False
    
    def _has_circular_path(
        self,
        start: str,
        current_deps: List[str],
        all_subagents: Dict,
        visited: set
    ) -> bool:
        """Check if there's a circular path from start."""
        for dep in current_deps:
            if dep == start:
                return True  # Found circle
            
            if dep in visited:
                continue
            
            visited.add(dep)
            
            dep_info = all_subagents.get(dep, {})
            if self._has_circular_path(
                start,
                dep_info.get("requires", []),
                all_subagents,
                visited
            ):
                return True
        
        return False
    
    def _calculate_score(self, factors: RiskFactors) -> float:
        """Calculate overall risk score (0-10)."""
        # Weight: 30% step count, 40% dependency depth, 30% complexity
        score = (
            factors.step_count_score * 0.3 +
            factors.dependency_depth_score * 0.4 +
            factors.dependency_complexity_score * 0.3 +
            factors.circular_dependency_score
        )
        
        # Cap at 10
        return min(10.0, score)
    
    def _generate_recommendations(
        self,
        factors: RiskFactors,
        execution_order: List[str],
        critical_path: List[str]
    ) -> List[str]:
        """Generate risk mitigation recommendations."""
        recommendations = []
        
        # Step count recommendations
        if factors.step_count > 5:
            recommendations.append(
                f"执行步骤较多 ({factors.step_count}步)，建议分阶段执行"
            )
        
        # Dependency depth recommendations
        if factors.max_dependency_depth > 2:
            recommendations.append(
                f"依赖链较长 (最多{factors.max_dependency_depth}层)，"
                "失败影响范围大，监控前置步骤"
            )
        
        # Circular dependency recommendations
        if factors.circular_dependencies:
            recommendations.append("⚠️ **严重**: 检测到循环依赖，计划无法执行！")
        
        # Critical path recommendations
        if critical_path:
            if len(critical_path) > 2:
                recommendations.append(
                    f"关键路径: {' → '.join(critical_path)}，"
                    "应优先保证这些步骤的成功"
                )
        
        # Default recommendation
        if not recommendations:
            recommendations.append("执行计划风险低，可以安心执行")
        
        return recommendations


# Singleton instance
_analyzer: RiskAnalyzer = None


def get_risk_analyzer() -> RiskAnalyzer:
    """Get or create RiskAnalyzer singleton."""
    global _analyzer
    if _analyzer is None:
        _analyzer = RiskAnalyzer()
    return _analyzer
