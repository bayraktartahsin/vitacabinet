"""The agents, and the reason each one is separate.

Splitting work across agents is only worth doing when the pieces differ in
something that matters. Three do here, and the differences are not stylistic:

  Identifier   its truth comes from an outside authority, and it must be able
               to return "I could not read this" without that becoming a guess
               somewhere downstream.
  Watchman     runs on a schedule rather than in a request. Recalls arrive when
               they arrive; nothing about them is triggered by somebody opening
               an app. This is the background half of the product.
  Scribe       writes what to ask a clinician, and is the one agent that must
               never form a medical opinion. It holds no tool that could.

That last one is the safety model. An agent able to look up whether a drug is
dangerous will eventually write the answer down as advice, however firmly its
prompt says otherwise — so the Scribe is not given the lookup. The boundary is
in what it holds, not in what it was told.
"""
from __future__ import annotations

import logging
import os

from strands import Agent
from strands.models import BedrockModel

from . import tools

log = logging.getLogger("vitacabinet.fleet")

# Nova rather than Claude, for a reason worth stating: Anthropic models on this
# account require a use-case form before ConverseStream will answer, and Strands
# is model-agnostic, so the fleet simply runs on a model that is available. The
# same code runs on Claude the moment that form is approved — which is the
# argument for a model-agnostic SDK, made by circumstance rather than in a
# README.
DEFAULT_MODEL = os.getenv("VITACABINET_MODEL", "eu.amazon.nova-lite-v1:0")
REGION = os.getenv("AWS_DEFAULT_REGION", "eu-north-1")


def _model(temperature: float = 0.2) -> BedrockModel:
    return BedrockModel(model_id=DEFAULT_MODEL, region_name=REGION,
                        temperature=temperature)


def text_of(result) -> str:
    """The agent's answer, without the streamed copy.

    Strands streams tokens to stdout as they arrive *and* returns the finished
    message, so printing str(result) shows everything twice. The message is the
    real value; the stream is a side effect of watching it think.
    """
    msg = getattr(result, "message", None)
    if isinstance(msg, dict):
        parts = [b.get("text", "") for b in msg.get("content", []) if "text" in b]
        if parts:
            return "\n".join(parts).strip()
    return str(result).strip()


IDENTIFIER_PROMPT = """\
You work out what is actually in somebody's medicine drawer from the text
printed on the boxes.

Use identify_medicine on each box and find_duplicate_medicines across all of
them together.

A box you cannot identify is reported as unreadable. Never guess at a name: a
wrong identity here becomes a wrong duplicate warning, or a recall alert about
a drug the person does not take.

State what you found plainly. Do not give medical advice of any kind.
"""

WATCHMAN_PROMPT = """\
You check whether any medicine in a drawer has been recalled.

Use check_for_recalls on each ingredient. Report only live recalls.

A recall is against specific batches, never against a medicine as such. Say "a
batch of X was recalled" and give the affected lot numbers so the person can
check the box in front of them. Never say somebody's medicine has been
recalled, and never suggest stopping anything — somebody frightened off a drug
they need is a worse outcome than the recall you were reporting.

If a recalled product is a combination and the person takes only one of its
ingredients, say so.
"""

SCRIBE_PROMPT = """\
You are a writing tool. You convert a structured finding into one plain-English
question for a pharmacist.

You are not talking to a patient and you are not being asked for an opinion.
The finding has already been established by other parts of the system; your
only job is to phrase it as a question somebody could read aloud at a counter.

Output the question and nothing else. One or two sentences. No preamble, no
advice, no reassurance, no recommendation about what to take.

Example finding: two boxes contain the same ingredient, metformin.
Example output: I have two boxes here that both seem to contain metformin —
Glucophage and one labelled metformin. Am I supposed to be taking both?
"""


def identifier() -> Agent:
    """Reads the drawer."""
    return Agent(model=_model(), tools=tools.CLERICAL_TOOLS,
                 system_prompt=IDENTIFIER_PROMPT)


def watchman() -> Agent:
    """Watches the safety record. Runs on a schedule, not on a request."""
    return Agent(model=_model(), tools=tools.SAFETY_TOOLS,
                 system_prompt=WATCHMAN_PROMPT)


def scribe() -> Agent:
    """Writes the questions. Holds no tool that can form a clinical opinion."""
    return Agent(model=_model(temperature=0.3), tools=tools.SCRIBE_TOOLS,
                 system_prompt=SCRIBE_PROMPT)


def write_question(finding: dict) -> str:
    """Turn one established finding into a question for a pharmacist.

    The Scribe is never handed what a person typed. Given a worried sentence —
    "she is 78, should she stop one, just tell me which to throw away" — the
    model stopped being a writing tool and became a health chatbot, refused,
    and offered a crisis line to somebody asking about two boxes of metformin.
    Nothing was produced, which is a failure at its actual job.

    So the interface is a structured finding, not free text. The Scribe cannot
    be argued with by a user because it never meets one.
    """
    kind = finding.get("kind", "uncertainty")
    detail = finding.get("detail", "")
    drugs = ", ".join(finding.get("drugs", [])) or "a medicine"

    brief = (f"Finding type: {kind}. Medicines involved: {drugs}. "
             f"What was established: {detail}")

    # callback_handler=None keeps the token stream off stdout; this runs inside
    # a request, not in front of somebody watching a terminal.
    agent = Agent(model=_model(temperature=0.3), tools=tools.SCRIBE_TOOLS,
                  system_prompt=SCRIBE_PROMPT, callback_handler=None)
    out = text_of(agent(brief))

    # The prompt shows a worked example labelled "Example output:", and the
    # model sometimes copies the label along with the format.
    for prefix in ("Output:", "Question:", "Example output:"):
        if out.lower().startswith(prefix.lower()):
            out = out[len(prefix):].strip()
    return out
