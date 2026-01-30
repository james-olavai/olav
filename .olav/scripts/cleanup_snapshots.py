#!/usr/bin/env python3
"""
Data Retention Cleanup Script

This script implements the tiered retention policy defined in retention_policy.yaml.
It can be run manually or scheduled via cron.

Usage:
    uv run python .olav/scripts/cleanup_snapshots.py [--dry-run]
    
Example:
    # Preview what would be deleted
    uv run python .olav/scripts/cleanup_snapshots.py --dry-run
    
    # Actually delete old snapshots
    uv run python .olav/scripts/cleanup_snapshots.py
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml


def load_retention_policy(config_path: Path) -> dict[str, Any]:
    """Load retention policy from YAML config.
    
    Args:
        config_path: Path to retention_policy.yaml
        
    Returns:
        Retention policy configuration
    """
    if not config_path.exists():
        print(f"⚠️  Config not found: {config_path}")
        print("Using default policy: keep last 90 days")
        return {
            "retention": {
                "enabled": True,
                "tiers": [
                    {"name": "hot", "duration_days": 7, "keep_frequency": "all"},
                    {"name": "warm", "duration_days": 30, "keep_frequency": "daily"},
                    {"name": "cold", "duration_days": 90, "keep_frequency": "weekly"},
                ],
            },
            "rules": {"delete_after_days": 90, "min_snapshots_to_keep": 3},
        }
    
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_snapshot_dirs(exports_dir: Path) -> list[tuple[Path, datetime]]:
    """Get all snapshot directories with their dates.
    
    Args:
        exports_dir: Path to exports/snapshots directory
        
    Returns:
        List of (path, date) tuples, sorted by date descending
    """
    snapshots = []
    
    for snapshot_dir in exports_dir.glob("*"):
        if not snapshot_dir.is_dir():
            continue
        if snapshot_dir.name == "latest":  # Skip symlink
            continue
            
        try:
            # Parse date from directory name (YYYY-MM-DD format)
            date = datetime.strptime(snapshot_dir.name, "%Y-%m-%d")
            snapshots.append((snapshot_dir, date))
        except ValueError:
            print(f"⚠️  Skipping invalid snapshot dir: {snapshot_dir.name}")
            continue
    
    # Sort by date, newest first
    snapshots.sort(key=lambda x: x[1], reverse=True)
    return snapshots


def should_keep_snapshot(
    snapshot_date: datetime, 
    now: datetime, 
    tiers: list[dict[str, Any]]
) -> tuple[bool, str]:
    """Determine if a snapshot should be kept based on retention policy.
    
    Args:
        snapshot_date: Date of the snapshot
        now: Current date
        tiers: Retention tier configuration
        
    Returns:
        (should_keep, reason) tuple
    """
    age_days = (now - snapshot_date).days
    
    # Check each tier
    for tier in tiers:
        duration = tier["duration_days"]
        frequency = tier["keep_frequency"]
        
        if age_days <= duration:
            if frequency == "all":
                return (True, f"Hot tier (age: {age_days}d)")
            elif frequency == "daily":
                # Keep if it's the last snapshot of the day
                # (This is simplified - in production, check if it's actually the last)
                return (True, f"Warm tier - daily (age: {age_days}d)")
            elif frequency == "weekly":
                # Keep if it's the last snapshot of the week
                # (Simplified - keep if it's a Monday or the last of the week)
                if snapshot_date.weekday() == 0:  # Monday
                    return (True, f"Cold tier - weekly (age: {age_days}d)")
    
    return (False, f"Expired (age: {age_days}d)")


def cleanup_snapshots(
    exports_dir: Path,
    policy: dict[str, Any],
    dry_run: bool = False
) -> dict[str, Any]:
    """Clean up old snapshots according to retention policy.
    
    Args:
        exports_dir: Path to exports/snapshots directory
        policy: Retention policy configuration
        dry_run: If True, only preview without deleting
        
    Returns:
        Cleanup statistics
    """
    if not policy["retention"]["enabled"]:
        print("⚠️  Retention policy is disabled")
        return {"status": "disabled"}
    
    now = datetime.now()
    tiers = policy["retention"]["tiers"]
    min_keep = policy["rules"]["min_snapshots_to_keep"]
    
    snapshots = get_snapshot_dirs(exports_dir)
    
    if len(snapshots) <= min_keep:
        print(f"✅ Only {len(snapshots)} snapshots, keeping all (min: {min_keep})")
        return {"status": "ok", "kept": len(snapshots), "deleted": 0}
    
    print(f"\n📊 Found {len(snapshots)} snapshots")
    print(f"📋 Retention policy: {len(tiers)} tiers")
    print(f"🔒 Minimum to keep: {min_keep}\n")
    
    to_keep = []
    to_delete = []
    
    for snapshot_dir, snapshot_date in snapshots:
        should_keep, reason = should_keep_snapshot(snapshot_date, now, tiers)
        
        if should_keep:
            to_keep.append((snapshot_dir, reason))
        else:
            to_delete.append((snapshot_dir, reason))
    
    # Ensure we keep at least min_snapshots_to_keep
    if len(to_keep) < min_keep:
        # Move some from to_delete to to_keep
        need_more = min_keep - len(to_keep)
        for i in range(min(need_more, len(to_delete))):
            snapshot_dir, _ = to_delete[i]
            to_keep.append((snapshot_dir, "Safety net (min keep)"))
        to_delete = to_delete[need_more:]
    
    # Display results
    print(f"✅ Keeping {len(to_keep)} snapshots:")
    for snapshot_dir, reason in to_keep[:5]:  # Show first 5
        print(f"   {snapshot_dir.name}: {reason}")
    if len(to_keep) > 5:
        print(f"   ... and {len(to_keep) - 5} more")
    
    print(f"\n🗑️  Deleting {len(to_delete)} snapshots:")
    for snapshot_dir, reason in to_delete:
        print(f"   {snapshot_dir.name}: {reason}")
    
    # Delete snapshots
    deleted_count = 0
    if not dry_run and to_delete:
        print(f"\n{'[DRY RUN] ' if dry_run else ''}Deleting snapshots...")
        for snapshot_dir, _ in to_delete:
            try:
                import shutil
                shutil.rmtree(snapshot_dir)
                deleted_count += 1
                print(f"   ✓ Deleted: {snapshot_dir.name}")
            except Exception as e:
                print(f"   ✗ Failed to delete {snapshot_dir.name}: {e}")
    elif dry_run:
        print(f"\n[DRY RUN] Would delete {len(to_delete)} snapshots")
    
    return {
        "status": "ok",
        "kept": len(to_keep),
        "deleted": deleted_count,
        "dry_run": dry_run,
    }


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Clean up old snapshots")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be deleted without actually deleting",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(".olav/config/retention_policy.yaml"),
        help="Path to retention policy config",
    )
    parser.add_argument(
        "--exports-dir",
        type=Path,
        default=Path("exports/snapshots"),
        help="Path to snapshots directory",
    )
    
    args = parser.parse_args()
    
    print("🧹 OLAV Snapshot Cleanup")
    print("=" * 50)
    
    # Load policy
    policy = load_retention_policy(args.config)
    
    # Run cleanup
    result = cleanup_snapshots(args.exports_dir, policy, args.dry_run)
    
    print("\n" + "=" * 50)
    print(f"✅ Cleanup complete: kept {result['kept']}, deleted {result['deleted']}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
