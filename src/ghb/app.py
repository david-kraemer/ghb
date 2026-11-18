"""The Textual shell: holds one :class:`~ghb.view.View`, redraws from it, runs actions."""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from typing import ClassVar

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Static

from ghb import github
from ghb.actions import Action, Context
from ghb.model import PullRequest, pull_requests
from ghb.view import FILTERS, WINDOWS, View, cycled, header, layout, row, visible

DEFAULT_THEME = "ansi-dark"
"""Defer to the terminal's own 16-color palette; any Textual theme name overrides it."""


class Board(App[None]):
    CSS = """
    Screen { background: $background; }
    #header { padding: 1 2 1 2; height: auto; }
    DataTable { height: 1fr; padding: 0 1; background: $background; scrollbar-size-vertical: 1; }
    DataTable > .datatable--header { background: $background; color: $text-muted; text-style: none; }
    DataTable > .datatable--cursor { background: $boost; text-style: bold; }
    DataTable > .datatable--hover { background: $background; }
    Footer { background: $background; }

    /* ANSI themes: the terminal's palette, no truecolor and no alpha blending */
    DataTable:ansi > .datatable--header { background: ansi_default; color: ansi_default; text-style: dim; }
    DataTable:ansi > .datatable--cursor { background: ansi_default; color: ansi_default; text-style: reverse; }
    DataTable:ansi > .datatable--hover { background: ansi_default; }
    """

    BINDINGS: ClassVar = [
        Binding("q", "quit", "quit"),
        Binding("r", "refresh", "refresh"),
        Binding("w", "window", "window"),
        Binding("f", "filter", "filter"),
        Binding("j", "cursor(1)", show=False),
        Binding("k", "cursor(-1)", show=False),
    ]

    def __init__(self, view: View, context: Context, actions: tuple[Action, ...], theme: str | None) -> None:
        super().__init__()
        self.view = view
        self.context = context
        self.actions = {a.key: a for a in actions}
        self.theme = theme or DEFAULT_THEME

    def compose(self) -> ComposeResult:
        yield Static(id="header")
        yield DataTable(cursor_type="row", zebra_stripes=False, show_cursor=True)
        yield Footer(compact=True, show_command_palette=False)

    def on_mount(self) -> None:
        for action in self.actions.values():
            self.bind(action.key, f"run({action.key!r})", description=action.label)
        snap = github.cached(self.view.repo, self.view.author, self.view.days)
        self.show(self.with_snapshot(snap) if snap else self.view)
        self.set_interval(30, lambda: self.show(self.view))  # keep ages fresh
        self.fetch()

    def on_resize(self) -> None:
        if self.query(DataTable):  # resize can arrive before compose
            self.show(self.view)

    # ── state ────────────────────────────────────────────────────────────────

    def show(self, view: View) -> None:
        """Replace the state and redraw everything from it."""
        self.view = view
        now = datetime.now(UTC)
        self.query_one("#header", Static).update(header(view, now, self.size.width))
        table = self.query_one(DataTable)
        keep = self.selected()
        table.clear(columns=True)
        columns, flex = layout(self.size.width)
        for c in columns:
            table.add_column(c.name, width=c.width or flex)
        for pr in visible(view):
            table.add_row(*row(pr, now, columns, flex), key=str(pr.number))
        if keep is not None and str(keep.number) in table.rows:
            table.move_cursor(row=table.get_row_index(str(keep.number)), animate=False)

    def with_snapshot(self, snap: github.Snapshot) -> View:
        return replace(self.view, prs=pull_requests(snap.history, snap.details), fetched=snap.fetched)

    def selected(self) -> PullRequest | None:
        table = self.query_one(DataTable)
        if not table.row_count:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return next((pr for pr in self.view.prs if str(pr.number) == key), None)

    @work(exclusive=True, group="fetch")
    async def fetch(self) -> None:
        v = self.view
        self.show(replace(v, loading=True, error=None))
        try:
            snap = await github.snapshot(v.repo, v.author, v.days)
        except Exception as e:  # noqa: BLE001 — any failure is shown, never fatal
            self.show(replace(self.view, loading=False, error=str(e)))
            return
        github.save_cache(v.repo, v.author, v.days, snap)
        self.show(replace(self.with_snapshot(snap), loading=False))

    # ── commands ─────────────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        self.fetch()

    def action_window(self) -> None:
        days = cycled(WINDOWS, self.view.days)
        snap = github.cached(self.view.repo, self.view.author, days)
        self.show(replace(self.view, days=days, prs=(), fetched=None))
        if snap:
            self.show(self.with_snapshot(snap))
        self.fetch()

    def action_filter(self) -> None:
        self.show(replace(self.view, filter=cycled(FILTERS, self.view.filter)))

    def action_cursor(self, step: int) -> None:
        table = self.query_one(DataTable)
        table.move_cursor(row=table.cursor_row + step)

    @on(DataTable.RowSelected)
    def browse(self) -> None:
        self.action_run("o")

    def action_run(self, key: str) -> None:
        action, pr = self.actions.get(key), self.selected()
        if action is None or pr is None:
            return
        if not action.applies(pr):
            self.notify(f"{action.label}: not applicable to a {pr.state} PR", severity="warning")
            return
        if action.confirm:
            prompt = Text.assemble((action.label, "bold"), f" #{pr.number}  ", (pr.title, "dim"))
            self.push_screen(Confirm(prompt), lambda ok: self.execute(action, pr) if ok else None)
        else:
            self.execute(action, pr)

    def execute(self, action: Action, pr: PullRequest) -> None:
        argv = list(action.argv(pr, self.context))
        if action.mode == "suspend":
            with self.suspend():
                subprocess.run(argv, check=False, cwd=self.context.path)
            self.after(action)
        else:
            self.run_background(action, pr, argv)

    @work(group="actions")
    async def run_background(self, action: Action, pr: PullRequest, argv: list[str]) -> None:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=self.context.path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        out, _ = await proc.communicate()
        last = (out.decode().strip().splitlines() or [""])[-1]
        if proc.returncode:
            self.notify(
                last or f"exit {proc.returncode}",
                title=f"{action.label} #{pr.number} failed",
                severity="error",
            )
        else:
            self.notify(last or "done", title=f"{action.label} #{pr.number}")
            self.after(action)

    def after(self, action: Action) -> None:
        if action.refresh:
            self.fetch()


class Confirm(ModalScreen[bool]):
    CSS = """
    Confirm { align: center middle; background: $background 60%; }
    Confirm Static { width: auto; }
    Confirm > Vertical { width: auto; max-width: 80%; height: auto; padding: 1 3; border: round $primary; background: $surface; }
    Confirm:ansi { background: ansi_default; }
    """
    BINDINGS: ClassVar = [("y", "answer(True)", "yes"), ("n,escape", "answer(False)", "no")]

    def __init__(self, prompt: Text) -> None:
        super().__init__()
        self.prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.prompt)
            yield Static(
                Text.assemble("\n", ("y", "bold"), (" confirm   ", "dim"), ("n", "bold"), (" cancel", "dim"))
            )

    def action_answer(self, ok: bool) -> None:
        self.dismiss(ok)
