"""
NetBox Reconciler - Sync differences back to NetBox.

Applies corrections to NetBox based on DiffEngine results,
with HITL approval for critical changes.
"""

import logging
from typing import Any, Callable

from olav.sync.models import (
    DiffResult,
    DiffSeverity,
    EntityType,
    ReconciliationReport,
    ReconcileAction,
    ReconcileResult,
)
from olav.sync.diff_engine import DiffEngine
from olav.tools.netbox_tool import NetBoxAPITool

logger = logging.getLogger(__name__)


class NetBoxReconciler:
    """
    Reconciler for syncing network state to NetBox.
    
    Supports three modes:
    1. Auto-correct: Safe fields updated automatically
    2. HITL: Critical changes require approval
    3. Report-only: Log differences without changes
    
    Usage:
        reconciler = NetBoxReconciler(netbox_tool)
        results = await reconciler.reconcile(report)
    """
    
    def __init__(
        self,
        netbox_tool: NetBoxAPITool | None = None,
        diff_engine: DiffEngine | None = None,
        hitl_callback: Callable[[DiffResult], bool] | None = None,
        dry_run: bool = False,
    ) -> None:
        """
        Initialize NetBoxReconciler.
        
        Args:
            netbox_tool: NetBox API tool (default: create new)
            diff_engine: Diff engine for field classification
            hitl_callback: Callback for HITL approval (receives diff, returns bool)
            dry_run: If True, don't make actual changes
        """
        self.netbox = netbox_tool or NetBoxAPITool()
        self.diff_engine = diff_engine or DiffEngine(netbox_tool=self.netbox)
        self.hitl_callback = hitl_callback
        self.dry_run = dry_run
        
        # Stats
        self.stats = {
            "auto_corrected": 0,
            "hitl_approved": 0,
            "hitl_rejected": 0,
            "hitl_pending": 0,
            "report_only": 0,
            "errors": 0,
        }
    
    async def reconcile(
        self,
        report: ReconciliationReport,
        auto_correct: bool = True,
        require_hitl: bool = True,
    ) -> list[ReconcileResult]:
        """
        Reconcile differences from a report.
        
        Args:
            report: ReconciliationReport from DiffEngine
            auto_correct: Apply auto-corrections for safe fields
            require_hitl: Require approval for critical fields
            
        Returns:
            List of ReconcileResult for each diff
        """
        results = []
        
        for diff in report.diffs:
            result = await self._process_diff(diff, auto_correct, require_hitl)
            results.append(result)
            
            # Update stats
            self.stats[result.action.value] = self.stats.get(result.action.value, 0) + 1
        
        return results
    
    async def _process_diff(
        self,
        diff: DiffResult,
        auto_correct: bool,
        require_hitl: bool,
    ) -> ReconcileResult:
        """Process a single diff."""
        
        # Check if this is just a missing entity report
        if diff.field == "existence":
            return ReconcileResult(
                diff=diff,
                action=ReconcileAction.REPORT_ONLY,
                success=True,
                message=f"Entity existence difference logged: {diff.network_value} vs {diff.netbox_value}",
            )
        
        # Check if auto-correctable
        if diff.auto_correctable and auto_correct:
            return await self._auto_correct(diff)
        
        # Check if HITL required
        if self.diff_engine.requires_hitl(diff):
            if require_hitl:
                return await self._request_hitl(diff)
            else:
                return ReconcileResult(
                    diff=diff,
                    action=ReconcileAction.SKIPPED,
                    success=True,
                    message="HITL required but disabled - skipping",
                )
        
        # Default: report only
        return ReconcileResult(
            diff=diff,
            action=ReconcileAction.REPORT_ONLY,
            success=True,
            message=f"Difference logged: {diff.field}",
        )
    
    async def _auto_correct(self, diff: DiffResult) -> ReconcileResult:
        """Apply auto-correction for a diff."""
        if self.dry_run:
            return ReconcileResult(
                diff=diff,
                action=ReconcileAction.AUTO_CORRECTED,
                success=True,
                message=f"[DRY RUN] Would update {diff.field} to {diff.network_value}",
            )
        
        if not diff.netbox_id or not diff.netbox_endpoint:
            return ReconcileResult(
                diff=diff,
                action=ReconcileAction.ERROR,
                success=False,
                message="Missing NetBox ID or endpoint for update",
            )
        
        try:
            # Build update payload
            field_name = diff.field.split(".")[-1]
            update_data = {field_name: diff.network_value}
            
            # Execute PATCH
            result = await self.netbox.execute(
                path=f"{diff.netbox_endpoint}{diff.netbox_id}/",
                method="PATCH",
                data=update_data,
            )
            
            if result.error:
                return ReconcileResult(
                    diff=diff,
                    action=ReconcileAction.ERROR,
                    success=False,
                    message=f"NetBox update failed: {result.error}",
                    netbox_response=result.data,
                )
            
            logger.info(f"Auto-corrected {diff.device}/{diff.field}: {diff.netbox_value} → {diff.network_value}")
            
            return ReconcileResult(
                diff=diff,
                action=ReconcileAction.AUTO_CORRECTED,
                success=True,
                message=f"Updated {diff.field} from {diff.netbox_value} to {diff.network_value}",
                netbox_response=result.data,
            )
            
        except Exception as e:
            logger.error(f"Auto-correct failed: {e}")
            return ReconcileResult(
                diff=diff,
                action=ReconcileAction.ERROR,
                success=False,
                message=f"Exception: {str(e)}",
            )
    
    async def _request_hitl(self, diff: DiffResult) -> ReconcileResult:
        """Request HITL approval for a diff."""
        if not self.hitl_callback:
            return ReconcileResult(
                diff=diff,
                action=ReconcileAction.HITL_PENDING,
                success=True,
                message="HITL approval required - no callback configured",
            )
        
        try:
            approved = self.hitl_callback(diff)
            
            if approved:
                # Apply the change
                if self.dry_run:
                    return ReconcileResult(
                        diff=diff,
                        action=ReconcileAction.HITL_APPROVED,
                        success=True,
                        message=f"[DRY RUN] HITL approved - would update {diff.field}",
                    )
                
                # Actually apply the change
                return await self._apply_hitl_approved(diff)
            else:
                return ReconcileResult(
                    diff=diff,
                    action=ReconcileAction.HITL_REJECTED,
                    success=True,
                    message="Change rejected by operator",
                )
                
        except Exception as e:
            logger.error(f"HITL callback failed: {e}")
            return ReconcileResult(
                diff=diff,
                action=ReconcileAction.ERROR,
                success=False,
                message=f"HITL callback exception: {str(e)}",
            )
    
    async def _apply_hitl_approved(self, diff: DiffResult) -> ReconcileResult:
        """Apply a HITL-approved change."""
        if not diff.netbox_id or not diff.netbox_endpoint:
            return ReconcileResult(
                diff=diff,
                action=ReconcileAction.ERROR,
                success=False,
                message="Missing NetBox ID or endpoint for HITL update",
            )
        
        try:
            field_name = diff.field.split(".")[-1]
            update_data = {field_name: diff.network_value}
            
            result = await self.netbox.execute(
                path=f"{diff.netbox_endpoint}{diff.netbox_id}/",
                method="PATCH",
                data=update_data,
            )
            
            if result.error:
                return ReconcileResult(
                    diff=diff,
                    action=ReconcileAction.ERROR,
                    success=False,
                    message=f"HITL update failed: {result.error}",
                    netbox_response=result.data,
                )
            
            logger.info(f"HITL approved and applied {diff.device}/{diff.field}")
            
            return ReconcileResult(
                diff=diff,
                action=ReconcileAction.HITL_APPROVED,
                success=True,
                message=f"HITL approved - updated {diff.field}",
                netbox_response=result.data,
            )
            
        except Exception as e:
            return ReconcileResult(
                diff=diff,
                action=ReconcileAction.ERROR,
                success=False,
                message=f"HITL apply exception: {str(e)}",
            )
    
    def get_stats(self) -> dict[str, int]:
        """Get reconciliation statistics."""
        return self.stats.copy()
    
    def reset_stats(self) -> None:
        """Reset statistics counters."""
        self.stats = {
            "auto_corrected": 0,
            "hitl_approved": 0,
            "hitl_rejected": 0,
            "hitl_pending": 0,
            "report_only": 0,
            "errors": 0,
        }


async def run_reconciliation(
    devices: list[str],
    dry_run: bool = True,
    auto_correct: bool = True,
) -> tuple[ReconciliationReport, list[ReconcileResult]]:
    """
    Convenience function to run full reconciliation.
    
    Args:
        devices: List of device hostnames
        dry_run: If True, don't make actual changes
        auto_correct: Apply auto-corrections
        
    Returns:
        Tuple of (ReconciliationReport, list of ReconcileResults)
    """
    netbox = NetBoxAPITool()
    engine = DiffEngine(netbox_tool=netbox)
    reconciler = NetBoxReconciler(
        netbox_tool=netbox,
        diff_engine=engine,
        dry_run=dry_run,
    )
    
    # Generate diff report
    report = await engine.compare_all(devices)
    
    # Apply reconciliation
    results = await reconciler.reconcile(
        report,
        auto_correct=auto_correct,
        require_hitl=True,
    )
    
    return report, results
