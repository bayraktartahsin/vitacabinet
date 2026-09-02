"""The agents on Bedrock AgentCore Runtime, and the web tier that calls them.

The runtime itself is exercised live by scripts/deploy.py's verification; here
the seam is tested — that a configured runtime ARN routes a reading through
invoke_agent_runtime and that the result is recorded exactly as a local
reading would be.
"""
from __future__ import annotations

import io
import json

import pytest

from app import api, store


def test_the_agentcore_entrypoint_is_the_same_fleet():
    """One code path, two places it runs. The entrypoint imports the same
    read_drawer the Lambda uses; it is a host, not a second implementation."""
    import agentcore_entry
    from app.agents.run import read_drawer
    assert agentcore_entry.read_drawer is read_drawer
    assert callable(agentcore_entry.invoke)


class _FakeRuntime:
    """What boto3's bedrock-agentcore client returns, shaped like the real one."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[dict] = []

    def invoke_agent_runtime(self, **kw):
        self.calls.append(kw)
        return {"response": io.BytesIO(json.dumps(self.payload).encode())}


def test_a_configured_runtime_receives_the_boxes_and_the_job_id(monkeypatch):
    fake = _FakeRuntime({"findings": [{"kind": "duplicate", "key": "duplicate:metformin",
                                       "headline": "Two boxes contain metformin"}],
                         "trace": [{"agent": "Identifier", "tool": "identify_medicine"}],
                         "unreadable": [], "seconds": 9.0})
    import boto3
    monkeypatch.setattr(api, "AGENTCORE_ARN", "arn:aws:bedrock-agentcore:eu-north-1:1:runtime/x")
    monkeypatch.setattr(boto3, "client", lambda *a, **k: fake)

    jid = store.new_job(["Glucophage 500mg", "Metformin 500 mg"])
    api.run_job(jid)

    job = store.get_job(jid)
    assert job["status"] == "done"
    assert job["result"]["ran_on"] == "bedrock-agentcore"
    sent = json.loads(fake.calls[0]["payload"])
    assert sent["boxes"] == ["Glucophage 500mg", "Metformin 500 mg"]
    assert sent["job"] == jid, "the runtime writes the trace to the job, so it must know which"
    assert fake.calls[0]["agentRuntimeArn"].endswith("runtime/x")


def test_a_runtime_error_fails_the_job_rather_than_hanging_the_page(monkeypatch):
    fake = _FakeRuntime({"error": "no boxes"})
    import boto3
    monkeypatch.setattr(api, "AGENTCORE_ARN", "arn:aws:bedrock-agentcore:eu-north-1:1:runtime/x")
    monkeypatch.setattr(boto3, "client", lambda *a, **k: fake)
    jid = store.new_job(["x"])
    api.run_job(jid)
    job = store.get_job(jid)
    assert job["status"] == "failed" and "no boxes" in job["error"]


def test_health_says_where_the_agents_run(monkeypatch):
    from fastapi.testclient import TestClient
    c = TestClient(api.app)
    monkeypatch.setattr(api, "AGENTCORE_ARN", None)
    assert c.get("/health").json()["agents_on"] == "local"
    monkeypatch.setattr(api, "AGENTCORE_ARN", "arn:x")
    assert c.get("/health").json()["agents_on"] == "bedrock-agentcore"


def test_the_scribe_runs_on_the_runtime_with_the_other_two(monkeypatch):
    """One fleet, one host. When a runtime is configured the question goes
    there too, so no agent runs in a different place from its siblings."""
    from fastapi.testclient import TestClient
    fake = _FakeRuntime({"question": "Am I supposed to be taking both?"})
    import boto3
    monkeypatch.setattr(api, "AGENTCORE_ARN", "arn:aws:bedrock-agentcore:eu-north-1:1:runtime/x")
    monkeypatch.setattr(boto3, "client", lambda *a, **k: fake)
    r = TestClient(api.app).post("/question", json={"kind": "duplicate", "drugs": ["a", "b"], "detail": "x"}).json()
    assert r["ok"] and r["ran_on"] == "bedrock-agentcore"
    assert json.loads(fake.calls[0]["payload"])["action"] == "question"
