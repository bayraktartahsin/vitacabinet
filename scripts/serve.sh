#!/usr/bin/env bash
# Run the web app locally, with credentials.
#
#   scripts/serve.sh [--port 8080]
#
# For running by hand. The Claude Code preview launcher cannot execute a shell
# script from this directory, so that path instead relies on ~/.aws/credentials,
# which boto3 reads on its own with no environment wiring at all — see
# scripts/aws-configure.sh. Either way the keys file stays where it is and its
# values are never written anywhere that could be committed.
#
# Without credentials the app still runs: /scan needs only the public NIH and
# FDA APIs, and /question reports that the writing model is unavailable rather
# than failing the page. That is deliberate — the drawer is still worth reading
# when Bedrock is not reachable.

set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

# shellcheck source=/dev/null
source scripts/dev-env.sh || echo "  continuing without AWS — /question will say so"

exec .venv/bin/python -m uvicorn app.api:app --port "${PORT:-8080}" "$@"
