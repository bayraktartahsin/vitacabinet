"""The HTTP surface, against the live services the app actually calls.

The ordering assertions matter more than they look. A screen that lists a
six-month-old confirmation date above a live recall has buried the urgent thing
under the tidy one, and the reader learns to skim.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.api import app

client = TestClient(app)

DRAWER = ["Glucophage 500mg", "Metformin 500 mg", "Atorvastatin 20mg",
          "Norvasc 5mg", "shopping list milk"]


def _wait(jid: str, timeout: float = 120) -> dict:
    """Poll the way the page does."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/jobs/{jid}").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(0.5)
    raise AssertionError("the job did not finish")


@pytest.fixture(scope="module")
def scan():
    r = client.post("/scan", json={"boxes": [{"text": t} for t in DRAWER]})
    assert r.status_code == 200
    jid = r.json()["job_id"]
    assert jid, "a scan must hand back a job to poll"
    job = _wait(jid)
    assert job["status"] == "done", job.get("error")
    return job


def test_a_scan_answers_at_once_and_the_trace_grows_while_it_runs():
    """API Gateway gives a request thirty seconds and two agents want more,
    so the page must be able to watch the agents think rather than wait."""
    t0 = time.time()
    jid = client.post("/scan", json={"boxes": [{"text": "Ramipril 5mg"}]}).json()["job_id"]
    assert time.time() - t0 < 2, "POST /scan must not block on the agents"
    job = _wait(jid)
    assert job["trace"] and job["trace"][0]["agent"] == "Identifier"


def test_the_brand_and_the_generic_come_back_as_one_duplicate(scan):
    dupes = [f for f in scan["result"]["findings"] if f["kind"] == "duplicate"]
    assert len(dupes) == 1
    assert set(dupes[0]["drugs"]) == {"Glucophage 500mg", "Metformin 500 mg"}


def test_nonsense_is_reported_unreadable_rather_than_named(scan):
    assert "shopping list milk" in scan["result"]["unreadable"]


def test_recall_findings_never_claim_the_persons_medicine_was_recalled(scan):
    for f in scan["result"]["findings"]:
        if f["kind"] == "recall":
            assert "a batch of" in f["detail"].lower()
            assert "your medicine" not in f["detail"].lower()
            assert "check the box" in f["detail"].lower()


def test_the_urgent_findings_come_before_the_tidy_ones(scan):
    kinds = [f["kind"] for f in scan["result"]["findings"]]
    assert kinds[0] == "duplicate"


def test_the_agents_left_a_trace_a_person_can_read(scan):
    trace = scan["result"]["trace"]
    tools = {s["tool"] for s in trace}
    assert {"identify_medicine", "find_duplicate_medicines", "check_for_recalls"} <= tools
    assert all(s["said"] for s in trace)


def test_a_kept_drawer_ages_and_remembers_what_the_watchman_found():
    d = client.post("/drawers", json={"boxes": ["Glucophage 500mg", "Metformin 500 mg"], "owner": "Mum"}).json()
    assert d["facts"] and all("confidence" in f and "why" in f for f in d["facts"])
    jid = client.post(f"/drawers/{d['id']}/check").json()["job_id"]
    job = _wait(jid)
    assert job["status"] == "done"
    after = client.get(f"/drawers/{d['id']}").json()
    assert after["last_checked"] and after["findings"]
    assert after["history"][-1]["new"] == len(after["findings"]), "everything is new the first time"
    again = _wait(client.post(f"/drawers/{d['id']}/check").json()["job_id"])
    assert again["result"]["new_since_last_check"] == [], "nothing is new the second time"


def test_confirming_a_fact_is_recorded_as_coming_from_the_person():
    d = client.post("/drawers", json={"boxes": ["Norvasc 5mg"]}).json()
    r = client.post(f"/drawers/{d['id']}/confirm", json={"subject": "Norvasc 5mg"}).json()
    fact = next(f for f in r["facts"] if f["subject"] == "Norvasc 5mg")
    assert fact["source"] == "the person themselves"


def test_a_bad_email_is_refused_before_it_reaches_sns():
    d = client.post("/drawers", json={"boxes": ["a"]}).json()
    assert client.post(f"/drawers/{d['id']}/subscribe", json={"email": "nope"}).status_code == 422


def test_a_photo_of_the_drawer_becomes_box_text():
    with open("web/sample-drawer.jpg", "rb") as fh:
        r = client.post("/read-label", files=[("images", ("drawer.jpg", fh, "image/jpeg"))])
    assert r.status_code == 200
    boxes = r.json()["boxes"]
    assert len(boxes) == 6 and any("glucophage" in b.lower() for b in boxes)


def test_an_empty_drawer_is_not_an_error():
    r = client.post("/scan", json={"boxes": []})
    assert r.status_code == 200 and r.json()["findings"] == []


def test_the_question_endpoint_answers_even_when_bedrock_is_unreachable():
    r = client.post("/question", json={
        "kind": "duplicate", "drugs": ["Glucophage 500mg", "Metformin 500 mg"],
        "detail": "both boxes resolve to the ingredient metformin"})
    assert r.status_code == 200
    body = r.json()
    if body["ok"]:
        assert "?" in body["question"] and "metformin" in body["question"].lower()
        for advice in ("you should stop", "stop taking", "throw away"):
            assert advice not in body["question"].lower()


def test_health_is_cheap_and_needs_no_network():
    h = client.get("/health").json()
    assert h["ok"] and h["store"] == "memory"


# ---------------------------------------------------------------------------
# The recording rig. These are cheap and they guard the one thing that cannot
# be fixed on the day: a demo that does not load while the camera is running.
# ---------------------------------------------------------------------------

def test_the_director_and_its_script_are_served():
    """Both pages come from this app, on one origin.

    They talk over a BroadcastChannel, which is same-origin only, so serving
    the teleprompter from anywhere else silently breaks the link between the
    words and the screen.
    """
    for path, must_contain in [
        ("/director", "director"),
        ("/autopilot.js", "SCRIPT"),
    ]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert must_contain in r.text


def test_the_architecture_image_is_served():
    """The last third of the script points at this picture."""
    r = client.get("/architecture.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert len(r.content) > 20_000


def test_the_script_fits_inside_the_five_minute_limit():
    """A submission over five minutes is disqualified, and the hold times are
    derived from the words — so a longer line silently lengthens the take. This
    recomputes the same arithmetic the director does."""
    import re
    js = (client.get("/autopilot.js")).text
    body = js[js.index("const SCRIPT = ["):js.index("/* --- plumbing")]

    total = 0.0
    for beat in re.finditer(r'\{ say: "(.*?)",.*?(?=\n\n  \{ say:|\n\];)', body, re.S):
        words = len(beat.group(1).split())
        floor = re.search(r"floor: ([\d.]+)", beat.group(0))
        total += max(float(floor.group(1)) if floor else 4.0, words / 2.4 + 1.4)

    assert 120 < total < 285, f"take is {total:.0f}s; the cap is 300s"


def test_the_pitch_covers_what_the_judges_are_told_to_look_for():
    """The rules require the pitch to cover the problem, who it is for, and why
    it matters. Easy to lose one while tightening for time."""
    js = client.get("/autopilot.js").text.lower()
    assert "cue: \"who it's for" in js
    assert "cue: \"why it matters" in js


def test_the_stage_only_obeys_the_director_that_claimed_it():
    """A BroadcastChannel reaches every tab on the origin. Without addressing,
    one click fires into every open window — six tabs, six of everything, which
    is exactly what happened the first time this was built."""
    page = client.get("/").text
    assert "m.stage !== STAGE_ID" in page, "commands are not addressed to one stage"
    assert "m.dir !== claimedBy" in page, "an unclaimed stage would still obey"


def test_the_stage_announces_itself_so_the_open_order_does_not_matter():
    """The failure this guards against looked like success: open the director
    first and it broadcasts its roll-call into an empty room, then sits on a
    stale claim showing a green 'app connected' badge while the app on screen
    does nothing at all. The stage now announces on load, and the director
    re-claims whatever answers — so reloading the app window recovers too."""
    page = client.get("/").text
    assert "\ntell('here');" in page, "the stage never announces itself on load"
    assert "m.t === 'ping'" in page, "the stage cannot answer a liveness check"

    director = client.get("/director").text
    assert "m.stage !== stage" in director, "the director will not re-claim a reloaded stage"
    assert "app lost" in director, "a dead stage would still show as connected"
