"""Pure summary statistics and momentum series over a time window."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from ghb.model import Checks, PullRequest, Review, State


@dataclass(frozen=True, slots=True)
class Summary:
    opened: int
    merged: int
    closed: int
    active: int
    drafts: int
    awaiting_review: int
    failing: int
    median_merge: timedelta | None

    @property
    def merge_rate(self) -> float | None:
        """Fraction of PRs resolved in the window that were merged rather than closed."""
        resolved = self.merged + self.closed
        return self.merged / resolved if resolved else None


@dataclass(frozen=True, slots=True)
class Momentum:
    """Event counts per bucket; ``start`` is the left edge of the first bucket."""

    start: datetime
    width: timedelta
    opened: tuple[int, ...]
    merged: tuple[int, ...]
    closed: tuple[int, ...]


def summary(prs: Sequence[PullRequest], since: datetime) -> Summary:
    merged = [pr for pr in prs if pr.merged and pr.merged >= since]
    active = [pr for pr in prs if pr.active]
    return Summary(
        opened=sum(1 for pr in prs if pr.created >= since),
        merged=len(merged),
        closed=sum(1 for pr in prs if pr.state is State.CLOSED and pr.closed and pr.closed >= since),
        active=len(active),
        drafts=sum(1 for pr in active if pr.state is State.DRAFT),
        awaiting_review=sum(1 for pr in active if pr.state is State.OPEN and pr.review is Review.REQUIRED),
        failing=sum(1 for pr in active if pr.checks is Checks.FAILING),
        median_merge=median(pr.merged - pr.created for pr in merged) if merged else None,
    )


def momentum(prs: Sequence[PullRequest], since: datetime, now: datetime, buckets: int) -> Momentum:
    """Opened / merged / closed counts in ``buckets`` equal slices of ``[since, now)``."""
    width = (now - since) / buckets

    def counts(times: Iterable[datetime | None]) -> tuple[int, ...]:
        bins = [0] * buckets
        for t in times:
            if t is not None and since <= t < now:
                bins[int((t - since) / width)] += 1
        return tuple(bins)

    return Momentum(
        start=since,
        width=width,
        opened=counts(pr.created for pr in prs),
        merged=counts(pr.merged for pr in prs),
        closed=counts(pr.closed for pr in prs if pr.state is State.CLOSED),
    )


BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values: Sequence[int], scale: int | None = None) -> str:
    """Unicode sparkline; zero is the floor glyph, any positive count is at least one step up.

    ``scale`` fixes the value mapped to the tallest block, so several lines can
    share an axis.
    """
    top = scale if scale is not None else max(values, default=0)
    if top <= 0:
        return BLOCKS[0] * len(values)
    steps = len(BLOCKS) - 1
    return "".join(BLOCKS[0] if v <= 0 else BLOCKS[max(1, round(v / top * steps))] for v in values)
