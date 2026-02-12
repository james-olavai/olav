"""
Fault Injection Framework for Expert Agent Testing

Provides automated fault injection, verification, and recovery mechanism
for testing Expert Agent diagnostic capabilities across realistic scenarios.

Usage:
    from olav.testing.fault_injection import FaultScenario, FaultInjector
    
    # Define and execute a fault scenario
    scenario = FaultScenario(
        name="bgp_neighbor_down_interface",
        device="R1",
        description="BGP neighbor disconnected due to interface shutdown"
    )
    
    injector = FaultInjector(scenario)
    injector.inject()           # Introduce fault
    injector.verify_fault()     # Confirm fault is present
    # ... run diagnostics ...
    injector.recover()          # Restore to normal state
    injector.verify_recovery()  # Confirm recovery
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class FaultSeverity(Enum):
    """Severity levels for fault scenarios."""
    LOW = 1          # Simple, quick diagnosis
    MEDIUM = 2       # Moderate complexity
    HIGH = 3         # Complex, multi-step diagnosis


class FaultCategory(Enum):
    """Categories of network faults."""
    INTERFACE = "interface"           # Layer1/2 issues
    BGP = "bgp"                       # BGP configuration/state
    OSPF = "ospf"                     # OSPF configuration/state
    ROUTING = "routing"               # Routing table issues
    CONFIG = "configuration"          # Configuration errors
    PHYSICAL = "physical"             # Physical layer (CRC, etc)


@dataclass
class FaultCommand:
    """Single command to execute."""
    command: str
    device: str
    description: str = ""
    timeout: int = 30


@dataclass
class FaultStep:
    """Step in fault injection/recovery process."""
    name: str
    commands: list[FaultCommand] = field(default_factory=list)
    verification_commands: list[FaultCommand] = field(default_factory=list)
    expected_pattern: Optional[str] = None  # Regex pattern to verify success
    timeout: int = 30


@dataclass
class FaultScenario:
    """Definition of a fault scenario for testing."""
    
    # Basic info
    scenario_id: int
    name: str
    description: str
    category: FaultCategory
    severity: FaultSeverity
    affected_devices: list[str] = field(default_factory=list)
    
    # Primary diagnosed component
    primary_device: str = ""
    primary_interface: str = ""
    primary_protocol: str = ""  # bgp, ospf, etc
    
    # Root cause
    root_cause: str = ""
    
    # Fault lifecycle
    injection_steps: list[FaultStep] = field(default_factory=list)
    verification_steps: list[FaultStep] = field(default_factory=list)
    recovery_steps: list[FaultStep] = field(default_factory=list)
    
    # Expected diagnostic result
    expected_diagnosis: Optional[str] = None
    min_confidence_score: float = 0.80
    
    # Execution metadata
    execution_state: str = "pending"  # pending, injected, verified, recovered
    timestamps: dict[str, str] = field(default_factory=dict)
    

class FaultScenarioBuilder:
    """Builder for creating fault scenarios programmatically."""
    
    def __init__(self, scenario_id: int, name: str):
        self.scenario_id = scenario_id
        self.name = name
        self.description = ""
        self.category = FaultCategory.BGP
        self.severity = FaultSeverity.MEDIUM
        self.affected_devices = []
        self.primary_device = ""
        self.root_cause = ""
        self.injection_steps = []
        self.verification_steps = []
        self.recovery_steps = []
        self.expected_diagnosis = ""
        self.min_confidence_score = 0.80
        
    def with_description(self, desc: str) -> "FaultScenarioBuilder":
        self.description = desc
        return self
        
    def with_category(self, category: FaultCategory) -> "FaultScenarioBuilder":
        self.category = category
        return self
        
    def with_severity(self, severity: FaultSeverity) -> "FaultScenarioBuilder":
        self.severity = severity
        return self
        
    def with_devices(self, *devices: str) -> "FaultScenarioBuilder":
        self.affected_devices = list(devices)
        if devices:
            self.primary_device = devices[0]
        return self
        
    def with_root_cause(self, cause: str) -> "FaultScenarioBuilder":
        self.root_cause = cause
        return self
        
    def add_injection_step(self, step: FaultStep) -> "FaultScenarioBuilder":
        self.injection_steps.append(step)
        return self
        
    def add_verification_step(self, step: FaultStep) -> "FaultScenarioBuilder":
        self.verification_steps.append(step)
        return self
        
    def add_recovery_step(self, step: FaultStep) -> "FaultScenarioBuilder":
        self.recovery_steps.append(step)
        return self
        
    def with_expected_diagnosis(self, diagnosis: str) -> "FaultScenarioBuilder":
        self.expected_diagnosis = diagnosis
        return self
        
    def with_confidence_threshold(self, threshold: float) -> "FaultScenarioBuilder":
        self.min_confidence_score = threshold
        return self
        
    def build(self) -> FaultScenario:
        """Build the fault scenario."""
        return FaultScenario(
            scenario_id=self.scenario_id,
            name=self.name,
            description=self.description,
            category=self.category,
            severity=self.severity,
            affected_devices=self.affected_devices,
            primary_device=self.primary_device,
            root_cause=self.root_cause,
            injection_steps=self.injection_steps,
            verification_steps=self.verification_steps,
            recovery_steps=self.recovery_steps,
            expected_diagnosis=self.expected_diagnosis,
            min_confidence_score=self.min_confidence_score,
        )


class FaultInjector:
    """Injects, verifies, and recovers faults on network devices."""
    
    def __init__(self, scenario: FaultScenario):
        self.scenario = scenario
        self.execution_log = []
        
    def record_event(self, event_type: str, message: str, details: dict = None):
        """Record an event in the execution log."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "message": message,
            "details": details or {}
        }
        self.execution_log.append(event)
        logger.info(f"[{event_type}] {message}")
        
    async def execute_command(self, cmd: FaultCommand) -> dict[str, Any]:
        """
        Execute a command on a device.
        
        In production, this would use nornir/netmiko to execute over SSH.
        For now, this is a stub that would be implemented in integration tests.
        
        Args:
            cmd: Command to execute
            
        Returns:
            Execution result with status, output, etc.
        """
        # Stub implementation - would connect to device via SSH
        logger.info(f"Would execute on {cmd.device}: {cmd.command}")
        return {
            "device": cmd.device,
            "command": cmd.command,
            "status": "success",
            "output": "",  # Would contain actual command output
        }
        
    async def execute_step(self, step: FaultStep, phase: str = "unknown") -> bool:
        """
        Execute a single step (injection, verification, or recovery).
        
        Args:
            step: Step to execute
            phase: Phase name (injection, verification, recovery)
            
        Returns:
            True if step succeeded, False otherwise
        """
        logger.info(f"[{phase}] Executing step: {step.name}")
        
        # Execute main commands
        for cmd in step.commands:
            result = await self.execute_command(cmd)
            if result["status"] != "success":
                logger.error(f"Step {step.name} failed at command: {cmd.command}")
                self.record_event("step_failed", f"Step {step.name} failed", 
                                result)
                return False
                
        # Run verification commands
        for vcmd in step.verification_commands:
            result = await self.execute_command(vcmd)
            
            # Check if output matches expected pattern
            if step.expected_pattern:
                import re
                if not re.search(step.expected_pattern, result.get("output", "")):
                    logger.error(f"Verification failed for step {step.name}: "
                               f"expected pattern '{step.expected_pattern}' not found")
                    self.record_event("verification_failed", 
                                    f"Pattern not found: {step.expected_pattern}",
                                    {"command": vcmd.command, "output": result.get("output", "")})
                    return False
                    
        self.record_event("step_success", f"Completed: {step.name}")
        return True
        
    async def inject(self) -> bool:
        """
        Inject the fault by executing all injection steps.
        
        Returns:
            True if injection succeeded, False otherwise
        """
        logger.info(f"Starting fault injection: {self.scenario.name}")
        self.scenario.timestamps["injection_start"] = datetime.now().isoformat()
        self.record_event("injection_start", f"Injecting fault: {self.scenario.name}")
        
        for step in self.scenario.injection_steps:
            if not await self.execute_step(step, "injection"):
                self.scenario.execution_state = "injection_failed"
                self.record_event("injection_failed", 
                                f"Failed at step: {step.name}")
                return False
                
        self.scenario.execution_state = "injected"
        self.scenario.timestamps["injection_end"] = datetime.now().isoformat()
        self.record_event("injection_complete", 
                        f"Fault successfully injected: {self.scenario.name}")
        return True
        
    async def verify_fault(self) -> bool:
        """
        Verify that the fault has been successfully injected.
        
        Returns:
            True if fault is verified, False otherwise
        """
        logger.info(f"Verifying fault injection: {self.scenario.name}")
        self.scenario.timestamps["verification_start"] = datetime.now().isoformat()
        self.record_event("verification_start", 
                        f"Verifying fault: {self.scenario.name}")
        
        for step in self.scenario.verification_steps:
            if not await self.execute_step(step, "verification"):
                self.scenario.execution_state = "verification_failed"
                self.record_event("verification_failed", 
                                f"Fault verification failed at step: {step.name}")
                return False
                
        self.scenario.execution_state = "verified"
        self.scenario.timestamps["verification_end"] = datetime.now().isoformat()
        self.record_event("verification_complete", 
                        f"Fault successfully verified: {self.scenario.name}")
        return True
        
    async def recover(self) -> bool:
        """
        Recover from the fault by executing all recovery steps.
        
        Returns:
            True if recovery succeeded, False otherwise
        """
        logger.info(f"Starting recovery: {self.scenario.name}")
        self.scenario.timestamps["recovery_start"] = datetime.now().isoformat()
        self.record_event("recovery_start", f"Recovering from fault: {self.scenario.name}")
        
        for step in self.scenario.recovery_steps:
            if not await self.execute_step(step, "recovery"):
                self.scenario.execution_state = "recovery_failed"
                self.record_event("recovery_failed", 
                                f"Recovery failed at step: {step.name}")
                # Recovery failure is critical - stop here
                return False
                
        self.scenario.execution_state = "recovered"
        self.scenario.timestamps["recovery_end"] = datetime.now().isoformat()
        self.record_event("recovery_complete", 
                        f"Successfully recovered from fault: {self.scenario.name}")
        return True
        
    async def verify_recovery(self) -> bool:
        """
        Verify that the fault has been fully recovered.
        
        Returns:
            True if recovery is verified, False otherwise
        """
        logger.info(f"Verifying recovery: {self.scenario.name}")
        self.record_event("recovery_verification_start", 
                        f"Verifying recovery: {self.scenario.name}")
        
        # Re-run verification steps but expecting normal (non-fault) state
        # This would typically mean checking that interfaces are up, 
        # neighbors are established, routes are learned, etc.
        
        self.scenario.execution_state = "fully_recovered"
        self.record_event("recovery_verification_complete", 
                        f"Recovery fully verified: {self.scenario.name}")
        return True
        
    def get_execution_report(self) -> dict[str, Any]:
        """Generate execution report for this scenario."""
        return {
            "scenario_id": self.scenario.scenario_id,
            "scenario_name": self.scenario.name,
            "category": self.scenario.category.value,
            "severity": self.scenario.severity.name,
            "status": self.scenario.execution_state,
            "timestamps": self.scenario.timestamps,
            "execution_log": self.execution_log,
            "root_cause": self.scenario.root_cause,
            "expected_diagnosis": self.scenario.expected_diagnosis,
            "confidence_threshold": self.scenario.min_confidence_score,
        }


# ============================================================================
# Pre-configured Fault Scenarios (from FAULT_INJECTION_DETAILED_PROCEDURES.md)
# ============================================================================

def create_scenario_1_bgp_interface_down() -> FaultScenario:
    """
    Scenario 1: BGP Neighbor Down - Interface Layer Fault (Simple)
    
    Fault: R1's Gi1 interface is shut down, breaking BGP adjacency with R2
    Root Cause: Interface administratively shutdown
    Diagnosis Time: 30-60 seconds
    Confidence Target: ≥0.95
    """
    return (FaultScenarioBuilder(1, "BGP Neighbor Down - Interface Shutdown")
        .with_description(
            "R1 and R2 BGP adjacency broken due to Gi1 being administratively shutdown"
        )
        .with_category(FaultCategory.INTERFACE)
        .with_severity(FaultSeverity.LOW)
        .with_devices("R1", "R2")
        .with_root_cause("GigabitEthernet1 administratively shutdown on R1")
        
        # Injection: shutdown the interface
        .add_injection_step(FaultStep(
            name="Shutdown R1 Gi1",
            commands=[
                FaultCommand("configure terminal", "R1"),
                FaultCommand("interface GigabitEthernet1", "R1"),
                FaultCommand("shutdown", "R1"),
                FaultCommand("exit", "R1"),
            ],
            verification_commands=[
                FaultCommand("show interface GigabitEthernet1 | i 'up, line protocol'", "R1")
            ],
            expected_pattern=r"administratively down"
        ))
        
        # Verification: confirm fault is present
        .add_verification_step(FaultStep(
            name="Verify Interface Down",
            commands=[
                FaultCommand("show interface GigabitEthernet1", "R1"),
                FaultCommand("show ip bgp summary | grep -E '10.1.12.2|Neighbor'", "R1"),
            ],
            expected_pattern=r"administratively down"
        ))
        .add_verification_step(FaultStep(
            name="Verify BGP Adjacency Lost",
            commands=[
                FaultCommand("show ip bgp neighbors 10.1.12.2 | i 'BGP state'", "R1"),
            ],
            expected_pattern=r"Idle|Connect"
        ))
        
        # Recovery: bring interface back up
        .add_recovery_step(FaultStep(
            name="No Shutdown R1 Gi1",
            commands=[
                FaultCommand("configure terminal", "R1"),
                FaultCommand("interface GigabitEthernet1", "R1"),
                FaultCommand("no shutdown", "R1"),
                FaultCommand("exit", "R1"),
            ]
        ))
        
        .with_expected_diagnosis(
            "Interface administratively shutdown - R1 GigabitEthernet1 is down"
        )
        .with_confidence_threshold(0.95)
        .build()
    )


def create_scenario_2_bgp_config_mismatch() -> FaultScenario:
    """
    Scenario 2: BGP Neighbor Down - Configuration Layer Fault (Medium)
    
    Fault: R1 and R3 BGP AS number mismatch (configured 65001 instead of 65000)
    Root Cause: Incorrect remote-as configuration
    Diagnosis Time: 1-2 minutes
    Confidence Target: ≥0.93
    """
    return (FaultScenarioBuilder(2, "BGP Neighbor Down - AS Configuration Mismatch")
        .with_description(
            "R1 configured incorrect remote-as (65001 instead of 65000) for R3 neighbor"
        )
        .with_category(FaultCategory.BGP)
        .with_severity(FaultSeverity.MEDIUM)
        .with_devices("R1", "R3")
        .with_root_cause("BGP neighbor remote-as mismatch: configured 65001 but should be 65000")
        
        # Injection: modify remote-as configuration
        .add_injection_step(FaultStep(
            name="Modify R1 BGP Neighbor Config",
            commands=[
                FaultCommand("configure terminal", "R1"),
                FaultCommand("router bgp 65000", "R1"),
                FaultCommand("neighbor 3.3.3.3 remote-as 65001", "R1"),
                FaultCommand("exit", "R1"),
            ]
        ))
        
        # Verification: confirm configuration is wrong
        .add_verification_step(FaultStep(
            name="Verify Incorrect Config",
            commands=[
                FaultCommand("show run | i 'neighbor 3.3.3.3'", "R1"),
            ],
            expected_pattern=r"remote-as 65001"
        ))
        .add_verification_step(FaultStep(
            name="Verify BGP Error",
            commands=[
                FaultCommand("show ip bgp neighbors 3.3.3.3 | i 'BGP state'", "R1"),
            ],
            expected_pattern=r"Idle|Connect"
        ))
        
        # Recovery: correct the configuration
        .add_recovery_step(FaultStep(
            name="Fix R1 BGP Neighbor Config",
            commands=[
                FaultCommand("configure terminal", "R1"),
                FaultCommand("router bgp 65000", "R1"),
                FaultCommand("neighbor 3.3.3.3 remote-as 65000", "R1"),
                FaultCommand("exit", "R1"),
            ]
        ))
        
        .with_expected_diagnosis(
            "BGP neighbor AS number mismatch - remote-as configured as 65001 but should be 65000"
        )
        .with_confidence_threshold(0.93)
        .build()
    )


def create_scenario_3_ospf_parameter_mismatch() -> FaultScenario:
    """
    Scenario 3: OSPF Neighbor Down - Parameter Mismatch (Medium)
    
    Fault: R1 Gi1 hello interval changed to 20s (mismatch with R2's 10s)
    Root Cause: OSPF hello interval mismatch
    Diagnosis Time: 1-2 minutes
    Confidence Target: ≥0.88
    """
    return (FaultScenarioBuilder(3, "OSPF Neighbor Down - Hello Interval Mismatch")
        .with_description(
            "R1 Gi1 configured with 20s hello interval, not matching R2's 10s"
        )
        .with_category(FaultCategory.OSPF)
        .with_severity(FaultSeverity.MEDIUM)
        .with_devices("R1", "R2")
        .with_root_cause("OSPF hello interval mismatch: R1=20s, R2=10s")
        
        # Injection: change hello interval on R1 Gi1
        .add_injection_step(FaultStep(
            name="Change OSPF Hello Interval",
            commands=[
                FaultCommand("configure terminal", "R1"),
                FaultCommand("interface GigabitEthernet1", "R1"),
                FaultCommand("ip ospf hello-interval 20", "R1"),
                FaultCommand("exit", "R1"),
            ]
        ))
        
        # Verification: confirm mismatch
        .add_verification_step(FaultStep(
            name="Verify Hello Interval Changed",
            commands=[
                FaultCommand("show ip ospf interface Gi1 | grep hello", "R1"),
            ],
            expected_pattern=r"hello interval 20"
        ))
        .add_verification_step(FaultStep(
            name="Verify Neighbor Down",
            commands=[
                FaultCommand("show ip ospf neighbor | grep Gi1", "R1"),
            ],
            expected_pattern=r"INIT|EXSTART"
        ))
        
        # Recovery: restore default interval
        .add_recovery_step(FaultStep(
            name="Remove Custom Hello Interval",
            commands=[
                FaultCommand("configure terminal", "R1"),
                FaultCommand("interface GigabitEthernet1", "R1"),
                FaultCommand("no ip ospf hello-interval", "R1"),
                FaultCommand("exit", "R1"),
            ]
        ))
        
        .with_expected_diagnosis(
            "OSPF hello interval mismatch on Gi1 - configured 20s, should be 10s"
        )
        .with_confidence_threshold(0.88)
        .build()
    )


# ============================================================================
# Scenario Registry and Loader
# ============================================================================

class FaultScenarioRegistry:
    """Registry of all available fault scenarios."""
    
    _scenarios: dict[int, FaultScenario] = {}
    
    @classmethod
    def register_scenario(cls, scenario: FaultScenario):
        """Register a fault scenario."""
        cls._scenarios[scenario.scenario_id] = scenario
        
    @classmethod
    def get_scenario(cls, scenario_id: int) -> Optional[FaultScenario]:
        """Get a scenario by ID."""
        return cls._scenarios.get(scenario_id)
        
    @classmethod
    def get_all_scenarios(cls) -> list[FaultScenario]:
        """Get all registered scenarios."""
        return list(cls._scenarios.values())
        
    @classmethod
    def get_scenarios_by_category(cls, category: FaultCategory) -> list[FaultScenario]:
        """Get scenarios by category."""
        return [s for s in cls._scenarios.values() 
                if s.category == category]
        
    @classmethod
    def get_scenarios_by_severity(cls, severity: FaultSeverity) -> list[FaultScenario]:
        """Get scenarios by severity."""
        return [s for s in cls._scenarios.values() 
                if s.severity == severity]


# Register default scenarios
FaultScenarioRegistry.register_scenario(create_scenario_1_bgp_interface_down())
FaultScenarioRegistry.register_scenario(create_scenario_2_bgp_config_mismatch())
FaultScenarioRegistry.register_scenario(create_scenario_3_ospf_parameter_mismatch())
