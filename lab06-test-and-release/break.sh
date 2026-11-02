#!/usr/bin/env bash
# break.sh: Lab 6, Part 2. Brings in a change from a "teammate" that keeps lint and the tests
# green but stops your image from starting. Your smoke test should catch it.
#
# Run it in the Ubuntu (WSL) terminal, in the root of your clone, on an up-to-date main:
#   git switch main && git pull
#   bash lab06-test-and-release/break.sh
#
# It makes ONE commit on a new branch, feat/startup-banner, and changes three files in api/.
# It never pushes: you push and open the pull request yourself.
#
# Exit code: 0 = the commit is made, 2 = nothing was changed (the reason is printed).
set -euo pipefail

BRANCH="feat/startup-banner"
MESSAGE="feat(api): log a startup banner"

refuse() { printf '✘ %s\n' "$1"; exit 2; }

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) refuse "Use the Ubuntu (WSL) terminal, not Git Bash or PowerShell." ;;
esac

[[ -d .git && -f api/server.js ]] ||
  refuse "Run this in the root of your clone (the folder with api/ and .git/): cd ~/turiba-devops-labs"
[[ -z "$(git config user.name || true)" ]] &&
  refuse "Git doesn't know your name yet: git config --global user.name \"Your Name\" (Lab 3, Part 0)"
[[ -e api/banner.js ]] &&
  refuse "api/banner.js already exists: break.sh has already run here. Look for the branch $BRANCH."
[[ -z "$(git status --porcelain)" ]] ||
  refuse "You have uncommitted changes. Commit or stash them first (git status shows them)."
[[ "$(git branch --show-current)" == "main" ]] ||
  refuse "Switch to main first: git switch main && git pull"
git show-ref --verify --quiet "refs/heads/$BRANCH" &&
  refuse "The branch $BRANCH already exists. Delete it (git branch -D $BRANCH) or carry on with it."

git switch --quiet -c "$BRANCH"

# 1. A new module that prints one line when the API starts.
cat > api/banner.js <<'EOF'
// Prints one line when the API starts, so the container log shows which version is running.
const { name, version } = require('./package.json');

console.log(`${name} ${version} starting (Node.js ${process.version})`);
EOF

# 2. server.js loads it. Append after a final newline, so the last line stays intact.
if [[ -s api/server.js && -n "$(tail -c 1 api/server.js)" ]]; then
  printf '\n' >> api/server.js
fi
printf '\n// Startup banner\nrequire('"'"'./banner'"'"');\n' >> api/server.js

# 3. The teammate also "tidied up" the build context.
if [[ -s api/.dockerignore && -n "$(tail -c 1 api/.dockerignore)" ]]; then
  printf '\n' >> api/.dockerignore
fi
printf '# Local helper scripts, not needed in the image\nbanner.js\n' >> api/.dockerignore

git add api/banner.js api/server.js api/.dockerignore
git commit --quiet -m "$MESSAGE"

cat <<EOF
✔ One commit on the new branch $BRANCH: "$MESSAGE"
  It changes api/banner.js (new), api/server.js and api/.dockerignore.

Next:
  1. git push -u origin HEAD
  2. Open a pull request into main in YOUR fork, and watch the checks.
     Before you look: which of lint, unit, integration and image will go red?
  3. Find the cause in the log, fix it on this branch, push, and merge when all four are green.
EOF
