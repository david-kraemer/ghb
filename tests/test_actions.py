from pathlib import Path

from conftest import raw

from ghb.actions import BUILTIN, Context, actions, configured_action, toggle_draft
from ghb.model import State, pull_request

CTX = Context("o/r", Path("/src/r"))


def test_config_template_and_override():
    spec = {"key": "m", "label": "nvim", "run": ["nvim", "+PRReview {number} {branch}"], "mode": "suspend"}
    merged = {a.key: a for a in actions({"actions": [spec]})}
    assert len(merged) == len(BUILTIN)  # overrides the built-in merge, adds nothing
    action = merged["m"]
    assert action.mode == "suspend"
    assert tuple(action.argv(pull_request(raw(7)), CTX)) == ("nvim", "+PRReview 7 b7")


def test_states_restrict_applicability():
    action = configured_action({"key": "z", "run": ["true"], "states": ["merged"]})
    assert action.applies(pull_request(raw(1, "MERGED", resolved_days=1)))
    assert not action.applies(pull_request(raw(1)))


def test_toggle_draft_direction():
    assert "--undo" in toggle_draft(pull_request(raw(1)), CTX)
    assert "--undo" not in toggle_draft(pull_request(raw(1, draft=True)), CTX)
    assert pull_request(raw(1, draft=True)).state is State.DRAFT
