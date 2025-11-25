"""Start API server with proper Windows event loop configuration.

Usage:
    uv run python scripts/start_api_server.py
    uv run python scripts/start_api_server.py --no-reload
"""

import argparse
import asyncio
import os

# CRITICAL: Set Windows event loop policy BEFORE any other imports
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    print("✓ Set WindowsSelectorEventLoopPolicy for compatibility")


def main():
    """Start API server with uvicorn."""
    parser = argparse.ArgumentParser(description="Start OLAV API Server")
    parser.add_argument("--no-reload", action="store_true", help="Disable auto-reload")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    args = parser.parse_args()
    
    # Import uvicorn and app here, after event loop policy is set
    from olav.server.app import app
    import uvicorn
    
    print(f"🚀 Starting OLAV API Server on {args.host}:{args.port}")
    print(f"📖 API Documentation: http://localhost:{args.port}/docs")
    if not args.no_reload:
        print("🔄 Auto-reload enabled (development mode)")
    
    # Run directly with app instance instead of string reference
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
