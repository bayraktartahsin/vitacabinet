"""The tools the agents are allowed to use.

Which agent gets which tool is the safety model of this system, so the tools
live together where the split is visible in one file.

Two rules shape every tool here.

The model is told little; the app is told everything.  A tool returns a short
sentence to the language model — enough to decide what to do next — and puts
the full structured result on a per-request ledger the application reads
afterwards. The first version returned the whole openFDA payload to the model,
and thirteen live recalls of amlodipine blew straight through its output
budget. The model's job is to orchestrate; the data never needed to pass
through it.

The Scribe holds none of these.  It writes what to ask a clinician, and an
agent that can look up whether a drug is dangerous will eventually write that
lookup down as advice. It cannot, because it has nothing to look up with.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from strands import tool

from ..tools import fda, rxnorm

# ---------------------------------------------------------------------------
# The ledger: what the tools actually found, kept out of the model's context.
# One per request; contextvars keeps concurrent Lambda invocations apart.
# ---------------------------------------------------------------------------


@dataclass
class Ledger:
    drugs: dict[str, rxnorm.Drug] = field(default_factory=dict)      # by box text
    duplicates: list[tuple[str, str, str]] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    recalls: dict[str, list[fda.Recall]] = field(default_factory=dict)  # by ingredient
    recall_errors: dict[str, str] = field(default_factory=dict)


# One ledger per reading, process-wide. A ContextVar looked right and was
# wrong: the concurrent tool executor runs tools on pool threads, and a pool
# thread that once created its own ledger keeps it — so the next reading's
# tool calls on that thread landed in a stale ledger and the duplicate
# vanished, but only when the tests ran in a particular order. Each Lambda
# invocation is its own process, and locally readings are serialised by the
# lock, so a plain module global is both simpler and correct.
_ledger: Ledger | None = None
_reading = threading.Lock()


def open_ledger() -> Ledger:
    global _ledger
    _ledger = Ledger()
    return _ledger


def ledger() -> Ledger:
    return _ledger if _ledger is not None else open_ledger()


def reading_lock() -> threading.Lock:
    return _reading


# ---------------------------------------------------------------------------
# Clerical tools — what is in the drawer.
# ---------------------------------------------------------------------------


@tool
def identify_medicine(box_text: str) -> str:
    """Resolve text read off one medicine box to a known drug via RxNorm.

    Args:
        box_text: exactly what is printed on the box, including the strength.

    Reports the drug and its active ingredient, or says the box could not be
    confirmed — in which case it must be reported as unreadable, never guessed.
    """
    d = rxnorm.identify(box_text)
    led = ledger()
    led.drugs[box_text] = d
    if not d.identified:
        if box_text not in led.unreadable:
            led.unreadable.append(box_text)
        return f"'{box_text}': could not be confirmed as a medicine. Report it as unreadable."
    ings = ", ".join(n for _, n in d.ingredients)
    return f"'{box_text}': {d.name} (RxCUI {d.rxcui}); active ingredient: {ings}."


@tool
def find_duplicate_medicines(box_texts: list[str] | None = None) -> str:
    """Find boxes that are the same medicine under different names.

    Args:
        box_texts: optional — the boxes to compare. If omitted, every box
            identified so far in this drawer is compared, which is what you
            usually want. Call this once, after identify_medicine on each box.

    A brand and its generic share an ingredient; two different drugs never do.
    Somebody sent home on the brand and repeated on the generic is taking a
    double dose.
    """
    led = ledger()
    # The model sometimes "helpfully" normalises the box texts before passing
    # them back — 'Glucophage 500mg' became 'metformin hydrochloride 500 mg' —
    # which collapses the very pair this exists to find. So the comparison runs
    # over what was actually read off the boxes, and the argument only adds.
    for t in (box_texts or []):
        if t not in led.drugs:
            led.drugs[t] = rxnorm.identify(t)
            if not led.drugs[t].identified and t not in led.unreadable:
                led.unreadable.append(t)
    drugs = list(led.drugs.values())
    pairs = rxnorm.find_duplicates(drugs)
    led.duplicates = [(a.query, b.query, ing) for a, b, ing in pairs]
    if not pairs:
        return f"Compared {len(drugs)} boxes: no two share an ingredient."
    lines = [f"'{a.query}' and '{b.query}' both contain {ing}" for a, b, ing in pairs]
    return f"Compared {len(drugs)} boxes. Duplicates: " + "; ".join(lines) + "."


# ---------------------------------------------------------------------------
# Safety tool — kept apart from the clerical ones, and never given to the
# agent that writes to a person.
# ---------------------------------------------------------------------------


@tool
def check_for_recalls(ingredient: str) -> str:
    """Check the FDA enforcement record for live recalls naming an ingredient.

    Args:
        ingredient: the drug's active ingredient, e.g. "atorvastatin".

    Only live recalls count; most of the record is closed history. A recall is
    against specific batches, never against a medicine — so never say
    "your medicine was recalled". Call this once per distinct ingredient.
    """
    led = ledger()
    key = ingredient.strip().lower()
    try:
        live = fda.recalls(key)
    except fda.SafetyDataUnavailable as e:
        led.recall_errors[key] = str(e)[:160]
        return f"{key}: the FDA record could not be reached right now; say so rather than guessing."
    led.recalls[key] = live
    if not live:
        return f"{key}: no live recalls on the FDA enforcement record."
    combos = sum(1 for r in live if r.names_other_ingredients)
    newest = live[0]
    return (f"{key}: {len(live)} live recall(s), {combos} of them combination products. "
            f"Newest: a batch of {newest.product.split(',')[0]} on {newest.date}, "
            f"lots {newest.lots or 'unspecified'}. Report batches and lots, never 'your medicine'.")


# ---------------------------------------------------------------------------
# What each agent is allowed to hold.
# ---------------------------------------------------------------------------

CLERICAL_TOOLS = [identify_medicine, find_duplicate_medicines]
SAFETY_TOOLS = [check_for_recalls]
SCRIBE_TOOLS: list = []          # deliberately empty — see the module docstring
