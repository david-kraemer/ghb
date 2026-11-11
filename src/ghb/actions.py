"""Actions: a keybinding that turns the selected PR into a command line.

Built-ins, ``config.toml`` entries and installed plugins all produce the same
:class:`Action` record, so the UI needs exactly one way to run them. Later
sources override earlier ones key-by-key: built-ins < plugins < config.

A plugin is any installed distribution exposing an entry point in the
``ghb.actions`` group whose value is an :class:`Action` or an iterable of them::

    [project.entry-points."ghb.actions"]
    review = "my_ghb_ext:actions"
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Literal

from ghb.model import ACTIVE, PullRequest, State

type Mode = Literal["background", "suspend"]


@dataclass(frozen=True, slots=True)
class Context:
    """Where the PR lives: ``owner/name`` and the local checkout (cwd for commands)."""

    repo: str
    path: Path


@dataclass(frozen=True, slots=True)
class Action:
    """A key, a label, and a pure function from (PR, context) to argv.

    ``mode`` is ``"suspend"`` for anything that wants the terminal (editors,
    pagers) and ``"background"`` otherwise. ``refresh`` re-fetches afterwards,
    for actions that change PR state.
    """

    key: str
    label: str
    argv: Callable[[PullRequest, Context], Sequence[str]]
    mode: Mode = "background"
    confirm: bool = False
    refresh: bool = False
    states: frozenset[State] = frozenset(State)

    def applies(self, pr: PullRequest) -> bool:
        return pr.state in self.states


def gh(*args: str) -> Callable[[PullRequest, Context], Sequence[str]]:
    """``gh pr <args> <number> -R <repo>``."""
    return lambda pr, ctx: ("gh", "pr", *args, str(pr.number), "-R", ctx.repo)


def toggle_draft(pr: PullRequest, ctx: Context) -> Sequence[str]:
    undo = ("--undo",) if pr.state is State.OPEN else ()
    return ("gh", "pr", "ready", str(pr.number), "-R", ctx.repo, *undo)


BUILTIN: tuple[Action, ...] = (
    Action("o", "browse", gh("view", "--web")),
    Action(
        "v",
        "view",
        lambda pr, ctx: (
            "sh",
            "-c",
            f"gh pr view {pr.number} -R {ctx.repo} --comments | ${{PAGER:-less -R}}",
        ),
        mode="suspend",
    ),
    Action(
        "d",
        "diff",
        lambda pr, ctx: ("sh", "-c", f"gh pr diff {pr.number} -R {ctx.repo} | ${{PAGER:-less -R}}"),
        mode="suspend",
    ),
    Action("c", "checkout", lambda pr, ctx: ("gh", "pr", "checkout", str(pr.number)), states=ACTIVE),
    Action("t", "draft/ready", toggle_draft, refresh=True, states=ACTIVE),
    Action("m", "merge", gh("merge", "--squash"), confirm=True, refresh=True, states=frozenset({State.OPEN})),
    Action("x", "close", gh("close"), confirm=True, refresh=True, states=ACTIVE),
    Action("u", "reopen", gh("reopen"), refresh=True, states=frozenset({State.CLOSED})),
)


def actions(config: Mapping[str, Any]) -> tuple[Action, ...]:
    """Every action in effect, deduplicated by key with later sources winning."""
    layered = [*BUILTIN, *plugin_actions(), *map(configured_action, config.get("actions", ()))]
    return tuple({a.key: a for a in layered}.values())


def configured_action(spec: Mapping[str, Any]) -> Action:
    """An :class:`Action` from a ``[[actions]]`` table.

    ``run`` is an argv list whose items are ``str.format`` templates over
    ``number url title branch base repo path``.
    """
    template: list[str] = list(spec["run"])

    def argv(pr: PullRequest, ctx: Context) -> Sequence[str]:
        fields = {
            "number": pr.number,
            "url": pr.url,
            "title": pr.title,
            "branch": pr.branch,
            "base": pr.base,
            "repo": ctx.repo,
            "path": ctx.path,
        }
        return tuple(part.format_map(fields) for part in template)

    return Action(
        key=spec["key"],
        label=spec.get("label", spec["key"]),
        argv=argv,
        mode=spec.get("mode", "background"),
        confirm=spec.get("confirm", False),
        refresh=spec.get("refresh", False),
        states=frozenset(State(s) for s in spec.get("states", State)),
    )


def plugin_actions() -> list[Action]:
    found: list[Action] = []
    for ep in entry_points(group="ghb.actions"):
        value = ep.load()
        found.extend([value] if isinstance(value, Action) else value)
    return found


def keymap(actions: Iterable[Action]) -> dict[str, Action]:
    return {a.key: a for a in actions}
