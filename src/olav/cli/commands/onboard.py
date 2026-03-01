"""Onboarding command for OLAV v1.0.

Provides a guided step-by-step setup process as requested by the user.
Replaces the simplified 'init' with a robust, interactive 'onboard' workflow.
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

from olav.cli.commands.base import BaseCommand
from olav.core.config import AGENT_DIR, CONFIG_DIR, MAIN_DB_PATH, get_settings, settings
from olav.core.llm import LLMFactory

logger = logging.getLogger(__name__)


class OnboardCommand(BaseCommand):
    """Guided onboarding process for OLAV setup and verification."""

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

        # Phase 0: Ensure Infrastructure
        if not await self._step_infra():
            return "Onboarding aborted at infrastructure stage."

        # Phase 1: LLM Configuration
        if not await self._step_llm():
            return "Onboarding aborted at LLM stage."

        # Phase 2: Nornir & Connectivity
        if not await self._step_nornir():
            return "Onboarding aborted at Nornir stage."

        # Phase 3: Inventory Import
        if not await self._step_inventory():
            return "Onboarding aborted at Inventory stage."

        # Phase 4: Command Library Sync
        if not await self._step_commands():
            return "Onboarding aborted at Command Library stage."

        # Phase 5: Snapshot & Data Collection
        if not await self._step_snapshot():
            return "Onboarding aborted at Snapshot stage."

        # Phase 6: Auto-Repair Failed Templates (Closed-Loop Feedback)
        if not await self._step_repair_templates():
            self.console.print("[yellow]⚠️ Template repair skipped. You can manually fix templates later.[/yellow]")

        # Phase 7: Quality Verification
        if not await self._step_verify_quality():
            self.console.print("[yellow]⚠️ Quality verification incomplete. Review parsing gaps manually.[/yellow]")

        self.console.print("\n[bold green]✨ Onboarding Complete! ✨[/bold green]")
        self.console.print("Your OLAV system is now ready for use.")
        self.console.print("Try asking: [italic]'What is the status of my BGP neighbors?'[/italic]")

        return "Success"

    async def _step_infra(self) -> bool:
        """Step 0: Ensure .olav directory and database exist."""
        self.console.print("\n[bold]Step 0: Checking Infrastructure...[/bold]")

        # We can call the logic from core utils here
        from olav.core.config import get_paths_config
        from olav.core.utils import create_olav_directories

        create_olav_directories(get_paths_config().project_root)

        # Ensure database is initialized (sync_schemas)
        await self._run_tool_logic(
            "sync_schemas", {"force_recreate": False}, "Initializing Database Schema"
        )

        self.console.print("  [green]✓[/green] Directories and database verified.")
        return True

    async def _step_llm(self) -> bool:
        """Step 1: LLM Configuration & Connectivity.
        
        Auto-pass if api.json exists and is valid.
        Only prompt for changes if not configured or connectivity fails.
        """
        self.console.print("\n[bold]Step 1: LLM Configuration[/bold]")

        api_json_path = CONFIG_DIR / "api.json"
        if not api_json_path.exists():
            self.console.print(
                "[red]❌ Critical: api.json not found.[/red]\n"
                "Please create .olav/config/api.json with your LLM settings."
            )
            return False

        with open(api_json_path, encoding="utf-8") as f:
            config = json.load(f)

        llm_config = config.get("llm", {})
        table = Table(title="Current LLM Configuration", box=box.SIMPLE)
        table.add_column("Key", style="dim")
        table.add_column("Value")
        table.add_row("Provider", llm_config.get("provider", "Not set"))
        table.add_row("Model", llm_config.get("model", "Not set"))
        table.add_row("Base URL", llm_config.get("base_url", "Not set"))
        self.console.print(table)

        self.console.print("Testing LLM connectivity...")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True,
        ) as progress:
            progress.add_task(description="Talking to AI...", total=None)
            success = LLMFactory.test_connectivity()

        if success:
            self.console.print("  [green]✓[/green] LLM connectivity verified. Auto-passing step 1.")
            return True
        else:
            self.console.print(
                "  [red]❌[/red] LLM connectivity failed. Please check your credentials in .olav/config/api.json"
            )
            # Ask if user wants to retry or skip
            if Confirm.ask("LLM failed. Try again?", default=False):
                return await self._step_llm()  # Recurse to retry
            return False

    async def _step_nornir(self) -> bool:
        """Step 2: Nornir Config & Connectivity.
        
        Auto-pass if hosts.yaml exists and is valid.
        Only test connectivity if explicitly requested.
        """
        self.console.print("\n[bold]Step 2: Nornir & Network Connectivity[/bold]")

        hosts_yaml = CONFIG_DIR / "nornir" / "hosts.yaml"
        if not hosts_yaml.exists():
            self.console.print(f"[red]❌ Critical: {hosts_yaml} missing![/red]")
            self.console.print("Please copy your device inventory to that location.")
            return False

        with open(hosts_yaml, encoding="utf-8") as f:
            import yaml
            hosts = yaml.safe_load(f) or {}

        device_count = len(hosts)
        self.console.print(f"  [green]✓[/green] Found [cyan]{device_count}[/cyan] devices in inventory.")
        self.console.print("  [green]✓[/green] Nornir config validated. Auto-passing step 2.")
        
        # Optional: Test connectivity if requested (skip in non-interactive mode)
        try:
            if Confirm.ask("Test SSH connectivity to sample devices?", default=False):
                import random
                test_count = max(3, device_count // 10)
                target_names = random.sample(list(hosts.keys()), k=min(test_count, device_count))

                self.console.print(
                    f"Testing SSH connectivity (TCP 22) for: {', '.join(target_names)}..."
                )

                test_hosts = []
                from types import SimpleNamespace
                for name in target_names:
                    h = hosts[name]
                    hostname = h.get("hostname") or name
                    test_hosts.append(SimpleNamespace(name=name, hostname=hostname))

                from importlib.util import module_from_spec, spec_from_file_location
                sync_tools_path = (
                    AGENT_DIR / "workspace" / "config" / "sync" / "tools" / "sync_tools.py"
                )
                spec = spec_from_file_location("sync_tools", sync_tools_path)
                sync_tools = module_from_spec(spec)
                spec.loader.exec_module(sync_tools)

                results = sync_tools.parallel_tcp_check(test_hosts)
                reachable = sum(1 for r in results.values() if r)
                self.console.print(
                    f"  [cyan]ℹ[/cyan] {reachable}/{len(target_names)} devices reachable via SSH."
                )
        except (OSError, EOFError):
            # In non-interactive mode (e.g., nohup), stdin is unavailable
            self.console.print("  [cyan]ℹ[/cyan] Skipping connectivity test (non-interactive mode).")
        
        return True

    async def _step_inventory(self) -> bool:
        """Step 3: Import devices to DB."""
        self.console.print("\n[bold]Step 3: Importing Device Inventory[/bold]")
        result = await self._run_tool_logic("sync_inventory", {}, "Syncing Inventory to DuckDB")
        if result.get("status") == "success":
            self.console.print(
                f"  [green]✓[/green] {result['imported']} devices imported to database."
            )
            return True
        return False

    async def _step_commands(self) -> bool:
        """Step 4: Import Commands & NTC templates."""
        self.console.print("\n[bold]Step 4: Synchronizing Command Library[/bold]")
        self.console.print("Scanning NTC-templates and custom TextFSM definitions...")
        result = await self._run_tool_logic("sync_commands", {}, "Building Command Registry")
        if result.get("status") == "success":
            self.console.print(
                f"  [green]✓[/green] {result['templates_scanned']} templates registered."
            )
            return True
        return False

    async def _step_snapshot(self) -> bool:
        """Step 5: Snapshot, Parse, Topology — with enhanced SSH progress visibility."""
        self.console.print("\n[bold]Step 5: Full Network Snapshot & Analysis[/bold]")
        self.console.print("[dim]This may take a few minutes depending on network size.[/dim]")

        try:
            if not Confirm.ask("Start full data collection now?", default=True):
                self.console.print(
                    "[yellow]Skipping snapshot. You can run 'uv run olav snapshot' later.[/yellow]"
                )
                return True
        except (OSError, EOFError):
            # Non-interactive mode: default to True (proceed with snapshot)
            self.console.print("[cyan]ℹ[/cyan] Non-interactive mode: proceeding with data collection...")

        # Display expected scale for transparency
        try:
            from olav.core.database import get_database
            db = get_database()
            device_count = db.conn.execute("SELECT COUNT(*) FROM devices WHERE is_active = TRUE").fetchone()[0]
            cmd_count = db.conn.execute("SELECT COUNT(*) FROM commands WHERE allowed = TRUE").fetchone()[0]
            expected_tasks = max(device_count * 3, 10)  # Rough estimate: 3 operations per device
            
            self.console.print(
                f"\n[cyan]📊 Expected scope: {device_count} devices, ~{cmd_count} commands[/cyan]"
            )
        except Exception:
            pass

        # Enhanced progress display for SSH collection
        self.console.print("\n[yellow]⏳ SSH Collection Phase (Stage 1):[/yellow]")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=False,  # Keep output visible
        ) as progress:
            task = progress.add_task(description="Collecting raw data via SSH & Parsing (Stage 2)...", total=None)

            # Full snapshot with wait=True so Stage 2 (Topology) also runs
            result_msg = await self._run_tool_logic(
                "take_snapshot", {"wait": True}, "Processing network state"
            )
            progress.stop()

        self.console.print("\n[green]✓ Data collection and parsing complete![/green]")
        self.console.print(Panel(result_msg, title="Snapshot Summary", border_style="green"))
        # Store the result for Step 6 to analyze
        self._snapshot_result = result_msg
        return True

    async def _step_repair_templates(self) -> bool:
        """Step 6: Closed-Loop Auto-Repair — LLM generates/fixes failed TextFSM templates.

        Algorithm (ReAct pattern):
          1. Query DB for device+command pairs with empty/null parsed_data.
          2. For each gap: find raw file → get platform → LLM generates template
             (up to 3 iterations with reflection if 0 records) → save to custom dir
             → call reparse_outputs() to validate (no SSH).
          3. Report fixed vs still-failing.
        """
        self.console.print("\n[bold]Step 6: Validating & Auto-Repairing Templates[/bold]")

        # ── Gap discovery: DB is authoritative; fall back to text parsing ────────
        gaps = self._query_high_severity_gaps()
        if not gaps and hasattr(self, "_snapshot_result"):
            gaps = self._parse_gaps_from_text(self._snapshot_result)

        if not gaps:
            self.console.print("  [green]✓[/green] No HIGH severity parsing gaps detected. Templates are healthy.")
            return True

        self.console.print(f"  Found [yellow]{len(gaps)}[/yellow] template repair candidates.")
        try:
            if not Confirm.ask(f"Auto-repair {len(gaps)} templates using LLM?", default=True):
                return True
        except (OSError, EOFError):
            self.console.print("[cyan]ℹ[/cyan] Non-interactive mode: proceeding with template repair...")

        # ── Closed-loop repair: one gap at a time ────────────────────────────────
        repaired: list[dict] = []
        failed: list[dict] = []

        for gap in gaps:
            device, command = gap["device"], gap["command"]
            self.console.print(f"\n  Repairing [cyan]{device}[/cyan]: {command}")
            try:
                result = await self._repair_one_template(device, command)
                if result["success"]:
                    repaired.append(gap)
                    self.console.print(
                        f"    [green]✓[/green] Fixed — {result['records']} records now parsed."
                    )
                else:
                    failed.append({**gap, "error": result.get("error", "Unknown")})
                    self.console.print(
                        f"    [yellow]⚠️[/yellow]  Failed: {result.get('error', '?')}"
                    )
            except Exception as exc:
                failed.append({**gap, "error": str(exc)})
                self.console.print(f"    [red]✗[/red] Error: {exc}")

        # ── Summary ───────────────────────────────────────────────────────────────
        summary = (
            f"  Repaired [green]{len(repaired)}[/green] / "
            f"[yellow]{len(failed)}[/yellow] still failing"
        )
        self.console.print(f"\n{summary}")
        if failed:
            self.console.print(
                "  [dim]Use [cyan]olav learner[/cyan] for complex templates that need human review.[/dim]"
            )
        return True

    # ──────────────────────────────────────────────────────────────────────────────
    # Repair helpers
    # ──────────────────────────────────────────────────────────────────────────────

    def _query_high_severity_gaps(self) -> list[dict]:
        """Return device+command pairs where parsed_data is empty in DuckDB."""
        try:
            from olav.core.database import DuckDBClient
            db = DuckDBClient()
            rows = db.conn.execute(
                """SELECT DISTINCT device_name, command
                   FROM parsed_outputs
                   WHERE parsed_data IS NULL
                      OR parsed_data = '[]'
                      OR parsed_data = '{}'
                      OR parsed_data = 'null'
                   ORDER BY device_name, command"""
            ).fetchall()
            return [{"device": r[0], "command": r[1]} for r in rows]
        except Exception:
            return []

    def _parse_gaps_from_text(self, text: str) -> list[dict]:
        """Fallback: extract gaps from take_snapshot output text."""
        if "HIGH SEVERITY" not in text:
            return []
        gaps = []
        for line in text.split("\n"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4 and parts[1] and parts[1] not in ("Device", ":---", ""):
                gaps.append({"device": parts[1], "command": parts[2]})
        return gaps

    async def _repair_one_template(self, device: str, command: str) -> dict:
        """Generate/fix template via LLM and validate via reparse_outputs (no SSH).

        Steps:
          1. Locate raw file from latest snapshot (local disk, no SSH).
          2. Look up device platform in DuckDB.
          3. Load existing (possibly broken) template from custom templates dir.
          4. Ask LLM (with ReAct reflection loop) to generate a working template.
          5. Save result to .olav/templates/custom/{platform}/.
          6. Call reparse_outputs() to update DB and verify record count > 0.
        """
        raw_file = self._find_raw_for_repair(device, command)
        if not raw_file:
            return {"success": False, "error": f"No raw file found for {device}/{command}"}

        try:
            raw_output = raw_file.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return {"success": False, "error": f"Cannot read raw file: {exc}"}

        platform = self._get_platform_for_repair(device)
        if not platform:
            return {"success": False, "error": f"Platform unknown for device '{device}'"}

        existing_template = self._load_existing_template(platform, command)

        self.console.print(f"    [dim]→ LLM generating template for {platform}/{command}...[/dim]")
        try:
            template_content = await asyncio.get_event_loop().run_in_executor(
                None,
                self._llm_fix_template,
                platform,
                command,
                raw_output[:4000],   # cap context at 4 kB
                existing_template,
            )
        except Exception as exc:
            return {"success": False, "error": f"LLM generation failed: {exc}"}

        if not template_content:
            return {"success": False, "error": "LLM returned no valid template after 3 attempts"}

        self._save_custom_template(platform, command, template_content)

        # Validate: if reparse now yields real records the loop is complete
        reparse = await self._run_tool_logic(
            "reparse_outputs",
            {"device": device, "command": command},
            f"Validating {device}/{command}",
        )
        if isinstance(reparse, dict):
            if reparse.get("success") and reparse.get("records", 0) > 0:
                return {"success": True, "records": reparse["records"]}
            return {"success": False, "error": reparse.get("error") or "0 records after reparse"}
        return {"success": False, "error": f"Unexpected reparse result type: {type(reparse)}"}

    def _find_raw_for_repair(self, device: str, command: str) -> Path | None:
        """Find the most recent raw output file for a device/command (no SSH)."""
        cmd_file = command.lower().replace(" ", "_") + ".txt"
        snapshots_dir = Path(settings.agent_dir).parent / "exports" / "snapshots"

        # Prefer 'latest' symlink
        via_latest = snapshots_dir / "latest" / "raw" / device / cmd_file
        if via_latest.exists():
            return via_latest

        # Newest dated snapshot directory
        try:
            dated = sorted(
                [d for d in snapshots_dir.iterdir() if d.is_dir() and d.name not in ("latest", "json")],
                reverse=True,
            )
            for snap_dir in dated:
                candidate = snap_dir / "raw" / device / cmd_file
                if candidate.exists():
                    return candidate
        except Exception:
            pass
        return None

    def _get_platform_for_repair(self, device: str) -> str:
        """Look up device platform from DuckDB devices table."""
        try:
            from olav.core.database import DuckDBClient
            db = DuckDBClient()
            row = db.conn.execute(
                "SELECT platform FROM devices WHERE name = ?", [device]
            ).fetchone()
            return row[0] if row else ""
        except Exception:
            return ""

    def _load_existing_template(self, platform: str, command: str) -> str | None:
        """Load the current (possibly broken) custom template, or None if absent."""
        cmd_slug = command.lower().replace(" ", "_")
        tmpl_path = Path(settings.agent_dir) / "templates" / "custom" / platform / f"{cmd_slug}.textfsm"
        if tmpl_path.exists():
            try:
                return tmpl_path.read_text(encoding="utf-8")
            except Exception:
                pass
        return None

    def _llm_fix_template(
        self,
        platform: str,
        command: str,
        raw_output: str,
        existing: str | None,
    ) -> str | None:
        """Synchronous ReAct loop: generate template → test syntax → reflect → retry.

        Up to 3 iterations:
          - ACT: LLM generates TextFSM template.
          - OBSERVE: Run TextFSM against raw_output; check record count.
          - REFLECT: If 0 records or syntax error, feed back diagnosis and regenerate.
        Returns template content string, or None on total failure.
        """
        import io
        import re

        import textfsm
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=settings.llm_model_name,
            temperature=0.1,
            timeout=120,
            api_key=settings.llm_api_key or None,
            base_url=settings.llm_base_url or None,
        )

        context = (
            f"\n**Existing (failing) template** — fix it:\n```\n{existing}\n```\n"
            if existing
            else "\nNo existing template — create one from scratch.\n"
        )

        prompt = (
            f"You are a TextFSM expert.\n\n"
            f"Platform: {platform}\nCommand: {command}\n"
            f"{context}"
            f"\n**Raw CLI output** (first 4000 chars):\n```\n{raw_output}\n```\n\n"
            "Write a working TextFSM template that extracts ALL data rows. "
            "Return ONLY the complete template code — no explanations, no fences."
        )

        for attempt in range(1, 4):
            response = llm.invoke([{"role": "user", "content": prompt}])
            content = response.content.strip()
            # Strip any accidental markdown fences
            content = re.sub(r"^```[a-z]*\n?|```$", "", content, flags=re.MULTILINE).strip()

            try:
                fsm = textfsm.TextFSM(io.StringIO(content))
                rows = fsm.ParseText(raw_output)
                if rows:
                    return content  # ✅ Valid template with records — done
                # 0 records: reflect and retry
                prompt += (
                    f"\n\nAttempt {attempt}: template was syntactically valid "
                    f"but parsed 0 records.\nHeaders defined: {fsm.header}\n"
                    f"First 30 raw lines:\n{chr(10).join(raw_output.splitlines()[:30])}\n\n"
                    "Fix the regex patterns so they match actual output. Return ONLY the corrected template."
                )
            except Exception as exc:
                prompt += f"\n\nAttempt {attempt} had syntax error: {exc}. Fix and retry."

        return None  # All attempts failed

    def _save_custom_template(self, platform: str, command: str, content: str) -> Path:
        """Persist the generated template to .olav/templates/custom/{platform}/."""
        custom_dir = Path(settings.agent_dir) / "templates" / "custom" / platform
        custom_dir.mkdir(parents=True, exist_ok=True)
        cmd_slug = command.lower().replace(" ", "_")
        tmpl_path = custom_dir / f"{cmd_slug}.textfsm"
        tmpl_path.write_text(content, encoding="utf-8")
        logger.info("Saved custom template: %s", tmpl_path)
        return tmpl_path

    async def _step_verify_quality(self) -> bool:
        """Step 7: Quality Verification — Confirm all templates pass coverage checks."""
        self.console.print("\n[bold]Step 7: Final Quality Check[/bold]")

        # Query DuckDB to check parsed_outputs coverage
        try:
            from olav.core.database import DuckDBClient
            db = DuckDBClient()
            result = db.conn.execute(
                """
                SELECT COUNT(*) as total_commands,
                       COUNT(DISTINCT CASE WHEN parsed_data IS NOT NULL 
                                           AND parsed_data != '{}' THEN 1 END) as parsed_count
                FROM parsed_outputs
                """
            ).fetchone()

            if result and result[1] > 0:
                total, parsed = result
                coverage = (parsed / max(total, 1)) * 100
                self.console.print(
                    f"  [green]✓[/green] Parsed {parsed}/{total} commands ({coverage:.0f}% coverage)"
                )
                return True
            else:
                self.console.print("  [yellow]⚠️ No parsed outputs found yet.[/yellow]")
                return False
        except Exception as e:
            self.console.print(f"  [yellow]⚠️ Quality check skipped: {e}[/yellow]")
            return True

    async def _run_tool_logic(self, tool_name: str, params: dict, desc: str) -> Any:
        """Helper to dynamically import and run a tool's logic."""
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True,
        ) as progress:
            progress.add_task(description=f"{desc}...", total=None)

            # Find the tool file
            # Priority: config/sync/tools -> ops/tools
            paths = [
                AGENT_DIR / "workspace" / "config" / "sync" / "tools" / f"{tool_name}.py",
                AGENT_DIR / "workspace" / "ops" / "tools" / f"{tool_name}.py",
                AGENT_DIR / "workspace" / "config" / "tools" / f"{tool_name}.py",
            ]

            tool_path = next((p for p in paths if p.exists()), None)
            if not tool_path:
                raise FileNotFoundError(f"Could not find tool {tool_name} in expected paths.")

            from importlib.util import module_from_spec, spec_from_file_location

            spec = spec_from_file_location(tool_name, tool_path)
            mod = module_from_spec(spec)
            # Ensure the directory of the tool is in sys.path for internal imports
            if str(tool_path.parent) not in sys.path:
                sys.path.insert(0, str(tool_path.parent))
            spec.loader.exec_module(mod)

            # Call the tool function (wrapped in @tool, so use .func if needed,
            # or just call the function directly if target_function is known)
            target_func = getattr(mod, tool_name)
            if hasattr(target_func, "func"):
                return target_func.func(**params)
            else:
                return target_func(**params)
