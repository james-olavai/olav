"""OLAV CLI Client Module.

Provides remote and local execution modes for OLAV workflows.

V2 Architecture:
- thin_client.py: Pure HTTP client (no server dependencies)
- display.py: Rich UI components (ThinkingTree, HITLPanel)
- repl.py: Interactive prompt_toolkit session
- commands.py: Typer CLI commands
"""

# Legacy exports (backward compatibility)
from .auth import (
    AuthClient,
    CredentialsManager,
    login_interactive,
    logout_interactive,
    whoami_interactive,
)
from .client import ExecutionResult, OLAVClient, ServerConfig, create_client

# V2 exports
from .thin_client import (
    ClientConfig,
    OlavThinClient,
    StreamEvent,
    StreamEventType,
)
from .display import (
    HITLPanel,
    InspectionProgress,
    ResultRenderer,
    ThinkingTree,
)
from .repl import REPLSession, handle_slash_command
from .commands import app as cli_app

__all__ = [
    # Legacy
    "AuthClient",
    "CredentialsManager",
    "ExecutionResult",
    "OLAVClient",
    "ServerConfig",
    "create_client",
    "login_interactive",
    "logout_interactive",
    "whoami_interactive",
    # V2
    "ClientConfig",
    "OlavThinClient",
    "StreamEvent",
    "StreamEventType",
    "HITLPanel",
    "InspectionProgress",
    "ResultRenderer",
    "ThinkingTree",
    "REPLSession",
    "handle_slash_command",
    "cli_app",
]
