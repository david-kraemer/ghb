"""The only module that talks to GitHub: thin wrappers over the ``gh`` CLI, plus a disk cache.

Everything here returns raw JSON-shaped data; :mod:`ghb.model` turns it into records.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

HISTORY_FIELDS = (
    "number,title,url,state,isDraft,headRefName,baseRefName,"
    "createdAt,updatedAt,closedAt,mergedAt,additions,deletions"
)
DETAIL_FIELDS = HISTORY_FIELDS + ",statusCheckRollup,reviewDecision,comments,reviews,mergeable"


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Raw PR data for one (repo, author, window) as fetched at ``fetched``."""

    history: list[dict[str, Any]]
    details: list[dict[str, Any]]
    fetched: datetime


class GhError(RuntimeError):
    pass


def repository(path: Path) -> str:
    """``owner/name`` of the GitHub repository checked out at ``path``."""
    out = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        check=False,
        cwd=path,
        capture_output=True,
        text=True,
    )
    if out.returncode:
        raise GhError(out.stderr.strip() or f"no GitHub repository at {path}")
    return out.stdout.strip()


async def snapshot(repo: str, author: str, days: int) -> Snapshot:
    """Fetch PRs touched in the last ``days`` plus full detail on every open PR.

    ``updated:>=`` bounds the history query: anything opened, merged or closed in
    the window was necessarily updated in it. Open PRs are fetched separately so
    stale ones outside the window still show up, with checks and reviews.
    """
    since = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    common = ["pr", "list", "-R", repo, "--author", author, "--limit", "1000"]
    history, details = await asyncio.gather(
        gh_json(*common, "--state", "all", "--search", f"updated:>={since}", "--json", HISTORY_FIELDS),
        gh_json(*common, "--state", "open", "--json", DETAIL_FIELDS),
    )
    return Snapshot(history, details, datetime.now(UTC))


async def gh_json(*args: str) -> Any:
    proc = await asyncio.create_subprocess_exec(
        "gh", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode:
        raise GhError(err.decode().strip())
    return json.loads(out)


def cached(repo: str, author: str, days: int) -> Snapshot | None:
    try:
        raw = json.loads(cache_path(repo, author, days).read_text())
        return Snapshot(raw["history"], raw["details"], datetime.fromisoformat(raw["fetched"]))
    except (OSError, ValueError, KeyError):
        return None


def save_cache(repo: str, author: str, days: int, snap: Snapshot) -> None:
    path = cache_path(repo, author, days)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"history": snap.history, "details": snap.details, "fetched": snap.fetched.isoformat()}
    path.write_text(json.dumps(payload))


def cache_path(repo: str, author: str, days: int) -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "ghb"
    return root / f"{repo.replace('/', '__')}--{author.lstrip('@')}--{days}d.json"
