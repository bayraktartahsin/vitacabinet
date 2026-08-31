"""Drug identity, from the US National Library of Medicine.

The single most useful thing a cabinet can tell you is that two of its boxes
are the same medicine. It happens constantly — a hospital sends someone home on
the brand, a GP repeats the generic, and nobody reconciles the two because
nobody is looking at both boxes. The person takes a double dose of something
they were told to take once.

Catching that needs an authority on what a drug *is*, not a string comparison.
"Glucophage" and "Metformin" share no characters; RxNorm resolves both to
ingredient 6809 and the duplicate becomes obvious.

RxNav is public, needs no key, and every answer carries an RxCUI — so a finding
here can be checked by anyone rather than believed because an agent said it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

log = logging.getLogger("vitacabinet.rxnorm")

_BASE = "https://rxnav.nlm.nih.gov/REST"
_TIMEOUT = 30.0


class DrugLookupUnavailable(RuntimeError):
    """RxNav could not be reached or gave an unusable answer.

    Its own type because the caller's correct response is to mark the box
    unidentified and say so, never to guess at what the medicine might be.
    """


@dataclass
class Drug:
    """One medicine, as RxNorm understands it."""

    query: str                                  # what was read off the box
    rxcui: str | None = None                    # RxNorm's id for that product
    name: str | None = None                     # its normalised name
    ingredients: list[tuple[str, str]] = field(default_factory=list)  # (rxcui, name)

    @property
    def identified(self) -> bool:
        return bool(self.rxcui and self.ingredients)

    @property
    def ingredient_ids(self) -> set[str]:
        return {cui for cui, _ in self.ingredients}


def _get(path: str, **params) -> dict:
    try:
        r = httpx.get(f"{_BASE}{path}", params=params, timeout=_TIMEOUT)
    except httpx.HTTPError as e:
        raise DrugLookupUnavailable(f"RxNav unreachable: {e}") from e
    if r.status_code >= 400:
        raise DrugLookupUnavailable(f"RxNav {path}: HTTP {r.status_code}")
    return r.json()


def _lookup(text: str) -> str | None:
    """Find an RxCUI for text that came off a box, not out of a database.

    The obvious call — /rxcui with search=2 — resolves "Metformin 500 mg" and
    fails flat on "Glucophage 500mg". Generic names survive a trailing strength
    and brand names do not, which is precisely backwards for a cabinet: the
    boxes with brand names on them are the ones most likely to be a hidden
    duplicate of something else in the drawer.
    
    So the exact lookup is only the first attempt. /approximateTerm is RxNav's
    fuzzy matcher and handles the strength suffix on both, which is why it is
    the fallback rather than the last resort.
    """
    ids = (_get("/rxcui.json", name=text, search=2).get("idGroup") or {}).get("rxnormId")
    if ids:
        return ids[0]

    cands = (_get("/approximateTerm.json", term=text, maxEntries=1)
             .get("approximateGroup") or {}).get("candidate") or []
    for c in cands:
        cui = c.get("rxcui")
        if cui and _confirms(text, cui):
            log.info("approximate match for %r -> %s", text, cui)
            return cui
    return None


def _words(text: str) -> set[str]:
    """Alphabetic words long enough to identify something."""
    return {w for w in "".join(
        ch if ch.isalpha() else " " for ch in text.lower()).split() if len(w) >= 4}


def _confirms(text: str, rxcui: str) -> bool:
    """Does the matched drug actually look like what was on the box?

    The fuzzy matcher always answers. Asked for "qqqzzz not a medicine 12345"
    it confidently returns bisphenol A, and its own score does not save you:
    "shopping list milk" scores 11.8 while a genuine "Atorvastatin 20mg" scores
    11.7. Ranking nonsense above a real drug is not a threshold problem.

    So the match is confirmed by round trip instead. A real box's product name
    contains the word that was read off it — "Glucophage 500mg" comes back as
    "...Oral Tablet [Glucophage]". Nonsense comes back as something sharing no
    word with the query, and is rejected.

    The cost of being wrong here is not a blank row. It is naming a box as a
    medicine it is not, and then warning about a duplicate or a recall that has
    nothing to do with what is in the drawer.
    """
    try:
        name = ((_get(f"/rxcui/{rxcui}/properties.json").get("properties") or {})
                .get("name") or "")
    except DrugLookupUnavailable:
        return False
    if not name:
        return False

    asked = _words(text)
    if not asked:
        return False

    # Overlap alone is too weak. "shopping list milk" really does contain a
    # substance RxNorm knows — cow milk allergenic extract — so one word out of
    # three matches and the nonsense confirms itself. A drug name read off a box
    # is one or two words and nearly all of them should land; a sentence where
    # a single word happens to be a substance should not.
    return len(asked & _words(name)) / len(asked) >= 0.5


def identify(text: str) -> Drug:
    """Resolve whatever was printed on a box to a drug RxNorm recognises."""
    drug = Drug(query=text)
    drug.rxcui = _lookup(text)
    if not drug.rxcui:
        log.info("no RxNorm match for %r", text)
        return drug

    props = (_get(f"/rxcui/{drug.rxcui}/properties.json").get("properties") or {})
    drug.name = props.get("name")

    # The ingredient is what makes two boxes the same medicine. A brand and a
    # generic share it; two different drugs never do.
    related = _get(f"/rxcui/{drug.rxcui}/related.json", tty="IN")
    for group in (related.get("relatedGroup") or {}).get("conceptGroup") or []:
        for concept in group.get("conceptProperties") or []:
            drug.ingredients.append((concept["rxcui"], concept["name"]))
    return drug


def find_duplicates(drugs: list[Drug]) -> list[tuple[Drug, Drug, str]]:
    """Pairs of boxes that are the same medicine under different names.

    Returns the two boxes and the shared ingredient, so the finding can be
    presented as evidence — "both of these are metformin, RxCUI 6809" — rather
    than as an assertion.
    """
    out: list[tuple[Drug, Drug, str]] = []
    for i, a in enumerate(drugs):
        if not a.identified:
            continue
        for b in drugs[i + 1:]:
            if not b.identified or a.rxcui == b.rxcui:
                continue
            shared = a.ingredient_ids & b.ingredient_ids
            if shared:
                name = next(n for cui, n in a.ingredients if cui in shared)
                out.append((a, b, name))
    return out
