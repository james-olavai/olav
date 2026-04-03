"""Digital Watermark Module for olav Framework.

Provides watermark generation and tracking for compliance and IP protection.
All outputs are tagged with version, copyright, and usage restrictions.
"""

from datetime import UTC, datetime

from olav.core.version import VERSION_STRING, COPYRIGHT_HOLDER, LICENSE, HOMEPAGE


def get_watermark_metadata() -> dict:
    """Get standard watermark metadata for all outputs.

    Returns:
        Dictionary containing framework watermark information.
    """
    return {
        "framework": "olav",
        "version": VERSION_STRING,
        "watermark_id": "DTP-OLAV-0100",
        "copyright": f"Copyright © 2026-2030 {COPYRIGHT_HOLDER}. All rights reserved.",
        "license": LICENSE,
        "license_url": f"{HOMEPAGE}/blob/main/LICENSE",
        "change_date": "2030-01-01",
        "usage_allowed": ["personal_use", "internal_enterprise"],
        "requires_license_for": ["MSP", "CSP", "resale", "commercial_service"],
        "terms_url": f"{HOMEPAGE}/blob/main/PARTNERS.md",
    }


def get_watermark_notice() -> str:
    """Get standard copyright/license notice for CLI output.

    Returns:
        Formatted notice string for display in CLI output.
    """
    return (
        f"olav v{VERSION_STRING} (DTP-OLAV-0100) | "
        f"© 2026-2030 {COPYRIGHT_HOLDER} | "
        f"Licensed under {LICENSE} | "
        "Unauthorized commercial use prohibited"
    )


def get_watermark_banner() -> str:
    """Get ASCII banner with watermark for startup display.

    Returns:
        Multi-line banner string with copyright and license info.
    """
    return f"""
╔─────────────────────────────────────────────────────────────╗
║          olav Framework v{VERSION_STRING} (DTP-OLAV-0100)            ║
║          © 2026-2030 {COPYRIGHT_HOLDER}                     ║
║          Licensed under {LICENSE}                           ║
║                                                              ║
║  Non-commercial use only                                    ║
║  Unauthorized commercial use prohibited                     ║
║  See LICENSE and PARTNERS.md for terms                      ║
╚─────────────────────────────────────────────────────────────╝
"""


def inject_watermark_json(data: dict) -> dict:
    """Inject watermark metadata into JSON output.

    Args:
        data: Original data dictionary

    Returns:
        Data dictionary with _watermark metadata prepended.
    """
    watermarked = {
        "_watermark": {
            **get_watermark_metadata(),
            "generated_at": datetime.now(UTC).isoformat(),
        },
        **data,
    }
    return watermarked


def get_audit_log_watermark() -> str:
    """Get watermark string for audit logs.

    Returns:
        Log entry string with watermark info.
    """
    timestamp = datetime.now(UTC).isoformat()
    return (
        f"[{timestamp}] [WATERMARK] olav Framework v{VERSION_STRING} (DTP-OLAV-0100) initialized | "
        f"© 2026-2030 {COPYRIGHT_HOLDER} | "
        f"Licensed under {LICENSE} - Non-commercial use only. "
        "See LICENSE for commercial licensing."
    )
