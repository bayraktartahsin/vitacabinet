"""The record that admits what it does not know.

Every medical record is a photograph of a moment presented as though it were
current. A GP's list is what was true in March. A hospital's is from the night
of an admission. Neither says so, and that unmarked confidence is the hazard —
not the staleness itself. A clinician who knows a list is six months old asks;
one who is handed the same list with no date acts on it.

So nothing here is stored as a bare fact. Every entry carries where it came
from and when it was last confirmed, and answers how much it should still be
believed. A cabinet is not a list of medicines; it is a set of claims of
differing and decaying strength.

The decay is deliberately crude — a straight line to zero over a horizon that
depends on the source. A pharmacy dispensing record earns a long horizon
because collecting a prescription is evidence of taking it. A box photographed
in a drawer earns a short one, because a box in a drawer is evidence that it
was bought, and nothing more. Precision here would be false: the honest claim
is "this is probably stale", not "this is 41% true".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum


class Source(Enum):
    """Where a claim came from, ordered by how long it stays believable.

    The horizon is how long, in days, before the claim decays to nothing.
    """

    PHARMACY = ("a pharmacy dispensing record", 180)
    CLINICIAN = ("a clinician's list", 120)
    PERSON = ("the person themselves", 90)
    BOX = ("a box photographed in the drawer", 60)
    INFERRED = ("inferred from other facts", 30)

    def __init__(self, description: str, horizon_days: int):
        self.description = description
        self.horizon_days = horizon_days


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Fact:
    """One claim about what somebody is taking, with its provenance."""

    subject: str                       # the drug, as we understand it
    source: Source
    confirmed_at: datetime
    rxcui: str | None = None
    detail: str = ""                   # strength, form, whatever the box said
    contested: str = ""                # set when sources disagree, says how

    @property
    def age_days(self) -> int:
        return max(0, (_now() - self.confirmed_at).days)

    @property
    def confidence(self) -> float:
        """How much of the original claim survives, 0 to 1.

        Linear to zero over the source's horizon. A contested fact is capped
        well below certain no matter how fresh it is — two sources disagreeing
        is itself evidence that neither should be acted on.
        """
        if self.contested:
            return min(0.4, self._decayed)
        return self._decayed

    @property
    def _decayed(self) -> float:
        remaining = 1.0 - (self.age_days / self.source.horizon_days)
        return round(max(0.0, min(1.0, remaining)), 2)

    @property
    def stale(self) -> bool:
        """Old enough that a person should be asked again."""
        return self.confidence < 0.5

    def why(self) -> str:
        """The sentence that should sit under this fact wherever it is shown.

        A record that shows only the drug name is making the same mistake as
        every record it is trying to improve on.
        """
        when = "today" if self.age_days == 0 else f"{self.age_days} days ago"
        base = f"from {self.source.description}, last confirmed {when}"
        if self.contested:
            return f"{base} — disputed: {self.contested}"
        if self.stale:
            return f"{base} — old enough to be worth asking about"
        return base


@dataclass
class Cabinet:
    """Everything believed about one person's medicines, and how strongly."""

    owner: str
    facts: list[Fact] = field(default_factory=list)

    def add(self, fact: Fact) -> None:
        self.facts.append(fact)

    @property
    def stale_facts(self) -> list[Fact]:
        """What the agent should go and reduce uncertainty about.

        This is the background work: not a form to fill in, but a queue of
        things worth one question each, oldest first.
        """
        return sorted((f for f in self.facts if f.stale),
                      key=lambda f: f.confidence)

    @property
    def contested_facts(self) -> list[Fact]:
        return [f for f in self.facts if f.contested]

    def summary(self) -> dict[str, object]:
        """Counts a person can check against what they can see."""
        return {
            "owner": self.owner,
            "medicines": len(self.facts),
            "confident": sum(1 for f in self.facts if not f.stale and not f.contested),
            "stale": len(self.stale_facts),
            "contested": len(self.contested_facts),
        }


def days_ago(n: int) -> datetime:
    """Readable construction for facts confirmed in the past."""
    return _now() - timedelta(days=n)
