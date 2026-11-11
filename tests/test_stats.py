from datetime import timedelta

from conftest import NOW, raw

from ghb.model import pull_request
from ghb.stats import momentum, sparkline, summary

PRS = tuple(
    map(
        pull_request,
        [
            raw(1, age_days=2),
            raw(2, draft=True, age_days=40),
            raw(3, "MERGED", age_days=3, resolved_days=1),
            raw(4, "MERGED", age_days=50, resolved_days=45),  # outside a 30d window
            raw(5, "CLOSED", age_days=10, resolved_days=5),
        ],
    )
)


def test_summary_counts_flow_in_window_and_stock_overall():
    s = summary(PRS, NOW - timedelta(days=30))
    assert (s.opened, s.merged, s.closed) == (3, 1, 1)
    assert (s.active, s.drafts) == (2, 1)
    assert s.merge_rate == 0.5
    assert s.median_merge == timedelta(days=2)


def test_momentum_buckets_partition_the_window():
    m = momentum(PRS, NOW - timedelta(days=30), NOW, 30)
    assert sum(m.opened) == 3 and sum(m.merged) == 1 and sum(m.closed) == 1
    assert m.merged[29] == 1  # merged exactly 1d ago → left edge of the last bucket [now-1d, now)


def test_sparkline_floor_and_shared_scale():
    assert sparkline([0, 0]) == "▁▁"
    assert sparkline([0, 1, 8]) == "▁▂█"
    assert sparkline([1], scale=8) == "▂"  # nonzero never renders as the floor
    assert sparkline([8], scale=8) == "█"
