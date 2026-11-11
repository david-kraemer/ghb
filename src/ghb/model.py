"""Immutable pull-request records and their construction from ``gh`` JSON."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class State(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"


class Checks(StrEnum):
    NONE = "none"
    PENDING = "pending"
    PASSING = "passing"
    FAILING = "failing"


class Review(StrEnum):
    NONE = "none"
    REQUIRED = "required"
    APPROVED = "approved"
    CHANGES = "changes"


ACTIVE = frozenset({State.DRAFT, State.OPEN})


@dataclass(frozen=True, slots=True)
class PullRequest:
    number: int
    title: str
    url: str
    state: State
    branch: str
    base: str
    created: datetime
    updated: datetime
    closed: datetime | None
    merged: datetime | None
    additions: int
    deletions: int
    checks: Checks = Checks.NONE
    review: Review = Review.NONE
    comments: int = 0
    conflicted: bool = False

    @property
    def active(self) -> bool:
        return self.state in ACTIVE


def pull_requests(
    history: Iterable[Mapping[str, Any]], details: Iterable[Mapping[str, Any]]
) -> tuple[PullRequest, ...]:
    """Union of light history rows and rich open-PR rows, keyed by number.

    Rich rows win: an open PR appears in both and only the detailed query carries
    checks, reviews and comments.
    """
    merged = {raw["number"]: raw for raw in history} | {raw["number"]: raw for raw in details}
    return tuple(pull_request(raw) for raw in merged.values())


def pull_request(raw: Mapping[str, Any]) -> PullRequest:
    """One :class:`PullRequest` from a ``gh pr list --json`` object."""
    return PullRequest(
        number=raw["number"],
        title=raw["title"],
        url=raw["url"],
        state=state(raw),
        branch=raw.get("headRefName", ""),
        base=raw.get("baseRefName", ""),
        created=datetime.fromisoformat(raw["createdAt"]),
        updated=datetime.fromisoformat(raw["updatedAt"]),
        closed=timestamp(raw.get("closedAt")),
        merged=timestamp(raw.get("mergedAt")),
        additions=raw.get("additions", 0),
        deletions=raw.get("deletions", 0),
        checks=checks(raw.get("statusCheckRollup") or ()),
        review=review(raw.get("reviewDecision") or ""),
        comments=len(raw.get("comments") or ()) + sum(1 for r in raw.get("reviews") or () if r.get("body")),
        conflicted=raw.get("mergeable") == "CONFLICTING",
    )


def state(raw: Mapping[str, Any]) -> State:
    match raw["state"], raw.get("isDraft", False):
        case "OPEN", True:
            return State.DRAFT
        case "OPEN", False:
            return State.OPEN
        case "MERGED", _:
            return State.MERGED
        case _:
            return State.CLOSED


_FAILED = frozenset({"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"})
_WAITING = frozenset({"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"})


def checks(rollup: Iterable[Mapping[str, Any]]) -> Checks:
    """Collapse a status-check rollup: any failure dominates, then anything unfinished.

    ``CheckRun`` entries report ``status``/``conclusion``; legacy ``StatusContext``
    entries report a single ``state``.
    """
    outcomes = {c.get("conclusion") or c.get("state") or c.get("status") or "" for c in rollup}
    if not outcomes:
        return Checks.NONE
    if outcomes & _FAILED:
        return Checks.FAILING
    if outcomes & _WAITING or "" in outcomes:
        return Checks.PENDING
    return Checks.PASSING


def review(decision: str) -> Review:
    return {
        "APPROVED": Review.APPROVED,
        "CHANGES_REQUESTED": Review.CHANGES,
        "REVIEW_REQUIRED": Review.REQUIRED,
    }.get(decision, Review.NONE)


def timestamp(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None
