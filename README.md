# ghb

An htop for your pull requests. One screen, one repo: what's open, what each
PR is waiting on, and how fast work is moving.

```
ghb  acme/widgets  ·  @me  ·  30d window  ·  all                    fetched 4s ago

opened  41 ▂▁▂▁▁▁▁▁▃▂▂▁▁▇▄▅▂▃▁▁▂▅▂▃▃▁▁▄▇█   active         9 needs review  3
merged  33 ▂▁▂▁▁▁▁▂▂▃▂▁▁▂▃▆▂▂▁▁▂▂▂▂▃▁▁▆▄▇   draft          4 ci failing    1
closed   5 ▁▁▁▁▁▁▁▁▁▁▁▁▁▂▁▄▂▂▁▁▁▂▁▂▁▁▁▂▂▁   merged %     87% to merge    14h

   #     title                                  ci  status        cmt  age   idle        ±
●  812   fix(parser): reject trailing commas…   ✗   ci failing      2  1d    7m     +41 −12
●  809   feat(cli): add --json output           ✓   needs review       2d    3h    +220 −18
◌  811   refactor(io): single read path…            conflicts          1d    5h    +373 −41
●  804   docs: clarify retry semantics          ✓   ready           4  4d    1d      +31 −4
◆  806   perf(index): skip unchanged shards           merged             3d    2d      +88 −12
q quit  r refresh  w window  f filter  o browse  v view  d diff  c checkout  t draft/ready  m merge …
```

## Install

Requires [`gh`](https://cli.github.com) (authenticated) and [`uv`](https://docs.astral.sh/uv/).

```sh
uv tool install /path/to/ghb          # or: uv tool install --editable /path/to/ghb
ghb                                   # PRs by you in the repo at cwd
ghb ~/src/other -d 90                 # another checkout, 90-day window
ghb -R owner/name -a someone          # any repo, any author
```

## Reading the screen

**Header, left — flow.** PRs opened / merged / closed (without merge) inside the
window, each with a momentum sparkline: the window split into equal buckets
(7d → 12h, 30d → 1d, 90d → 2d, 365d → 1w, coarser if the terminal is narrow), all three lines on a shared scale so
heights compare across rows.

**Header, right — stock.** Active (open + draft) right now, drafts, open PRs
awaiting review, PRs with failing CI; merge rate (merged ÷ resolved in window)
and median creation-to-merge time.

**List.** All active PRs, however old, then PRs resolved inside the window.
Glyphs: `●` open, `◌` draft, `◆` merged, `×` closed. CI: `✓` `✗` `◷`.
`status` is the single most pressing thing the PR is waiting on, in priority
order: *conflicts → ci failing → draft → changes req → ci running → needs
review → ready*. `idle` is time since last update (or since resolution).
Narrow terminals drop `±`, `age`, `cmt`, `ci` in that order.

## Keys

| key | action | | key | action |
|---|---|---|---|---|
| `↑↓` `jk` | move | | `o` `⏎` | open in browser |
| `f` | filter: all / active / merged / closed | | `v` | view with comments (pager) |
| `w` | window: 7 / 30 / 90 / 365 days | | `d` | diff (pager) |
| `r` | refresh | | `c` | `gh pr checkout` |
| `q` | quit | | `t` | toggle draft ⇄ ready |
| | | | `m` | squash-merge (confirms) |
| | | | `x` | close (confirms) |
| | | | `u` | reopen |

Actions that don't apply to the selected PR's state (merging a draft, reopening
a merged PR) are refused with a toast instead of failing in `gh`.

## Configuration

`$XDG_CONFIG_HOME/ghb/config.toml` (default `~/.config/ghb/config.toml`).
See [`examples/config.toml`](examples/config.toml).

```toml
author = "@me"
days = 30
theme = "nord"   # any Textual theme; default "ansi-dark" uses the terminal's palette

[[actions]]
key = "n"
label = "nvim"
run = ["nvim", "-c", "PRReview {number}"]   # templates: number url title branch base repo path
mode = "suspend"                            # give the command the terminal
states = ["open", "draft"]
```

## Extending

Every action — built-in, configured, or plugin — is the same record: a key, a
label, and a pure function `(PullRequest, Context) -> argv`, plus how to run it
(`background` with output as a toast, or `suspend` to hand over the terminal)
and whether to confirm or refresh. Sources layer by key:
**built-ins < plugins < config**, so any of them can replace a built-in.

**TOML** covers anything expressible as a templated command line. Use it first.

**Plugins** are for when building the command needs code. Any installed package
exposing an `ghb.actions` entry point that yields an `Action` (or an iterable of
them) is picked up. [`examples/ghb-nvim`](examples/ghb-nvim) is a complete one:

```toml
# pyproject.toml of your plugin
[project.entry-points."ghb.actions"]
nvim = "ghb_nvim:actions"
```

```python
from ghb.actions import ACTIVE, Action

def review(pr, ctx):
    return ("nvim", "-c", f"lua require('prview').open({pr.number})")

actions = (Action("n", "nvim", review, mode="suspend", states=ACTIVE),)
```

Install it into ghb's tool environment:

```sh
uv tool install --editable /path/to/ghb --with-editable /path/to/ghb-nvim
```

## Design

State is one frozen `View`; every keypress produces a new one with
`dataclasses.replace`, and every widget is redrawn from it by pure functions.
Side effects live at the edges.

| module | role | pure? |
|---|---|---|
| `model.py` | frozen `PullRequest` + parsing `gh` JSON | yes |
| `stats.py` | summary statistics, momentum buckets, sparklines | yes |
| `view.py` | `View` state, filtering, ordering, column layout, rendering | yes |
| `actions.py` | `Action` record, built-ins, config + plugin loading | yes, except entry-point discovery |
| `github.py` | `gh` subprocess calls and the disk cache | no |
| `app.py` | Textual shell: holds the `View`, dispatches keys, runs commands | no |
| `cli.py` | argument and config parsing | no |

**Fetching.** Two concurrent `gh pr list` calls: a light one over every PR
updated in the window (`updated:>=` bounds it — anything opened, merged or
closed in the window was updated in it), and a detailed one (checks, reviews,
comments, mergeability) over open PRs only. Large repos take 5–25 s, so the last
snapshot per (repo, author, window) is cached under `$XDG_CACHE_HOME/ghb/` and
shown instantly while the refresh runs.

## Development

```sh
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
```
