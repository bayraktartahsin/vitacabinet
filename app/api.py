"""The HTTP surface.

Reading a drawer is agent work and takes ten to thirty seconds; API Gateway
gives a request thirty. So a scan is a *job*: POST /scan hands the boxes to a
background invocation and answers at once with an id, the agents write every
tool call to the job as it happens, and the page polls GET /jobs/{id} and draws
the trace as it grows. The person sees the agents think. That is better than a
spinner, and it is the only shape that fits inside the gateway's limit.

Locally there is no second Lambda, so the job runs on a thread. Same code,
same store interface, no cloud required for the tests.

Nothing on this surface can tell anyone what to take.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field

from . import store
from .cabinet import Fact, Source
from .cabinet import days_ago as _days_ago  # noqa: F401  (re-exported for tests)

log = logging.getLogger("vitacabinet.api")

app = FastAPI(title="VitaCabinet", version="2.0",
              description="Finds what is uncertain in a medicine drawer. "
                          "Gives no medical advice.")

WEB = Path(__file__).resolve().parent.parent / "web"
ON_LAMBDA = bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


AGENTCORE_ARN = os.getenv("VITACABINET_AGENTCORE_ARN")


def read_on_agentcore(boxes: list[str], jid: str) -> dict:
    """The reading, run by the fleet on Bedrock AgentCore Runtime.

    The runtime writes the trace to the job itself as the tools fire, so the
    page keeps drawing the agents thinking; this side only waits for the
    finished result. A session id per job keeps readings apart on the runtime.
    """
    import json
    import boto3
    client = boto3.client("bedrock-agentcore")
    r = client.invoke_agent_runtime(
        agentRuntimeArn=AGENTCORE_ARN,
        runtimeSessionId=f"vitacabinet-job-{jid}-{'x' * 20}"[:64].ljust(33, "x"),
        contentType="application/json", accept="application/json",
        payload=json.dumps({"action": "read", "boxes": boxes, "job": jid}).encode())
    body = r["response"].read() if hasattr(r.get("response"), "read") else r.get("response", b"")
    result = json.loads(body or b"{}")
    if "error" in result and "findings" not in result:
        raise RuntimeError(result["error"])
    result["ran_on"] = "bedrock-agentcore"
    return result


def ask_on_agentcore(finding: dict) -> str:
    """The Scribe, on the runtime with the other two. One fleet, one host."""
    import json
    import uuid
    import boto3
    r = boto3.client("bedrock-agentcore").invoke_agent_runtime(
        agentRuntimeArn=AGENTCORE_ARN,
        runtimeSessionId=f"vitacabinet-q-{uuid.uuid4().hex}"[:64].ljust(33, "x"),
        contentType="application/json", accept="application/json",
        payload=json.dumps({"action": "question", "finding": finding}).encode())
    body = r["response"].read() if hasattr(r.get("response"), "read") else r.get("response", b"")
    return json.loads(body or b"{}").get("question", "")


def run_job(jid: str) -> None:
    """The background half of a scan. Called by a second Lambda invocation in
    the cloud and by a thread locally; identical either way. The agents run on
    AgentCore when a runtime is configured, and in-process otherwise."""
    job = store.get_job(jid)
    if not job:
        return
    store.job_started(jid)
    try:
        if AGENTCORE_ARN:
            result = read_on_agentcore(job["boxes"], jid)
        else:
            from .agents.run import read_drawer          # imported late: Strands is slow to load
            result = read_drawer(
                job["boxes"],
                on_step=lambda s: store.job_step(jid, s),
                say=lambda agent, text: store.job_said(jid, agent, text))
            result["ran_on"] = "lambda"
        if job.get("drawer_id"):
            diff = store.set_findings(job["drawer_id"], result["findings"], len(result["trace"]))
            result["new_since_last_check"] = diff["new"]
            if diff["new"]:
                notify(job["drawer_id"], diff["new"])
        store.job_done(jid, result)
    except Exception as e:                                   # noqa: BLE001
        log.exception("job %s failed", jid)
        store.job_failed(jid, f"{type(e).__name__}: {e}")


def dispatch(jid: str) -> None:
    """Hand a job to whoever runs jobs here."""
    if ON_LAMBDA:
        import json
        import boto3
        boto3.client("lambda").invoke(
            FunctionName=os.environ["VITACABINET_FUNCTION"],
            InvocationType="Event", Payload=json.dumps({"job": jid}).encode())
    else:
        threading.Thread(target=run_job, args=(jid,), daemon=True).start()


def notify(drawer_id: str, new: list[dict]) -> None:
    """Only when there is something new. A nightly email that says 'nothing
    changed' is how people stop reading the one that matters."""
    topic = os.getenv("VITACABINET_TOPIC")
    drawer = store.get_drawer(drawer_id) or {}
    if not topic or not drawer.get("subscribers"):
        return
    import boto3
    lines = [f"- {f['headline']}" for f in new[:8]]
    body = ("VitaCabinet's Watchman found something new in a drawer you asked it to watch:\n\n"
            + "\n".join(lines)
            + "\n\nThis is not medical advice. Check the box, and ask a pharmacist.")
    boto3.client("sns").publish(TopicArn=topic, Subject="VitaCabinet: something new in the drawer",
                                Message=body)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Box(BaseModel):
    text: str = Field(..., min_length=1, max_length=120)


class Drawer(BaseModel):
    boxes: list[Box] = Field(..., max_length=25)
    owner: str = "the drawer"
    drawer_id: str | None = None


class SaveDrawer(BaseModel):
    boxes: list[str] = Field(..., min_length=1, max_length=25)
    owner: str = "the drawer"


class Confirm(BaseModel):
    subject: str


class Subscribe(BaseModel):
    email: EmailStr


class Finding(BaseModel):
    kind: str
    drugs: list[str] = []
    detail: str = ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


TESTS = int(os.getenv("VITACABINET_TESTS", "0"))   # stamped at deploy time


@app.get("/health")
def health() -> dict:
    return {"ok": True, "store": store.backend_name(), "lambda": ON_LAMBDA, "tests": TESTS,
            "agents_on": "bedrock-agentcore" if AGENTCORE_ARN else ("lambda" if ON_LAMBDA else "local")}


@app.post("/scan")
def scan(drawer: Drawer) -> dict:
    """Start reading a drawer. Answers immediately with a job to poll."""
    boxes = [b.text.strip() for b in drawer.boxes if b.text.strip()]
    if not boxes:
        return {"job_id": None, "findings": [], "trace": []}
    jid = store.new_job(boxes, drawer.drawer_id)
    dispatch(jid)
    return {"job_id": jid}


@app.get("/jobs/{jid}")
def job(jid: str) -> dict:
    j = store.get_job(jid)
    if not j:
        raise HTTPException(404, "no such job")
    return {k: j.get(k) for k in ("id", "status", "boxes", "trace", "said", "result", "error")}


@app.post("/drawers")
def create_drawer(body: SaveDrawer) -> dict:
    row = store.new_drawer([b.strip() for b in body.boxes if b.strip()], body.owner)
    return enrich(row)


@app.get("/drawers/{did}")
def get_drawer(did: str) -> dict:
    row = store.get_drawer(did)
    if not row:
        raise HTTPException(404, "no such drawer")
    return enrich(row)


@app.post("/drawers/{did}/confirm")
def confirm(did: str, body: Confirm) -> dict:
    row = store.confirm_fact(did, body.subject)
    if not row:
        raise HTTPException(404, "no such drawer")
    return enrich(row)


@app.post("/drawers/{did}/check")
def check_now(did: str) -> dict:
    """What the schedule does every night, on demand — same code path."""
    row = store.get_drawer(did)
    if not row:
        raise HTTPException(404, "no such drawer")
    jid = store.new_job(row["boxes"], did)
    dispatch(jid)
    return {"job_id": jid}


@app.post("/drawers/{did}/subscribe")
def subscribe(did: str, body: Subscribe) -> dict:
    if not store.get_drawer(did):
        raise HTTPException(404, "no such drawer")
    store.add_subscriber(did, body.email)
    topic = os.getenv("VITACABINET_TOPIC")
    if topic:
        import boto3
        boto3.client("sns").subscribe(TopicArn=topic, Protocol="email", Endpoint=body.email)
    return {"ok": True, "confirm": "AWS will email a confirmation link first."}


@app.post("/read-label")
async def read_label(images: list[UploadFile] = File(...)) -> dict:
    """Photos of boxes in; printed names and strengths out. Identity still
    comes from RxNorm afterwards, exactly as it does for typed text."""
    from .vision import read_labels
    payload = []
    for up in images[:6]:
        data = await up.read()
        if len(data) > 8_000_000:
            raise HTTPException(413, "image too large")
        payload.append((data, (up.filename or "x.jpg").rsplit(".", 1)[-1]))
    try:
        return {"boxes": read_labels(payload)}
    except Exception as e:                                   # noqa: BLE001
        log.warning("vision failed: %s", e)
        return {"boxes": [], "why": "the vision model is unavailable"}


@app.post("/question")
def question(finding: Finding) -> dict:
    """Turn one established finding into a question for a pharmacist.

    The Scribe is only ever handed a finding, never a person's own words: this
    signature is that rule expressed as a type.
    """
    try:
        if AGENTCORE_ARN:
            q = ask_on_agentcore(finding.model_dump())
        else:
            from .agents import fleet
            q = fleet.write_question(finding.model_dump())
        return {"ok": bool(q), "question": q, "ran_on": "bedrock-agentcore" if AGENTCORE_ARN else "local"}
    except Exception as e:                                   # noqa: BLE001
        log.warning("scribe unavailable: %s", e)
        return {"ok": False, "why": "the writing model is unavailable", "question": ""}


# ---------------------------------------------------------------------------
# Enrichment: a drawer row becomes a cabinet with confidence on every fact.
# ---------------------------------------------------------------------------


def enrich(row: dict) -> dict:
    from datetime import datetime, timezone
    facts = []
    for f in row.get("facts", []):
        fact = Fact(subject=f["subject"], source=Source[f.get("source", "BOX")],
                    confirmed_at=datetime.fromtimestamp(f["confirmed_at"], timezone.utc))
        facts.append({"subject": fact.subject, "source": fact.source.description,
                      "age_days": fact.age_days, "confidence": fact.confidence,
                      "stale": fact.stale, "why": fact.why()})
    facts.sort(key=lambda x: x["confidence"])
    out = {k: row.get(k) for k in ("id", "owner", "boxes", "findings", "last_checked",
                                   "history", "last_new", "created")}
    out["facts"] = facts
    out["subscribers"] = len(row.get("subscribers") or [])
    out["stale_count"] = sum(1 for x in facts if x["stale"])
    return out


# ---------------------------------------------------------------------------
# Static
# ---------------------------------------------------------------------------


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/director")
def director() -> FileResponse:
    return FileResponse(WEB / "director.html")


@app.get("/autopilot.js")
def autopilot() -> FileResponse:
    return FileResponse(WEB / "autopilot.js", media_type="text/javascript")


@app.get("/sample-drawer.jpg")
def sample_drawer() -> FileResponse:
    """The demo drawer, as a photograph, for the recording's vision beat."""
    return FileResponse(WEB / "sample-drawer.jpg", media_type="image/jpeg")


@app.get("/architecture.png")
def architecture() -> FileResponse:
    return FileResponse(WEB / "architecture.png", media_type="image/png")
