#!/usr/bin/env bash
# Load AWS credentials for local development.
#
#   source scripts/dev-env.sh
#
# Reads the git-ignored keys file and exports the standard AWS variables and
# nothing else. Values are never echoed — the only output is whether each one
# was found and how long it is, which is enough to debug a bad paste without
# putting a secret in a terminal that scrolls back, gets screen-shared, or ends
# up in a recording.
#
# Deployed code never reads this file. On AgentCore the same variables arrive
# from the task role, so the application only ever knows about the environment.

set -uo pipefail

# Locate this script whether it was sourced from bash or zsh. BASH_SOURCE is
# unset in zsh, which is the default shell here, so the zsh form comes first
# and bash falls through to its own.
if [ -n "${ZSH_VERSION:-}" ]; then
  _self="${(%):-%x}"
else
  _self="${BASH_SOURCE[0]:-$0}"
fi
KEYS="$(cd "$(dirname "$_self")/.." && pwd)/vitacabinet keys.rtf"
unset _self

if [ ! -f "$KEYS" ]; then
  echo "  no keys file at: ${KEYS##*/}" >&2
  return 1 2>/dev/null || exit 1
fi

# textutil strips the RTF wrapper; the file is plain text underneath.
_raw="$(textutil -stdout -convert txt "$KEYS" 2>/dev/null || cat "$KEYS")"

export AWS_ACCESS_KEY_ID="$(printf '%s\n' "$_raw" | awk -F': *' '/^Access key/{print $2}' | tr -d ' \r')"
export AWS_SECRET_ACCESS_KEY="$(printf '%s\n' "$_raw" | awk -F': *' '/^Secret access key/{print $2}' | tr -d ' \r')"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-eu-north-1}"
export AWS_REGION="$AWS_DEFAULT_REGION"
unset _raw

if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
  echo "  keys file found but could not be parsed" >&2
  echo "  expected lines: 'Access key: AKIA...' and 'Secret access key: ...'" >&2
  return 1 2>/dev/null || exit 1
fi

echo "  aws ready · key ${#AWS_ACCESS_KEY_ID} chars · secret ${#AWS_SECRET_ACCESS_KEY} chars · ${AWS_DEFAULT_REGION}"
