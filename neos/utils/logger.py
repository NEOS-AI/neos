"""Logging utilities for NEOS"""

import logging
from typing import Optional


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get a logger instance

    Args:
        name: Logger name (default: __name__ of the caller)

    Returns:
        Logger instance
    """
    return logging.getLogger(name or __name__)


def setup_logging(level: str = "INFO") -> None:
    """Setup basic logging configuration

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
