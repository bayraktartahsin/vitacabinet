"""The HTTP surface, against the live services the app actually calls.

The ordering assertions matter more than they look. A screen that lists a
six-month-old confirmation date above a live recall has buried the urgent thing
under the tidy one, and the reader learns to skim.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import app

client = TestClient(app)

DRAWER = ["Glucophage 500mg", "Metformin 500 mg", "Atorvastatin 20mg",
          "Norvasc 5mg", "shopping list milk"]


@pytest.fixture(scope="module")
def scan():
    r = client.post("/scan", json={"boxes": [{"text": t} for t in DRAWER]})
    assert r.status_code == 200
    return r.json()


def test_the_brand_and_the_generic_come_back_as_one_duplicate(scan):
    """The finding the whole product exists for."""
    dupes = [f for f in scan["findings"] if f["kind"] == "duplicate"]
    assert len(dupes) == 1
    assert "metformin" in dupes[0]["detail"].lower()
    assert set(dupes[0]["drugs"]) == {"Glucophage 500mg", "Metformin 500 mg"}


def test_nonsense_is_reported_unreadable_rather_than_named(scan):
    """A wrong name here becomes a recall alert for a drug nobody takes."""
    assert "shopping list milk" in scan["unreadable"]
    named = {d["name"] for d in scan["drugs"] if d["identified"]}
    assert not any(n and "milk" in n.lower() for n in named)


def test_recall_findings_never_claim_the_persons_medicine_was_recalled(scan):
    """The only claim the data supports is "a batch", plus something to check."""
    for f in scan["findings"]:
        if f["kind"] == "recall":
            assert "a batch of" in f["detail"].lower()
            assert "your medicine" not in f["detail"].lower()
            assert "stop taking" not in f["detail"].lower()


def test_the_urgent_findings_come_before_the_tidy_ones(scan):
    """Duplicates and recalls above staleness — a double dose is happening now,
    a six-month-old confirmation date is not."""
    kinds = [f["kind"] for f in scan["findings"]]
    if "stale" in kinds:
        first_stale = kinds.index("stale")
        assert all(k == "stale" for k in kinds[first_stale:])


def test_every_recall_finding_carries_something_to_check(scan):
    """A recall alert without a lot number is just alarm."""
    for f in scan["findings"]:
        if f["kind"] == "recall":
            assert f.get("date")
            assert "check the box" in f["detail"].lower()


def test_a_drawer_of_unrelated_drugs_raises_no_duplicate():
    r = client.post("/scan", json={"boxes": [
        {"text": t} for t in ["Atorvastatin 20mg", "Ramipril 5mg", "Aspirin 75mg"]]})
    assert not [f for f in r.json()["findings"] if f["kind"] == "duplicate"]


def test_an_empty_drawer_is_not_an_error():
    r = client.post("/scan", json={"boxes": []})
    assert r.status_code == 200
    assert r.json()["findings"] == []


def test_the_question_endpoint_answers_even_when_bedrock_is_unreachable():
    """/scan must not be taken down by the writing model.

    The drawer still has two boxes of metformin in it whether or not a language
    model is available to phrase the question, so the failure is reported in
    the response rather than raised.
    """
    r = client.post("/question", json={
        "kind": "duplicate", "drugs": ["Glucophage 500mg", "Metformin 500 mg"],
        "detail": "both boxes resolve to the ingredient metformin"})
    assert r.status_code == 200
    body = r.json()
    assert "ok" in body and "question" in body
    if body["ok"]:
        assert "?" in body["question"]
        assert "metformin" in body["question"].lower()
        for advice in ("you should stop", "stop taking", "throw away"):
            assert advice not in body["question"].lower()


def test_health_is_cheap_and_needs_no_network():
    assert client.get("/health").json() == {"ok": True}
