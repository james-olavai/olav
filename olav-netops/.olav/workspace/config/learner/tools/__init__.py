"""
Command Learner Agent Tools

7 tools for autonomous TextFSM template learning:
1. execute_command - Execute command on network device
2. analyze_output - LLM-powered field detection
3. search_ntc_templates - Search NTC-templates (metadata only)
4. read_template_file - Read full template content (on-demand)
5. browse_ntc_directory - Browse NTC templates
6. generate_template - LLM-powered template generation
7. save_template - Save template with auto-reload
"""

from .analyze_output import analyze_output
from .execute_command import execute_command
from .ntc_browser import browse_ntc_directory
from .ntc_search import search_ntc_templates
from .template_generator import generate_template
from .template_reader import read_template_file
from .template_saver import save_template

__version__ = "2.1.0"
__all__ = [
    "execute_command",
    "analyze_output",
    "search_ntc_templates",
    "read_template_file",
    "browse_ntc_directory",
    "generate_template",
    "save_template",
]
