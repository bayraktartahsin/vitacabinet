"""Recalls, against the live FDA enforcement record.

The recall feature is the one most able to cause harm. Everything here exists
to stop it frightening somebody off a medicine they need.
"""
from __future__ import annotations

import pytest

from app.tools.fda import Recall, describe, recalls


def test_only_live_recalls_are_returned_by_default():
    """Most of what openFDA holds is history — metformin has 91 records and
    two thirds are terminated. Presenting a closed 2013 recall as news teaches
    the reader to ignore the next one, which may not be closed."""
    live = recalls("metformin")
    everything = recalls("metformin", live_only=False)

    assert len(live) < len(everything), "the status filter is doing nothing"
    assert all(r.live for r in live)
    assert all(r.status == "Ongoing" for r in live)


def test_recalls_come_back_newest_first():
    live = recalls("metformin")
    dates = [r.initiated for r in live]
    assert dates == sorted(dates, reverse=True)


def test_a_combination_product_is_flagged_as_such():
    """Searching metformin returns Synjardy XR — empagliflozin *and* metformin.
    Somebody on plain metformin has not been affected, and telling them
    otherwise is a false alarm about a drug they need."""
    combo = Recall(
        ingredient="metformin",
        product="Synjardy XR Tablets (empagliflozin and metformin hydrochloride)",
        lots="", reason="", classification="Class II", status="Ongoing",
        firm="", initiated="20260612", distribution="")
    plain = Recall(
        ingredient="atorvastatin",
        product="Atorvastatin Calcium Tablets USP, 80 mg",
        lots="", reason="", classification="Class II", status="Ongoing",
        firm="", initiated="20250919", distribution="")

    assert combo.names_other_ingredients
    assert not plain.names_other_ingredients


def test_the_wording_never_claims_the_persons_medicine_was_recalled():
    """A recall is against specific lots. The only claim the data supports is
    "a batch of this product" plus "go and look at the box" — never "your
    medicine has been recalled", which is how someone stops taking something
    they need."""
    rec = Recall(
        ingredient="atorvastatin",
        product="Atorvastatin Calcium Tablets USP, 80 mg",
        lots="Lot#: 25140249, Exp. Dec. 2026",
        reason="Failed dissolution specifications",
        classification="Class II", status="Ongoing",
        firm="Ascend Laboratories, LLC", initiated="20250919",
        distribution="Nationwide")

    text = describe(rec).lower()
    assert "a batch of" in text
    assert "check the box" in text
    assert "your medicine" not in text
    assert "25140249" in text, "the lot number is the actionable part"


def test_an_unrecalled_drug_returns_nothing_rather_than_erroring():
    """openFDA answers 404 for 'nothing matched', which is good news and must
    not surface as a failure."""
    assert recalls("zzzznotadrugzzzz") == []


@pytest.mark.parametrize("ingredient", ["atorvastatin", "losartan"])
def test_every_live_recall_carries_something_to_check(ingredient):
    """A recall alert without lots, a date and a class is just alarm."""
    for r in recalls(ingredient)[:5]:
        assert r.date and r.classification and r.product
