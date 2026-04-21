"""Stable event helpers for JoyBoy agent streams."""

from __future__ import annotations

from typing import Any, Dict


TERMINAL_EVENT_VERSION = 1

TERMINAL_EVENT_TYPES = {
    "intent",
    "warning",
    "thinking",
    "tool_call",
    "tool_result",
    "approval_required",
    "loop_warning",
    "content",
    "done",
    "error",
}


def runtime_event(event_type: str, **payload: Any) -> Dict[str, Any]:
    """Build a typed runtime event with a schema version.

    The terminal route can still adapt these events to its current SSE wire
    format, but core agent code should use one stable vocabulary.
    """
    if event_type not in TERMINAL_EVENT_TYPES:
        raise ValueError(f"Unknown terminal event type: {event_type}")
    return {
        "version": TERMINAL_EVENT_VERSION,
        "type": event_type,
        **payload,
    }
