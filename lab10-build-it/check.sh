#!/usr/bin/env bash
# check.sh: the Lab 10 self-check. It shows what the grader will see, gate by gate.
#
# Run it in the Ubuntu (WSL) terminal (or the macOS Terminal), in the root of your clone:
#   bash lab10-build-it/check.sh
#
# It reads your fork through the GitHub API and copies infra/ and charts/course-app from your main into a temporary
# folder. It reads the .tf files first and runs nothing outside the Mission 10 allowlist. Then tofu fmt, init,
# validate and plan, and a build from zero on a throwaway cluster (lab10-check): apply, the app, plan, destroy,
# apply again, destroy. About 5 minutes and 1.5 GB of memory. Add --no-fresh to skip the cluster part.
# Run `tofu destroy` in infra/ first: the throwaway cluster is built only when no other kind cluster runs
# (two at once hit a Linux limit in WSL, "too many open files").
# It changes nothing in your fork, your state or ~/.kube/config. Providers are cached in
# ~/.cache/lab10-tofu-plugins, so only the first run downloads them (about 170 MB).
# It uses a GitHub token if it finds one (GITHUB_TOKEN, or `gh auth token`), or asks for one and hides what you
# paste. The token is sent only to api.github.com. Without a token it still works, but a classroom shares one
# address and GitHub allows only 60 calls an hour without one.
#
# Exit code: 0 = every gate the script can check passes, 1 = not yet, 2 = wrong usage.
set -euo pipefail

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) echo "✘ Use the Ubuntu (WSL) terminal, not Git Bash or PowerShell."; exit 2 ;;
esac
command -v python3 >/dev/null || { echo "✘ python3 is missing. In Ubuntu: sudo apt install -y python3"; exit 2; }

exec python3 -I "$(dirname "$0")/check.py" "$@"
