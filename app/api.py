"""The HTTP surface.

One endpoint does the whole job, because the job is one thing: hand it what is
written on the boxes in a drawer and it hands back what is worth asking about.

The ordering here is the product. Duplicates first, because a double dose is
the thing happening right now. Recalls second, because they are urgent but
rare. Unreadable boxes last, because "I could not read this" is honest but not
alarming. Nothing on this surface can tell anyone what to take.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .cabinet import Cabinet, Fact, Source, days_ago
from .tools import fda, rxnorm

log = logging.getLogger("vitacabinet.api")

app = FastAPI(title="VitaCabinet", version="1.0",
              description="Finds what is uncertain in a medicine drawer. "
                          "Gives no medical advice.")

WEB = Path(__file__).resolve().parent.parent / "web"


class Box(BaseModel):
    """One box, as read off the label."""

    text: str = Field(..., description="exactly what is printed on the box")
    source: str = Field("BOX", description="where this claim came from")
    days_since_confirmed: int = Field(0, ge=0)


class Drawer(BaseModel):
    boxes: list[Box]
    owner: str = "the drawer"


def _drug_json(d: rxnorm.Drug) -> dict:
    return {"query": d.query, "identified": d.identified, "rxcui": d.rxcui,
            "name": d.name, "ingredients": [n for _, n in d.ingredients]}


def _source(name: str) -> Source:
    try:
        return Source[name.upper()]
    except KeyError:
        return Source.BOX


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/scan")
def scan(drawer: Drawer) -> dict:
    """Read a drawer and report what is worth a question.

    The lookups are independent per box and each is a network round trip, so
    they run together — a drawer of twelve boxes should not take twelve times
    as long as a drawer of one.
    """
    with ThreadPoolExecutor(max_workers=8) as pool:
        drugs = list(pool.map(lambda b: rxnorm.identify(b.text), drawer.boxes))

    cabinet = Cabinet(owner=drawer.owner)
    for box, drug in zip(drawer.boxes, drugs):
        cabinet.add(Fact(subject=drug.name or box.text,
                         source=_source(box.source),
                         confirmed_at=days_ago(box.days_since_confirmed),
                         rxcui=drug.rxcui, detail=box.text))

    pairs = rxnorm.find_duplicates(drugs)

    # One recall lookup per distinct ingredient, not per box: two boxes of the
    # same drug are one question to the FDA, and the drawer is small enough
    # that the saving is about being polite to a public API.
    ingredients = sorted({n.lower() for d in drugs for _, n in d.ingredients})
    with ThreadPoolExecutor(max_workers=8) as pool:
        found = list(pool.map(_safe_recalls, ingredients))

    findings: list[dict] = []
    for a, b, ingredient in pairs:
        findings.append({
            "kind": "duplicate",
            "severity": "high",
            "drugs": [a.query, b.query],
            "detail": f"both boxes resolve to the ingredient {ingredient}",
            "headline": f"Two boxes contain {ingredient}",
        })

    for ingredient, recs in zip(ingredients, found):
        for r in recs[:3]:
            findings.append({
                "kind": "recall",
                "severity": "high" if r.classification.startswith("Class I ") else "medium",
                "drugs": [ingredient],
                "detail": fda.describe(r),
                "headline": f"A batch of {r.product.split(',')[0]} was recalled",
                "lots": r.lots,
                "is_combination_product": r.names_other_ingredients,
                "date": r.date,
            })

    for fact in cabinet.stale_facts:
        findings.append({
            "kind": "stale",
            "severity": "low",
            "drugs": [fact.detail or fact.subject],
            "detail": fact.why(),
            "headline": f"{fact.subject} has not been confirmed recently",
        })

    return {
        "owner": drawer.owner,
        "summary": cabinet.summary(),
        "drugs": [_drug_json(d) for d in drugs],
        "unreadable": [d.query for d in drugs if not d.identified],
        "ingredients_checked": ingredients,
        "findings": findings,
    }


def _safe_recalls(ingredient: str) -> list[fda.Recall]:
    """A safety lookup that fails quietly.

    openFDA being down must not take the duplicate finding down with it. The
    drawer still has two boxes of metformin in it either way.
    """
    try:
        return fda.recalls(ingredient)
    except fda.SafetyDataUnavailable as e:
        log.warning("recall lookup failed for %s: %s", ingredient, e)
        return []


class Finding(BaseModel):
    kind: str
    drugs: list[str] = []
    detail: str = ""


@app.post("/question")
def question(finding: Finding) -> dict:
    """Turn one established finding into a question for a pharmacist.

    A separate endpoint, and a separate round trip from /scan, for two reasons.
    The drawer reading is useful on its own — if Bedrock is unreachable the page
    still shows the duplicates rather than showing nothing. And the Scribe is
    only ever handed a finding, never a person's own words: this signature is
    that rule expressed as a type.
    """
    from .agents import fleet          # imported late: /scan must not need Bedrock

    try:
        return {"ok": True, "question": fleet.write_question(finding.model_dump())}
    except Exception as e:                                   # noqa: BLE001
        log.warning("scribe unavailable: %s", e)
        return {"ok": False, "why": "the writing model is unavailable", "question": ""}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")
