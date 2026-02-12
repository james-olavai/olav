"""
Shared tools bridge module

This package bridges between src/olav/shared and .olav/skills/shared
by re-exporting all tools from the actual implementation location.

Location: src/olav/shared/ (bridge)
Implementation: .olav/skills/shared/tools/ (actual code)
"""

import sys
from pathlib import Path

# Add .olav/skills/shared to the path so we can import its modules
_shared_tools_path = Path(__file__).parent.parent.parent.parent / ".olav" / "skills" / "shared"
if str(_shared_tools_path) not in sys.path:
    sys.path.insert(0, str(_shared_tools_path))
