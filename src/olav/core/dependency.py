"""Dependency Graph Management for Collaborative Mode (Phase 5)

This module provides utilities for building, validating, and traversing
dependency graphs defined in SKILL.md collaborative_mode configurations.

Key Components:
- DependencyGraph: Directed Acyclic Graph representation
- CircularDependencyError: Raised when circular dependency detected
- MissingContextError: Raised when required context unavailable
- build_dependency_graph(): Construct and validate DAG
- topological_sort(): Determine execution order
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# =============================================================================
# Custom Exceptions
# =============================================================================


class CircularDependencyError(Exception):
    """Raised when a circular dependency is detected in the dependency graph."""
    
    def __init__(self, cycle_path: List[str]):
        self.cycle_path = cycle_path
        super().__init__(
            f"Circular dependency detected: {' → '.join(cycle_path)} → {cycle_path[0]}"
        )


class MissingContextError(Exception):
    """Raised when required context is not available during execution."""
    
    def __init__(self, subagent: str, missing_keys: Set[str]):
        self.subagent = subagent
        self.missing_keys = missing_keys
        super().__init__(
            f"SubAgent '{subagent}' missing required context: {', '.join(missing_keys)}"
        )


class InvalidDependencyError(Exception):
    """Raised when dependency configuration is invalid."""
    
    def __init__(self, message: str):
        super().__init__(message)


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class SubAgentMetadata:
    """Metadata for a single SubAgent in the dependency configuration."""
    
    name: str
    task_template: str
    output_context_key: str
    requires: List[str] = field(default_factory=list)
    
    def validate(self) -> None:
        """Validate metadata has required fields."""
        if not self.name:
            raise InvalidDependencyError("SubAgent 'name' is required")
        if not self.task_template:
            raise InvalidDependencyError(f"SubAgent '{self.name}': 'task_template' is required")
        if not self.output_context_key:
            raise InvalidDependencyError(f"SubAgent '{self.name}': 'output_context_key' is required")
        if not isinstance(self.requires, list):
            raise InvalidDependencyError(
                f"SubAgent '{self.name}': 'requires' must be a list"
            )


@dataclass
class DependencyGraph:
    """Directed Acyclic Graph representing SubAgent dependencies."""
    
    # Maps subagent name to list of subagent names it depends on
    graph: Dict[str, List[str]] = field(default_factory=dict)
    
    # Maps output_context_key to producing subagent
    output_to_subagent: Dict[str, str] = field(default_factory=dict)
    
    # Maps subagent name to its metadata
    subagents: Dict[str, SubAgentMetadata] = field(default_factory=dict)
    
    def get_dependencies(self, subagent: str) -> List[str]:
        """Get list of subagents that the given subagent depends on."""
        return self.graph.get(subagent, [])
    
    def get_dependents(self, subagent: str) -> List[str]:
        """Get list of subagents that depend on the given subagent."""
        return [
            name for name, deps in self.graph.items()
            if subagent in deps
        ]
    
    def validate(self) -> None:
        """Validate graph structure (idempotent check)."""
        # Check that all dependencies reference existing subagents
        for name, deps in self.graph.items():
            for dep in deps:
                if dep not in self.subagents:
                    raise InvalidDependencyError(
                        f"SubAgent '{name}' depends on non-existent '{dep}'"
                    )


# =============================================================================
# Graph Building
# =============================================================================


def build_dependency_graph(
    dependencies: List[Dict[str, Any]],
) -> DependencyGraph:
    """Build and validate a dependency graph from configuration.
    
    Args:
        dependencies: List of dependency declarations from collaborative_mode
        
    Returns:
        DependencyGraph object with validated DAG structure
        
    Raises:
        CircularDependencyError: If circular dependency detected
        InvalidDependencyError: If configuration is invalid
    """
    if not dependencies:
        return DependencyGraph()
    
    # Parse and validate metadata
    subagents_dict: Dict[str, SubAgentMetadata] = {}
    output_map: Dict[str, str] = {}
    
    for dep in dependencies:
        if not isinstance(dep, dict):
            continue
        
        name = dep.get("subagent")
        if not name:
            continue
        
        # Create metadata
        metadata = SubAgentMetadata(
            name=name,
            task_template=dep.get("task_template", ""),
            output_context_key=dep.get("output_context_key", ""),
            requires=dep.get("requires", [])
        )
        metadata.validate()
        
        subagents_dict[name] = metadata
        
        # Map output key to subagent
        if metadata.output_context_key:
            output_map[metadata.output_context_key] = name
    
    # Build adjacency list (convert output keys to subagent names)
    graph_dict: Dict[str, List[str]] = {}
    
    for name, metadata in subagents_dict.items():
        dependencies_list: List[str] = []
        
        # Convert output_context_key dependencies to subagent dependencies
        for required_key in metadata.requires:
            if required_key in output_map:
                required_subagent = output_map[required_key]
                if required_subagent not in dependencies_list:
                    dependencies_list.append(required_subagent)
        
        graph_dict[name] = dependencies_list
    
    # Check for circular dependencies
    _detect_cycles(graph_dict, subagents_dict)
    
    # Create and validate graph
    graph = DependencyGraph(
        graph=graph_dict,
        output_to_subagent=output_map,
        subagents=subagents_dict
    )
    graph.validate()
    
    logger.debug(
        f"Built dependency graph: {len(subagents_dict)} subagents, "
        f"{sum(len(d) for d in graph_dict.values())} edges"
    )
    
    return graph


def _detect_cycles(
    graph: Dict[str, List[str]],
    subagents: Dict[str, SubAgentMetadata],
) -> None:
    """Detect cycles in the dependency graph using DFS.
    
    Args:
        graph: Adjacency list representation
        subagents: SubAgent metadata
        
    Raises:
        CircularDependencyError: If cycle detected
    """
    visited: Set[str] = set()
    rec_stack: Set[str] = set()
    parent_map: Dict[str, Optional[str]] = {}
    
    def visit_dfs(node: str, path: List[str]) -> None:
        """DFS traversal to detect cycles."""
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                parent_map[neighbor] = node
                visit_dfs(neighbor, path.copy())
            elif neighbor in rec_stack:
                # Found cycle
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                raise CircularDependencyError(cycle)
        
        rec_stack.remove(node)
    
    # Check all nodes
    for node in graph:
        if node not in visited:
            try:
                visit_dfs(node, [])
            except CircularDependencyError:
                raise


# =============================================================================
# Topological Sort
# =============================================================================


def topological_sort(graph: DependencyGraph) -> List[str]:
    """Determine execution order using Kahn's algorithm.
    
    Subagents with no dependencies execute first, followed by their
    dependents in order of dependency satisfaction.
    
    Args:
        graph: DependencyGraph object
        
    Returns:
        List of subagent names in execution order (dependencies first)
    """
    if not graph.graph:
        return []
    
    # Calculate in-degree for each node
    in_degree: Dict[str, int] = {node: 0 for node in graph.graph}
    
    for node in graph.graph:
        for dependent in graph.get_dependents(node):
            in_degree[dependent] += 1
    
    # Initialize queue with nodes having no dependencies
    queue: List[str] = sorted([
        node for node in graph.graph
        if in_degree[node] == 0
    ])
    
    result: List[str] = []
    
    while queue:
        # Process node with lowest in-degree (for deterministic ordering)
        node = queue.pop(0)
        result.append(node)
        
        # Reduce in-degree of dependents
        for dependent in sorted(graph.get_dependents(node)):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)
                queue.sort()
    
    # Verify all nodes processed (would indicate cycle, but already checked)
    if len(result) != len(graph.graph):
        logger.warning(
            f"Topological sort processed {len(result)}/{len(graph.graph)} nodes. "
            "This may indicate a cycle (should have been caught earlier)."
        )
    
    return result


def get_execution_order(dependencies: List[Dict[str, Any]]) -> List[str]:
    """Get the execution order for SubAgents given dependencies.
    
    Convenience function that combines build and sort.
    
    Args:
        dependencies: List of dependency declarations
        
    Returns:
        List of subagent names in execution order
        
    Raises:
        CircularDependencyError: If circular dependency detected
        InvalidDependencyError: If configuration invalid
    """
    if not dependencies:
        return []
    
    graph = build_dependency_graph(dependencies)
    return topological_sort(graph)


# =============================================================================
# Execution Planning
# =============================================================================


def plan_execution(
    dependencies: List[Dict[str, Any]],
    include_metadata: bool = False,
) -> Dict[str, Any]:
    """Create an execution plan from dependency configuration.
    
    Args:
        dependencies: List of dependency declarations
        include_metadata: If True, include subagent metadata in plan
        
    Returns:
        Dictionary with:
            - 'execution_order': List of subagent names
            - 'graph': DependencyGraph (if requested)
            - 'metadata': SubAgent metadata (if requested)
    """
    graph = build_dependency_graph(dependencies)
    order = topological_sort(graph)
    
    result = {"execution_order": order}
    
    if include_metadata:
        result["graph"] = graph
        result["metadata"] = {
            name: {
                "task_template": meta.task_template,
                "output_context_key": meta.output_context_key,
                "requires": meta.requires,
            }
            for name, meta in graph.subagents.items()
        }
    
    return result
