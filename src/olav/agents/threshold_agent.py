import yaml
from pathlib import Path
from typing import Any, Dict, List
import logging
import numpy as np
from olav.core.unified_database import UnifiedDatabase

logger = logging.getLogger(__name__)

class ThresholdAgent:
    """Agent for adaptive threshold calculation and anomaly detection."""

    def __init__(self, config_path: str | Path | None = None):
        if config_path is None:
            from config.paths import CONFIG_DIR
            config_path = CONFIG_DIR / "thresholds.yaml"
        
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.udb = UnifiedDatabase()

    def _load_config(self) -> Dict[str, Any]:
        """Load threshold configuration from YAML."""
        if not self.config_path.exists():
            logger.warning(f"Config file {self.config_path} not found. Using empty config.")
            return {"defaults": {}, "metrics": {}, "devices": {}}
        
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _save_config(self):
        """Save threshold configuration back to YAML."""
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.config, f, allow_unicode=True)

    async def detect_anomalies(self, device: str, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Detect anomalies for a device based on provided metrics."""
        anomalies = []
        
        for metric_name, value in metrics.items():
            if value is None:
                continue
            
            threshold_info = await self.get_threshold(device, metric_name)
            if not threshold_info:
                continue
            
            severity = "normal"
            threshold_val = None
            
            strategy = threshold_info.get("strategy", "fixed")
            
            if strategy == "fixed":
                # Fixed threshold logic
                expected = threshold_info.get("expected")
                match_mode = threshold_info.get("match_mode", "exact")  # exact | contains
                
                if expected is not None:
                    # 字符串匹配
                    value_str = str(value).lower()
                    expected_str = str(expected).lower()
                    
                    is_match = False
                    if match_mode == "contains":
                        is_match = expected_str in value_str
                    else:  # exact
                        is_match = value_str == expected_str
                    
                    if not is_match:
                        severity = "critical"
                        threshold_val = expected
                else:
                    # Numeric fixed threshold
                    warn = threshold_info.get("warning")
                    crit = threshold_info.get("critical")
                    if crit is not None and value >= crit:
                        severity = "critical"
                        threshold_val = crit
                    elif warn is not None and value >= warn:
                        severity = "warning"
                        threshold_val = warn
            
            elif strategy == "statistical":
                mean = threshold_info.get("mean")
                std = threshold_info.get("std")
                w_sigma = threshold_info.get("warning_sigma", 2.0)
                c_sigma = threshold_info.get("critical_sigma", 3.0)
                
                if mean is not None and std is not None and std > 0:
                    if value >= mean + c_sigma * std:
                        severity = "critical"
                        threshold_val = mean + c_sigma * std
                    elif value >= mean + w_sigma * std:
                        severity = "warning"
                        threshold_val = warning_val = mean + w_sigma * std
            
            elif strategy == "percentile":
                p_warn = threshold_info.get("warning_val")
                p_crit = threshold_info.get("critical_val")
                
                if p_crit is not None and value >= p_crit:
                    severity = "critical"
                    threshold_val = p_crit
                elif p_warn is not None and value >= p_warn:
                    severity = "warning"
                    threshold_val = p_warn

            if severity != "normal":
                anomalies.append({
                    "metric": metric_name,
                    "value": value,
                    "threshold": threshold_val,
                    "severity": severity,
                    "strategy": strategy,
                    "device": device
                })
        
        return anomalies

    async def get_threshold(self, device: str, metric_name: str) -> Dict[str, Any]:
        """Get threshold configuration for a specific device and metric."""
        # 1. Check device-specific override
        device_cfg = self.config.get("devices", {}).get(device, {}).get(metric_name)
        if device_cfg:
            return device_cfg

        # 2. Check metric-specific config
        metric_cfg = self.config.get("metrics", {}).get(metric_name)
        if metric_cfg:
            # If strategy is adaptive (statistical/percentile), check learned thresholds
            if metric_cfg.get("strategy") in ["statistical", "percentile"]:
                learned = self.config.get("learned_thresholds", {}).get(device, {}).get(metric_name)
                if learned:
                    # Merge with metric_cfg (like sigmas)
                    return {**metric_cfg, **learned}
                else:
                    # Need to learn it
                    learned = await self._learn_threshold(device, metric_name, metric_cfg)
                    if learned:
                        return {**metric_cfg, **learned}
            
            return metric_cfg

        # 3. Fallback to defaults
        return self.config.get("defaults", {})

    async def _learn_threshold(self, device: str, metric_name: str, metric_cfg: Dict[str, Any]) -> Dict[str, Any] | None:
        """Learn threshold from historical data in DuckDB."""
        if not self.config.get("auto_learning", True):
            return None

        window_days = metric_cfg.get("learning_window_days", self.config["defaults"].get("learning_window_days", 30))
        strategy = metric_cfg.get("strategy", "statistical")
        
        # Determine source table and column
        # 映射关系：metric_name -> (table, column)
        mapping = {
            # CPU 指标
            "cpu_utilization": ("v_cpu_utilization", "cpu_5sec"),
            "cpu_1min": ("v_cpu_utilization", "cpu_1min"),
            "cpu_5min": ("v_cpu_utilization", "cpu_5min"),
            
            # 内存指标
            "memory_utilization": ("v_memory_utilization", "memory_used_percent"),
            
            # 路由计数
            "route_count": ("v_routes", "COUNT(*)"),
        }
        
        if metric_name not in mapping:
            return None
            
        table, column = mapping[metric_name]
        
        sql = f"""
            SELECT {column} 
            FROM main.{table} 
            WHERE device = ? 
        """
        
        try:
            results = self.udb.query(sql, [device])
            data = [row[0] for row in results if row[0] is not None]
            
            if len(data) < self.config["defaults"].get("min_samples", 50):
                return None
                
            arr = np.array(data)
            learned = {"last_learned": "2026-01-29T11:00:00+11:00"}
            
            if strategy == "statistical":
                mean_val = float(np.mean(arr))
                std_val = float(np.std(arr))
                
                # 关键修复：如果方差为 0，说明数据没有变化，不应该学习阈值
                if std_val == 0:
                    logger.warning(
                        f"Skipping threshold learning for {device}/{metric_name}: "
                        f"std=0 (all values are {mean_val}). "
                        "Consider using fixed threshold instead."
                    )
                    return None
                
                learned["mean"] = mean_val
                learned["std"] = std_val
                
            elif strategy == "percentile":
                p_warn = metric_cfg.get("warning_percentile", 95)
                p_crit = metric_cfg.get("critical_percentile", 99)
                learned["warning_val"] = float(np.percentile(arr, p_warn))
                learned["critical_val"] = float(np.percentile(arr, p_crit))
            
            # Save to configuration
            if device not in self.config["learned_thresholds"]:
                self.config["learned_thresholds"][device] = {}
            self.config["learned_thresholds"][device][metric_name] = learned
            self._save_config()
            
            return learned
        except Exception as e:
            logger.error(f"Error learning threshold for {device}/{metric_name}: {e}")
            return None
