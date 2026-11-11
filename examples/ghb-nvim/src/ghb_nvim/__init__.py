"""Example ghb plugin: hand the selected PR to a Neovim PR viewer.

Replace ``VIEWER`` with whatever your viewer exposes. The argv function is plain
Python, so it can do anything a TOML template cannot: pick a worktree, export
environment, branch on PR state, and so on.
"""

from collections.abc import Sequence

from ghb.actions import ACTIVE, Action, Context
from ghb.model import PullRequest

VIEWER = "lua require('prview').open({number})"  # ← your viewer's entry point


def review(pr: PullRequest, ctx: Context) -> Sequence[str]:
    return ("nvim", "-c", VIEWER.format(number=pr.number, branch=pr.branch, repo=ctx.repo))


actions = (Action("n", "nvim", review, mode="suspend", states=ACTIVE),)
