#!/usr/bin/env bash
# check.sh: the Lab 6 self-check. It shows what the grader will see, gate by gate.
#
# Run it in the Ubuntu (WSL) terminal, in the root of your clone:
#   bash lab06-test-and-release/check.sh
#
# It only reads: your fork through the GitHub API, and your image from ghcr.io without logging in.
# It changes nothing. It uses a GitHub token if it finds one (GITHUB_TOKEN, or `gh auth token`),
# or asks for one and hides what you paste. The token is sent only to api.github.com.
# Without a token it still works, but a classroom shares one address and GitHub allows
# only 60 calls an hour without one.
#
# Exit code: 0 = every gate the script can check passes, 1 = not yet, 2 = wrong usage.
set -euo pipefail

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) echo "✘ Use the Ubuntu (WSL) terminal, not Git Bash or PowerShell."; exit 2 ;;
esac
command -v python3 >/dev/null || { echo "✘ python3 is missing. In Ubuntu: sudo apt install -y python3"; exit 2; }

exec python3 -I "$(dirname "$0")/check.py" "$@"
