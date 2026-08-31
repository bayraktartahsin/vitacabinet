"""Drug recalls, from the FDA's public enforcement record.

This is the part of the cabinet nobody else is doing. Recalls are published
continuously and nobody telephones your mother about them; the box stays in the
drawer and she keeps taking it. An agent that already knows what is in there is
the only thing positioned to notice.

It is also the part most capable of doing harm, and the shape of the data is
why. Three things in a single record make the naive version dangerous:

    code_info      "Lot# 4260340; Exp.12/31/2025"
    status         "Terminated"
    product        "xigduo XR (dapagliflozin/metformin HCl)..."

A recall is against **specific lots**, not a medicine. It is frequently
**closed** years ago. And a text search for an ingredient matches **combination
products** the person may never have taken.

Get any of those wrong and the app tells someone their heart medication was
recalled when it was one batch, from one firm, in 2013, of a drug they do not
take — and they stop taking it. That is worse than saying nothing at all, so
none of it is left to phrasing: the type carries the lot, the status filter is
the default, and there is no method anywhere that returns "your drug is
recalled".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger("vitacabinet.fda")

_BASE = "https://api.fda.gov/drug"
_TIMEOUT = 40.0

# openFDA's own vocabulary. Only the first means "this is live".
_LIVE = "Ongoing"


class SafetyDataUnavailable(RuntimeError):
    """openFDA could not be reached.

    Its own type so the caller can say "we could not check for recalls today"
    rather than implying there were none.
    """


@dataclass
class Recall:
    """One enforcement action against specific lots of a specific product."""

    ingredient: str          # what we were searching on behalf of
    product: str             # the product actually recalled, verbatim
    lots: str                # the lot/code information — what to check the box against
    reason: str
    classification: str      # Class I is the most serious
    status: str
    firm: str
    initiated: str           # YYYYMMDD as published
    distribution: str

    @property
    def live(self) -> bool:
        return self.status == _LIVE

    @property
    def date(self) -> str:
        d = self.initiated
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d

    @property
    def names_other_ingredients(self) -> bool:
        """Is the recalled product a combination containing something else?

        A search for metformin returns Xigduo XR, which is dapagliflozin *and*
        metformin. Somebody taking plain metformin has not been affected by it,
        and telling them otherwise is a false alarm about a drug they need.
        """
        text = self.product.lower()
        marks = ("/", " and ", "+")
        return any(m in text for m in marks) and self.ingredient.lower() in text


def recalls(ingredient: str, *, live_only: bool = True, limit: int = 100) -> list[Recall]:
    """Enforcement records naming this ingredient.

    ``live_only`` defaults to True because most of what openFDA holds is
    historical: metformin has 91 records and 67 of them are terminated. A
    closed 2013 recall is not news, and presenting it as one teaches the reader
    to ignore the next alert, which may not be closed.
    """
    try:
        r = httpx.get(f"{_BASE}/enforcement.json",
                      params={"search": f'product_description:"{ingredient}"',
                              "limit": limit},
                      timeout=_TIMEOUT)
    except httpx.HTTPError as e:
        raise SafetyDataUnavailable(f"openFDA unreachable: {e}") from e

    # openFDA answers 404 for "nothing matched", which is good news here.
    if r.status_code == 404:
        return []
    if r.status_code >= 400:
        raise SafetyDataUnavailable(f"openFDA enforcement: HTTP {r.status_code}")

    out = []
    for x in r.json().get("results", []):
        rec = Recall(
            ingredient=ingredient,
            product=(x.get("product_description") or "").strip(),
            lots=(x.get("code_info") or "").strip(),
            reason=(x.get("reason_for_recall") or "").strip(),
            classification=x.get("classification") or "",
            status=x.get("status") or "",
            firm=x.get("recalling_firm") or "",
            initiated=x.get("recall_initiation_date") or "",
            distribution=x.get("distribution_pattern") or "",
        )
        if live_only and not rec.live:
            continue
        out.append(rec)

    out.sort(key=lambda r: r.initiated, reverse=True)
    log.info("recalls(%s): %d live of %d returned", ingredient, len(out),
             len(r.json().get("results", [])))
    return out


def describe(rec: Recall) -> str:
    """How to tell a person about this, without frightening them off a drug.

    Deliberately never says "your medicine has been recalled". It reports what
    was recalled, which lots, and asks them to look — because that is the only
    claim the data actually supports.
    """
    combo = (" This is a combination product; it is only relevant if that is "
             "what is in the box." if rec.names_other_ingredients else "")
    lots = f" Affected lots: {rec.lots}." if rec.lots else ""
    return (f"A batch of {rec.product} was recalled on {rec.date} by {rec.firm} "
            f"({rec.classification}). Reason: {rec.reason}{lots}{combo} "
            f"Check the box before doing anything else.")
