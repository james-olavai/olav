"""Log Monitor Service - Phase 5 Day 7-8.

Monitors JSON log files in real-time and processes events through AlertManager:
- Tail log files for new entries
- Parse JSON log events
- Route events to alert rules
- Support multiple log sources
"""

import logging
import time
from pathlib import Path
from threading import Thread

from src.olav.monitoring.alerts import get_alert_manager


class LogMonitor:
    """Real-time log file monitor.
    
    Tails JSON log files and processes events through AlertManager:
    - Non-blocking file reading
    - Automatic file rotation handling
    - Multi-file monitoring support
    """
    
    def __init__(self, log_file: str | Path):
        """Initialize log monitor.
        
        Args:
            log_file: Path to JSON log file to monitor
        """
        self.log_file = Path(log_file)
        self.alert_manager = get_alert_manager()
        self.logger = logging.getLogger(__name__)
        self.running = False
        self.thread = None
    
    def start(self):
        """Start monitoring log file in background thread."""
        if self.running:
            return
        
        self.running = True
        self.thread = Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        self.logger.info(f"Started monitoring {self.log_file}")
    
    def stop(self):
        """Stop monitoring log file."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5.0)
        self.logger.info(f"Stopped monitoring {self.log_file}")
    
    def _monitor_loop(self):
        """Monitor loop that tails log file."""
        # Wait for log file to exist
        while self.running and not self.log_file.exists():
            time.sleep(1.0)
        
        if not self.running:
            return
        
        # Open file and seek to end
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                # Seek to end of file
                f.seek(0, 2)
                
                while self.running:
                    # Read new lines
                    line = f.readline()
                    
                    if line:
                        # Process log event
                        try:
                            self.alert_manager.process_log_event(line.strip())
                        except Exception as e:
                            self.logger.error(f"Failed to process log event: {e}")
                    else:
                        # No new data, sleep briefly
                        time.sleep(0.1)
        except Exception as e:
            self.logger.error(f"Monitor loop error: {e}")
            # File error, wait and retry if still running
            if self.running:
                time.sleep(1.0)
                self._monitor_loop()


class LogMonitorService:
    """Service for monitoring multiple log files.
    
    Manages multiple LogMonitor instances:
    - Start/stop all monitors
    - Add/remove log sources
    - Centralized lifecycle management
    """
    
    def __init__(self):
        """Initialize log monitor service."""
        self.monitors: dict[str, LogMonitor] = {}
        self.logger = logging.getLogger(__name__)
    
    def add_log_file(self, log_file: str | Path, name: str = ""):
        """Add log file to monitor.
        
        Args:
            log_file: Path to log file
            name: Optional monitor name (defaults to filename)
        """
        log_path = Path(log_file)
        monitor_name = name or log_path.name
        
        if monitor_name in self.monitors:
            self.logger.warning(f"Monitor {monitor_name} already exists")
            return
        
        monitor = LogMonitor(log_path)
        self.monitors[monitor_name] = monitor
        self.logger.info(f"Added log monitor: {monitor_name}")
    
    def remove_log_file(self, name: str):
        """Remove log file monitor.
        
        Args:
            name: Monitor name
        """
        if name not in self.monitors:
            return
        
        monitor = self.monitors.pop(name)
        monitor.stop()
        self.logger.info(f"Removed log monitor: {name}")
    
    def start_all(self):
        """Start all log monitors."""
        for monitor in self.monitors.values():
            monitor.start()
        self.logger.info(f"Started {len(self.monitors)} log monitors")
    
    def stop_all(self):
        """Stop all log monitors."""
        for monitor in self.monitors.values():
            monitor.stop()
        self.logger.info(f"Stopped {len(self.monitors)} log monitors")


# Global service instance
_log_monitor_service = None


def get_log_monitor_service() -> LogMonitorService:
    """Get global log monitor service.
    
    Returns:
        LogMonitorService instance
    """
    global _log_monitor_service
    if _log_monitor_service is None:
        _log_monitor_service = LogMonitorService()
        # Add default OLAV log file
        _log_monitor_service.add_log_file("logs/olav.json", "olav")
    return _log_monitor_service


def start_monitoring():
    """Start log monitoring service."""
    service = get_log_monitor_service()
    service.start_all()


def stop_monitoring():
    """Stop log monitoring service."""
    service = get_log_monitor_service()
    service.stop_all()
