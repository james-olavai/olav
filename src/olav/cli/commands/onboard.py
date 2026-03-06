"""Onboarding command for OLAV — UI/UX Guidance Layer only.

Architecture (per dev_docs/04.workflow.md §3.1):
  Steps 0-2: interactive environment validation (this file).
  Steps 3+:  delegated entirely to Config Agent via run_single_query().
             Agent reads snapshot_sop.md and orchestrates atomically.

  Entry points:
    olav onboard                                          # guided setup
    olav --agent config "take snapshot"                   # manual run
    olav --agent config --auto-approve "take snapshot"    # cron / unattended
"""

import json
import logging
import sys
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm
from rich.table import Table

from olav.cli.commands.base import BaseCommand
from olav.core.config import AGENT_DIR, CONFIG_DIR, REPAIR_QUEUE_PATH
from olav.core.llm import LLMFactory

logger = logging.getLogger(__name__)


class OnboardCommand(BaseCommand):
    """Guided onboarding — interactive UI layer only."""

    def __init__(self) -> None:
        super().__init__(name="onboard", description="Guided OLAV setup and data collection")
        self.console = Console()

    async def execute(self, args: str = "") -> str:
        """Execute the guided onboarding workflow."""
        self.console.clear()
        self.console.print(
            Panel.fit(
                "[bold cyan]Welcome to OLAV Onboarding[/bold cyan]\n"
                "This process will guide you through configuring your AI and synchronizing your network data.",
                border_style="cyan",
            )
        )

        if not await self._step_infra():
            return "Onboarding aborted at infrastructure stage."
        if not await self._step_llm():
            return "Onboarding aborted at LLM stage."
        if not await self._step_nornir():
            return "Onboarding aborted at Nornir stage."

        # ── Step A: Sync inventory + command library ──────────────────────────
        # Two fast deterministic calls — still via agent for status reporting.
        self.console.print(
            Panel.fit(
                "[bold green]✅ Environment verified[/bold green]\n\n"
                "Step 3a: Syncing inventory and command library...",
                border_style="green",
            )
        )

        from olav.cli.main import run_single_query

        await run_single_query(
            "Run sync_inventory() then sync_commands(). "
            "DO NOT run collect_commands or generate_topology — those run next. "
            "Report device count and template count only.",
            assistant_id="config",
        )

        # ── Step B: Staged pipeline — each stage has its own live progress ──────
        # collect_commands → repair HIGH gaps (LLM per gap) → run_topology_sandbox
        # Stages are called individually so the user sees real-time progress.
        _sync_tools = AGENT_DIR / "workspace" / "config" / "sync" / "tools"
        _learner_tools = AGENT_DIR / "workspace" / "config" / "learner" / "tools"
        _discovery_tools = AGENT_DIR / "workspace" / "config" / "discovery" / "tools"
        for _p in (_sync_tools, _learner_tools, _discovery_tools):
            if str(_p) not in sys.path:
                sys.path.insert(0, str(_p))

        from collect_commands import collect_commands  # noqa: PLC0415
        from repair_template import repair_template  # noqa: PLC0415
        from run_topology_sandbox import run_topology_sandbox  # noqa: PLC0415

        # ── Stage 1: SSH Collect + TextFSM Parse ──────────────────────────────
        self.console.rule("[bold cyan]Stage 1: SSH Collect + Parse[/bold cyan]")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
        ) as progress:
            task = progress.add_task("SSH connecting to all devices...", total=None)
            collect_result = collect_commands.func(wait=True)
            progress.update(task, description="✅ Collection complete", completed=True)

        snapshot_id = collect_result.get("snapshot_id", "unknown")
        parse_errors = collect_result.get("parse_errors", [])
        devices = collect_result.get("devices", [])
        diff_records = collect_result.get("diff_records", 0)

        stage1_table = Table(title=f"Snapshot: {snapshot_id}", box=box.ROUNDED)
        stage1_table.add_column("Metric", style="cyan")
        stage1_table.add_column("Value", style="green")
        stage1_table.add_row("Devices", str(len(devices)))
        stage1_table.add_row("Total parse errors", str(len(parse_errors)))
        stage1_table.add_row("Diff records", str(diff_records))
        self.console.print(stage1_table)

        # ── Stage 2: Read repair_queue.json + route by error_type ────────────
        repair_queue_path = Path(REPAIR_QUEUE_PATH)
        queue_entries: list[dict] = []
        if repair_queue_path.exists():
            try:
                with open(repair_queue_path, encoding="utf-8") as _f:
                    _rq = json.load(_f)
                queue_entries = _rq.get("queue", [])
            except Exception as _rq_err:
                self.console.print(
                    f"[yellow]⚠ Could not read repair_queue.json: {_rq_err}[/yellow]"
                )

        # Split queue by error type
        wrap_p0 = [
            q
            for q in queue_entries
            if q.get("error_type") == "collection_wrap" and q.get("priority") == "P0_core"
        ]
        repair_p0 = [
            q
            for q in queue_entries
            if q.get("error_type") in ("textfsm_exception", "zero_rows_semantic")
            and q.get("priority") == "P0_core"
        ]
        deferred = [
            q for q in queue_entries if q.get("priority") in ("P1_important", "P2_optional")
        ]

        if queue_entries:
            q_table = Table(title="Repair Queue Summary", box=box.ROUNDED)
            q_table.add_column("Type", style="cyan")
            q_table.add_column("Count", justify="right")
            q_table.add_row("collection_wrap (P0)", str(len(wrap_p0)))
            q_table.add_row("textfsm_exception / zero_rows (P0)", str(len(repair_p0)))
            q_table.add_row("P1 / P2 deferred", str(len(deferred)))
            self.console.print(q_table)
        else:
            self.console.print("[green]✅ Stage 2: No parse gaps detected.[/green]")

        # ── Stage 3a: collection_wrap P0 — notify, no LLM needed ─────────────
        if wrap_p0:
            self.console.rule("[bold yellow]Stage 3a: Collection Wrap Artifacts (P0)[/bold yellow]")
            self.console.print(
                f"[yellow]{len(wrap_p0)} command(s) detected with terminal line-wrapping[/yellow] "
                "— raw output is truncated, so TextFSM cannot parse it.\n"
                "[dim]Cause:[/dim] Juniper CLI terminal width not fully applied "
                "([bold]set cli screen-width 0[/bold] pre-command is deployed but "
                "may not take effect on all vJunos/EVE-NG sessions).\n"
                "[dim]Action:[/dim] LLM repair is [bold]skipped[/bold] for these "
                "(LLM cannot fix broken raw data). "
                "Run [bold]olav sync commands[/bold] to retry collection, or check "
                "SSH session setup for Juniper screen-width.\n"
            )
            for _entry in wrap_p0:
                self.console.print(
                    f"  • [dim]{_entry['platform']}[/dim] / [cyan]{_entry['command']}[/cyan] "
                    f"({', '.join(_entry.get('affected_devices', []))})"
                )

        # ── Stage 3b: LLM Auto-Repair P0 template errors ──────────────────────
        gaps_fixed = 0
        gaps_remaining: list[dict] = []

        if repair_p0:
            self.console.rule(
                f"[bold yellow]Stage 3b: LLM Auto-Repair {len(repair_p0)} P0 Template Gaps[/bold yellow]"
            )
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console,
            ) as progress:
                task = progress.add_task(
                    f"Repairing 0/{len(repair_p0)} P0 gaps...", total=len(repair_p0)
                )
                for i, gap in enumerate(repair_p0, 1):
                    dev = gap.get("sample_device", "")
                    cmd = gap.get("command", "")
                    progress.update(
                        task,
                        description=f"Repairing {i}/{len(repair_p0)}: [cyan]{dev}[/cyan] / [dim]{cmd}[/dim]",
                    )
                    repair_result = repair_template.func(device=dev, command=cmd)
                    if repair_result.get("success") and repair_result.get("records", 0) > 0:
                        gaps_fixed += 1
                        n_devs = len(gap.get("affected_devices", [dev]))
                        self.console.log(
                            f"  ✅ [green]{cmd}[/green] ({gap.get('platform')}) "
                            f"→ {repair_result['records']} records × {n_devs} device(s)"
                        )
                    else:
                        gaps_remaining.append(gap)
                        self.console.log(
                            f"  ❌ [red]{cmd}[/red] — {repair_result.get('error', 'unknown error')}"
                        )
                    progress.advance(task)
        else:
            self.console.print("[green]✅ Stage 3b: No P0 template gaps to repair.[/green]")

        if deferred:
            self.console.print(
                f"\n[dim]ℹ {len(deferred)} P1/P2 gap(s) deferred — run "
                "[bold]olav sync commands --repair[/bold] to fix optionally.[/dim]"
            )

        # ── Stage 3c: Check Discovery Commands (Critical for Topology) ─────────
        # Topology generation depends on CDP/LLDP/BGP/OSPF neighbor discovery.
        # If these commands are still failing, warn user before topology generation.
        discovery_critical = {
            "show cdp neighbors",
            "show cdp neighbors detail",
            "show lldp neighbors",
            "show lldp neighbors detail",
            "show bgp summary",
            "show bgp all summary",
            "show ip ospf neighbors",
            "show ospf neighbors",
        }

        discovery_p0 = [
            q
            for q in gaps_remaining
            if q.get("command", "").lower() in discovery_critical and q.get("priority") == "P0_core"
        ]

        if discovery_p0:
            self.console.rule(
                "[bold yellow]⚠️  Stage 3c: Discovery Commands Still Failing[/bold yellow]"
            )
            self.console.print(
                f"\n[yellow]{len(discovery_p0)} critical discovery command(s) not parsed:[/yellow]\n"
                "These commands are essential for generating network topology (CDP/LLDP/BGP/OSPF).\n"
                "Without them, topology will be incomplete or inaccurate.\n"
            )
            for _gap in discovery_p0:
                self.console.print(
                    f"  • [cyan]{_gap.get('platform', '?')}[/cyan] / {_gap.get('command', '?')}"
                )

            self.console.print(
                "\n[dim]TextFSM problem details: View[/dim] [bold]"
                + str(repair_queue_path)
                + "[/bold]"
            )

            # ── HITL Decision Point ───────────────────────────────────────────────
            self.console.print("\n[bold]What would you like to do?[/bold]")
            try:
                if sys.stdin.isatty():
                    choice = Confirm.ask(
                        "[A] Continue topology generation (data may be incomplete) or "
                        "[B] Pause & fix manually (recommended)",
                        default=False,
                        console=self.console,
                    )
                    use_option_b = choice is False
                else:
                    use_option_b = False
            except (OSError, EOFError):
                use_option_b = False

            if use_option_b:
                self.console.print(
                    "\n[yellow]⏸️  Onboarding paused for manual repair.[/yellow]\n"
                    "[bold]Next steps:[/bold]\n"
                    "  1. Review TextFSM issues: [bold]cat " + str(repair_queue_path) + "[/bold]\n"
                    "  2. Fix SSH/device config (check Juniper screen-width, timeout, etc.)\n"
                    "  3. Re-collect from problem devices:\n"
                    "     [bold]uv run olav --agent config \"Call collect_commands(devices=['R1','R2'])\""
                    "[/bold]\n"
                    "  4. Or manually fix templates in: [bold].olav/templates/[/bold]\n"
                    "  5. Re-parse with fixed templates:\n"
                    '     [bold]uv run olav --agent config "Call reparse_outputs('
                    "platform='juniper_junos', command='show cdp neighbors')\""
                    "[/bold]\n"
                    "  6. Then resume: [bold]uv run olav onboard[/bold] (or use Config Agent)\n"
                )
                return (
                    f"Onboarding paused at discovery check. "
                    f"Review {repair_queue_path} and fix, then rerun."
                )
            else:
                self.console.print(
                    "[yellow]⚠️  Proceeding with incomplete discovery data — "
                    "topology may have gaps.[/yellow]\n"
                )

        # ── Stage 4: Generate Topology ─────────────────────────────────────────
        self.console.rule("[bold cyan]Stage 4: Generate Topology[/bold cyan]")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
        ) as progress:
            task = progress.add_task("Building topology from CDP/LLDP/OSPF...", total=None)
            topo_result = run_topology_sandbox.func(snapshot_id=snapshot_id)
            topo_links = topo_result.get("edge_count", 0) if isinstance(topo_result, dict) else 0
            progress.update(
                task,
                description=f"✅ {topo_links} topology edges built",
                completed=True,
            )

        # ── Final summary ──────────────────────────────────────────────────────
        final_table = Table(title="🎉 Onboarding Complete", box=box.DOUBLE_EDGE)
        final_table.add_column("Stage", style="bold cyan")
        final_table.add_column("Result", style="green")
        final_table.add_row("Snapshot ID", snapshot_id)
        final_table.add_row("Devices collected", str(len(devices)))
        final_table.add_row("Diff records", str(diff_records))
        final_table.add_row("Total parse gaps", str(len(queue_entries)))
        final_table.add_row("Wrap artifacts (P0)", str(len(wrap_p0)))
        final_table.add_row("P0 gaps auto-fixed", str(gaps_fixed))
        final_table.add_row("P0 gaps remaining", str(len(gaps_remaining)))
        final_table.add_row("Topology edges", str(topo_links))
        self.console.print(final_table)

        if gaps_remaining:
            self.console.print(f"\n[yellow]⚠ {len(gaps_remaining)} P0 gaps not repaired:[/yellow]")
            for _gap in gaps_remaining:
                self.console.print(f"  • {_gap.get('platform', '?')} / {_gap.get('command', '?')}")

        return (
            f"Onboarding complete. Snapshot {snapshot_id}: "
            f"{len(devices)} devices, "
            f"{gaps_fixed}/{len(repair_p0)} P0 gaps fixed, "
            f"{len(wrap_p0)} wrap artifacts (resolve next collect), "
            f"{topo_links} topology edges."
        )

    # ──────────────────────────────────────────────────────────────────────────────
    # Step 0 — Infrastructure
    # ──────────────────────────────────────────────────────────────────────────────

    async def _step_infra(self) -> bool:
        self.console.print("\n[bold]Step 0: Checking Infrastructure...[/bold]")
        from importlib.util import module_from_spec, spec_from_file_location

        from olav.core.config import AGENT_DIR, get_paths_config
        from olav.core.utils import create_olav_directories

        create_olav_directories(get_paths_config().project_root)
        _tool = AGENT_DIR / "workspace" / "config" / "sync" / "tools" / "sync_schemas.py"
        if _tool.exists():
            _spec = spec_from_file_location("sync_schemas", _tool)
            _mod = module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            # sync_schemas is a LangChain @tool (StructuredTool) — use .invoke()
            _mod.sync_schemas.invoke({"force_recreate": False})
        self.console.print("  [green]✓[/green] Directories and database verified.")
        return True

    # ──────────────────────────────────────────────────────────────────────────────
    # Step 1 — LLM (api.json)
    # ──────────────────────────────────────────────────────────────────────────────

    async def _step_llm(self) -> bool:
        self.console.print("\n[bold]Step 1: LLM Configuration[/bold]")

        api_json_path = CONFIG_DIR / "api.json"
        if not api_json_path.exists():
            self.console.print(
                "[red]❌ api.json not found.[/red]\n"
                "Create .olav/config/api.json with your LLM settings."
            )
            return False

        with open(api_json_path, encoding="utf-8") as f:
            config = json.load(f)

        llm_cfg = config.get("llm", {})
        table = Table(title="Current LLM Configuration", box=box.SIMPLE)
        table.add_column("Key", style="dim")
        table.add_column("Value")
        table.add_row("Provider", llm_cfg.get("provider", "Not set"))
        table.add_row("Model", llm_cfg.get("model", "Not set"))
        table.add_row("Base URL", llm_cfg.get("base_url", "Not set"))
        self.console.print(table)

        self.console.print("Testing LLM connectivity...")
        with Progress(
            SpinnerColumn(), TextColumn("{task.description}"), console=self.console, transient=True
        ) as p:
            p.add_task(description="Talking to AI...", total=None)
            success = LLMFactory.test_connectivity()

        if success:
            self.console.print("  [green]✓[/green] LLM connectivity verified. Auto-passing step 1.")
            return True

        self.console.print(
            "  [red]❌[/red] LLM connectivity failed. Check .olav/config/api.json credentials."
        )
        try:
            if sys.stdin.isatty() and Confirm.ask("Retry?", default=False):
                return await self._step_llm()
        except (OSError, EOFError):
            pass
        return False

    # ──────────────────────────────────────────────────────────────────────────────
    # Step 2 — Nornir (hosts.yaml)
    # ──────────────────────────────────────────────────────────────────────────────

    async def _step_nornir(self) -> bool:
        self.console.print("\n[bold]Step 2: Nornir & Network Connectivity[/bold]")

        nornir_config = CONFIG_DIR / "nornir" / "config.yaml"
        if not nornir_config.exists():
            self.console.print(f"[red]❌ {nornir_config} missing![/red]")
            return False

        # ── Verify Nornir can initialise (validates config + backend connection) ──
        try:
            import os

            from nornir import InitNornir

            _orig = os.getcwd()
            os.chdir(CONFIG_DIR.parent.parent)  # PROJECT_ROOT
            nr = InitNornir(config_file=str(nornir_config))
            os.chdir(_orig)
        except Exception as exc:
            self.console.print(f"[red]❌ Nornir init failed:[/red] {exc}")
            return False

        hosts = nr.inventory.hosts
        device_count = len(hosts)
        if device_count == 0:
            self.console.print("[red]❌ Nornir inventory is empty — no devices found.[/red]")
            return False

        # ── Display inventory summary (source-agnostic) ────────────────────────
        platforms: dict[str, int] = {}
        for h in hosts.values():
            p = str(h.platform or "unknown")
            platforms[p] = platforms.get(p, 0) + 1

        table = Table(title="Nornir Inventory Summary", box=box.SIMPLE)
        table.add_column("Platform", style="dim")
        table.add_column("Devices", justify="right")
        for plat, count in sorted(platforms.items()):
            table.add_row(plat, str(count))
        table.add_row("[bold]Total[/bold]", f"[bold]{device_count}[/bold]")
        self.console.print(table)

        # ── Optional: connectivity check via Nornir (random sample) ───────────
        try:
            do_check = sys.stdin.isatty() and Confirm.ask(
                "Test SSH connectivity to a sample of devices?", default=False
            )
        except (OSError, EOFError):
            do_check = False

        if do_check:
            import random

            from nornir_netmiko.tasks import netmiko_send_command  # type: ignore

            sample_names = random.sample(list(hosts.keys()), k=min(3, device_count))
            nr_sample = nr.filter(filter_func=lambda h: h.name in sample_names)

            self.console.print(f"  Checking {len(sample_names)} hosts: {', '.join(sample_names)}")
            with Progress(
                SpinnerColumn(),
                TextColumn("{task.description}"),
                console=self.console,
                transient=True,
            ) as p:
                p.add_task(description="Connecting...", total=None)
                result = nr_sample.run(task=netmiko_send_command, command="show clock")

            reachable = sum(1 for r in result.values() if not r.failed)
            failed = [name for name, r in result.items() if r.failed]
            self.console.print(
                f"  [green]✓[/green] {reachable}/{len(sample_names)} devices reachable."
            )
            if failed:
                self.console.print(f"  [yellow]⚠[/yellow] Unreachable: {', '.join(failed)}")
        else:
            self.console.print(
                "  [green]✓[/green] Nornir config verified. Skipping connectivity test."
            )

        return True
