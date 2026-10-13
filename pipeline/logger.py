"""
Structured logging configuration for AuctionNow PK Market Engine.

Provides unified logging across adapters, pipeline components, and orchestrator.
"""
from __future__ import annotations

import logging
import sys


def setup_logging(level: str | int = "INFO") -> logging.Logger:
    """
    Configure root logging with timestamps, levels, and logger names.
    Returns the root logger.
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    if root.handlers:
        root.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.setLevel(level)

    root.setLevel(level)
    root.addHandler(handler)

    return root


def get_logger(name: str) -> logging.Logger:
    """Return a logger scoped to the module or component."""
    return logging.getLogger(name)
