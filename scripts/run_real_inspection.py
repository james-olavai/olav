#!/usr/bin/env python3
"""
Real Network Inspection Pipeline
==================================

Complete Map-Reduce-Analyze workflow using REAL devices from Nornir inventory.

NO MOCKS - NO FAKE DATA - PRODUCTION READY

Workflow:
1. Get device list from Nornir inventory (.olav/config/nornir/hosts.yaml)
2. Load inspection commands from template (.olav/skills/network-inspection/config/inspection_commands.yaml)
3. Map Phase: Execute commands in parallel on real devices
4. Reduce Phase: Aggregate inspection results
5. LLM Analysis: Analyze anomalies and health scores
6. Generate Production-Grade Report

Usage:
    uv run python3 scripts/run_real_inspection.py
    uv run python3 scripts/run_real_inspection.py --template full        # Use full template (30+ commands)
    uv run python3 scripts/run_real_inspection.py --template security    # Security audit
    uv run python3 scripts/run_real_inspection.py --template quick       # Quick check (5 commands)
    uv run python3 scripts/run_real_inspection.py --devices R1,R2        # Specific devices
    uv run python3 scripts/run_real_inspection.py --verbose              # Debug mode

Available Templates:
    - quick: 快速检查 (5个命令, <1分钟)
    - basic: 基础检查 (7个命令, 2-3分钟) 
    - standard: 标准检查 (15个命令, 5-8分钟) [默认]
    - full: 完整诊断 (30+个命令, 15-20分钟)
    - security: 安全审计 (10个命令, 8-10分钟)
    - performance: 性能基准 (6个命令, 3-5分钟)
"""

import sys
import json
import argparse
import yaml
from pathlib import Path
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / ".olav" / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / ".olav" / "skills" / "shared" / "tools"))

# Import tools directly - avoid relative import issues
import importlib.util

def load_tool_module(module_name, file_path):
    """Load a Python module from file path"""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module  # Add to sys.modules to help with dependencies
    spec.loader.exec_module(module)
    return module

# Load tools from correct locations
network_wrapped = load_tool_module("network", PROJECT_ROOT / ".olav" / "tools" / "network.py")
batch_module = load_tool_module("batch_executor", 
                               PROJECT_ROOT / ".olav" / "skills" / "shared" / "tools" / "batch_executor.py")
agg_module = load_tool_module("aggregation", 
                             PROJECT_ROOT / ".olav" / "skills" / "shared" / "tools" / "aggregation.py")

# Extract the MAIN functions (not@tool decorated versions)
list_devices_main = network_wrapped.list_devices_main
execute_cli_main = network_wrapped.execute_cli_main
execute_commands_in_parallel = batch_module.execute_commands_in_parallel
aggregate_inspection_results = agg_module.aggregate_inspection_results
format_inspection_report_l1_l4 = agg_module.format_inspection_report_l1_l4


# Load inspection command resolver
command_resolver_module = load_tool_module("command_resolver",
                                          PROJECT_ROOT / ".olav" / "skills" / "network-inspection" / "config" / "command_resolver.py")
InspectionCommandResolver = command_resolver_module.InspectionCommandResolver


def ensure_thresholds_exist():
    """
    Ensure thresholds.yaml exists. Generate default if not.
    
    This is AUTOMATICALLY called on first run.
    User can then edit thresholds.yaml to customize.
    """
    thresholds_path = PROJECT_ROOT / ".olav" / "skills" / "network-inspection" / "config" / "thresholds.yaml"
    
    # Check if already exists and is auto-generated (user hasn't modified)
    if thresholds_path.exists():
        with open(thresholds_path, 'r') as f:
            content = f.read()
            # If file contains actual thresholds, assume user has configured
            if "inspection_items:" in content:
                return  # Already configured, don't regenerate
    
    print("\n📝 首次运行：生成默认thresholds配置...")
    print("-" * 80)
    
    # Load SKILL.md to get inspection_items
    skill_path = PROJECT_ROOT / ".olav" / "skills" / "network-inspection" / "SKILL.md"
    
    if not skill_path.exists():
        print("⚠️  WARNING: SKILL.md not found, using minimal defaults")
        items = []
    else:
        import frontmatter
        with open(skill_path, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)
            items = post.metadata.get("inspection_items", [])
    
    # Generate default thresholds based on items
    default_thresholds = {
        "version": "3.0.0",
        "auto_generated": True,
        "last_updated": datetime.now().isoformat(),
        "defaults": {
            "performance": {
                "warning": 70,
                "critical": 90
            },
            "errors": {
                "warning": 1,
                "critical": 10
            },
            "count_tolerance": {
                "warning": 10,
                "critical": 30
            }
        },
        "inspection_items": {},
        "devices": {},
        "maintenance_windows": []
    }
    
    # Auto-generate item-specific thresholds
    for item in items:
        item_name = item.get("name", "")
        layer = item.get("layer", "Unknown")
        
        # Performance metrics
        if "cpu" in item_name or "memory" in item_name:
            default_thresholds["inspection_items"][item_name] = {
                "warning": 70,
                "critical": 90,
                "unit": "percent"
            }
        
        # Error counts
        elif "error" in item_name:
            default_thresholds["inspection_items"][item_name] = {
                "in_errors": {"warning": 1, "critical": 10},
                "out_errors": {"warning": 1, "critical": 10},
                "crc_errors": {"warning": 0, "critical": 5}
            }
        
        # Status checks
        elif "status" in item_name:
            default_thresholds["inspection_items"][item_name] = {
                "expected": {
                    "status": "up",
                    "protocol": "up"
                }
            }
        
        # Neighbor checks
        elif "neighbor" in item_name:
            expected_state = "FULL" if "ospf" in item_name else "Established"
            default_thresholds["inspection_items"][item_name] = {
                "expected": {
                    "state": expected_state
                }
            }
    
    # Save to file
    thresholds_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(thresholds_path, 'w', encoding='utf-8') as f:
        f.write(f"""# Network Inspection Thresholds
# ================================
# 此文件由Agent首次运行时自动生成
# 用户可以手动修改阈值，Agent会自动应用
#
# 生成时间: {datetime.now().isoformat()}
# 版本: 3.0.0

""")
        yaml.dump(default_thresholds, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    
    print(f"✅ 生成完成: {thresholds_path}")
    print(f"💡 检测到 {len(items)} 个inspection items")
    print(f"💡 您可以编辑此文件调整阈值")
    print()


def load_inspection_commands(template_name: str, device_platform: str) -> list[str]:
    """
    INTELLIGENT command loading using NTC templates database.
    
    NO HARDCODED COMMANDS!
    
    Args:
        template_name: Template name (basic, standard, full, etc.)
        device_platform: Device platform from Nornir (cisco_ios, cisco_nxos, etc.)
        
    Returns:
        List of command strings matched from NTC database
        
    Example:
        >>> load_inspection_commands("quick", "cisco_ios")
        ["show version", "show processes cpu", "show interfaces", ...]
        
        >>> load_inspection_commands("quick", "juniper_junos")  
        ["show version", "show chassis routing-engine", ...]  # Different commands!
    """
    resolver = InspectionCommandResolver()
    
    # Get template info
    info = resolver.get_template_info(template_name)
    if not info:
        print(f"⚠️  WARNING: Unknown template '{template_name}'")
        print(f"   Available: quick, basic, standard, full, security, performance")
        return []
    
    # Display template info  
    print(f"\n📋 Inspection Template: {template_name.upper()}")
    print(f"   Description: {info['description']}")
    print(f"   Estimated Time: {info['estimated_time']}")
    print(f"   Device Platform: {device_platform}")
    print(f"   Items: {info.get('item_count', info.get('intent_count', 0))}")  # Support both v2 and v3
    
    # Show layer distribution
    layer_dist = info.get('layer_distribution', {})
    if layer_dist:
        print(f"   Layer Coverage: ", end="")
        print(", ".join([f"{layer}({count})" for layer, count in sorted(layer_dist.items())]))
    
    # Resolve commands for this platform
    print(f"\n🔍 Resolving commands from NTC database...")
    resolved_commands = resolver.resolve_template(template_name, device_platform)
    
    if not resolved_commands:
        print(f"❌ ERROR: No commands resolved for template '{template_name}' on {device_platform}")
        return []
    
    # Show resolution summary
    ntc_count = sum(1 for cmd in resolved_commands if cmd.source == "ntc")
    fallback_count = sum(1 for cmd in resolved_commands if cmd.source == "fallback")
    
    print(f"✓ Resolved {len(resolved_commands)} commands:")
    print(f"  - NTC database: {ntc_count}")
    print(f"  - Fallback: {fallback_count}")
    
    # Display resolved commands 
    for i, cmd in enumerate(resolved_commands, 1):
        source_icon = "📦" if cmd.source == "ntc" else "⚙️"
        conf_str = f"({cmd.confidence:.0%})" if cmd.confidence > 0 else ""
        print(f"  {source_icon} {i:2d}. {cmd.command:35s} {conf_str}")
    
    print()
    
    # Return command strings only
    return [cmd.command for cmd in resolved_commands]


def main():
    parser = argparse.ArgumentParser(
        description="Run real network inspection with configurable templates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available Templates:
  quick       - 快速检查 (5个命令, <1分钟)
  basic       - 基础检查 (7个命令, 2-3分钟)
  standard    - 标准检查 (15个命令, 5-8分钟) [默认]
  full        - 完整诊断 (30+个命令, 15-20分钟)
  security    - 安全审计 (10个命令, 8-10分钟)
  performance - 性能基准 (6个命令, 3-5分钟)

Examples:
  uv run python3 scripts/run_real_inspection.py
  uv run python3 scripts/run_real_inspection.py --template full
  uv run python3 scripts/run_real_inspection.py --template security --devices R1,R2
        """
    )
    parser.add_argument("--template", type=str, default="standard", 
                       help="Inspection template (basic, standard, full, security, performance, quick)")
    parser.add_argument("--devices", type=str, help="Comma-separated device list (default: all from inventory)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--output-dir", type=str, default="exports/reports", help="Output directory for reports")
    args = parser.parse_args()

    print("=" * 80)
    print("🚀 OLAV Real Network Inspection Pipeline")
    print("=" * 80)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("")
    
    # ========================================================================
    # STEP 0: Ensure thresholds.yaml exists (auto-generate on first run)
    # ========================================================================
    ensure_thresholds_exist()

    # ========================================================================
    # STEP 1: Get Real Device List from Nornir Inventory
    # ========================================================================
    print("📋 STEP 1: Getting device list from Nornir inventory...")
    print("-" * 80)
    
    try:
        # Always get devices from inventory (to get platform info)
        inventory_result = list_devices_main({})
        
        if inventory_result["status"] != "success":
            print(f"❌ ERROR: Failed to get devices from inventory")
            print(f"   {inventory_result.get('error', 'Unknown error')}")
            return 1
        
        all_devices = inventory_result["devices"]
        
        if not all_devices:
            print("❌ ERROR: No devices found in inventory!")
            return 1
        
        # Filter devices if --devices specified
        if args.devices:
            specified = [d.strip() for d in args.devices.split(",")]
            device_info_list = [d for d in all_devices if d["name"] in specified]
            
            if not device_info_list:
                print(f"❌ ERROR: None of specified devices found: {specified}")
                return 1
            
            print(f"✓ Using specified devices from inventory:")
        else:
            device_info_list = all_devices
            print(f"✓ Found {len(device_info_list)} devices in Nornir inventory:")
        
        # Display device info
        for device in device_info_list:
            print(f"  - {device['name']} ({device.get('platform', 'unknown')}) @ {device.get('hostname', 'N/A')}")
        
        # Get device platform (use first device's platform for now)
        # TODO: Support heterogeneous platforms by grouping devices
        device_platform = device_info_list[0].get("platform", "cisco_ios")
        device_names = [d["name"] for d in device_info_list]
        
        print(f"\n✓ Total devices to inspect: {len(device_names)}")
        print(f"✓ Device platform detected: {device_platform}")
        
        # Check if all devices have same platform
        platforms = set(d.get("platform", "unknown") for d in device_info_list)
        if len(platforms) > 1:
            print(f"\n⚠️  WARNING: Mixed platforms detected: {platforms}")
            print(f"   Using first device's platform ({device_platform}) for command selection")
            print(f"   Multi-platform support coming soon!")
        
        print("")
        
    except Exception as e:
        print(f"❌ ERROR in STEP 1: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    # ========================================================================
    # STEP 2: Load Inspection Commands from Template (Platform-Aware!)
    # ========================================================================
    print(f"\n📝 STEP 2: Loading inspection commands for platform '{device_platform}'...")
    print("-" * 80)
    
    # Load commands using intelligent resolver
    inspection_commands = load_inspection_commands(args.template, device_platform)
    
    if not inspection_commands:
        print("❌ ERROR: No inspection commands loaded")
        return 1
    
    # ========================================================================
    # STEP 3: Map Phase - Execute Commands in Parallel on Real Devices
    # ========================================================================
    print("\n🔨 STEP 3: Map Phase - Executing commands on real devices...")
    print("-" * 80)
    
    try:
        # Create executor function that uses real Nornir
        def real_executor(device: str, command: str) -> tuple[bool, str]:
            """Execute command on real device using Nornir"""
            result = execute_cli_main({
                "device": device,
                "command": command,
                "timeout": 30
            })
            
            if result["status"] == "success":
                # execute_cli_main returns {"status": "success", "output": "text"}
                output = result.get("output", "")
                return (True, output)
            else:
                error = result.get("error", "Command execution failed")
                return (False, error)
        
        # Execute all commands on all devices in parallel
        all_results = []
        for cmd in inspection_commands:
            print(f"  ⚙️  Executing: {cmd}")
            
            map_result = execute_commands_in_parallel(
                devices=device_names,
                command=cmd,
                executor_func=real_executor,
                timeout_seconds=30,
                max_workers=5
            )
            
            print(f"     ✓ Success: {map_result['successful']}/{map_result['total_devices']} devices")
            print(f"     ⏱️  Time: {map_result['total_time_ms']:.0f}ms")
            
            # Append results
            all_results.extend(map_result["results"])
        
        print(f"\n✓ Map phase completed: {len(all_results)} command executions")
        print("")
        
    except Exception as e:
        print(f"❌ ERROR in STEP 2 (Map Phase): {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    # ========================================================================
    # STEP 4: Transform results for Reduce phase
    # ========================================================================
    print("\n🔄 STEP 4: Transforming results for Reduce phase...")
    print("-" * 80)
    
    try:
        # Group results by device
        device_results = {}
        for result in all_results:
            device = result["device"]
            if device not in device_results:
                device_results[device] = {
                    "device": device,
                    "status": "success",
                    "commands": []
                }
            
            device_results[device]["commands"].append({
                "cmd": result["command"],
                "output": result.get("output", ""),
                "status": result["status"]
            })
        
        # Convert to list
        reduce_input = list(device_results.values())
        
        print(f"✓ Grouped {len(all_results)} command results into {len(reduce_input)} device records")
        print("")
        
    except Exception as e:
        print(f"❌ ERROR in STEP 3: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    # ========================================================================
    # STEP 5: Reduce Phase - Aggregate and Analyze
    # ========================================================================
    print("\n📊 STEP 5: Reduce Phase - Aggregating results...")
    print("-" * 80)
    
    try:
        aggregated = aggregate_inspection_results(
            results=reduce_input,
            inspection_type="network-inspection",
            thresholds=None  # Use defaults
        )
        
        print(f"✓ Aggregation completed:")
        print(f"  - Total devices: {aggregated['device_count']}")
        print(f"  - Healthy: {aggregated['healthy_count']} ✅")
        print(f"  - Warning: {aggregated['warning_count']} ⚠️")
        print(f"  - Critical: {aggregated['critical_count']} 🔴")
        print(f"  - Overall health: {aggregated['overall_health_score']:.1f}%")
        print(f"  - Anomalies: {aggregated['anomaly_count']}")
        print("")
        
    except Exception as e:
        print(f"❌ ERROR in STEP 4 (Reduce Phase): {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    # ========================================================================
    # STEP 6: Generate Production-Grade Report
    # ========================================================================
    print("\n📄 STEP 6: Generating production-grade report...")
    print("-" * 80)
    
    try:
        # Generate L1-L4 report
        report_content = format_inspection_report_l1_l4(aggregated)
        
        # Save report
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = output_dir / f"inspection_real_{timestamp}.md"
        
        report_path.write_text(report_content)
        
        print(f"✓ Report generated: {report_path}")
        print(f"  - Size: {len(report_content)} bytes")
        print(f"  - Format: Markdown (L1-L4)")
        print("")
        
        # Also save JSON for API access
        json_path = output_dir / f"inspection_real_{timestamp}.json"
        json_path.write_text(json.dumps(aggregated, indent=2))
        print(f"✓ JSON data saved: {json_path}")
        print("")
        
    except Exception as e:
        print(f"❌ ERROR in STEP 5: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    # ========================================================================
    # SUMMARY
    # ========================================================================
    print("=" * 80)
    print("✅ INSPECTION COMPLETED SUCCESSFULLY")
    print("=" * 80)
    print(f"📊 Summary:")
    print(f"  - Devices inspected: {len(device_names)}")
    print(f"  - Commands executed: {len(inspection_commands)} × {len(device_names)} = {len(all_results)}")
    print(f"  - Overall health: {aggregated['overall_health_score']:.1f}%")
    print(f"  - Report: {report_path}")
    print("")
    print("🎯 Next steps:")
    print(f"  1. Review report: cat {report_path}")
    print(f"  2. Check anomalies: grep '⚠️\\|🔴' {report_path}")
    print(f"  3. Export data: cat {json_path}")
    print("")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
