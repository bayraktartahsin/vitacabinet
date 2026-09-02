#!/usr/bin/env python3
"""Put VitaCabinet on a public URL.

    python scripts/deploy.py

Builds a Lambda zip, creates (or updates) the function, and gives it a public
Function URL. Idempotent: run it again after any change and it updates in
place rather than making a second one.

Lambda rather than a container, for one reason: there is no Docker on this
machine and there is no reason to require one. The app is a FastAPI app either
way — `app/lambda_handler.py` is four lines of adapter, not a second
implementation. Nothing about the deployed behaviour differs from the local
one, which is the only way a demo is worth anything.

The function gets its AWS credentials from its execution role, exactly as the
local process gets them from ~/.aws/credentials: the application reads neither.
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent
REGION = "eu-north-1"
FUNCTION = "vitacabinet"
ROLE = "vitacabinet-lambda"
TABLE = "vitacabinet"
TOPIC = "vitacabinet-watchman"
SCHEDULE = "vitacabinet-nightly"
BUILD = ROOT / ".build"

# Only what the app imports directly. boto3 is not listed because the Lambda
# runtime already has it — though strands-agents depends on it and pulls it in
# regardless, which is most of the 28MB. Left alone deliberately: pruning a
# transitive SDK to save upload seconds is how a deploy starts differing from
# the thing that was tested.
DEPS = ["fastapi", "mangum", "httpx", "pydantic", "strands-agents",
        "email-validator", "python-multipart"]

TRUST = {
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"},
        "Action": "sts:AssumeRole",
    }],
}

# What the function is allowed to touch, and nothing else: the models, its own
# table, its own topic, and itself (a scan is handed to a second, asynchronous
# invocation because API Gateway will not wait more than 30 seconds).
def policy(account: str) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Resource": "*",
             "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]},
            {"Effect": "Allow",
             "Resource": f"arn:aws:dynamodb:{REGION}:{account}:table/{TABLE}",
             "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
                        "dynamodb:Scan", "dynamodb:Query"]},
            {"Effect": "Allow",
             "Resource": f"arn:aws:sns:{REGION}:{account}:{TOPIC}",
             "Action": ["sns:Publish", "sns:Subscribe"]},
            {"Effect": "Allow",
             "Resource": f"arn:aws:lambda:{REGION}:{account}:function:{FUNCTION}",
             "Action": ["lambda:InvokeFunction"]},
        ],
    }


def say(msg: str) -> None:
    print(f"  {msg}", flush=True)


def count_tests() -> int:
    """The number the closing card shows. Counted, not typed, so it cannot
    drift from the suite the way a hand-written '38' once did."""
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                         capture_output=True, text=True, cwd=ROOT).stdout
    return sum(1 for ln in out.splitlines() if "::" in ln)


def build_zip() -> bytes:
    """Application code plus its dependencies, and nothing else."""
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir()

    say(f"installing {len(DEPS)} dependencies for linux/arm64…")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "--target", str(BUILD),
         "--platform", "manylinux2014_aarch64", "--implementation", "cp",
         "--python-version", "3.12", "--only-binary=:all:", *DEPS],
        check=True, cwd=ROOT)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in BUILD.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                z.write(path, path.relative_to(BUILD))
        for sub in ("app", "web"):
            for path in (ROOT / sub).rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    z.write(path, path.relative_to(ROOT))

    data = buf.getvalue()
    say(f"zip is {len(data) / 1e6:.1f} MB")
    if len(data) > 50_000_000:
        sys.exit("  zip exceeds Lambda's 50MB direct-upload limit")
    return data


def ensure_role(iam) -> str:
    try:
        arn = iam.get_role(RoleName=ROLE)["Role"]["Arn"]
        say(f"role exists: {ROLE}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
        say(f"creating role {ROLE}…")
        arn = iam.create_role(
            RoleName=ROLE,
            AssumeRolePolicyDocument=json.dumps(TRUST),
            Description="VitaCabinet on Lambda: writes logs, invokes Bedrock.",
        )["Role"]["Arn"]
        iam.attach_role_policy(
            RoleName=ROLE,
            PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")
        say("waiting for the role to propagate…")
        time.sleep(12)

    return arn


def ensure_table(ddb) -> None:
    """One table, one key. Jobs expire; drawers do not."""
    try:
        ddb.describe_table(TableName=TABLE)
        say(f"table exists: {TABLE}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        say(f"creating table {TABLE}…")
        ddb.create_table(TableName=TABLE, BillingMode="PAY_PER_REQUEST",
                         AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
                         KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}])
        ddb.get_waiter("table_exists").wait(TableName=TABLE)
    try:
        ddb.update_time_to_live(TableName=TABLE,
                                TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires"})
    except ClientError as e:
        if "already enabled" not in e.response["Error"]["Message"].lower():
            say(f"ttl: {e.response['Error']['Code']}")


def ensure_topic(sns) -> str:
    """The Watchman's way of saying 'something new' — and only something new."""
    arn = sns.create_topic(Name=TOPIC)["TopicArn"]
    say(f"topic: {TOPIC}")
    return arn


def ensure_schedule(events, lam, account: str) -> None:
    """Nightly. Recalls arrive when they arrive; nobody opens an app for them."""
    rule = events.put_rule(Name=SCHEDULE, ScheduleExpression="rate(1 day)",
                           State="ENABLED",
                           Description="VitaCabinet: the Watchman re-reads every drawer")["RuleArn"]
    fn_arn = f"arn:aws:lambda:{REGION}:{account}:function:{FUNCTION}"
    events.put_targets(Rule=SCHEDULE, Targets=[{
        "Id": "watchman", "Arn": fn_arn,
        "Input": json.dumps({"source": "schedule", "job": "watchman"})}])
    try:
        lam.add_permission(FunctionName=FUNCTION, StatementId="eventbridge-nightly",
                           Action="lambda:InvokeFunction", Principal="events.amazonaws.com",
                           SourceArn=rule)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceConflictException":
            raise
    say(f"schedule: {SCHEDULE} (rate(1 day))")


def ensure_function(lam, role_arn: str, code: bytes, topic_arn: str) -> None:
    common = dict(
        Handler="app.lambda_handler.handler",
        Runtime="python3.12",
        Timeout=300,         # a background reading runs two agents; the HTTP path
        MemorySize=1024,     # answers in milliseconds and never waits on this
        Environment={"Variables": {
            "VITACABINET_MODEL": "eu.amazon.nova-lite-v1:0",
            "VITACABINET_TABLE": TABLE,
            "VITACABINET_TOPIC": topic_arn,
            "VITACABINET_FUNCTION": FUNCTION,
            "VITACABINET_TESTS": str(count_tests()),
        }},
    )
    try:
        lam.get_function(FunctionName=FUNCTION)
        say("updating the existing function…")
        lam.update_function_code(FunctionName=FUNCTION, ZipFile=code)
        _wait(lam)
        lam.update_function_configuration(FunctionName=FUNCTION, Role=role_arn, **common)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        say("creating the function…")
        lam.create_function(FunctionName=FUNCTION, Role=role_arn,
                            Code={"ZipFile": code}, Architectures=["arm64"], **common)
    _wait(lam)


def _wait(lam) -> None:
    for _ in range(60):
        s = lam.get_function(FunctionName=FUNCTION)["Configuration"]
        if s.get("LastUpdateStatus") != "InProgress" and s.get("State") != "Pending":
            return
        time.sleep(2)


def ensure_url(lam, account: str) -> str:
    """A public front door, via API Gateway rather than a Lambda Function URL.

    The Function URL was the obvious choice and it does not work here. Created
    with AuthType NONE and the exact resource policy AWS documents — Principal
    "*", lambda:InvokeFunctionUrl, the FunctionUrlAuthType condition — it still
    answers 403 AccessDeniedException to anonymous callers. The console shows
    the policy without complaint, the account is in no organization so no SCP
    is in play, direct lambda:Invoke of the same function returns 200, and
    deleting and recreating the URL config changes nothing. The block is above
    the policy layer and not visible from here.

    An HTTP API is public by default and needs no resource policy for anonymous
    callers, so it sidesteps the whole question. It is also the more ordinary
    way to put a web application in front of a Lambda.
    """
    api = boto3.client("apigatewayv2", region_name=REGION)

    existing = [a for a in api.get_apis(MaxResults="500")["Items"]
                if a["Name"] == FUNCTION]
    if existing:
        api_id = existing[0]["ApiId"]
        say(f"api exists: {api_id}")
    else:
        say("creating the HTTP API…")
        api_id = api.create_api(
            Name=FUNCTION, ProtocolType="HTTP",
            Target=f"arn:aws:lambda:{REGION}:{account}:function:{FUNCTION}",
            CorsConfiguration={"AllowOrigins": ["*"], "AllowMethods": ["*"],
                               "AllowHeaders": ["*"]},
        )["ApiId"]

    # The quick-create Target above wires $default -> the function. API Gateway
    # invokes it as a service principal, so this is the permission that matters.
    try:
        lam.add_permission(
            FunctionName=FUNCTION, StatementId="apigateway-invoke",
            Action="lambda:InvokeFunction", Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:aws:execute-api:{REGION}:{account}:{api_id}/*/*")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceConflictException":
            raise

    return f"https://{api_id}.execute-api.{REGION}.amazonaws.com"


def main(infra_only: bool = False) -> None:
    print("\nVitaCabinet → AWS Lambda\n")
    account = boto3.client("sts").get_caller_identity()["Account"]
    iam = boto3.client("iam")
    role_arn = ensure_role(iam)
    iam.put_role_policy(RoleName=ROLE, PolicyName="vitacabinet",
                        PolicyDocument=json.dumps(policy(account)))
    ensure_table(boto3.client("dynamodb", region_name=REGION))
    topic_arn = ensure_topic(boto3.client("sns", region_name=REGION))
    if infra_only:
        print("\n  infrastructure ready\n")
        return
    code = build_zip()
    lam = boto3.client("lambda", region_name=REGION)
    ensure_function(lam, role_arn, code, topic_arn)
    url = ensure_url(lam, account)
    ensure_schedule(boto3.client("events", region_name=REGION), lam, account)
    shutil.rmtree(BUILD, ignore_errors=True)
    print(f"\n  live at  {url}\n")


if __name__ == "__main__":
    main(infra_only="--infra" in sys.argv)
