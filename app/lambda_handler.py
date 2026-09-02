"""The Lambda entry point. One function, three kinds of event.

  An HTTP request from API Gateway  -> the FastAPI app, via Mangum.
  {"job": "<id>"}                    -> run that reading in the background.
                                        (The HTTP path invoked us asynchronously,
                                        because the gateway gives it 30 seconds
                                        and the agents want more.)
  {"source": "schedule"}             -> the nightly pass: every saved drawer is
                                        re-read by the Watchman, and anyone
                                        subscribed hears about what is *new*.

Credentials come from the execution role. Nothing in this codebase reads a key.
"""
from __future__ import annotations

import logging

from mangum import Mangum

from . import store
from .api import app, notify, run_job

log = logging.getLogger("vitacabinet.lambda")
_http = Mangum(app, lifespan="off")


def nightly() -> dict:
    from .agents.run import read_drawer
    checked, told = 0, 0
    for row in store.list_drawers():
        try:
            result = read_drawer(row["boxes"])
            diff = store.set_findings(row["id"], result["findings"], len(result["trace"]))
            checked += 1
            if diff["new"]:
                notify(row["id"], diff["new"])
                told += 1
        except Exception:                                    # noqa: BLE001
            log.exception("nightly: drawer %s", row.get("id"))
    return {"checked": checked, "notified": told}


def handler(event, context):
    if isinstance(event, dict):
        if event.get("job") and event.get("source") != "schedule":
            run_job(event["job"])
            return {"ok": True, "job": event["job"]}
        if event.get("source") == "schedule":
            return nightly()
    return _http(event, context)
