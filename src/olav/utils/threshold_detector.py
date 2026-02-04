"""Threshold detection utility functions.

Migrated from ThresholdAgent (v0.9.8) to align with OLAV design principles:
- Configuration in settings.py + SKILL.md frontmatter
- Logic as utility functions instead of Agent class
- Database queries via UnifiedDatabase

Usage:
    from olav.utils.threshold_detector import detect_anomalies
    
    anomalies = await detect_anomalies(device="R1", metrics={"cpu_5sec": 85.5})
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def detect_anomalies(
    device: str,
    metrics: dict[str, Any],
    threshold_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Detect anomalies for a device based on provided metrics.
    
    Args:
        device: Device name
        metrics: Metric name -> value mapping
        threshold_config: Threshold configuration (from settings or SKILL.md)
                         If None, uses default from config.settings
    
    Returns:
        List of anomaly dictionaries with keys:
        - metric: Metric name
        - value: Current value
        - threshold: Threshold value
        - severity: "warning" or "critical"
        - strategy: "fixed", "statistical", or "percentile"
        - device: Device name
    """
    if threshold_config is None:
        from config.settings import Settings
        settings = Settings()
        threshold_config = settings.threshold.model_dump()
    
    anomalies = []
    
    for metric_name, value in metrics.items():
        if value is None:
            continue
        
        threshold_info = _get_threshold(device, metric_name, threshold_config)
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
                # String matching
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
                    threshold_val = mean + w_sigma * std
        
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
                "device": device,
            })
    
    return anomalies


def _get_threshold(
    device: str,
    metric_name: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Get threshold configuration for a specific device and metric.
    
    Priority:
    1. Device-specific override
    2. Metric-specific config
    3. Defaults
    """
    # 1. Check device-specific override
    device_cfg = config.get("devices", {}).get(device, {}).get(metric_name)
    if device_cfg:
        return device_cfg
    
    # 2. Check metric-specific config
    metric_cfg = config.get("metrics", {}).get(metric_name)
    if metric_cfg:
        return metric_cfg
    
    # 3. Fallback to defaults
    return config.get("defaults", {})
