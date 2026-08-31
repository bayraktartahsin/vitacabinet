"""The record that carries its own uncertainty.

The product's claim is that a medical record should say how much it should be
believed. These pin the behaviour that claim rests on.
"""
from __future__ import annotations

from app.cabinet import Cabinet, Fact, Source, days_ago


def test_a_fresh_fact_is_believed_and_an_old_one_is_not():
    fresh = Fact("Metformin", Source.PHARMACY, days_ago(5))
    old = Fact("Metformin", Source.PHARMACY, days_ago(175))

    assert fresh.confidence > 0.9
    assert old.confidence < 0.1
    assert not fresh.stale and old.stale


def test_the_same_age_means_less_from_a_weaker_source():
    """A pharmacy dispensing record is evidence somebody collected the drug. A
    box in a drawer is evidence somebody bought it once, which is a much weaker
    claim about what they are swallowing today."""
    age = 45
    dispensed = Fact("Metformin", Source.PHARMACY, days_ago(age))
    in_drawer = Fact("Metformin", Source.BOX, days_ago(age))

    assert dispensed.confidence > in_drawer.confidence


def test_a_contested_fact_is_never_confident_however_fresh():
    """Two sources disagreeing is itself evidence that neither should be acted
    on. A conflict found this morning is not a strong fact."""
    today = Fact("Amlodipine", Source.PHARMACY, days_ago(0),
                 contested="the cardiologist stopped this; a box is still in the drawer")
    assert today.age_days == 0
    assert today.confidence <= 0.4


def test_every_fact_can_say_where_it_came_from():
    """A record showing only a drug name repeats the mistake it exists to fix."""
    f = Fact("Ramipril", Source.CLINICIAN, days_ago(130))
    why = f.why()
    assert "clinician" in why
    assert "130 days ago" in why
    assert "worth asking about" in why


def test_the_queue_of_things_to_ask_about_is_worst_first():
    """The background job is not a form to fill in. It is a queue of things
    worth one question each, least believable first."""
    c = Cabinet(owner="test")
    c.add(Fact("fresh", Source.PHARMACY, days_ago(2)))
    c.add(Fact("middling", Source.BOX, days_ago(40)))
    c.add(Fact("ancient", Source.CLINICIAN, days_ago(200)))

    queue = [f.subject for f in c.stale_facts]
    assert "fresh" not in queue
    assert queue[0] == "ancient", "the least believable should be asked about first"


def test_summary_counts_add_up():
    c = Cabinet(owner="test")
    c.add(Fact("a", Source.PHARMACY, days_ago(1)))
    c.add(Fact("b", Source.BOX, days_ago(90)))
    c.add(Fact("c", Source.BOX, days_ago(1), contested="two sources disagree"))

    s = c.summary()
    assert s["medicines"] == 3
    assert s["confident"] == 1
    assert s["contested"] == 1
