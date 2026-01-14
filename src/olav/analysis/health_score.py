"""Health scoring rules for network layers.

Defines scoring rules for L1-L4 network health assessment.
Each layer has specific metrics and scoring weights.
"""

from typing import Any

# Health scoring rules by layer
HEALTH_SCORING_RULES = {
    "L1": {
        "name": "Physical Layer",
        "metrics": {
            "interface_up": {"weight": 10, "description": "Interface operational"},
            "interface_down": {"weight": -20, "description": "Interface down"},
            "crc_errors": {"weight": -5, "description": "CRC errors detected"},
            "input_errors": {"weight": -3, "description": "Input errors"},
            "output_errors": {"weight": -3, "description": "Output errors"},
        },
        "thresholds": {
            "healthy": 80,  # >= 80: Healthy
            "warning": 50,  # 50-79: Warning
            # < 50: Critical
        },
    },
    "L2": {
        "name": "Data Link Layer",
        "metrics": {
            "vlan_active": {"weight": 5, "description": "VLAN active"},
            "vlan_suspended": {"weight": -10, "description": "VLAN suspended"},
            "stp_forwarding": {"weight": 5, "description": "STP forwarding"},
            "stp_blocking": {"weight": -5, "description": "STP blocking"},
        },
        "thresholds": {
            "healthy": 80,
            "warning": 50,
        },
    },
    "L3": {
        "name": "Network Layer",
        "metrics": {
            "route_active": {"weight": 3, "description": "Active route"},
            "ospf_full": {"weight": 10, "description": "OSPF neighbor FULL"},
            "ospf_down": {"weight": -20, "description": "OSPF neighbor down"},
            "static_route": {"weight": 2, "description": "Static route"},
        },
        "thresholds": {
            "healthy": 80,
            "warning": 50,
        },
    },
    "L4": {
        "name": "Transport Layer",
        "metrics": {
            "bgp_established": {
                "weight": 15,
                "description": "BGP session established",
            },
            "bgp_idle": {"weight": -25, "description": "BGP session idle"},
            "bgp_active": {"weight": -15, "description": "BGP session active"},
            "prefix_received": {"weight": 1, "description": "BGP prefix received"},
        },
        "thresholds": {
            "healthy": 80,
            "warning": 50,
        },
    },
}


def calculate_layer_score(
    layer: str, metrics: dict[str, int]
) -> dict[str, Any]:
    """Calculate health score for a specific layer.

    Args:
        layer: Layer name (L1, L2, L3, L4)
        metrics: Dictionary of metric_name -> count

    Returns:
        Dictionary with score, status, and breakdown

    Example:
        >>> metrics = {"interface_up": 10, "interface_down": 2, "crc_errors": 5}
        >>> result = calculate_layer_score("L1", metrics)
        >>> print(result["score"])
        70
    """
    if layer not in HEALTH_SCORING_RULES:
        return {"error": f"Unknown layer: {layer}"}

    rules = HEALTH_SCORING_RULES[layer]
    metric_rules = rules["metrics"]

    # Calculate raw score
    raw_score = 0
    breakdown = []

    for metric_name, count in metrics.items():
        if metric_name in metric_rules:
            weight = metric_rules[metric_name]["weight"]
            contribution = weight * count
            raw_score += contribution
            breakdown.append(
                {
                    "metric": metric_name,
                    "count": count,
                    "weight": weight,
                    "contribution": contribution,
                }
            )

    # Normalize to 0-100 scale
    # Assume baseline of 100, adjust based on negative factors
    base_score = 100
    normalized_score = max(0, min(100, base_score + raw_score))

    # Determine status
    thresholds = rules["thresholds"]
    if normalized_score >= thresholds["healthy"]:
        status = "healthy"
        icon = "🟢"
    elif normalized_score >= thresholds["warning"]:
        status = "warning"
        icon = "🟡"
    else:
        status = "critical"
        icon = "🔴"

    return {
        "layer": layer,
        "name": rules["name"],
        "score": int(normalized_score),
        "status": status,
        "icon": icon,
        "raw_score": raw_score,
        "breakdown": breakdown,
    }


def calculate_overall_score(
    layer_scores: dict[str, int]
) -> dict[str, Any]:
    """Calculate overall network health score from layer scores.

    Args:
        layer_scores: Dictionary of layer -> score

    Returns:
        Dictionary with overall score and status

    Example:
        >>> scores = {"L1": 85, "L2": 90, "L3": 75, "L4": 80}
        >>> result = calculate_overall_score(scores)
        >>> print(result["score"])
        82
    """
    if not layer_scores:
        return {"score": 0, "status": "unknown", "icon": "⚪"}

    # Weighted average (L3/L4 more important for core functionality)
    weights = {"L1": 1.0, "L2": 1.0, "L3": 1.5, "L4": 1.5}

    total_weighted = 0
    total_weight = 0

    for layer, score in layer_scores.items():
        weight = weights.get(layer, 1.0)
        total_weighted += score * weight
        total_weight += weight

    overall_score = int(total_weighted / total_weight) if total_weight > 0 else 0

    # Determine status
    if overall_score >= 80:
        status = "healthy"
        icon = "🟢"
    elif overall_score >= 50:
        status = "warning"
        icon = "🟡"
    else:
        status = "critical"
        icon = "🔴"

    return {
        "score": overall_score,
        "status": status,
        "icon": icon,
        "layer_scores": layer_scores,
    }


def format_score_report(score_data: dict[str, Any]) -> str:
    """Format health score data as human-readable report.

    Args:
        score_data: Score data from calculate_layer_score or calculate_overall_score

    Returns:
        Formatted markdown report
    """
    if "layer" in score_data:
        # Layer-specific report
        report = f"## {score_data['icon']} {score_data['name']} (L{score_data['layer'][1]})\n\n"
        report += f"**Score**: {score_data['score']}/100 ({score_data['status'].upper()})\n\n"

        if score_data.get("breakdown"):
            report += "### Breakdown\n\n"
            for item in score_data["breakdown"]:
                sign = "+" if item["contribution"] >= 0 else ""
                report += f"- {item['metric']}: {item['count']} × {item['weight']} = {sign}{item['contribution']}\n"

        return report
    else:
        # Overall report
        report = f"## {score_data['icon']} Overall Network Health\n\n"
        report += f"**Score**: {score_data['score']}/100 ({score_data['status'].upper()})\n\n"

        if score_data.get("layer_scores"):
            report += "### Layer Scores\n\n"
            for layer, score in sorted(score_data["layer_scores"].items()):
                rules = HEALTH_SCORING_RULES.get(layer, {})
                name = rules.get("name", layer)
                if score >= 80:
                    icon = "🟢"
                elif score >= 50:
                    icon = "🟡"
                else:
                    icon = "🔴"
                report += f"- {icon} **{name}**: {score}/100\n"

        return report
