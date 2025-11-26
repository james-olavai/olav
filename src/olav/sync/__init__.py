"""
NetBox Bidirectional Sync Module.

This module provides:
- DiffEngine: Compare network state (SuzieQ/CLI/OpenConfig) with NetBox SSOT
- NetBoxReconciler: Sync differences back to NetBox with HITL approval
- InspectionIntegration: Integrate diff into inspection/巡检 workflow

Architecture:
    SuzieQ/OpenConfig/CLI → DiffEngine → Reconciliation → NetBox

Usage:
    from olav.sync import DiffEngine, NetBoxReconciler
    
    engine = DiffEngine()
    diffs = await engine.compare_all(devices=["R1", "R2"])
    
    reconciler = NetBoxReconciler(netbox_tool)
    result = await reconciler.reconcile(diffs)
"""

from olav.sync.models import (
    DiffResult,
    DiffSeverity,
    DiffSource,
    EntityType,
    ReconciliationReport,
    ReconcileAction,
    ReconcileResult,
)
from olav.sync.diff_engine import DiffEngine
from olav.sync.reconciler import NetBoxReconciler

__all__ = [
    "DiffEngine",
    "DiffResult",
    "DiffSeverity",
    "DiffSource",
    "EntityType",
    "NetBoxReconciler",
    "ReconciliationReport",
    "ReconcileAction",
    "ReconcileResult",
]
