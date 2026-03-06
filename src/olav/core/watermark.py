"""Digital Watermark Module for olav Framework.

Provides watermark generation and tracking for compliance and IP protection.
All outputs are tagged with version, copyright, and usage restrictions.
"""

from datetime import datetime


def get_watermark_metadata() -> dict:
    """Get standard watermark metadata for all outputs.

    Returns:
        Dictionary containing framework watermark information.
    """
    return {
        "framework": "olav",
        "version": "0.10.0",
        "watermark_id": "DTP-OLAV-0100",
        "copyright": "Copyright © 2026-2030 DATATECHIE PTY LTD. All rights reserved.",
        "license": "Business Source License 1.1",
        "license_url": "https://github.com/[repo]/LICENSE",
        "change_date": "2030-01-01",
        "usage_allowed": ["personal_use", "internal_enterprise"],
        "requires_license_for": ["MSP", "CSP", "resale", "commercial_service"],
        "terms_url": "https://github.com/[repo]/PARTNERS.md",
    }


def get_watermark_notice() -> str:
    """Get standard copyright/license notice for CLI output.

    Returns:
        Formatted notice string for display in CLI output.
    """
    return (
        "olav v0.10.0 (DTP-OLAV-0100) | "
        "© 2026-2030 DATATECHIE PTY LTD | "
        "Licensed under BSL 1.1 | "
        "Unauthorized commercial use prohibited"
    )


def get_watermark_banner() -> str:
    """Get ASCII banner with watermark for startup display.

    Returns:
        Multi-line banner string with copyright and license info.
    """
    return """
╔─────────────────────────────────────────────────────────────╗
║          olav Framework v0.10.0 (DTP-OLAV-0100)            ║
║          © 2026-2030 DATATECHIE PTY LTD                     ║
║          Licensed under Business Source License 1.1        ║
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
            "generated_at": datetime.utcnow().isoformat() + "Z",
        },
        **data,
    }
    return watermarked


def get_audit_log_watermark() -> str:
    """Get watermark string for audit logs.

    Returns:
        Log entry string with watermark info.
    """
    timestamp = datetime.utcnow().isoformat() + "Z"
    return (
        f"[{timestamp}] [WATERMARK] olav Framework v0.10.0 (DTP-OLAV-0100) initialized | "
        "© 2026-2030 DATATECHIE PTY LTD | "
        "Licensed under BSL 1.1 - Non-commercial use only. "
        "See LICENSE for commercial licensing."
    )
