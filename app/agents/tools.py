"""The tools the agents are allowed to use.

Which agent gets which tool is the safety model of this system, so the tools
live together where the split is visible in one file.

The Scribe — the agent that writes what to ask a clinician — is deliberately
not given anything here that can assert a clinical fact. It cannot look up
whether a drug is dangerous, because an agent that can look that up will
eventually write it down as advice. It can only name what is uncertain and turn
that into a question. The boundary is enforced by what it holds, not by asking
it nicely in a prompt.
"""
from __future__ import annotations

from strands import tool

from ..tools import fda, rxnorm


@tool
def identify_medicine(box_text: str) -> dict:
    """Resolve text read off a medicine box to a known drug.

    Args:
        box_text: exactly what is printed on the box, including the strength.

    Returns the RxNorm identity and ingredients, or identified=False when the
    text cannot be confirmed — in which case the box must be reported as
    unreadable rather than guessed at.
    """
    d = rxnorm.identify(box_text)
    return {
        "query": d.query,
        "identified": d.identified,
        "rxcui": d.rxcui,
        "name": d.name,
        "ingredients": [n for _, n in d.ingredients],
    }


@tool
def find_duplicate_medicines(box_texts: list[str]) -> dict:
    """Find boxes that are the same medicine under different names.

    Args:
        box_texts: the text from every box in the drawer.

    A brand and its generic share an ingredient; two different drugs never do.
    This is the finding the cabinet exists for — somebody sent home on the
    brand and repeated on the generic is taking a double dose.
    """
    drugs = [rxnorm.identify(t) for t in box_texts]
    pairs = rxnorm.find_duplicates(drugs)
    return {
        "checked": len(box_texts),
        "unreadable": [d.query for d in drugs if not d.identified],
        "duplicates": [
            {"a": a.query, "b": b.query, "shared_ingredient": ing}
            for a, b, ing in pairs
        ],
    }


@tool
def check_for_recalls(ingredient: str) -> dict:
    """Check the FDA enforcement record for live recalls naming an ingredient.

    Args:
        ingredient: the drug's ingredient name, e.g. "atorvastatin".

    Only live recalls are returned; most of the record is closed history. Each
    result names the specific product and the affected lots, because a recall
    is against batches rather than against a medicine. Never report this to
    somebody as "your medicine was recalled".
    """
    try:
        live = fda.recalls(ingredient)
    except fda.SafetyDataUnavailable as e:
        return {"checked": False, "why": str(e)[:160], "recalls": []}

    return {
        "checked": True,
        "ingredient": ingredient,
        "live_recalls": len(live),
        "recalls": [
            {
                "product": r.product,
                "date": r.date,
                "classification": r.classification,
                "affected_lots": r.lots,
                "reason": r.reason,
                "firm": r.firm,
                "is_combination_product": r.names_other_ingredients,
                "how_to_say_it": fda.describe(r),
            }
            for r in live[:5]
        ],
    }


# ---------------------------------------------------------------------------
# What the Scribe is allowed to hold.
#
# Identity and duplicates are questions about *what is in the drawer*, which is
# clerical. Recalls are a safety lookup, and an agent that can perform one will
# sooner or later write its conclusion down as advice — so the Scribe does not
# get it. It is told what was found and turns that into a question for a
# clinician; it cannot go and form a medical opinion of its own.
# ---------------------------------------------------------------------------

CLERICAL_TOOLS = [identify_medicine, find_duplicate_medicines]
SAFETY_TOOLS = [check_for_recalls]
SCRIBE_TOOLS: list = []          # deliberately empty — see above
