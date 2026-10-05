from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass(frozen=True)
class ExecutionEvent:
    event_type: str
    message: str
    payload: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "message": self.message,
            "payload": self.payload or {},
            "created_at": self.created_at.isoformat(),
        }


class EventStore:
    """Stores execution state and emits domain events."""

    def __init__(self) -> None:
        self._events: list[ExecutionEvent] = []
        self._listeners: list[Callable[[ExecutionEvent], None]] = []

    def subscribe(self, listener: Callable[[ExecutionEvent], None]) -> None:
        self._listeners.append(listener)

    def emit(self, event_type: str, message: str, payload: dict[str, Any] | None = None) -> ExecutionEvent:
        event = ExecutionEvent(event_type=event_type, message=message, payload=payload)
        self._events.append(event)
        for listener in self._listeners:
            listener(event)
        return event

    def publish(self, event_type: str, message: str, payload: dict[str, Any] | None = None) -> ExecutionEvent:
        return self.emit(event_type, message, payload)

    def history(self) -> list[ExecutionEvent]:
        return list(self._events)

    def snapshot(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self._events]
