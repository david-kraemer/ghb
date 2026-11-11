"""The whole UI state as one immutable value, and pure renderings of it.

The app holds exactly one :class:`View`; every event produces a new one via
:func:`dataclasses.replace`, and every widget is redrawn from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from ghb.model import Checks, PullRequest, Review, State
from ghb.stats import Momentum, Summary, momentum, sparkline, summary

type Filter = Literal["all", "active", "merged", "closed"]

FILTERS: tuple[Filter, ...] = ("all", "active", "merged", "closed")
WINDOWS: tuple[int, ...] = (7, 30, 90, 365)
BUCKETS: dict[int, int] = {7: 14, 30: 30, 90: 45, 365: 52}


@dataclass(frozen=True, slots=True)
class View:
    repo: str
    author: str
    days: int = 30
    filter: Filter = "all"
    prs: tuple[PullRequest, ...] = ()
    fetched: datetime | None = None
    loading: bool = False
    error: str | None = None

    @property
    def since(self) -> datetime:
        return (self.fetched or datetime.now(UTC)) - timedelta(days=self.days)


def cycled[T](options: tuple[T, ...], current: T) -> T:
    return options[(options.index(current) + 1) % len(options)]


# ── list ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    width: int
    drop: int = 0
    """Order in which the column is sacrificed on narrow terminals; 0 never drops."""


COLUMNS: tuple[Column, ...] = (
    Column("", 1),
    Column("#", 5),
    Column("title", 0),
    Column("ci", 2, drop=4),
    Column("status", 12),
    Column("cmt", 3, drop=3),
    Column("age", 4, drop=2),
    Column("idle", 4),
    Column("±", 11, drop=1),
)
"""Width 0 is the flexible title column."""

MIN_TITLE = 30
CELL_PADDING = 2
CHROME = 3  # table padding plus scrollbar


def layout(total: int) -> tuple[tuple[Column, ...], int]:
    """Columns that fit in ``total`` cells, and the width left for the title.

    Optional columns go, in ``drop`` order, until the title gets ``MIN_TITLE``.
    """

    def title_width(cols: tuple[Column, ...]) -> int:
        return total - CHROME - sum(c.width + CELL_PADDING for c in cols)

    cols = COLUMNS
    for victim in sorted((c for c in COLUMNS if c.drop), key=lambda c: c.drop):
        if title_width(cols) >= MIN_TITLE:
            break
        cols = tuple(c for c in cols if c is not victim)
    return cols, max(title_width(cols), 10)


def visible(view: View) -> tuple[PullRequest, ...]:
    """PRs to list: all active ones, plus those resolved inside the window.

    Active first (most recently touched on top), then resolved (most recent first).
    """
    since = view.since

    def shown(pr: PullRequest) -> bool:
        if pr.active:
            return view.filter in ("all", "active")
        resolved = pr.merged or pr.closed
        in_window = resolved is not None and resolved >= since
        return in_window and view.filter in ("all", pr.state.value)

    def order(pr: PullRequest) -> tuple[bool, float]:
        when = pr.updated if pr.active else (pr.merged or pr.closed or pr.updated)
        return (not pr.active, -when.timestamp())

    return tuple(sorted(filter(shown, view.prs), key=order))


GLYPH: dict[State, Text] = {
    State.OPEN: Text("●", "green"),
    State.DRAFT: Text("◌", "dim"),
    State.MERGED: Text("◆", "magenta"),
    State.CLOSED: Text("×", "red"),
}

CI: dict[Checks, Text] = {
    Checks.NONE: Text(""),
    Checks.PASSING: Text("✓", "green"),
    Checks.FAILING: Text("✗", "bold red"),
    Checks.PENDING: Text("◷", "yellow"),
}


def status(pr: PullRequest) -> Text:
    """The single most pressing thing this PR is waiting on."""
    match pr:
        case PullRequest(state=State.MERGED):
            return Text("merged", "magenta dim")
        case PullRequest(state=State.CLOSED):
            return Text("closed", "red dim")
        case PullRequest(conflicted=True):
            return Text("conflicts", "bold red")
        case PullRequest(checks=Checks.FAILING):
            return Text("ci failing", "red")
        case PullRequest(state=State.DRAFT):
            return Text("draft", "dim")
        case PullRequest(review=Review.CHANGES):
            return Text("changes req", "yellow")
        case PullRequest(checks=Checks.PENDING):
            return Text("ci running", "yellow dim")
        case PullRequest(review=Review.REQUIRED):
            return Text("needs review", "cyan")
        case PullRequest(review=Review.APPROVED):
            return Text("ready", "bold green")
        case _:
            return Text("open", "green dim")


def row(pr: PullRequest, now: datetime, columns: tuple[Column, ...], title_width: int) -> tuple[Text, ...]:
    resolved = pr.merged or pr.closed
    cells = {
        "": GLYPH[pr.state],
        "#": Text(str(pr.number), "dim"),
        "title": Text(truncated(pr.title, title_width), "" if pr.active else "dim"),
        "ci": CI[pr.checks] if pr.active else Text(""),
        "status": status(pr),
        "cmt": Text(str(pr.comments) if pr.comments else "", "dim", justify="right"),
        "age": Text(ago(now - pr.created), "dim"),
        "idle": Text(ago(now - (resolved or pr.updated)), "dim"),
        "±": Text.assemble(
            (f"+{pr.additions}", "green dim"), " ", (f"−{pr.deletions}", "red dim"), justify="right"
        ),
    }
    return tuple(cells[c.name] for c in columns)


# ── header ────────────────────────────────────────────────────────────────────


METER_CHROME = 50
"""Header cells that are not sparkline: padding, labels, totals and the stock column."""


def header(view: View, now: datetime, width: int) -> RenderableType:
    """Title line plus meters; sparklines get as many buckets as ``width`` affords, up to ``BUCKETS``."""
    since = view.since
    buckets = max(min(BUCKETS.get(view.days, 30), width - METER_CHROME), 8)
    s = summary(view.prs, since)
    m = momentum(view.prs, since, view.fetched or now, buckets)
    return Group(title_line(view, now), Text(""), meters(s, m))


def title_line(view: View, now: datetime) -> Table:
    left = Text.assemble(
        ("ghb", "bold"),
        "  ",
        view.repo,
        ("  ·  ", "dim"),
        view.author,
        ("  ·  ", "dim"),
        (f"{view.days}d", "bold"),
        (" window", "dim"),
        ("  ·  ", "dim"),
        (view.filter, "bold"),
    )
    if view.error:
        right = Text(view.error.splitlines()[0], "red")
    elif view.loading:
        right = Text("fetching…", "yellow dim")
    elif view.fetched:
        right = Text(f"fetched {ago(now - view.fetched)} ago", "dim")
    else:
        right = Text("")
    grid = Table.grid(expand=True)
    grid.add_column()
    grid.add_column(justify="right")
    grid.add_row(left, right)
    return grid


def meters(s: Summary, m: Momentum) -> Table:
    """Flow on the left (counts in window + momentum on a shared scale), stock on the right."""
    scale = max((*m.opened, *m.merged, *m.closed), default=0)
    flow = (
        ("opened", s.opened, m.opened, "green"),
        ("merged", s.merged, m.merged, "magenta"),
        ("closed", s.closed, m.closed, "red"),
    )
    stock = (
        (("active", str(s.active), ""), ("needs review", str(s.awaiting_review), "cyan")),
        (("draft", str(s.drafts), ""), ("ci failing", str(s.failing), "red")),
        (
            ("merged %", f"{s.merge_rate:.0%}" if s.merge_rate is not None else "—", ""),
            ("to merge", ago(s.median_merge) if s.median_merge else "—", ""),
        ),
    )
    grid = Table.grid(padding=(0, 1))
    for justify in ("left", "right", "left", "left", "right", "left", "right"):
        grid.add_column(justify=justify)
    for (label, total, series, style), ((l1, v1, s1), (l2, v2, s2)) in zip(flow, stock, strict=True):
        grid.add_row(
            Text(label, "dim"),
            Text(str(total), "bold"),
            Text(sparkline(series, scale) + "    ", style),
            Text(l1, "dim"),
            Text(v1, "bold") + Text("    "),
            Text(l2, "dim"),
            Text(v2, f"bold {s2}" if v2 not in ("0", "—") else "bold"),
        )
    return grid


# ── formatting ────────────────────────────────────────────────────────────────


def ago(delta: timedelta) -> str:
    """Compact age: ``42s 7m 5h 3d 2w 4mo 1y``."""
    s = max(delta.total_seconds(), 0)
    for unit, size in (
        ("y", 31_536_000),
        ("mo", 2_592_000),
        ("w", 604_800),
        ("d", 86_400),
        ("h", 3_600),
        ("m", 60),
    ):
        if s >= size * (2 if unit in ("y", "mo", "w") else 1):
            return f"{int(s // size)}{unit}"
    return f"{int(s)}s"


def truncated(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(width - 1, 0)] + "…"
