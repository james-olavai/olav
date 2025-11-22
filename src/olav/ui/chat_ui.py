"""Chat UI components for elegant conversation interface."""

from typing import Optional, Any
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.live import Live
from rich.spinner import Spinner
from rich.tree import Tree
from rich.text import Text
from rich.columns import Columns


class ChatUI:
    """Elegant chat interface with streaming support."""
    
    def __init__(self, console: Optional[Console] = None):
        """Initialize chat UI.
        
        Args:
            console: Rich console instance. If None, creates a new one.
        """
        self.console = console or Console()
        self.history = []
        
        # Tool display names (Chinese)
        self.tool_names = {
            "suzieq_schema_search": "搜索数据模型",
            "suzieq_query": "查询历史数据",
            "netconf_tool": "NETCONF 配置",
            "cli_tool": "CLI 命令执行",
            "nornir_tool": "设备操作",
        }
    
    def show_user_message(self, text: str) -> None:
        """Display user message in a panel.
        
        Args:
            text: User's query text
        """
        self.console.print(
            Panel(
                text,
                title="[bold cyan]👤 You[/bold cyan]",
                border_style="cyan",
                padding=(0, 2),
            )
        )
        self.console.print()
    
    def create_thinking_context(self) -> Live:
        """Create a Live context for displaying agent thinking process.
        
        Returns:
            Live context manager that can be updated with thinking progress
        """
        spinner = Spinner("dots", text="[dim]OLAV 正在分析...[/dim]", style="cyan")
        return Live(
            spinner,
            console=self.console,
            refresh_per_second=10,
            transient=True,  # Remove when done
        )
    
    def show_agent_response(
        self,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Display agent's response in a formatted panel.
        
        Args:
            content: Response content (supports Markdown)
            metadata: Optional metadata (tools_used, data_source, etc.)
        """
        # Render content as Markdown
        md = Markdown(content)
        
        # Build subtitle with metadata
        subtitle = None
        if metadata:
            parts = []
            if "tools_used" in metadata and metadata["tools_used"]:
                tool_names = [
                    self.tool_names.get(t, t) for t in metadata["tools_used"]
                ]
                parts.append(f"🔧 {', '.join(tool_names)}")
            
            if "data_source" in metadata:
                parts.append(f"📊 {metadata['data_source']}")
            
            if parts:
                subtitle = " | ".join(parts)
        
        self.console.print(
            Panel(
                md,
                title="[bold green]🤖 OLAV[/bold green]",
                subtitle=f"[dim]{subtitle}[/dim]" if subtitle else None,
                border_style="green",
                padding=(1, 2),
            )
        )
        self.console.print()
    
    def get_tool_display_name(self, tool_name: str) -> str:
        """Get Chinese display name for a tool.
        
        Args:
            tool_name: Internal tool name
            
        Returns:
            User-friendly display name
        """
        return self.tool_names.get(tool_name, tool_name)
    
    def create_thinking_tree(self) -> Tree:
        """Create a tree structure for displaying agent's thinking process.
        
        Returns:
            Tree object that can be updated with thinking steps
        """
        return Tree("🧠 [cyan]思考过程[/cyan]")
    
    def add_tool_call(self, tree: Tree, tool_name: str, args: dict) -> Any:
        """Add a tool call node to the thinking tree.
        
        Args:
            tree: Tree to add node to
            tool_name: Name of the tool being called
            args: Tool arguments
            
        Returns:
            The added node (for later updates)
        """
        display_name = self.get_tool_display_name(tool_name)
        
        # Format args preview (first 60 chars)
        args_preview = str(args)
        if len(args_preview) > 60:
            args_preview = args_preview[:57] + "..."
        
        node = tree.add(f"[yellow]⏳ {display_name}[/yellow]")
        node.add(f"[dim]{args_preview}[/dim]")
        
        return node
    
    def mark_tool_complete(self, node: Any, tool_name: str, success: bool = True) -> None:
        """Mark a tool call as complete in the tree.
        
        Args:
            node: Tree node to update
            tool_name: Name of the tool
            success: Whether the tool call succeeded
        """
        display_name = self.get_tool_display_name(tool_name)
        
        if success:
            node.label = Text.from_markup(f"[green]✓ {display_name}[/green]")
        else:
            node.label = Text.from_markup(f"[red]✗ {display_name}[/red]")
    
    def show_error(self, message: str) -> None:
        """Display an error message.
        
        Args:
            message: Error message to display
        """
        self.console.print(f"[red]❌ 错误: {message}[/red]")
    
    def show_warning(self, message: str) -> None:
        """Display a warning message.
        
        Args:
            message: Warning message to display
        """
        self.console.print(f"[yellow]⚠️  {message}[/yellow]")
    
    def show_info(self, message: str) -> None:
        """Display an info message.
        
        Args:
            message: Info message to display
        """
        self.console.print(f"[cyan]ℹ️  {message}[/cyan]")
