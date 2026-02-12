"""
Time Estimator for SubAgent Execution Planning

Phase 6.2.2.1: Dynamic time estimation for execution plan display.
Provides per-subagent timing profiles and calculates total/critical path times.

Author: OLAV Development Team
Version: 0.9.8
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass
class SubAgentTimingProfile:
    """Timing profile for a SubAgent type."""
    name: str
    base_duration_seconds: int  # e.g., 20, 45
    memory_multiplier: float = 1.0  # Adjust based on data size
    description: str = ""


@dataclass
class StepTiming:
    """Timing information for a single execution step."""
    step_number: int
    subagent_name: str
    estimated_duration: int  # seconds
    wait_time: int = 0  # seconds waiting for dependencies
    critical_path: bool = False  # Is this step on the critical path?
    
    @property
    def total_time(self) -> int:
        """Total time including waits."""
        return self.estimated_duration + self.wait_time


class TimeEstimator:
    """
    Estimates execution times for SubAgent plans.
    
    Features:
    - Per-SubAgent timing profiles (configurable)
    - Critical path analysis
    - Parallel opportunity detection
    - Total execution time calculation
    """
    
    # Default timing profiles (in seconds)
    DEFAULT_PROFILES: Dict[str, SubAgentTimingProfile] = {
        "query": SubAgentTimingProfile(
            name="query",
            base_duration_seconds=20,
            description="Query network devices or databases"
        ),
        "netbox": SubAgentTimingProfile(
            name="netbox",
            base_duration_seconds=45,
            description="Query NetBox API and process data"
        ),
        "analyzer": SubAgentTimingProfile(
            name="analyzer",
            base_duration_seconds=20,
            description="Analyze and compare data"
        ),
        "bgp": SubAgentTimingProfile(
            name="bgp",
            base_duration_seconds=30,
            description="BGP diagnosis and analysis"
        ),
        "ospf": SubAgentTimingProfile(
            name="ospf",
            base_duration_seconds=25,
            description="OSPF diagnosis and analysis"
        ),
        "generic": SubAgentTimingProfile(
            name="generic",
            base_duration_seconds=20,
            description="Generic SubAgent execution"
        ),
    }
    
    def __init__(self):
        """Initialize with default or custom profiles."""
        self.profiles: Dict[str, SubAgentTimingProfile] = self.DEFAULT_PROFILES.copy()
        self._load_custom_profiles()
    
    def _load_custom_profiles(self) -> None:
        """Load custom timing profiles from settings/environment."""
        # Could load from .olav/settings.json or environment variables
        # For now, just use defaults
        pass
    
    def estimate_step_duration(
        self, 
        subagent_name: str, 
        data_size_factor: float = 1.0
    ) -> int:
        """
        Estimate execution duration for a single SubAgent.
        
        Args:
            subagent_name: Name of the SubAgent (e.g., "query", "netbox")
            data_size_factor: Multiplier for data size (1.0 = normal, 2.0 = 2x data)
        
        Returns:
            Estimated duration in seconds
        """
        profile = self.profiles.get(
            subagent_name.lower(),
            self.profiles["generic"]
        )
        
        # Apply data size multiplier
        duration = int(profile.base_duration_seconds * data_size_factor)
        return duration
    
    def calculate_execution_times(
        self,
        dependency_graph: Dict,
        execution_order: List[str]
    ) -> Tuple[List[StepTiming], int, List[str]]:
        """
        Calculate timing for all steps in execution plan.
        
        Args:
            dependency_graph: Graph with subagents and their dependencies
            execution_order: Topologically sorted execution order
        
        Returns:
            Tuple of:
            - List[StepTiming]: Timing for each step
            - int: Total estimated time in seconds
            - List[str]: Critical path (list of step names)
        """
        step_timings: List[StepTiming] = []
        step_completion_times: Dict[str, int] = {}
        
        # Calculate completion time for each step
        for step_idx, subagent_name in enumerate(execution_order, 1):
            # Get step duration
            duration = self.estimate_step_duration(subagent_name)
            
            # Calculate wait time (time waiting for dependencies)
            subagent_info = dependency_graph["subagents"].get(subagent_name, {})
            requires = subagent_info.get("requires", [])
            
            wait_time = 0
            if requires:
                # Maximum completion time of dependencies
                # In linear execution, this is max of all dep completion times
                wait_time = max(
                    step_completion_times.get(dep, 0) 
                    for dep in requires
                )
            
            # Completion time for this step
            completion_time = wait_time + duration
            step_completion_times[subagent_name] = completion_time
            
            # Create StepTiming
            timing = StepTiming(
                step_number=step_idx,
                subagent_name=subagent_name,
                estimated_duration=duration,
                wait_time=wait_time
            )
            step_timings.append(timing)
        
        # Total time is completion time of last step
        total_time = step_completion_times.get(
            execution_order[-1] if execution_order else "",
            0
        )
        
        # Identify critical path
        # Critical path = steps that directly affect total execution time
        critical_path = self._identify_critical_path(
            execution_order,
            dependency_graph,
            step_completion_times
        )
        
        # Mark critical path steps
        for timing in step_timings:
            if timing.subagent_name in critical_path:
                timing.critical_path = True
        
        return step_timings, total_time, critical_path
    
    def _identify_critical_path(
        self,
        execution_order: List[str],
        dependency_graph: Dict,
        step_completion_times: Dict[str, int]
    ) -> List[str]:
        """
        Identify critical path (steps that determine total execution time).
        
        Args:
            execution_order: Execution order list
            dependency_graph: Dependency graph
            step_completion_times: Completion time for each step
        
        Returns:
            List of step names on the critical path
        """
        if not execution_order:
            return []
        
        # For a simple case, work backwards from the last step
        critical_path = []
        last_step = execution_order[-1]
        critical_path.append(last_step)
        
        # Trace back dependencies
        current = last_step
        while True:
            subagent_info = dependency_graph["subagents"].get(current, {})
            requires = subagent_info.get("requires", [])
            
            if not requires:
                # No more dependencies
                break
            
            # Find the dependency that determines this step's timing
            # (the one that finishes last)
            next_critical = max(
                requires,
                key=lambda dep: step_completion_times.get(dep, 0)
            )
            
            critical_path.append(next_critical)
            current = next_critical
        
        return list(reversed(critical_path))
    
    def format_duration(self, seconds: int) -> str:
        """
        Format duration for display.
        
        Args:
            seconds: Duration in seconds
        
        Returns:
            Formatted string (e.g., "1m 25s", "20s")
        """
        if seconds < 60:
            return f"{seconds}s"
        else:
            minutes = seconds // 60
            secs = seconds % 60
            if secs == 0:
                return f"{minutes}m"
            else:
                return f"{minutes}m {secs}s"
    
    def get_profile_description(self, subagent_name: str) -> str:
        """Get human-readable description of a SubAgent."""
        profile = self.profiles.get(
            subagent_name.lower(),
            self.profiles["generic"]
        )
        return profile.description


# Singleton instance
_estimator: TimeEstimator = None


def get_time_estimator() -> TimeEstimator:
    """Get or create TimeEstimator singleton."""
    global _estimator
    if _estimator is None:
        _estimator = TimeEstimator()
    return _estimator
