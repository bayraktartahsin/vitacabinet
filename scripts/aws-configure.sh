#!/usr/bin/env bash
# Put the local AWS credentials where boto3 looks by default.
#
#   bash scripts/aws-configure.sh
#
# Writes ~/.aws/credentials and ~/.aws/config at mode 600, reading the values
# from the git-ignored keys file through shell variables. Nothing is echoed and
# nothing is written inside this repository.
#
# This exists because the dev-server launcher cannot source a shell script, and
# an application that has to be handed credentials by its launcher is one that
# will eventually have them pasted into a config file that gets committed. The
# shared credentials file is where the AWS SDKs already look, so the app needs
# no configuration for them at all — which is also true on AgentCore, where the
# task role supplies them the same invisible way.

set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

# shellcheck source=/dev/null
source scripts/dev-env.sh

mkdir -p "$HOME/.aws"
umask 077

printf '[default]\naws_access_key_id = %s\naws_secret_access_key = %s\n' \
  "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" > "$HOME/.aws/credentials"
printf '[default]\nregion = %s\noutput = json\n' \
  "${AWS_DEFAULT_REGION:-eu-north-1}" > "$HOME/.aws/config"

chmod 600 "$HOME/.aws/credentials" "$HOME/.aws/config"
echo "  wrote ~/.aws/credentials and ~/.aws/config (mode 600)"
