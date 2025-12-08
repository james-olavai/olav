"""Inspection Scheduler - Background daemon for periodic inspections.

Provides scheduled execution using the unified inspection config:
- Reads schedule from config/inspections/inspection.yaml
- Supports cron expressions and timezone
- Background daemon mode
- Graceful shutdown handling

Usage:
    # Start scheduler daemon
    uv run python -m olav.main inspect --daemon

    # Or run scheduler directly
    python -m olav.modes.inspection.scheduler
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime
from typing import Any

from config.settings import settings

logger = logging.getLogger("olav.modes.inspection.scheduler")


class InspectionScheduler:
    """Schedule and run periodic inspections from unified config."""

    def __init__(self) -> None:
        self.running = False
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the scheduler daemon."""
        if not settings.inspection_enabled:
            logger.warning("Inspection scheduler is disabled (inspection_enabled=False)")
            logger.info("To enable, set INSPECTION_ENABLED=true in .env")
            return

        self.running = True
        logger.info("Inspection scheduler starting...")

        # Setup signal handlers for graceful shutdown
        if sys.platform != "win32":
            loop = asyncio.get_event_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self._signal_handler)

        try:
            await self._run_loop()
        except asyncio.CancelledError:
            logger.info("Scheduler cancelled")
        finally:
            self.running = False
            logger.info("Inspection scheduler stopped")

    def _signal_handler(self) -> None:
        """Handle shutdown signals."""
        logger.info("Shutdown signal received")
        self._stop_event.set()

    async def stop(self) -> None:
        """Stop the scheduler gracefully."""
        self._stop_event.set()

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self) -> None:
        """Main scheduler loop - reads schedule from unified inspection.yaml."""
        from olav.inspection import get_schedule_config

        schedule_config = get_schedule_config()

        if not schedule_config:
            logger.warning("No schedule configuration found in inspection.yaml")
            logger.info("Add 'schedule' section to config/inspections/inspection.yaml")
            return

        if not schedule_config.get("enabled", False):
            logger.info("Schedule is disabled in inspection.yaml (enabled: false)")
            return

        cron_expr = schedule_config.get("cron")
        timezone = schedule_config.get("timezone", "UTC")

        if cron_expr:
            logger.info(f"Running inspections on schedule: {cron_expr} ({timezone})")
            await self._run_cron_loop(cron_expr, timezone)
        else:
            # Default to daily at 6 AM if no cron specified
            logger.info("No cron expression found, defaulting to daily at 06:00")
            await self._run_cron_loop("0 6 * * *", timezone)

    async def _run_cron_loop(self, cron_expr: str, timezone: str = "UTC") -> None:
        """Run inspections based on cron expression."""
        try:
            from croniter import croniter
        except ImportError:
            logger.error("croniter package not installed. Install with: uv add croniter")
            return

        try:
            import pytz

            tz = pytz.timezone(timezone)
        except ImportError:
            logger.warning("pytz not installed, using local time")
            tz = None
        except Exception as e:
            logger.warning(f"Invalid timezone {timezone}, using local: {e}")
            tz = None

        try:
            cron = croniter(cron_expr)
        except Exception as e:
            logger.error(f"Invalid cron expression: {cron_expr} ({e})")
            return

        logger.info(f"Scheduler started with cron: {cron_expr}")

        while not self._stop_event.is_set():
            # Get next run time
            next_run = cron.get_next(datetime)
            now = datetime.now()
            wait_seconds = (next_run - now).total_seconds()

            if wait_seconds > 0:
                logger.info(
                    f"Next inspection at {next_run.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"({wait_seconds / 3600:.1f} hours)"
                )
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=wait_seconds,
                    )
                    break  # Stop event was set
                except TimeoutError:
                    pass  # Time to run

            # Run inspection
            await self._execute_inspection()

    async def _execute_inspection(self) -> dict[str, Any]:
        """Execute the unified inspection."""
        from olav.inspection import execute_inspection

        logger.info("Starting scheduled inspection")

        try:
            report = await execute_inspection(save_report=True)

            passed = report.passed_count
            total = report.total_checks
            critical_count = len([
                c for stage in report.stages
                for c in stage.get("checks", [])
                if c.get("severity") == "critical" and c.get("status") == "failed"
            ])

            logger.info(
                f"Inspection completed: {passed}/{total} passed, critical: {critical_count}"
            )

            # Check for critical failures
            if critical_count > 0 and settings.inspection_notify_on_failure:
                await self._send_notification({
                    "critical": critical_count,
                    "passed": passed,
                    "total_checks": total,
                })

            return {
                "status": "success",
                "passed": passed,
                "total_checks": total,
                "critical": critical_count,
            }

        except Exception as e:
            logger.exception(f"Inspection execution error: {e}")
            return {"status": "error", "message": str(e)}

    async def _send_notification(self, result: dict[str, Any]) -> None:
        """Send notification for critical failures."""
        if not settings.inspection_notify_webhook_url:
            return

        try:
            import aiohttp

            payload = {
                "text": f"🚨 OLAV Inspection Alert: {result.get('critical')} critical issues found",
                "attachments": [
                    {
                        "title": "Daily Network Inspection",
                        "text": f"Passed: {result.get('passed')}/{result.get('total_checks')}",
                        "color": "danger",
                    }
                ],
            }

            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    settings.inspection_notify_webhook_url,
                    json=payload,
                ) as resp,
            ):
                if resp.status != 200:
                    logger.warning(f"Notification webhook failed: {resp.status}")
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")


async def run_scheduler() -> None:
    """Run the inspection scheduler."""
    scheduler = InspectionScheduler()
    await scheduler.start()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    asyncio.run(run_scheduler())
