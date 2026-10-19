#!/usr/bin/env bash
# Lab 4 Compose clinic. From your fork: bash lab04-multi-service-compose/clinic.sh setup
# Then: bash ~/compose-clinic/clinic.sh check N | hint N | reset N | down N | status | export | clean
set -euo pipefail
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) echo "✘ Use the Ubuntu (WSL) terminal, not Git Bash or PowerShell."; exit 1 ;;
esac
command -v python3 >/dev/null || { echo "✘ python3 is missing. In Ubuntu: sudo apt install -y python3"; exit 1; }
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
export PYTHONDONTWRITEBYTECODE=1          # no tools/__pycache__ in the student's fork
exec python3 "$here/tools/clinic.py" "$@"
