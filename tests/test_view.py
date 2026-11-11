from dataclasses import replace
from datetime import timedelta

from conftest import NOW, raw

from ghb.model import pull_request
from ghb.view import COLUMNS, MIN_TITLE, View, ago, cycled, layout, status, visible

PRS = tuple(
    map(
        pull_request,
        [
            raw(1, age_days=2),
            raw(2, draft=True, age_days=400),  # stale but active: always listed
            raw(3, "MERGED", age_days=3, resolved_days=1),
            raw(4, "MERGED", age_days=50, resolved_days=45),
            raw(5, "CLOSED", age_days=10, resolved_days=5),
        ],
    )
)
VIEW = View("o/r", "@me", days=30, prs=PRS, fetched=NOW)


def test_visible_lists_active_first_then_resolved_in_window():
    assert [pr.number for pr in visible(VIEW)] == [1, 2, 3, 5]
    assert [pr.number for pr in visible(replace(VIEW, filter="merged"))] == [3]
    assert [pr.number for pr in visible(replace(VIEW, filter="active"))] == [1, 2]


def test_status_priority():
    base = pull_request(raw(1, reviewDecision="APPROVED"))
    assert status(base).plain == "ready"
    assert status(replace(base, conflicted=True)).plain == "conflicts"


def test_layout_drops_optional_columns_on_narrow_terminals():
    wide, title = layout(200)
    assert wide == COLUMNS and title > MIN_TITLE
    narrow, title = layout(80)
    assert "±" not in {c.name for c in narrow} and title >= MIN_TITLE


def test_ago_and_cycled():
    assert ago(timedelta(minutes=5)) == "5m"
    assert ago(timedelta(days=10)) == "10d"
    assert ago(timedelta(days=21)) == "3w"
    assert cycled((7, 30, 90), 90) == 7


def test_header_sparklines_fit_the_terminal():
    from rich.console import Console

    from ghb.view import header

    console = Console(width=80, record=True)
    console.print(header(replace(VIEW, days=365), NOW, 80))
    assert "…" not in console.export_text()
