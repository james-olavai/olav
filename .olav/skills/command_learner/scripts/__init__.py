"""
Command Learner Skill Scripts

Utility scripts for the command_learner skill.
- ntc_search: Local NTC-Templates search without internet
"""

from .ntc_search import search_ntc_templates, find_ntc_path

__all__ = [
    "search_ntc_templates",
    "find_ntc_path",
]
