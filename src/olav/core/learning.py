"""Learning workflow - Solution capture and knowledge base integration.

This module handles saving diagnostic solutions to the knowledge base,
with optional automatic Git commits and vectorization.
"""

import subprocess
from pathlib import Path
from datetime import datetime
from typing import List

from config.paths import AGENT_DIR

# Knowledge base paths
KNOWLEDGE_BASE_PATH = AGENT_DIR / "knowledge"


def save_solution(
    title: str,
    problem: str,
    process: List[str],
    root_cause: str,
    solution: str,
    commands: List[str],
    tags: List[str],
    auto_commit: bool = True,
    auto_vectorize: bool = True,
) -> Path:
    """Save diagnostic solution to knowledge base.
    
    Args:
        title: Solution title (kebab-case)
        problem: Problem description
        process: Diagnostic process steps
        root_cause: Root cause analysis
        solution: Solution description
        commands: Commands to apply the fix
        tags: Solution tags for categorization
        auto_commit: Automatically commit to git (default: True)
        auto_vectorize: Automatically trigger vectorization (default: True)
    
    Returns:
        Path to saved solution file
    """
    # Ensure solutions directory exists
    solutions_dir = KNOWLEDGE_BASE_PATH / "solutions"
    solutions_dir.mkdir(parents=True, exist_ok=True)
    
    # Create document path
    doc_path = solutions_dir / f"{title}.md"
    
    # Build markdown content
    timestamp = datetime.now().isoformat()
    content = f"""# {title}

## Problem
{problem}

## Diagnostic Process
{create_list(process)}

## Root Cause
{root_cause}

## Solution
{solution}

## Commands
{create_list(commands)}

## Tags
{', '.join(f'`{tag}`' for tag in tags) if tags else 'None'}

## Metadata
- Created: {timestamp}
- Type: Diagnostic Solution
"""
    
    # Save file
    doc_path.write_text(content, encoding="utf-8")
    
    # Auto-commit to Git if enabled
    if auto_commit:
        _git_commit_solution(doc_path, title)
    
    # Auto-vectorize if enabled
    if auto_vectorize:
        _trigger_vectorization()
    
    return doc_path


def _git_commit_solution(file_path: Path, title: str) -> None:
    """Commit solution file to git.
    
    Args:
        file_path: Path to the solution file
        title: Solution title for commit message
    """
    try:
        # Add file to git
        subprocess.run(
            ["git", "add", str(file_path)],
            cwd=file_path.parent.parent.parent,
            check=True,
            capture_output=True,
        )
        
        # Commit with descriptive message
        commit_message = f"docs: add diagnostic solution for {title}"
        subprocess.run(
            ["git", "commit", "-m", commit_message],
            cwd=file_path.parent.parent.parent,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        # Log but don't fail if git operations fail
        print(f"Warning: Git commit failed: {e}")


def _trigger_vectorization() -> None:
    """Trigger knowledge base vectorization in background.
    
    This spawns a background process to vectorize new solutions
    without blocking the main flow.
    """
    try:
        subprocess.Popen(
            ["olav", "knowledge", "index", "--incremental"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        # Log but don't fail if vectorization fails
        print(f"Warning: Background vectorization failed: {e}")


def create_list(items: List[str]) -> str:
    """Create markdown list from items.
    
    Args:
        items: List of strings
    
    Returns:
        Formatted markdown list or 'None' if empty
    """
    if not items:
        return "None"
    return "\n".join(f"- {item}" for item in items)
