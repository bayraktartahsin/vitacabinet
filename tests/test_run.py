"""The agents actually reading a drawer, against the live models and APIs.

This is the request path a judge exercises, so it is tested as one: the
Identifier's tool calls, the Watchman's tool calls, the trace they leave, and
the findings assembled from the ledger rather than from anybody's prose.
"""
from __future__ import annotations

import pytest

from app.agents.run import read_drawer

BOXES = ["Glucophage 500mg", "Metformin 500 mg", "Norvasc 5mg", "shopping list milk"]


@pytest.fixture(scope="module")
def reading():
    steps = []
    said = {}
    result = read_drawer(BOXES, on_step=steps.append, say=lambda a, t: said.__setitem__(a, t))
    return result, steps, said


def test_the_identifier_reads_every_box_through_its_tool(reading):
    result, steps, _ = reading
    asked = {s["input"]["box_text"] for s in steps
             if s["agent"] == "Identifier" and s["tool"] == "identify_medicine"}
    assert asked == set(BOXES), "a box was not read through the agent's tool"


def test_the_watchman_checks_every_ingredient_through_its_tool(reading):
    result, steps, _ = reading
    checked = {s["input"]["ingredient"].lower() for s in steps if s["tool"] == "check_for_recalls"}
    assert checked == set(result["ingredients_checked"])
    assert "metformin" in checked and "amlodipine" in checked


def test_the_trace_is_streamed_as_it_happens_not_dumped_at_the_end(reading):
    result, steps, _ = reading
    assert len(steps) == len(result["trace"]) >= 6
    ats = [s["at"] for s in steps]
    assert ats == sorted(ats)
    assert all(s["ms"] >= 0 for s in steps)


def test_findings_come_from_the_ledger_and_the_duplicate_survives(reading):
    """Nova rewrote the box texts into normalised names on the way into
    find_duplicate_medicines and the pair vanished. The ledger is the truth."""
    result, _, _ = reading
    dupes = [f for f in result["findings"] if f["kind"] == "duplicate"]
    assert len(dupes) == 1
    assert set(dupes[0]["drugs"]) == {"Glucophage 500mg", "Metformin 500 mg"}
    assert result["findings"][0]["kind"] == "duplicate", "a double dose goes first"


def test_nonsense_is_unreadable_never_named(reading):
    result, _, _ = reading
    assert result["unreadable"] == ["shopping list milk"]


def test_each_agent_reports_in_plain_words_without_showing_its_working(reading):
    _, _, said = reading
    assert set(said) == {"Identifier", "Watchman"}
    for text in said.values():
        assert text and "<thinking>" not in text
        for advice in ("you should stop", "stop taking", "throw away"):
            assert advice not in text.lower()


def test_every_finding_carries_a_key_so_tomorrow_can_tell_what_is_new(reading):
    result, _, _ = reading
    assert all(f.get("key") for f in result["findings"])
