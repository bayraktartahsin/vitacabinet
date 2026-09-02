"""The fleet, hosted on Amazon Bedrock AgentCore Runtime.

The same three agents, the same tools, the same ledger — served from AgentCore
instead of from inside the Lambda. The web app calls this runtime for a
reading and keeps everything else (jobs, drawers, the nightly schedule) where
it was. One code path for the agents; two places it can run.

Payloads:
  {"action": "read",     "boxes": [...]}            -> a full reading, with trace
  {"action": "question", "finding": {...}}           -> the Scribe's one sentence
"""
from __future__ import annotations

from bedrock_agentcore import BedrockAgentCoreApp

from app.agents import fleet
from app.agents.run import read_drawer

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict, context=None) -> dict:
    action = (payload or {}).get("action", "read")
    if action == "question":
        return {"question": fleet.write_question(payload.get("finding") or {})}
    boxes = [str(b).strip() for b in (payload or {}).get("boxes", []) if str(b).strip()]
    if not boxes:
        return {"error": "no boxes"}
    return read_drawer(boxes)


if __name__ == "__main__":
    app.run()
