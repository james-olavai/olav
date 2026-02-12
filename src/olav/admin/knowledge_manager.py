"""
Knowledge Base Management for Admin Agent.

Provides operations for managing the OLAV knowledge base:
- Add/delete/search knowledge entries
- Full-text search and tagging
- Markdown-based storage with metadata
"""

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.logging import get_logger
from src.olav.admin.admin_file_manager import AdminFileManager
from src.olav.admin.exceptions import ValidationError

logger = get_logger(__name__)


class KnowledgeManager:
    """
    Manage knowledge base entries in .olav/knowledge/.

    Each knowledge entry is stored as a Markdown file with:
    - Title (h1)
    - Content (body)
    - Metadata (YAML frontmatter)
    - Tags (for categorization)
    - Created/updated timestamps
    """

    def __init__(self):
        """Initialize Knowledge Manager."""
        self.file_manager = AdminFileManager()
        self.knowledge_dir = ".olav/knowledge"
        self.index_file = f"{self.knowledge_dir}/index.json"
        logger.info("KnowledgeManager initialized")

    async def add_knowledge(
        self,
        title: str,
        content: str,
        topic: str = "",
        tags: Optional[List[str]] = None,
        description: str = "",
    ) -> str:
        """
        Add a new knowledge entry.

        Args:
            title: Knowledge entry title
            content: Main content in markdown
            topic: Topic/category (e.g., 'bgp', 'ospf')
            tags: List of tags for categorization
            description: Brief description

        Returns:
            Success message with details

        Raises:
            ValidationError: If title is empty or entry already exists
        """
        if not title or not title.strip():
            raise ValidationError("Knowledge title is required")

        if not content or not content.strip():
            raise ValidationError("Knowledge content is required")

        # Generate filename from title
        filename = self._generate_filename(title)
        filepath = f"{self.knowledge_dir}/{filename}.md"

        # Check if already exists
        try:
            existing_path = self.file_manager._validate_path(filepath)
            if existing_path.exists():
                raise ValidationError(f"Knowledge entry '{title}' already exists")
        except Exception as e:
            if "already exists" in str(e):
                raise
            # If path validation fails, that's a separate error
            raise ValidationError(f"Cannot access knowledge directory: {str(e)}")

        # Create knowledge entry with metadata
        # Combine topic and tags
        final_tags = list(tags) if tags else []
        if topic and topic not in final_tags:
            final_tags.insert(0, topic)

        metadata = {
            "title": title,
            "topic": topic,
            "tags": final_tags,
            "description": description,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

        # Format markdown file
        markdown_content = self._format_knowledge_entry(title, content, metadata)

        # Save file via ConfigManager (for security)
        self.file_manager.save_yaml(
            filepath,
            {"raw_content": markdown_content},  # Store raw markdown
        )

        # Update index
        await self._update_index(title, filename, metadata)

        logger.info(f"Knowledge entry '{title}' added with tags: {final_tags}")
        tags_str = ", ".join(final_tags) if final_tags else "(none)"
        return f"✓ Knowledge '{title}' has been added\n  Topic: {topic}\n  Tags: {tags_str}"

    async def delete_knowledge(self, title: str) -> str:
        """
        Delete a knowledge entry.

        Args:
            title: Title of knowledge entry to delete

        Returns:
            Success message

        Raises:
            ValidationError: If entry doesn't exist
        """
        if not title or not title.strip():
            raise ValidationError("Knowledge title is required")

        # Find the file
        filename = self._generate_filename(title)
        filepath = f"{self.knowledge_dir}/{filename}.md"

        try:
            path = self.file_manager._validate_path(filepath)
            if not path.exists():
                raise ValidationError(f"Knowledge entry '{title}' not found")

            # Delete the file
            path.unlink()

            # Update index
            await self._remove_from_index(filename)

            logger.info(f"Knowledge entry '{title}' deleted")
            return f"✓ Knowledge '{title}' has been deleted"

        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f"Cannot delete knowledge entry: {str(e)}")

    async def list_knowledge(self, topic: str = "", tags: Optional[List[str]] = None) -> str:
        """
        List all knowledge entries, optionally filtered by topic/tags.

        Args:
            topic: Filter by topic (optional)
            tags: Filter by tags (optional)

        Returns:
            List of knowledge entries
        """
        index = await self._load_index()

        if not index:
            return "ℹ️  No knowledge entries in knowledge base"

        entries = list(index.values())

        # Filter by topic if provided
        if topic and topic.strip():
            entries = [e for e in entries if e.get("topic") == topic]

        # Filter by tags if provided
        if tags:
            entries = [
                e
                for e in entries
                if any(tag in e.get("tags", []) for tag in tags)
            ]

        if not entries:
            filter_str = f"topic='{topic}'" if topic else ""
            tags_str = f"tags={tags}" if tags else ""
            filter_info = " or ".join(filter(None, [filter_str, tags_str])) or "applied"
            return f"ℹ️  No knowledge entries found for {filter_info}"

        # Format output
        lines = [f"📚 Knowledge Base ({len(entries)} entries):\n"]
        for entry in sorted(entries, key=lambda x: x.get("created_at", "")):
            title = entry.get("title", "N/A")
            topic_str = entry.get("topic", "general")
            tags_str = ", ".join(entry.get("tags", []))
            lines.append(f"  • {title:30} | Topic: {topic_str:10} | Tags: {tags_str}")

        return "\n".join(lines)

    async def search_knowledge(self, query: str) -> str:
        """
        Search knowledge base by keyword.

        Args:
            query: Search query (keywords)

        Returns:
            Search results with matching entries

        Raises:
            ValidationError: If query is empty
        """
        if not query or not query.strip():
            raise ValidationError("Search query is required")

        index = await self._load_index()

        if not index:
            return f"ℹ️  No knowledge entries found matching '{query}'"

        # Simple keyword search in title, description, and tags
        query_lower = query.lower()
        results = []

        for entry in index.values():
            title = entry.get("title", "").lower()
            description = entry.get("description", "").lower()
            topic = entry.get("topic", "").lower()
            tags = [t.lower() for t in entry.get("tags", [])]

            # Check if query matches any field (title, description, topic, or tags)
            is_match = (
                query_lower in title
                or query_lower in description
                or query_lower in topic
                or any(query_lower in tag for tag in tags)
            )
            
            if is_match:
                results.append(entry)

        if not results:
            return f"ℹ️  No knowledge entries found matching '{query}'"

        # Format results
        lines = [f"🔍 Search Results for '{query}' ({len(results)} matches):\n"]
        for entry in results:
            title = entry.get("title", "N/A")
            description = entry.get("description", "")
            lines.append(f"  • {title}")
            if description:
                lines.append(f"    Description: {description}")

        return "\n".join(lines)

    async def describe_knowledge(self, title: str) -> str:
        """
        Show detailed information about a knowledge entry.

        Args:
            title: Title of knowledge entry

        Returns:
            Detailed information

        Raises:
            ValidationError: If entry not found
        """
        if not title or not title.strip():
            raise ValidationError("Knowledge title is required")

        index = await self._load_index()

        # Find by title
        entry = None
        for e in index.values():
            if e.get("title") == title:
                entry = e
                break

        if not entry:
            raise ValidationError(f"Knowledge entry '{title}' not found")

        # Format detailed output
        lines = [f"📖 Knowledge Entry: {title}\n"]
        lines.append(f"  Topic: {entry.get('topic', 'N/A')}")
        lines.append(f"  Description: {entry.get('description', 'N/A')}")
        lines.append(f"  Tags: {', '.join(entry.get('tags', []))}")
        lines.append(f"  Created: {entry.get('created_at', 'N/A')}")
        lines.append(f"  Updated: {entry.get('updated_at', 'N/A')}")

        return "\n".join(lines)

    # Private helper methods

    def _generate_filename(self, title: str) -> str:
        """
        Generate filename from title.

        Converts title to lowercase, replaces spaces with underscores,
        removes special characters.
        """
        filename = title.lower()
        filename = re.sub(r"[^\w\s-]", "", filename)
        filename = re.sub(r"[-\s]+", "_", filename)
        return filename

    def _format_knowledge_entry(self, title: str, content: str, metadata: Dict[str, Any]) -> str:
        """Format knowledge entry as markdown with metadata."""
        yaml_block = "---\n"
        for key, value in metadata.items():
            if isinstance(value, list):
                yaml_block += f"{key}: [{', '.join(value)}]\n"
            else:
                yaml_block += f"{key}: {value}\n"
        yaml_block += "---\n\n"

        return f"{yaml_block}# {title}\n\n{content}\n"

    async def _update_index(
        self, title: str, filename: str, metadata: Dict[str, Any]
    ) -> None:
        """Update knowledge index with new entry."""
        index = await self._load_index()
        index[filename] = metadata
        await self._save_index(index)

    async def _remove_from_index(self, filename: str) -> None:
        """Remove entry from knowledge index."""
        index = await self._load_index()
        if filename in index:
            del index[filename]
        await self._save_index(index)

    async def _load_index(self) -> Dict[str, Dict[str, Any]]:
        """Load knowledge index."""
        try:
            index_path = self.file_manager._validate_path(self.index_file)
            if index_path.exists():
                content = index_path.read_text()
                return json.loads(content) if content.strip() else {}
        except Exception as e:
            logger.warning(f"Could not load knowledge index: {e}")

        return {}

    async def _save_index(self, index: Dict[str, Dict[str, Any]]) -> None:
        """Save knowledge index."""
        try:
            index_path = self.file_manager._validate_path(self.index_file)
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index_path.write_text(json.dumps(index, indent=2))
        except Exception as e:
            logger.error(f"Could not save knowledge index: {e}")
