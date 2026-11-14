#!/usr/bin/env bash
# break.sh: Lab 8, Part 4. Brings in a "tidy-up" from a teammate that breaks your app in three ways.
# You find each one with the debug loop.
#
# Run it in the Ubuntu (WSL) terminal, in the root of your clone, on an up-to-date main,
# after Part 3 (your k8s/ is merged and works):
#   git switch main && git pull
#   bash lab08-run-the-whole-app/break.sh
#
# It makes ONE commit on a new branch, chore/tidy-config, and changes two files in k8s/.
# It never pushes and never touches your cluster: you apply the branch yourself.
#
# Exit code: 0 = the commit is made, 2 = nothing was changed (the reason is printed).
set -euo pipefail

BRANCH="chore/tidy-config"
MESSAGE="chore(k8s): tidy up config and probes"

refuse() { printf '✘ %s\n' "$1"; exit 2; }

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) refuse "Use the Ubuntu (WSL) terminal, not Git Bash or PowerShell." ;;
esac
command -v python3 >/dev/null || refuse "python3 is missing. In Ubuntu: sudo apt install -y python3"

[[ -d .git && -d k8s ]] ||
  refuse "Run this in the root of your clone (the folder with k8s/ and .git/): cd ~/turiba-devops-labs"
for f in k8s/app-config.yaml k8s/api-deployment.yaml; do
  [[ -f $f ]] || refuse "$f is missing. Parts 1–2 ask for exactly these file names."
done
[[ -z "$(git config user.name || true)" ]] &&
  refuse "Git doesn't know your name yet: git config --global user.name \"Your Name\" (Lab 3, Part 0)"
[[ -z "$(git status --porcelain)" ]] ||
  refuse "You have uncommitted changes. Commit or stash them first (git status shows them)."
[[ "$(git branch --show-current)" == "main" ]] ||
  refuse "Switch to main first: git switch main && git pull"
git show-ref --verify --quiet "refs/heads/$BRANCH" &&
  refuse "The branch $BRANCH already exists: break.sh has already run here. Carry on with that branch."

# The three edits. "check" only looks; "apply" changes the files. Both refuse if a pattern is missing.
edit() {
  python3 -I - "$1" <<'PY'
import pathlib, re, sys

mode = sys.argv[1]
cfg = pathlib.Path('k8s/app-config.yaml')
dep = pathlib.Path('k8s/api-deployment.yaml')
c, d = cfg.read_text(encoding='utf-8'), dep.read_text(encoding='utf-8')

host = re.compile(r'''(?m)((?:^|[{,])\s*DB_HOST\s*:\s*["']?)db(?=["']?\s*(?:[,}#]|$))''')
key = re.compile(r'''(?m)(\bkey\s*:\s*["']?)password(?=["']?\s*(?:[,}#]|$))''')
port = re.compile(r'''(?<![A-Za-z])(port\s*:\s*["']?)5000(?!\d)''')

def refuse(text):
    print('✘ ' + text)
    sys.exit(2)

if re.search(r'''(?m)(?:^|[{,])\s*DB_HOST\s*:\s*["']?database''', c):
    refuse('DB_HOST is already "database": break.sh has already run here.')
if len(host.findall(c)) != 1:
    refuse('k8s/app-config.yaml needs exactly one "DB_HOST: db". Part 1 asks for that value.')
if len(key.findall(d)) != 1:
    refuse('k8s/api-deployment.yaml needs exactly one "key: password" (the secretKeyRef for DB_PASSWORD, Part 2).')

start = d.find('readinessProbe')
if start < 0:
    refuse('k8s/api-deployment.yaml has no readinessProbe yet. Do Part 3 first.')
match = port.search(d, start)
if not match or re.search(r'livenessProbe|startupProbe|containerPort|initContainers|\n\s*- name:', d[start:match.start()]):
    refuse('The readinessProbe in k8s/api-deployment.yaml needs "httpGet" with "port: 5000" (a number). Part 3 asks for that.')

if mode == 'apply':
    cfg.write_text(host.sub(lambda m: m.group(1) + 'database', c), encoding='utf-8', newline='')
    d = d[:match.start()] + match.group(1) + '5001' + d[match.end():]
    dep.write_text(key.sub(lambda m: m.group(1) + 'pasword', d), encoding='utf-8', newline='')
PY
}

edit check
git switch --quiet -c "$BRANCH"
edit apply
git add k8s/app-config.yaml k8s/api-deployment.yaml
git commit --quiet -m "$MESSAGE"

cat <<EOF
✔ One commit on the new branch $BRANCH: "$MESSAGE"
  It changes k8s/app-config.yaml and k8s/api-deployment.yaml.

Next:
  1. git push -u origin HEAD, then open a pull request into main in YOUR fork.
     No check runs on k8s/: this time you are the check.
  2. 🔮 Before you apply it: what will you see first?
  3. kubectl apply -f k8s/   (this branch, on your own cluster, where main already runs)
  4. Use the debug loop to find all three faults. Fix each in its own commit, apply, push.
  5. Merge when every Pod is Ready and GET /api/todos answers through port-forward.
EOF
