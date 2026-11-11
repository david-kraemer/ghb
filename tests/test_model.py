from conftest import raw

from ghb.model import Checks, Review, State, checks, pull_request, pull_requests


def test_state_distinguishes_draft():
    assert pull_request(raw(1, draft=True)).state is State.DRAFT
    assert pull_request(raw(1)).state is State.OPEN
    assert pull_request(raw(1, "MERGED", resolved_days=1)).state is State.MERGED
    assert pull_request(raw(1, "CLOSED", resolved_days=1)).state is State.CLOSED


def test_checks_failure_dominates_pending_dominates_success():
    run = lambda status, conclusion="": {"status": status, "conclusion": conclusion}
    assert checks([]) is Checks.NONE
    assert checks([run("COMPLETED", "SUCCESS"), run("COMPLETED", "SKIPPED")]) is Checks.PASSING
    assert checks([run("COMPLETED", "SUCCESS"), run("IN_PROGRESS")]) is Checks.PENDING
    assert checks([run("IN_PROGRESS"), run("COMPLETED", "FAILURE")]) is Checks.FAILING
    assert checks([{"state": "ERROR"}]) is Checks.FAILING


def test_details_override_history_and_count_comments():
    history = [raw(1), raw(2, "MERGED", resolved_days=1)]
    details = [raw(1, reviewDecision="APPROVED", comments=[{}, {}], reviews=[{"body": "lgtm"}, {"body": ""}])]
    prs = {pr.number: pr for pr in pull_requests(history, details)}
    assert prs[1].review is Review.APPROVED
    assert prs[1].comments == 3
    assert prs[2].review is Review.NONE
