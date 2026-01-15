"""
Logging configuration for prediction markets library.
"""

import logging
import sys
from typing import TextIO


def setup_logger(
    name: str = "prediction_markets",
    level: int | str = logging.INFO,
    format_string: str | None = None,
    stream: TextIO | None = None,
) -> logging.Logger:
    """
    Setup and configure logger.

    Args:
        name: Logger name
        level: Logging level (INFO, DEBUG, etc.)
        format_string: Custom format string
        stream: Output stream (default: stderr)

    Returns:
        Configured logger instance

    Example:
        ```python
        logger = setup_logger("prediction_markets", level=logging.DEBUG)
        logger.debug("Debug message")
        ```
    """
    logger = logging.getLogger(name)

    # Convert string level to int
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    logger.setLevel(level)

    # Remove existing handlers
    logger.handlers.clear()

    # Default format
    if format_string is None:
        format_string = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    formatter = logging.Formatter(format_string, datefmt="%Y-%m-%d %H:%M:%S")

    # Stream handler
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """
    Get a logger instance.

    Args:
        name: Logger name (appended to "prediction_markets")

    Returns:
        Logger instance

    Example:
        ```python
        logger = get_logger("polymarket")  # prediction_markets.polymarket
        logger.info("Connected")
        ```
    """
    if name:
        return logging.getLogger(f"prediction_markets.{name}")
    return logging.getLogger("prediction_markets")


# Default logger
logger = get_logger()
