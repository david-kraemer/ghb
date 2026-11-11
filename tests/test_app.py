"""Smoke test of the Textual shell with ``gh`` stubbed out."""

from pathlib import Path

import pytest
from conftest import NOW, raw
from textual.widgets import DataTable

from ghb import github
from ghb.actions import BUILTIN, Context
from ghb.app import Board, Confirm
from ghb.view import View


@pytest.fixture
def board(monkeypatch: pytest.MonkeyPatch) -> Board:
    async def snapshot(repo: str, author: str, days: int) -> github.Snapshot:
        return github.Snapshot([raw(1), raw(2, "MERGED", resolved_days=1)], [raw(1)], NOW)

    monkeypatch.setattr(github, "snapshot", snapshot)
    monkeypatch.setattr(github, "cached", lambda *a: None)
    monkeypatch.setattr(github, "save_cache", lambda *a: None)
    return Board(View("o/r", "@me"), Context("o/r", Path(".")), BUILTIN, None)


async def test_loads_filters_and_confirms(board: Board):
    async with board.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        assert board.query_one(DataTable).row_count == 2
        await pilot.press("f")  # → active
        assert board.query_one(DataTable).row_count == 1
        await pilot.press("x")  # close asks first
        assert isinstance(board.screen, Confirm)
        await pilot.press("n")
        assert not isinstance(board.screen, Confirm)
