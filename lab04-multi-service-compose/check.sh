#!/usr/bin/env bash
# Lab 4 self-check: what the grader will see, before the grader sees it.
# From the root of your fork: bash lab04-multi-service-compose/check.sh preflight|stack|writeup|clinic|fresh|all
set -euo pipefail
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) echo "✘ Use the Ubuntu (WSL) terminal, not Git Bash or PowerShell."; exit 1 ;;
esac
command -v python3 >/dev/null || { echo "✘ python3 is missing. In Ubuntu: sudo apt install -y python3"; exit 1; }
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
export PYTHONDONTWRITEBYTECODE=1          # no tools/__pycache__ in the student's fork
exec python3 "$here/tools/check.py" "$@"
