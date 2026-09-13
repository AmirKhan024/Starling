"""Structured JSON logging for Starling nodes.

With 4-20 processes running concurrently, interleaved bare `print` output is
unreadable and cannot be parsed for metric collection (STARLING_BUILD_STATE.md
WP-00 task 3). Every log record is JSON and carries node_id.
"""

from __future__ import annotations

import logging
import sys

import structlog


def setup_logging(node_id: int | None, level: str = "INFO") -> None:
    """Configure structlog to emit JSON lines tagged with node_id."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    def _bind_node_id(logger, method_name, event_dict):
        event_dict.setdefault("node_id", node_id)
        return event_dict

    structlog.configure(
        processors=[
            _bind_node_id,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Return a structlog logger bound to `name`; node_id is added by setup_logging."""
    return structlog.get_logger(name)
