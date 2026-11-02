#!/usr/bin/env bash
# break.sh: Lab 7, Part 4. Brings in a "tidy-up" from a teammate that breaks your manifests in three
# ways. You find each one with the debug loop.
#
# Run it in the Ubuntu (WSL) terminal, in the root of your clone, on an up-to-date main,
# after Part 3 (your k8s/ is merged and works):
#   git switch main && git pull
#   bash lab07-run-it-on-a-cluster/break.sh
#
# It makes ONE commit on a new branch, chore/tidy-manifests, and changes two files in k8s/.
# It never pushes and never touches your cluster: you apply the branch yourself.
#
# Exit code: 0 = the commit is made, 2 = nothing was changed (the reason is printed).
set -euo pipefail

BRANCH="chore/tidy-manifests"
MESSAGE="chore(k8s): tidy up the manifests"

refuse() { printf '✘ %s\n' "$1"; exit 2; }

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) refuse "Use the Ubuntu (WSL) terminal, not Git Bash or PowerShell." ;;
esac
command -v python3 >/dev/null || refuse "python3 is missing. In Ubuntu: sudo apt install -y python3"

[[ -d .git && -d k8s ]] ||
  refuse "Run this in the root of your clone (the folder with k8s/ and .git/): cd ~/turiba-devops-labs"
for f in k8s/api-deployment.yaml k8s/api-service.yaml; do
  [[ -f $f ]] || refuse "$f is missing. Part 1 asks for exactly these file names."
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
dep = pathlib.Path('k8s/api-deployment.yaml')
svc = pathlib.Path('k8s/api-service.yaml')
d, s = dep.read_text(encoding='utf-8'), svc.read_text(encoding='utf-8')

image = re.compile(r'''(?m)((?:^|[{,])\s*-?\s*image:\s*["']?ghcr\.io/[^\s:"']+/api:)([^\s"',}#]+)''')
selector = re.compile(r'''(?m)(?<![\w./-])app(\s*:\s*["']?api["']?)(?=\s*(?:[,}#]|$))''')
target = re.compile(r'''(?m)(targetPort:\s*["']?)5000(?!\d)''')

def refuse(text):
    print('✘ ' + text)
    sys.exit(2)

found = image.findall(d)
if len(found) != 1:
    refuse('k8s/api-deployment.yaml needs exactly one image line like "image: ghcr.io/<you>/turiba-devops-labs/api:<tag>".')
if found[0][1] == '0.2.O':
    refuse('The image tag is already 0.2.O: break.sh has already run here.')
if not selector.search(s):
    refuse('k8s/api-service.yaml has no selector "app: api". Part 1 asks for that label.')
if not target.search(s):
    refuse('k8s/api-service.yaml has no "targetPort: 5000". Part 1 asks for the number, not a port name.')

if mode == 'apply':
    dep.write_text(image.sub(lambda m: m.group(1) + '0.2.O', d), encoding='utf-8', newline='')
    s = selector.sub(lambda m: 'app.kubernetes.io/name' + m.group(1), s)
    svc.write_text(target.sub(lambda m: m.group(1) + '8080', s), encoding='utf-8', newline='')
PY
}

edit check
git switch --quiet -c "$BRANCH"
edit apply
git add k8s/api-deployment.yaml k8s/api-service.yaml
git commit --quiet -m "$MESSAGE"

cat <<EOF
✔ One commit on the new branch $BRANCH: "$MESSAGE"
  It changes k8s/api-deployment.yaml and k8s/api-service.yaml.

Next:
  1. git push -u origin HEAD, then open a pull request into main in YOUR fork.
     No check runs on k8s/: this time you are the check.
  2. 🔮 Before you apply it: what will you see first?
  3. kubectl apply -f k8s/   (this branch, on your own cluster)
  4. Use the debug loop to find all three faults. Fix each in its own commit, apply, push.
  5. Merge when 3 Pods are Ready and GET / answers through port-forward.
EOF
