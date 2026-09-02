"""The fleet, hosted on Amazon Bedrock AgentCore Runtime.

The same three agents, the same tools, the same ledger — served from AgentCore
instead of from inside the Lambda. The web tier stays on Lambda and calls this
runtime for a reading; jobs, drawers and the nightly schedule stay where they
were. One code path for the agents; two places it can run.

When a payload carries a job id, every tool call is written to that job in
DynamoDB as it happens — from here, inside the runtime — so the page still
draws the agents thinking even though the reading no longer runs next to it.

Payloads:
  {"action": "read", "boxes": [...], "job": "<id>"?}   -> a full reading, with trace
  {"action": "question", "finding": {...}}             -> the Scribe's one sentence
"""
from __future__ import annotations

from bedrock_agentcore import BedrockAgentCoreApp

from app import store
from app.agents import fleet
from app.agents.run import read_drawer

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict, context=None) -> dict:
    payload = payload or {}
    if payload.get("action") == "question":
        return {"question": fleet.write_question(payload.get("finding") or {})}

    boxes = [str(b).strip() for b in payload.get("boxes", []) if str(b).strip()]
    if not boxes:
        return {"error": "no boxes"}

    jid = payload.get("job")
    on_step = (lambda s: store.job_step(jid, s)) if jid else None
    say = (lambda agent, text: store.job_said(jid, agent, text)) if jid else None
    return read_drawer(boxes, on_step=on_step, say=say)


if __name__ == "__main__":
    app.run()
