"""Where things are kept between requests.

Two kinds of record. A *job* is one reading of a drawer in progress: the agents
write each tool call here as it happens, and the page polls it. A *drawer* is
somebody's cabinet: the boxes, the facts with their sources and ages, what the
Watchman found last time it looked, and who wants to be told.

One DynamoDB table when VITACABINET_TABLE is set; a dictionary otherwise, so
the tests and the local dev server need no cloud at all. Jobs carry a TTL — a
trace is worth keeping for an hour, not forever.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from decimal import Decimal
from typing import Any

TABLE = os.getenv("VITACABINET_TABLE")
JOB_TTL = 3600


# ---------------------------------------------------------------------------
# Backends. Both expose get / put / update-append / scan-prefix, nothing more.
# ---------------------------------------------------------------------------


class _Memory:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def get(self, pk: str) -> dict | None:
        row = self.rows.get(pk)
        return json.loads(json.dumps(row)) if row else None

    def put(self, row: dict) -> None:
        self.rows[row["pk"]] = json.loads(json.dumps(row))

    def append(self, pk: str, field: str, item: dict) -> None:
        self.rows[pk].setdefault(field, []).append(json.loads(json.dumps(item)))

    def set(self, pk: str, **fields: Any) -> None:
        self.rows[pk].update(json.loads(json.dumps(fields)))

    def prefix(self, prefix: str) -> list[dict]:
        return [self.get(k) for k in sorted(self.rows) if k.startswith(prefix)]


class _Dynamo:
    def __init__(self, table: str) -> None:
        import boto3
        self.t = boto3.resource("dynamodb").Table(table)

    @staticmethod
    def _in(v: Any) -> Any:
        return json.loads(json.dumps(v), parse_float=Decimal)

    @staticmethod
    def _out(v: Any) -> Any:
        if isinstance(v, list):
            return [_Dynamo._out(x) for x in v]
        if isinstance(v, dict):
            return {k: _Dynamo._out(x) for k, x in v.items()}
        if isinstance(v, Decimal):
            return int(v) if v == int(v) else float(v)
        return v

    def get(self, pk: str) -> dict | None:
        r = self.t.get_item(Key={"pk": pk}).get("Item")
        return self._out(r) if r else None

    def put(self, row: dict) -> None:
        self.t.put_item(Item=self._in(row))

    def append(self, pk: str, field: str, item: dict) -> None:
        self.t.update_item(
            Key={"pk": pk},
            UpdateExpression="SET #f = list_append(if_not_exists(#f, :empty), :i)",
            ExpressionAttributeNames={"#f": field},
            ExpressionAttributeValues={":i": [self._in(item)], ":empty": []})

    def set(self, pk: str, **fields: Any) -> None:
        names = {f"#{i}": k for i, k in enumerate(fields)}
        values = {f":{i}": self._in(v) for i, v in enumerate(fields.values())}
        self.t.update_item(
            Key={"pk": pk},
            UpdateExpression="SET " + ", ".join(f"#{i} = :{i}" for i in range(len(fields))),
            ExpressionAttributeNames=names, ExpressionAttributeValues=values)

    def prefix(self, prefix: str) -> list[dict]:
        from boto3.dynamodb.conditions import Attr
        rows, kw = [], {"FilterExpression": Attr("pk").begins_with(prefix)}
        while True:
            r = self.t.scan(**kw)
            rows += r.get("Items", [])
            if "LastEvaluatedKey" not in r:
                break
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        return sorted((self._out(x) for x in rows), key=lambda x: x["pk"])


_backend = _Dynamo(TABLE) if TABLE else _Memory()


def backend_name() -> str:
    return "dynamodb" if TABLE else "memory"


# ---------------------------------------------------------------------------
# Jobs — one reading of a drawer, in progress.
# ---------------------------------------------------------------------------


def new_job(boxes: list[str], drawer_id: str | None = None) -> str:
    jid = uuid.uuid4().hex[:12]
    _backend.put({"pk": f"job#{jid}", "id": jid, "status": "queued", "boxes": boxes,
                  "drawer_id": drawer_id, "trace": [], "said": {}, "result": None,
                  "created": time.time(), "expires": int(time.time()) + JOB_TTL})
    return jid


def job_started(jid: str) -> None:
    _backend.set(f"job#{jid}", status="running")


def job_step(jid: str, step: dict) -> None:
    _backend.append(f"job#{jid}", "trace", step)


def job_said(jid: str, agent: str, text: str) -> None:
    row = _backend.get(f"job#{jid}") or {}
    said = row.get("said") or {}
    said[agent] = text
    _backend.set(f"job#{jid}", said=said)


def job_done(jid: str, result: dict) -> None:
    _backend.set(f"job#{jid}", status="done", result=result)


def job_failed(jid: str, why: str) -> None:
    _backend.set(f"job#{jid}", status="failed", error=why[:300])


def get_job(jid: str) -> dict | None:
    return _backend.get(f"job#{jid}")


# ---------------------------------------------------------------------------
# Drawers — a cabinet that persists, with facts that age.
# ---------------------------------------------------------------------------


def new_drawer(boxes: list[str], owner: str = "the drawer") -> dict:
    did = uuid.uuid4().hex[:10]
    now = time.time()
    row = {"pk": f"drawer#{did}", "id": did, "owner": owner, "boxes": boxes,
           "facts": [{"subject": b, "source": "BOX", "confirmed_at": now} for b in boxes],
           "findings": [], "seen_keys": [], "last_checked": None, "history": [],
           "subscribers": [], "created": now}
    _backend.put(row)
    return row


def get_drawer(did: str) -> dict | None:
    return _backend.get(f"drawer#{did}")


def list_drawers() -> list[dict]:
    return _backend.prefix("drawer#")


def confirm_fact(did: str, subject: str, source: str = "PERSON") -> dict | None:
    row = get_drawer(did)
    if not row:
        return None
    for f in row["facts"]:
        if f["subject"] == subject:
            f["confirmed_at"] = time.time()
            f["source"] = source
    _backend.set(f"drawer#{did}", facts=row["facts"])
    return get_drawer(did)


def set_findings(did: str, findings: list[dict], trace_len: int) -> dict:
    """Record a Watchman pass and return what is new since the last one.

    'New' is by key, not by count: the same recall showing up again tomorrow
    is not news, and a page that shouts every night trains people to ignore it.
    """
    row = get_drawer(did)
    seen = set(row.get("seen_keys") or [])
    new = [f for f in findings if f.get("key") and f["key"] not in seen]
    seen |= {f["key"] for f in findings if f.get("key")}
    entry = {"at": time.time(), "findings": len(findings), "new": len(new), "tool_calls": trace_len}
    history = (row.get("history") or [])[-29:] + [entry]
    _backend.set(f"drawer#{did}", findings=findings, seen_keys=sorted(seen),
                 last_checked=time.time(), history=history, last_new=new)
    return {"new": new, "total": len(findings)}


def add_subscriber(did: str, email: str) -> None:
    row = get_drawer(did)
    subs = row.get("subscribers") or []
    if email not in subs:
        subs.append(email)
    _backend.set(f"drawer#{did}", subscribers=subs)
