"""Drug identity against the real RxNav service.

These call the live NIH API rather than a fixture, on purpose. The whole claim
of this project is that its findings are checkable by anyone — a test suite
that passes against a recorded response proves the recording, not the claim.
They are slow and they need a network, which is the honest cost.
"""
from __future__ import annotations

import pytest

from app.tools.rxnorm import find_duplicates, identify


@pytest.mark.parametrize("text", [
    "Metformin 500 mg",
    "Glucophage 500mg",     # brand + strength: the case that first failed
    "Norvasc 5mg",          # brand + strength, no space
    "Atorvastatin 20mg",
])
def test_box_text_resolves_to_a_drug(text):
    """Text arrives through a camera, not a keyboard.

    A strength glued to a brand name defeated the exact lookup while sailing
    through on generics — backwards for a cabinet, where the branded box is the
    one most likely to be hiding a duplicate.
    """
    drug = identify(text)
    assert drug.identified, f"{text!r} did not resolve to a drug"
    assert drug.rxcui and drug.ingredients


def test_a_brand_and_its_generic_are_recognised_as_one_medicine():
    """The finding the product exists for.

    A hospital sends someone home on the brand, a GP repeats the generic, and
    the person takes both because the boxes look nothing alike.
    """
    brand, generic = identify("Glucophage 500mg"), identify("Metformin 500 mg")
    dupes = find_duplicates([brand, generic])

    assert len(dupes) == 1
    _, _, ingredient = dupes[0]
    assert ingredient.lower() == "metformin"


def test_different_medicines_are_not_flagged():
    """A duplicate warning that fires on unrelated drugs would train the reader
    to ignore all of them, which is worse than saying nothing."""
    drugs = [identify(x) for x in
             ["Atorvastatin 20mg", "Ramipril 5mg", "Aspirin 75mg"]]
    assert find_duplicates(drugs) == []


def test_an_unreadable_box_is_left_unidentified_rather_than_guessed():
    """Better to report a box we could not read than to name it wrongly — a
    wrong name here becomes a wrong duplicate warning, or a missed one."""
    drug = identify("qqqzzz not a medicine 12345")
    assert not drug.identified


@pytest.mark.parametrize("junk", [
    "qqqzzz not a medicine 12345",   # RxNav answers this with "bisphenol A"
    "shopping list milk",            # scores 11.8 — above a real Atorvastatin box
    "hello world",
])
def test_nonsense_is_never_named_as_a_medicine(junk):
    """RxNav's fuzzy matcher always answers, and its score does not separate a
    real drug from nonsense — "shopping list milk" outscored "Atorvastatin
    20mg". A wrong name is worse than a blank row: it becomes a duplicate
    warning about a drug that is not in the drawer, or a recall alert for
    someone who never took the thing."""
    assert not identify(junk).identified
