"""Reading a drawer, end to end, with the agents doing the work.

This is the request path. The Identifier reads the boxes through its tools,
the Watchman checks the safety record through its tool, and every tool call
is recorded as it happens so the person watching the screen sees the agents
think rather than a spinner.

The findings are assembled from the ledger the tools wrote to — not from the
models' prose. A language model's sentence about what it found is a fine thing
to show; it is not a fine thing to parse. The tools return structured data,
the agents decide when to call them, and the app reads the data.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, field_validator
from strands import Agent
from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry
from strands.models import BedrockModel
from strands.tools.executors import ConcurrentToolExecutor

from ..tools import fda
from . import fleet, tools

StepFn = Callable[[dict], None]


@dataclass
class Trace(HookProvider):
    """Every tool call, as it happens, handed to whoever is watching."""

    agent_name: str
    on_step: StepFn | None = None
    steps: list[dict] = field(default_factory=list)
    _started: dict[str, float] = field(default_factory=dict)

    def register_hooks(self, registry: HookRegistry, **_) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before)
        registry.add_callback(AfterToolCallEvent, self.after)

    def before(self, ev: BeforeToolCallEvent) -> None:
        self._started[ev.tool_use.get("toolUseId", "")] = time.time()

    def after(self, ev: AfterToolCallEvent) -> None:
        tu = ev.tool_use
        t0 = self._started.pop(tu.get("toolUseId", ""), time.time())
        content = ev.result.get("content", []) if isinstance(ev.result, dict) else []
        said = next((c.get("text", "") for c in content if "text" in c), "")
        step = {
            "agent": self.agent_name,
            "tool": tu.get("name"),
            "input": tu.get("input"),
            "said": said[:240],
            "ms": int((time.time() - t0) * 1000),
            "at": time.time(),
        }
        self.steps.append(step)
        if self.on_step:
            self.on_step(step)


class DrawerReport(BaseModel):
    """What the Identifier concluded, as data rather than prose.

    The ledger is still the truth about *what was found*; this is the agent's
    own account of it, typed so the page can render it and a test can check
    it against the ledger. A model that has to fill in fields cannot bury an
    unreadable box in a paragraph.
    """

    boxes_read: int = Field(description="how many boxes were identified")
    unreadable: list[str] = Field(default_factory=list,
                                  description="box texts that could not be confirmed as a medicine")
    duplicate_pairs: list[list[str]] = Field(default_factory=list,
                                             description="pairs of box texts that share an active ingredient")
    one_line: str = Field(description="one plain sentence for the person, no advice")

    @field_validator("unreadable", "duplicate_pairs", mode="before")
    @classmethod
    def _none_is_empty(cls, v):
        """Nova writes `null` for an empty list when there is nothing to
        report, and a report that fails validation because the drawer was
        *fine* is a bad joke. None means none."""
        return [] if v is None else v


def _model() -> BedrockModel:
    # Larger output budget than the Scribe's: these two narrate a whole drawer.
    return BedrockModel(model_id=fleet.DEFAULT_MODEL, region_name=fleet.REGION,
                        temperature=0.1, max_tokens=1500)


def _clean(text: str) -> str:
    """Nova sometimes shows its working in <thinking> tags. Not for the screen."""
    return re.sub(r"<thinking>.*?</thinking>\s*", "", text, flags=re.S).strip()


def read_drawer(boxes: list[str], on_step: StepFn | None = None,
                say: Callable[[str, str], None] | None = None) -> dict:
    """Run the Identifier, then the Watchman, and assemble what they found.

    `on_step` is called after every tool call; `say` after each agent's final
    word. Both are how a job writes progress somewhere a page can poll.
    """
    with tools.reading_lock():
        return _read_drawer(boxes, on_step, say)


def _read_drawer(boxes: list[str], on_step: StepFn | None, say) -> dict:
    led = tools.open_ledger()
    t0 = time.time()

    # --- the Identifier: what is in the drawer ---------------------------
    ident_trace = Trace("Identifier", on_step)
    identifier = Agent(model=_model(), tools=tools.CLERICAL_TOOLS, hooks=[ident_trace],
                       system_prompt=fleet.IDENTIFIER_PROMPT, callback_handler=None,
                       tool_executor=ConcurrentToolExecutor())
    listing = "; ".join(f"'{b}'" for b in boxes)
    ident_said = _clean(fleet.text_of(identifier(
        f"Boxes in the drawer: {listing}. Identify every box with identify_medicine, "
        f"then call find_duplicate_medicines once with all of them, then report.")))
    if say:
        say("Identifier", ident_said)

    # The same agent, asked for its conclusion as a typed object. This is a
    # second, cheap model call over the conversation it already had; the
    # schema is the contract, and the ledger is the check on it.
    try:
        report = identifier.structured_output(
            DrawerReport,
            "Report what you found as the requested structure. Do not give advice.")
        report_json = report.model_dump()
    except Exception as e:                                       # noqa: BLE001
        report_json = {"error": f"{type(e).__name__}: {e}"[:160]}

    # Anything the model skipped is read directly, and the trace says so. The
    # drawer is the truth; the model is how it is read, not a gate on it.
    for b in boxes:
        if b not in led.drugs:
            tools.identify_medicine(b)
            step = {"agent": "Identifier", "tool": "identify_medicine", "input": {"box_text": b},
                    "said": "(read directly — the agent did not ask)", "ms": 0, "at": time.time()}
            ident_trace.steps.append(step)
            if on_step:
                on_step(step)
    # Duplicates are recomputed from the ledger unconditionally. It is cheap
    # (every box is already resolved), deterministic, and immune to the model
    # having rewritten the box texts on the way into the tool.
    tools.find_duplicate_medicines(None)

    # --- the Watchman: the safety record -----------------------------------
    ingredients = sorted({n.lower() for d in led.drugs.values() for _, n in d.ingredients})
    watch_trace = Trace("Watchman", on_step)
    watch_said = ""
    if ingredients:
        watchman = Agent(model=_model(), tools=tools.SAFETY_TOOLS, hooks=[watch_trace],
                         system_prompt=fleet.WATCHMAN_PROMPT, callback_handler=None,
                         tool_executor=ConcurrentToolExecutor())
        watch_said = _clean(fleet.text_of(watchman(
            f"Ingredients in the drawer: {', '.join(ingredients)}. "
            f"Call check_for_recalls once for each, then report only what is live.")))
        for ing in ingredients:
            if ing not in led.recalls and ing not in led.recall_errors:
                tools.check_for_recalls(ing)
        if say:
            say("Watchman", watch_said)

    return {
        "boxes": boxes,
        "drugs": [_drug_json(led.drugs[b]) for b in boxes if b in led.drugs],
        "unreadable": [b for b in boxes if b in led.unreadable],
        "ingredients_checked": ingredients,
        "findings": assemble_findings(led),
        "trace": ident_trace.steps + watch_trace.steps,
        "agents_said": {"Identifier": ident_said, "Watchman": watch_said},
        "report": report_json,
        "seconds": round(time.time() - t0, 1),
    }


def _drug_json(d) -> dict:
    return {"query": d.query, "identified": d.identified, "rxcui": d.rxcui,
            "name": d.name, "ingredients": [n for _, n in d.ingredients]}


def assemble_findings(led: tools.Ledger) -> list[dict]:
    """Duplicates first, because a double dose is happening now. Recalls next.
    The order is the product."""
    findings: list[dict] = []
    for a, b, ingredient in led.duplicates:
        findings.append({
            "kind": "duplicate", "severity": "high",
            "drugs": [a, b],
            "detail": f"both boxes resolve to the ingredient {ingredient}",
            "headline": f"Two boxes contain {ingredient}",
            "key": f"duplicate:{ingredient}",
        })
    for ingredient, recs in led.recalls.items():
        for r in recs[:3]:
            findings.append({
                "kind": "recall",
                "severity": "high" if r.classification.startswith("Class I ") else "medium",
                "drugs": [ingredient],
                "detail": fda.describe(r),
                "headline": f"A batch of {r.product.split(',')[0]} was recalled",
                "lots": r.lots, "date": r.date,
                "is_combination_product": r.names_other_ingredients,
                "key": f"recall:{ingredient}:{r.date}:{(r.lots or '')[:24]}",
            })
    for ingredient, why in led.recall_errors.items():
        findings.append({
            "kind": "unchecked", "severity": "low", "drugs": [ingredient],
            "detail": f"The FDA record could not be reached for {ingredient}: {why}",
            "headline": f"{ingredient} could not be checked for recalls",
            "key": f"unchecked:{ingredient}",
        })
    return findings
