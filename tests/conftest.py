from datetime import UTC, datetime, timedelta
from typing import Any

NOW = datetime(2026, 11, 11, 12, tzinfo=UTC)


def raw(
    number: int,
    state: str = "OPEN",
    *,
    draft: bool = False,
    age_days: float = 1,
    resolved_days: float | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """A ``gh pr list --json`` object, ``age_days`` old, resolved ``resolved_days`` ago."""
    iso = lambda d: (NOW - timedelta(days=d)).isoformat()
    out = {
        "number": number,
        "title": f"pr {number}",
        "url": f"https://x/{number}",
        "state": state,
        "isDraft": draft,
        "headRefName": f"b{number}",
        "baseRefName": "main",
        "createdAt": iso(age_days),
        "updatedAt": iso(resolved_days or 0),
        "closedAt": iso(resolved_days) if state != "OPEN" else None,
        "mergedAt": iso(resolved_days) if state == "MERGED" else None,
        "additions": 10,
        "deletions": 2,
    }
    return out | extra
