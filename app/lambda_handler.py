"""The Lambda entry point.

The same FastAPI application that runs locally, wrapped for Lambda's event
shape. Nothing about the app changes: no branch on "am I in the cloud", no
second code path that only the judges see and only the deploy exercises.

Credentials arrive from the execution role, which is why nothing in this
codebase ever reads a key file — locally boto3 finds ~/.aws/credentials, here
it finds the role, and the application knows about neither.
"""
from __future__ import annotations

from mangum import Mangum

from .api import app

handler = Mangum(app, lifespan="off")
