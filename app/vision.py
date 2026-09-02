"""Reading the label off a photograph.

Amazon Nova Lite is multimodal, and it is already the model the fleet runs on,
so a photo of the drawer goes to the same place the text does. The model is
asked for the printed product name and strength, one line per box, and nothing
else — the identity still comes from RxNorm afterwards, exactly as it does for
typed text. A vision model that also decided what the drug *was* would be a
second, unaccountable source of identity, and the whole point of this record is
that every fact can say where it came from.
"""
from __future__ import annotations

import os

import boto3

MODEL = os.getenv("VITACABINET_MODEL", "eu.amazon.nova-lite-v1:0")
REGION = os.getenv("AWS_DEFAULT_REGION", "eu-north-1")

PROMPT = (
    "These are photographs of medicine boxes from somebody's drawer. For each box "
    "you can read, write the product name and the strength exactly as printed, on "
    "one line, like 'Glucophage 500 mg'. One line per box. If a box is unreadable, "
    "write UNREADABLE on its line. Output only those lines — no numbering, no "
    "commentary, no advice.")

FORMATS = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif"}


def read_labels(images: list[tuple[bytes, str]]) -> list[str]:
    """Box texts read off one or more photos. Returns lines, never advice."""
    content: list[dict] = []
    for data, fmt in images[:6]:
        f = FORMATS.get(fmt.lower().lstrip("."), "jpeg")
        content.append({"image": {"format": f, "source": {"bytes": data}}})
    content.append({"text": PROMPT})

    r = boto3.client("bedrock-runtime", region_name=REGION).converse(
        modelId=MODEL, messages=[{"role": "user", "content": content}],
        inferenceConfig={"maxTokens": 400, "temperature": 0.0})
    text = "".join(c.get("text", "") for c in r["output"]["message"]["content"])
    lines = [ln.strip(" -•*\t") for ln in text.splitlines()]
    return [ln for ln in lines if ln and ln.upper() != "UNREADABLE"][:15]
