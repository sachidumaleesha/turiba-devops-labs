#!/usr/bin/env bash
# check.sh: the Lab 9 self-check. It shows what the grader will see, gate by gate.
#
# Run it in the Ubuntu (WSL) terminal, in the root of your clone:
#   bash lab09-package-it/check.sh
#
# It reads your fork through the GitHub API, runs helm lint and helm template on charts/course-app from your
# main, and tests it on a throwaway kind cluster (lab9-check), which it deletes again. Add --no-fresh to skip
# the cluster part.
# It changes nothing in your fork, your own cluster or your Helm setup. It uses a GitHub token if it finds one
# (GITHUB_TOKEN, or `gh auth token`), or asks for one and hides what you paste. The token is sent only to
# api.github.com. Without a token it still works, but a classroom shares one address and GitHub allows
# only 60 calls an hour without one.
#
# Exit code: 0 = every gate the script can check passes, 1 = not yet, 2 = wrong usage.
set -euo pipefail

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) echo "✘ Use the Ubuntu (WSL) terminal, not Git Bash or PowerShell."; exit 2 ;;
esac
command -v python3 >/dev/null || { echo "✘ python3 is missing. In Ubuntu: sudo apt install -y python3"; exit 2; }

exec python3 -I "$(dirname "$0")/check.py" "$@"
