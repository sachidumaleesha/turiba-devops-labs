#!/usr/bin/env bash
# break.sh: Lab 9, Part 4. Brings in a "tidy-up" of your chart from a teammate that breaks it in three ways.
# You find each one with helm and kubectl.
#
# Run it in the Ubuntu (WSL) terminal, in the root of your clone, on an up-to-date main,
# after Part 3 (your chart is merged and installed):
#   git switch main && git pull
#   bash lab09-package-it/break.sh
#
# It makes ONE commit on a new branch, chore/tidy-chart. It changes two files in charts/course-app/ and adds one.
# It never pushes and never touches your cluster: you upgrade your release with the branch yourself.
#
# Exit code: 0 = the commit is made, 2 = nothing was changed (the reason is printed).
set -euo pipefail

BRANCH="chore/tidy-chart"
MESSAGE="chore(chart): tidy up values and templates"
CHART="charts/course-app"

refuse() { printf '✘ %s\n' "$1"; exit 2; }

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) refuse "Use the Ubuntu (WSL) terminal, not Git Bash or PowerShell." ;;
esac
command -v python3 >/dev/null || refuse "python3 is missing. In Ubuntu: sudo apt install -y python3"

[[ -d .git && -d $CHART ]] ||
  refuse "Run this in the root of your clone (the folder with $CHART/ and .git/): cd ~/turiba-devops-labs"
for f in "$CHART/values.yaml" "$CHART/templates/api-deployment.yaml"; do
  [[ -f $f ]] || refuse "$f is missing. Parts 1–2 ask for exactly these file names."
done
[[ ! -e $CHART/templates/namespace.yaml ]] ||
  refuse "$CHART/templates/namespace.yaml already exists. The Namespace stays outside the chart (Part 1): delete that file first."
[[ -z "$(git config user.name || true)" ]] &&
  refuse "Git doesn't know your name yet: git config --global user.name \"Your Name\" (Lab 3, Part 0)"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] ||
  refuse "You have uncommitted changes. Commit or stash them first (git status shows them)."
[[ "$(git branch --show-current)" == "main" ]] ||
  refuse "Switch to main first: git switch main && git pull"
git show-ref --verify --quiet "refs/heads/$BRANCH" &&
  refuse "The branch $BRANCH already exists: break.sh has already run here. Carry on with that branch."

# The three edits. "check" only looks; "apply" changes the files. Both refuse if a pattern is missing.
edit() {
  python3 -I - "$1" "$CHART" <<'PY'
import pathlib, re, sys

mode, chart = sys.argv[1], pathlib.Path(sys.argv[2])
values = chart / 'values.yaml'
dep = chart / 'templates' / 'api-deployment.yaml'
ns = chart / 'templates' / 'namespace.yaml'
v, d = values.read_text(encoding='utf-8'), dep.read_text(encoding='utf-8')

# `replicas: 3` (any number, quoted or not), indented under api:
replicas = re.compile(r'''(?m)^([ \t]+)replicas(\s*:\s*["']?\d+["']?[ \t]*(?:#.*)?)$''')
repo_ref = re.compile(r'\.Values\.api\.image\.repository\b')

def refuse(text):
    print('✘ ' + text)
    sys.exit(2)

if re.search(r'(?m)^\s+replicaCount\s*:', v) or '.Values.api.images.' in d:
    refuse('Your chart already has the teammate\'s changes: break.sh has already run here.')
if len(replicas.findall(v)) != 1:
    refuse('charts/course-app/values.yaml needs exactly one "replicas: <number>" under "api:". Part 2 asks for that value.')
if len(repo_ref.findall(d)) != 1:
    refuse('charts/course-app/templates/api-deployment.yaml needs exactly one ".Values.api.image.repository" '
           '(the image line, Part 2).')

if mode == 'apply':
    values.write_text(replicas.sub(lambda m: m.group(1) + 'replicaCount' + m.group(2), v), encoding='utf-8', newline='')
    dep.write_text(repo_ref.sub('.Values.api.images.repository', d), encoding='utf-8', newline='')
    ns.write_text('# The chart brings its own namespace, so nobody has to create it by hand.\n'
                  'apiVersion: v1\n'
                  'kind: Namespace\n'
                  'metadata:\n'
                  '  name: {{ .Release.Namespace }}\n', encoding='utf-8', newline='')
PY
}

edit check
git switch --quiet -c "$BRANCH"
edit apply
git add "$CHART/values.yaml" "$CHART/templates/api-deployment.yaml" "$CHART/templates/namespace.yaml"
git commit --quiet -m "$MESSAGE"

cat <<EOF
✔ One commit on the new branch $BRANCH: "$MESSAGE"
  It changes $CHART/values.yaml and $CHART/templates/api-deployment.yaml,
  and adds $CHART/templates/namespace.yaml.

Next:
  1. git push -u origin HEAD, then open a pull request into main in YOUR fork.
     No check runs on the chart: this time you are the check.
  2. 🔮 Before you upgrade: what will you see first?
  3. helm upgrade course-app $CHART -n course   (this branch, on your own cluster, where main is installed)
  4. Find all three faults. Fix each in its own commit, upgrade again, push.
  5. Merge when helm upgrade works, kubectl -n course get deployment api shows 3/3,
     and GET /api/todos answers through port-forward.
EOF
