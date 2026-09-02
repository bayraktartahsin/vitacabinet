"""The store, on the memory backend. The DynamoDB backend exposes the same
five operations and is exercised live by the deploy check, not here."""
from __future__ import annotations

from app import store


def test_a_job_accumulates_its_trace_as_it_runs():
    j = store.new_job(["a", "b"])
    store.job_started(j)
    store.job_step(j, {"tool": "identify_medicine"})
    store.job_step(j, {"tool": "check_for_recalls"})
    store.job_said(j, "Identifier", "two boxes")
    store.job_done(j, {"findings": []})
    row = store.get_job(j)
    assert row["status"] == "done"
    assert [s["tool"] for s in row["trace"]] == ["identify_medicine", "check_for_recalls"]
    assert row["said"]["Identifier"] == "two boxes"


def test_only_what_is_new_counts_as_new():
    """The same recall showing up again tomorrow is not news. A page that
    shouts every night trains people to ignore the one that matters."""
    d = store.new_drawer(["Glucophage 500mg", "Metformin 500 mg"])
    first = store.set_findings(d["id"], [{"key": "duplicate:metformin"}], 7)
    again = store.set_findings(d["id"], [{"key": "duplicate:metformin"}], 7)
    then = store.set_findings(d["id"], [{"key": "duplicate:metformin"}, {"key": "recall:x:1"}], 7)
    assert len(first["new"]) == 1
    assert again["new"] == []
    assert [f["key"] for f in then["new"]] == ["recall:x:1"]
    assert len(store.get_drawer(d["id"])["history"]) == 3


def test_confirming_a_fact_moves_it_to_the_person_and_resets_its_age():
    d = store.new_drawer(["Norvasc 5mg"])
    row = store.confirm_fact(d["id"], "Norvasc 5mg")
    fact = next(f for f in row["facts"] if f["subject"] == "Norvasc 5mg")
    assert fact["source"] == "PERSON"


def test_subscribers_are_not_duplicated():
    d = store.new_drawer(["a"])
    store.add_subscriber(d["id"], "x@y.z")
    store.add_subscriber(d["id"], "x@y.z")
    assert store.get_drawer(d["id"])["subscribers"] == ["x@y.z"]
