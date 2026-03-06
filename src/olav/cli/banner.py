"""OLAV CLI Banner - Professional industrial-grade theme."""

import sys

from olav.core.watermark import get_watermark_banner, get_watermark_notice

# Configuration parameters: NetAIOps industrial-grade color scheme (deep blue -> tech teal)
COLOR_START = (60, 80, 255)  # Protocol Blue (physical layer stability)
COLOR_END = (0, 255, 180)  # Logic Teal (intelligent logic layer)


def get_ansi_rgb(r: int, g: int, b: int) -> str:
    """Generate 24-bit ANSI color sequence"""
    return f"\x1b[38;2;{r};{g};{b}m"


def print_olav_banner() -> None:
    """Print OLAV banner with professional industrial theme."""
    apply_professional_theme()


def apply_professional_theme() -> None:
    """Apply professional NetAIOps theme to OLAV ASCII art."""
    # OLAV ASCII structure
    olav_ascii = [
        "  ██████╗  ██╗       █████╗  ██╗   ██╗",
        " ██╔═══██╗ ██║      ██╔══██╗ ██║   ██║",
        " ██║   ██║ ██║      ███████║ ██║   ██║",
        " ██║   ██║ ██║      ██╔══██║ ╚██╗ ██╔╝",
        " ╚██████╔╝ ███████╗ ██║  ██║  ╚████╔╝ ",
        "  ╚═════╝  ╚══════╝ ╚═╝  ╚═╝   ╚═══╝  ",
    ]

    tagline = "Online Analytical Vertex for Agentic Networking ☃️"
    reset = "\x1b[0m"
    bold = "\x1b[1m"

    sys.stdout.write("\n")  # Blank line

    # Print logo area (pure gradient, no particle effects)
    for line in olav_ascii:
        out = "  "
        width = len(line)
        for c_idx, char in enumerate(line):
            if char == " " or char == "":
                out += " "
                continue

            # Horizontal gradient
            ratio = c_idx / max(1, width - 1)
            r = int(COLOR_START[0] + (COLOR_END[0] - COLOR_START[0]) * ratio)
            g = int(COLOR_START[1] + (COLOR_END[1] - COLOR_START[1]) * ratio)
            b = int(COLOR_START[2] + (COLOR_END[2] - COLOR_START[2]) * ratio)

            out += f"{get_ansi_rgb(r, g, b)}{char}{reset}"

        sys.stdout.write(out + "\n")

    # Print tagline
    sys.stdout.write(f"\n  {bold}{tagline}{reset}\n")

    # Print watermark notice
    sys.stdout.write(f"\n{get_watermark_notice()}\n\n")
    sys.stdout.flush()
