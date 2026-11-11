"""Command-line entry point: resolve repo, author and config, then hand off to the app."""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

from ghb import github
from ghb.actions import Context, actions
from ghb.view import WINDOWS, View


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    config = settings(args.config)
    path = Path(args.path).resolve()
    try:
        repo = args.repo or github.repository(path)
    except github.GhError as e:
        sys.exit(f"ghb: {e}")
    view = View(
        repo=repo,
        author=args.author or config.get("author", "@me"),
        days=args.days or config.get("days", 30),
    )
    from ghb.app import Board  # deferred: textual import is the slow part of startup

    Board(view, Context(repo, path), actions(config), config.get("theme")).run()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ghb", description="An htop for your pull requests.")
    p.add_argument("path", nargs="?", default=".", help="local checkout (default: cwd)")
    p.add_argument("-R", "--repo", help="owner/name; default: inferred from PATH")
    p.add_argument("-a", "--author", help="PR author (default: @me)")
    p.add_argument("-d", "--days", type=int, choices=WINDOWS, help="statistics window")
    p.add_argument("-c", "--config", type=Path, default=config_path(), help="config file")
    return p


def settings(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text())
    except FileNotFoundError:
        return {}


def config_path() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "ghb" / "config.toml"
