#!/usr/bin/env python
"""OLAV Initialization Script - One-time setup for all components.

This script initializes:
1. .olav/settings.json - Agent configuration (from defaults)
2. .olav/knowledge/aliases.md - Device aliases (from nornir hosts.yaml)
3. .olav/capabilities.db - Command whitelist database
4. .olav/data/knowledge.db - Knowledge base (empty, ready for indexing)

Usage:
    uv run python scripts/init.py           # Initialize all
    uv run python scripts/init.py --force   # Overwrite existing files
    uv run python scripts/init.py --check   # Check status only
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root and src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from dotenv import load_dotenv
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

load_dotenv()

console = Console()


def init_settings(olav_dir: Path, force: bool = False) -> bool:
    """Generate .olav/settings.json from .env values with fallback to defaults.

    Args:
        olav_dir: Path to .olav directory
        force: Overwrite existing file

    Returns:
        True if created/updated, False if skipped
    """
    import os

    settings_file = olav_dir / "settings.json"

    if settings_file.exists() and not force:
        print("  ⏭️  settings.json already exists (use --force to overwrite)")
        return False

    # Read values from .env (already loaded by load_dotenv() in main)
    llm_provider = os.getenv("LLM_PROVIDER", "openai")
    llm_model = os.getenv("LLM_MODEL_NAME", "gpt-4o")
    llm_temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))
    llm_max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4096"))

    # Settings structure with values from .env
    settings: dict[str, object] = {
        "agent": {
            "name": "OLAV",
            "description": "Network Operations AI Assistant",
            "version": "0.9",
        },
        "llm": {
            "provider": llm_provider,
            "model": llm_model,
            "temperature": llm_temperature,
            "max_tokens": llm_max_tokens,
        },
        "cli": {"banner": "default", "showBanner": True},
        "diagnosis": {
            "requireApprovalForMicroAnalysis": True,
            "autoApproveIfConfidenceBelow": 0.5,
        },
        "execution": {
            "useTextFSM": True,
            "textFSMFallbackToRaw": True,
            "enableTokenStatistics": True,
        },
        "learning": {"autoSaveSolutions": False, "autoLearnAliases": True},
    }

    # Write settings.json
    settings_file.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  ✅ Created settings.json (from .env: {llm_provider}/{llm_model})")

    return True


def init_aliases_from_nornir(olav_dir: Path, force: bool = False) -> bool:
    """Generate .olav/knowledge/aliases.md from Nornir inventory.

    Supports both SimpleInventory (hosts.yaml) and external inventories
    (NetBox, Nautobot, etc.) by using Nornir API to query devices.

    Args:
        olav_dir: Path to .olav directory
        force: Overwrite existing file

    Returns:
        True if created/updated, False if skipped
    """
    aliases_file = olav_dir / "knowledge" / "aliases.md"

    if aliases_file.exists() and not force:
        print("  ⏭️  aliases.md already exists (use --force to overwrite)")
        return False

    # Try to initialize Nornir and query inventory directly
    hosts_data = {}
    try:
        from nornir import InitNornir

        # Initialize Nornir using config.yaml (supports any inventory plugin)
        config_file = olav_dir / "config" / "nornir" / "config.yaml"
        if not config_file.exists():
            print("  ⚠️  config.yaml not found, cannot initialize Nornir")
        else:
            nr = InitNornir(config_file=str(config_file))
            print(f"  📡 Loaded {len(nr.inventory.hosts)} devices from Nornir inventory")

            # Extract device data from Nornir inventory
            for hostname, host in nr.inventory.hosts.items():
                hosts_data[hostname] = {
                    "hostname": host.hostname,  # IP address
                    "platform": host.platform or "unknown",
                    "data": {
                        "role": host.data.get("role", ""),
                        "site": host.data.get("site", ""),
                        "aliases": host.data.get("aliases", []),
                    },
                }
    except ImportError:
        print("  ⚠️  Nornir not installed, falling back to hosts.yaml")
    except Exception as e:
        print(f"  ⚠️  Error initializing Nornir: {e}, falling back to hosts.yaml")

    # Fallback: Try to read hosts.yaml directly if Nornir failed
    if not hosts_data:
        hosts_file = olav_dir / "config" / "nornir" / "hosts.yaml"
        if not hosts_file.exists():
            print("  ⚠️  hosts.yaml not found, creating empty aliases.md template")
        else:
            try:
                import yaml

                loaded = yaml.safe_load(hosts_file.read_text(encoding="utf-8"))
                hosts_data = loaded if isinstance(loaded, dict) else {}
                print(f"  📖 Loaded {len(hosts_data)} devices from hosts.yaml (fallback)")
            except ImportError:
                print("  ⚠️  PyYAML not installed, creating empty aliases.md template")
            except Exception as e:
                print(f"  ⚠️  Error reading hosts.yaml: {e}")

    # Build aliases markdown
    content = """# Device Aliases

Agent should consult this file before executing commands to convert user-provided aliases to actual device names, IPs, or interfaces.

## Instructions
- When user mentions these aliases, automatically replace them with actual values
- Supports multiple types: device names, IP addresses, interface names, VLANs, etc.
- If user uses a new alias, ask for clarification and then update this file

## Alias Table

| Alias | Actual Value | Type | Platform | Notes |
|-------|--------------|------|----------|-------|
"""

    # Generate aliases from inventory data
    for hostname, host_data in hosts_data.items():
        if not isinstance(host_data, dict):
            continue

        ip: str = str(host_data.get("hostname") or "")  # type: ignore[arg-type]
        platform: str = str(host_data.get("platform") or "unknown")  # type: ignore[arg-type]
        data_val = host_data.get("data")  # type: ignore[attr-defined]
        data: dict[str, object] = data_val if isinstance(data_val, dict) else {}  # type: ignore[assignment]
        role_val = data.get("role")  # type: ignore[attr-defined]
        role: str = str(role_val) if role_val else ""  # type: ignore[arg-type]
        site_val = data.get("site")  # type: ignore[attr-defined]
        site: str = str(site_val) if site_val else ""  # type: ignore[arg-type]
        notes = f"{role}@{site}" if role and site else role or site or ""

        # Add hostname → IP alias
        content += f"| {hostname} | {ip} | device | {platform} | {notes} |\n"

        # Add custom aliases from data.aliases
        aliases_val = data.get("aliases")  # type: ignore[attr-defined]
        aliases: list[object] = aliases_val if isinstance(aliases_val, list) else []  # type: ignore[assignment]
        for alias in aliases:
            alias_str = str(alias)
            content += (
                f"| {alias_str} | {hostname} | device | {platform} | alias for {hostname} |\n"
            )

    content += """
## Usage Examples

### Example 1: Device Alias
User: "Check R1 CPU usage"
Agent Parsing:
- Alias: "R1" → 192.168.100.101
- Execute: nornir_execute("R1", "show processes cpu")

### Example 2: Natural Language
User: "Check the border router status"
Agent Parsing:
- Alias: "border-router-1" → R1
- Execute: nornir_execute("R1", "show version")

## Notes
- Aliases are auto-generated from hosts.yaml during init
- Agent can learn new aliases during conversations
- Run `uv run python scripts/init.py --force` to regenerate from hosts.yaml
"""

    # Ensure directory exists
    aliases_file.parent.mkdir(parents=True, exist_ok=True)
    aliases_file.write_text(content, encoding="utf-8")
    print(f"  ✅ Created aliases.md with {len(hosts_data)} device entries")  # type: ignore[arg-type]

    return True


def init_capabilities(olav_dir: Path, reload: bool = False) -> bool:
    """[DEPRECATED] Command discovery is now handled by CommandRegistry.

    In v0.9+, commands are discovered from TextFSM templates.
    """
    console.print("  ⏭️  Skipping capabilities.db (deprecated in v0.9)")
    return True


def init_knowledge_db(olav_dir: Path) -> bool:
    """Initialize knowledge database schema.

    Args:
        olav_dir: Path to .olav directory

    Returns:
        True if initialized successfully
    """
    from olav.core.database import init_knowledge_db as _init_knowledge_db

    db_path = olav_dir / "data" / "knowledge.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if db_path.exists():
        print("  ⏭️  knowledge.db already exists")
        return False

    _init_knowledge_db()
    print("  ✅ Created knowledge.db schema")
    return True


def init_network_db(olav_dir: Path) -> bool:
    """Initialize network snapshot database with minimal tables.

    Per the Zero-ETL design, we do NOT create structured tables like
    interfaces, routes, bgp_neighbors, etc. Instead, parsed JSON files
    are queried directly using read_json_auto().

    This function only creates:
    - raw_outputs: For tracking raw command outputs (optional metadata)
    - sync_metadata: For tracking sync operations

    Args:
        olav_dir: Path to .olav directory

    Returns:
        True if initialized successfully
    """
    import duckdb

    db_dir = olav_dir / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "olav.duckdb"

    if db_path.exists():
        print("  ⏭️  olav.duckdb already exists")
        return False

    try:
        from olav.core.database import get_database

        get_database(db_path)
        print("  ✅ Initialized olav.duckdb (Zero-ETL: minimal tables)")
        print("     → Parsed data accessed via read_json_auto()")
        return True
    except Exception as e:
        print(f"  ❌ Error initializing olav.duckdb: {e}")
        return False

def validate_hosts_yaml(olav_dir: Path) -> tuple[bool, str]:
    """Validate hosts.yaml exists and has valid structure.

    Args:
        olav_dir: Path to .olav directory

    Returns:
        Tuple of (is_valid, message)
    """
    hosts_file = olav_dir / "config" / "nornir" / "hosts.yaml"

    if not hosts_file.exists():
        return False, f"hosts.yaml not found at {hosts_file}"

    try:
        import yaml

        content = hosts_file.read_text(encoding="utf-8")
        data = yaml.safe_load(content)

        if not isinstance(data, dict):
            return False, "hosts.yaml must contain a YAML dictionary"

        if len(data) == 0:
            return False, "hosts.yaml has no devices defined"

        # Validate each host has required fields
        for hostname, host_data in data.items():
            if not isinstance(host_data, dict):
                return False, f"Host {hostname} must be a dictionary"
            if "hostname" not in host_data:
                return False, f"Host {hostname} missing 'hostname' field (IP address)"

        return True, f"hosts.yaml valid with {len(data)} devices"

    except ImportError:
        return False, "PyYAML not installed, cannot validate hosts.yaml"
    except Exception as e:
        return False, f"Error parsing hosts.yaml: {e}"


def test_device_connectivity(olav_dir: Path, sample_count: int = 1) -> tuple[bool, str]:
    """Test connectivity to sample devices.

    Args:
        olav_dir: Path to .olav directory
        sample_count: Number of devices to test (default: 1)

    Returns:
        Tuple of (all_success, message)
    """
    try:
        from nornir_netmiko.tasks import netmiko_send_command

        from olav.tools.network_executor import get_nornir, reset_nornir

        # Reset to ensure fresh credentials are applied
        reset_nornir()
        nr = get_nornir()

        hosts = list(nr.inventory.hosts.keys())[:sample_count]
        if not hosts:
            return False, "No devices found in inventory"

        print(f"  🔌 Testing connectivity to {len(hosts)} device(s)...")

        success_count = 0
        failed_devices = []

        for host_name in hosts:
            try:
                result = nr.filter(lambda h, name=host_name: h.name == name).run(
                    task=netmiko_send_command,
                    command_string="show version",
                )

                host_result = result.get(host_name)
                if host_result and not host_result.failed:
                    success_count += 1
                    print(f"     ✓ {host_name}: Connected successfully")
                else:
                    failed_devices.append(host_name)
                    error = str(host_result.exception) if host_result else "Unknown error"
                    print(f"     ✗ {host_name}: {error[:60]}...")
            except Exception as e:
                failed_devices.append(host_name)
                print(f"     ✗ {host_name}: {str(e)[:60]}...")

        if success_count == len(hosts):
            return True, f"All {success_count} device(s) connected successfully"
        elif success_count > 0:
            return (
                True,
                f"{success_count}/{len(hosts)} devices connected ({', '.join(failed_devices)} failed)",
            )
        else:
            return False, f"All {len(hosts)} device(s) failed to connect"

    except ImportError as e:
        return False, f"Missing dependency: {e}"
    except Exception as e:
        return False, f"Connection test error: {e}"


def init_directories(olav_dir: Path) -> None:
    """Ensure all required directories exist.

    Args:
        olav_dir: Path to .olav directory
    """
    directories = [
        olav_dir / "knowledge" / "solutions",
        olav_dir / "data",
        olav_dir / "db",
        olav_dir / "reports",
        olav_dir / "scratch",
        olav_dir / "skills",
        olav_dir / "commands",
        olav_dir / "config" / "nornir",
        olav_dir / "config" / "textfsm",  # Custom TextFSM templates
        olav_dir / "config" / "nornir",
        Path("logs"),  # Nornir log directory
        Path("exports"),  # Snapshot exports
    ]

    for dir_path in directories:
        dir_path.mkdir(parents=True, exist_ok=True)


def check_status(olav_dir: Path) -> None:
    """Check initialization status of all components.

    Args:
        olav_dir: Path to .olav directory
    """
    print("\n📋 OLAV Initialization Status")
    print("=" * 50)

    # Check settings.json
    settings_file = olav_dir / "settings.json"
    if settings_file.exists():
        print("✅ settings.json exists")
    else:
        print("❌ settings.json missing")

    # Check aliases.md
    aliases_file = olav_dir / "knowledge" / "aliases.md"
    if aliases_file.exists():
        print("✅ aliases.md exists")
    else:
        print("❌ aliases.md missing")

    # Check capabilities.db
    cap_db = olav_dir / "capabilities.db"
    if cap_db.exists():
        try:
            from olav.core.database import get_database

            db = get_database()
            result = db.conn.execute("SELECT COUNT(*) FROM capabilities").fetchone()
            if result is not None:
                print(f"✅ capabilities.db exists ({result[0]} entries)")
            else:
                print("✅ capabilities.db exists")
        except Exception as e:
            print(f"⚠️  capabilities.db exists but error: {e}")
    else:
        print("❌ capabilities.db missing")

    # Check knowledge.db
    knowledge_db = olav_dir / "db" / "knowledge.duckdb" # v0.9 update
    if knowledge_db.exists():
        print("✅ knowledge.db exists")
    else:
        print("❌ knowledge.db missing")

    # Check hosts.yaml
    hosts_file = olav_dir / "config" / "nornir" / "hosts.yaml"
    if hosts_file.exists():
        print("✅ hosts.yaml exists")
    else:
        print("⚠️  hosts.yaml missing (copy from hosts.yaml.example)")

    print("=" * 50)





# Logic moved to olav.tools.schema_catalog



def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Initialize OLAV environment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    uv run python scripts/init.py                  # Initialize all components
    uv run python scripts/init.py --force          # Overwrite existing files
    uv run python scripts/init.py --check          # Check status only
    uv run python scripts/init.py --refresh-schema # Refresh schema catalog from JSON files
    uv run python scripts/init.py --validate       # Validate configuration only (non-interactive)
        """,
    )
    parser.add_argument("--force", "-f", action="store_true", help="Overwrite existing files")
    parser.add_argument(
        "--check", "-c", action="store_true", help="Check status only, don't initialize"
    )
    parser.add_argument(
        "--validate",
        "-v",
        action="store_true",
        help="Validate configuration only (non-interactive, exit on failure)",
    )
    parser.add_argument(
        "--refresh-schema",
        "-s",
        action="store_true",
        help="Refresh _schema_catalog table from JSON files",
    )
    parser.add_argument(
        "--reload-commands",
        "-r",
        action="store_true",
        help="[DEPRECATED] Reload commands from whitelist files",
    )
    parser.add_argument(
        "--olav-dir",
        type=Path,
        default=project_root / ".olav",
        help="Path to .olav directory",
    )

    args = parser.parse_args()
    olav_dir = args.olav_dir

    if args.check:
        check_status(olav_dir)
        return

    # Refresh schema mode: (No-op in v0.9.6 - Dynamic Discovery used)
    if args.refresh_schema:
        console.print("\n🔄 [bold]Refreshing Schema Catalog[/bold]")
        console.print("=" * 50)
        console.print("[yellow]⚠️  Manual schema refresh is deprecated. Dynamic discovery enabled.[/yellow]")
        console.print("=" * 50)
        return

    # Validation mode: non-interactive, exit on failure
    if args.validate:
        console.print("\n🔍 [bold]OLAV Configuration Validation[/bold]")
        console.print("=" * 50)

        # Validate hosts.yaml
        is_valid, message = validate_hosts_yaml(olav_dir)
        if is_valid:
            console.print(f"✅ {message}")
        else:
            console.print(f"[red]❌ {message}[/red]")
            sys.exit(1)

        # Check if network database exists
        db_path = olav_dir / "db" / "olav.duckdb"
        if db_path.exists():
            console.print(f"✅ olav.duckdb exists at {db_path}")
        else:
            console.print("⚠️  olav.duckdb not found (will be created)")

        # Check settings.json
        settings_file = olav_dir / "settings.json"
        if settings_file.exists():
            console.print("✅ settings.json exists")
        else:
            console.print("⚠️  settings.json not found (will be created)")

        console.print("=" * 50)
        console.print("[green]✅ Validation passed - ready for snapshot[/green]")
        return

    console.print("\n🚀 [bold]OLAV Initialization[/bold]")
    console.print(f"   Directory: {olav_dir}")
    console.print(f"   Force: {args.force}")
    console.print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    console.print("=" * 50)

    # Validate hosts.yaml first (fail fast)
    console.print("\n🔍 [bold]Validating hosts.yaml...[/bold]")
    is_valid, message = validate_hosts_yaml(olav_dir)
    if is_valid:
        console.print(f"  ✅ {message}")
    else:
        console.print(f"  [red]❌ {message}[/red]")
        console.print("\n[yellow]⚠️  Please configure hosts.yaml before running init:[/yellow]")
        console.print("   1. Copy .olav/config/nornir/hosts.yaml.example to hosts.yaml")
        console.print("   2. Add your network devices")
        console.print("   3. Run init again")
        sys.exit(1)

    # Ensure directories exist
    console.print("\n📁 [bold]Creating directories...[/bold]")
    init_directories(olav_dir)
    console.print("  ✅ All directories ready")

    # Initialize settings.json
    console.print("\n⚙️  [bold]Initializing settings.json...[/bold]")
    init_settings(olav_dir, args.force)

    # Initialize aliases.md from nornir
    console.print("\n📝 [bold]Initializing aliases.md from nornir...[/bold]")
    init_aliases_from_nornir(olav_dir, args.force)

    # Initialize capabilities database
    console.print("\n🗃️  [bold]Initializing capabilities.db...[/bold]")
    init_capabilities(olav_dir, reload=args.reload_commands)

    # Initialize knowledge database
    console.print("\n📚 [bold]Initializing knowledge.db...[/bold]")
    init_knowledge_db(olav_dir)

    # Initialize network snapshot database
    console.print("\n🌐 [bold]Initializing olav.duckdb...[/bold]")
    init_network_db(olav_dir)

    # Test device connectivity
    console.print("\n🔌 [bold]Testing device connectivity...[/bold]")
    conn_ok, conn_msg = test_device_connectivity(olav_dir, sample_count=1)
    if conn_ok:
        console.print(f"  ✅ {conn_msg}")
    else:
        console.print(f"  [yellow]⚠️  {conn_msg}[/yellow]")
        console.print("     (Connectivity issues - check credentials in .env)")

    console.print("\n" + "=" * 50)
    console.print("[bold green]✅ OLAV initialization complete![/bold green]")
    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Run: [cyan]uv run olav snapshot[/cyan]  (to collect network data)")
    console.print("  2. Run: [cyan]uv run olav inspect[/cyan]   (to analyze data)")
    console.print("  3. Run: [cyan]uv run olav[/cyan]           (to start interactive query)")


if __name__ == "__main__":
    main()
