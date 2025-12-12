from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

_bot_start_time: Optional[datetime] = None


def set_bot_start_time(moment: Optional[datetime] = None) -> None:
    """Store the timestamp from which events should be processed."""
    global _bot_start_time
    _bot_start_time = moment or datetime.now(timezone.utc)


def should_process_event(event) -> bool:
    """Return True if the event timestamp is newer than the bot start time."""
    if _bot_start_time is None:
        return True
    timestamp = getattr(event, "timestamp", None)
    if not timestamp:
        return True
    try:
        event_time = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
    except Exception:
        return True
    return event_time >= _bot_start_time
