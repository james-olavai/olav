"""Initialize PostgreSQL Checkpointer tables."""

import logging

from langgraph.checkpoint.postgres import PostgresSaver

from olav.core.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    """Initialize PostgreSQL Checkpointer tables for LangGraph."""
    logger.info("Initializing PostgreSQL Checkpointer...")
    logger.info(f"Connecting to: {settings.postgres_uri}")

    try:
        # Create checkpointer and setup tables
        with PostgresSaver.from_conn_string(settings.postgres_uri) as checkpointer:
            checkpointer.setup()

        logger.info("✓ Checkpointer tables created successfully")
        logger.info("  - checkpoints")
        logger.info("  - checkpoint_writes")
        logger.info("  - checkpoint_migrations")

    except Exception as e:
        logger.error(f"✗ Failed to initialize Checkpointer: {e}")
        raise


if __name__ == "__main__":
    main()
