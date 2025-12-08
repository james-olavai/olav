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
from .commands import app as cli_app
from .display import (
    HITLPanel,
    InspectionProgress,
    ResultRenderer,
    ThinkingTree,
)
from .repl import REPLSession, handle_slash_command

# V2 exports
from .thin_client import (
    ClientConfig,
    OlavThinClient,
    StreamEvent,
    StreamEventType,
)

__all__ = [
    # Legacy
    "AuthClient",
    # V2
    "ClientConfig",
    "CredentialsManager",
    "ExecutionResult",
    "HITLPanel",
    "InspectionProgress",
    "OLAVClient",
    "OlavThinClient",
    "REPLSession",
    "ResultRenderer",
    "ServerConfig",
    "StreamEvent",
    "StreamEventType",
    "ThinkingTree",
    "cli_app",
    "create_client",
    "handle_slash_command",
    "login_interactive",
    "logout_interactive",
    "whoami_interactive",
]
