"""Structured JSON logging (one rotating .jsonl file per service) with secret redaction."""

import logging
import logging.handlers
import sys
import threading
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import structlog

_SECRET_KEYS = {"token", "session_token", "authorization", "api_key", "password", "secret", "ticket"}
_secrets: set[str] = set()
_secrets_lock = threading.Lock()


def register_secret(value: str | None) -> None:
    """Any log value containing this string is redacted from then on."""
    if value and len(value) >= 8:
        with _secrets_lock:
            _secrets.add(value)


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        with _secrets_lock:
            for secret in _secrets:
                if secret in value:
                    value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, dict):
        return {k: "[redacted]" if k.lower() in _SECRET_KEYS else _scrub(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(_scrub(v) for v in value)
    return value


def redact(_logger: Any, _method: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        if key.lower() in _SECRET_KEYS:
            event_dict[key] = "[redacted]"
        else:
            event_dict[key] = _scrub(event_dict[key])
    return event_dict


def configure_logging(service: str, log_dir: Path | None, *, level: str = "INFO", console: bool = True) -> None:
    """Route stdlib logging and structlog through JSON renderers into <log_dir>/<service>.jsonl."""
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.format_exc_info,
        redact,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=[structlog.stdlib.add_logger_name, *shared],
    )
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / f"{service}.jsonl", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    # stderr is captured by the supervisor (logs/<service>.out.log) and shown in safe mode, so
    # warnings and errors always go there; `console=False` only silences the info chatter.
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    stream.setLevel(level if console else logging.WARNING)
    root.addHandler(stream)
    root.setLevel(level)
    structlog.contextvars.bind_contextvars(service=service)


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)
