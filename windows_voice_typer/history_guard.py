from __future__ import annotations

import datetime as _datetime
from typing import Any


HISTORY_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def is_recent_duplicate_history(
    history: list[dict[str, Any]],
    output: str,
    *,
    now: _datetime.datetime | None = None,
    window_seconds: float = 180.0,
) -> bool:
    if not history or not output:
        return False
    latest = history[0]
    if str(latest.get("out", "")) != output:
        return False
    try:
        latest_time = _datetime.datetime.strptime(str(latest.get("time", "")), HISTORY_TIME_FORMAT)
    except Exception:
        return False
    current = now or _datetime.datetime.now()
    age = (current - latest_time).total_seconds()
    return 0 <= age <= float(window_seconds)
