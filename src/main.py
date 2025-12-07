"""Main entry point for ig2rss application."""

import logging
import sys
from dotenv import load_dotenv

# Load environment variables from .env file (for local development)
load_dotenv()

from src.config import Config
from src.api import run_server


def main() -> int:
    """Main application entry point.

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    logger = logging.getLogger(__name__)

    try:
        # Run Flask server (handles config validation, logging setup, etc.)
        run_server(Config)
        return 0
    except ValueError as e:
        # Configuration validation failed
        logger.error(f"Configuration error: {e}")
        return 1
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
        return 0
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
