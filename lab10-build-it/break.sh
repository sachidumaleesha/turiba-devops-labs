#!/usr/bin/env bash
# break.sh: Lab 10, Part 4. Brings in a "tidy-up" of your infra/ from a teammate that breaks it in three ways.
# You find each one with tofu.
#
# Run it in the Ubuntu (WSL) terminal (or the macOS Terminal), in the root of your clone, on an up-to-date main,
# after Part 3 (your infra/ is merged and your cluster is up from tofu apply):
#   git switch main && git pull
#   bash lab10-build-it/break.sh
#
# It makes ONE commit on a new branch, chore/tidy-infra. It changes one or two files in infra/.
# It never pushes and never runs tofu: you plan and apply the branch yourself.
#
# Exit code: 0 = the commit is made, 2 = nothing was changed (the reason is printed).
set -euo pipefail

BRANCH="chore/tidy-infra"
MESSAGE="chore(infra): tidy up providers and paths"

refuse() { printf '✘ %s\n' "$1"; exit 2; }

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) refuse "Use the Ubuntu (WSL) terminal, not Git Bash or PowerShell." ;;
esac
command -v python3 >/dev/null || refuse "python3 is missing. In Ubuntu: sudo apt install -y python3"

[[ -d .git ]] ||
  refuse "Run this in the root of your clone (the folder with infra/ and .git/): cd ~/turiba-devops-labs"
[[ -d infra ]] ||
  refuse "There is no infra/ folder here yet. Parts 1–3 come first: infra/ merged into main."
[[ -z "$(git config user.name || true)" ]] &&
  refuse "Git doesn't know your name yet: git config --global user.name \"Your Name\" (Lab 3, Part 0)"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] ||
  refuse "You have uncommitted changes. Commit or stash them first (git status shows them)."
[[ "$(git branch --show-current)" == "main" ]] ||
  refuse "Switch to main first: git switch main && git pull"
git show-ref --verify --quiet "refs/heads/$BRANCH" &&
  refuse "The branch $BRANCH already exists: break.sh has already run here. Carry on with that branch."

# The three edits. "check" only looks; "apply" changes the files and prints their names.
# Both refuse if a pattern is missing or appears more than once.
edit() {
  python3 -I - "$1" <<'PY'
import glob, re, sys

mode = sys.argv[1]
files = {p: open(p, encoding='utf-8', newline='').read() for p in sorted(glob.glob('infra/*.tf'))}


def refuse(text):
    print('✘ ' + text)
    sys.exit(2)


def in_comment(text, pos):
    line = text[text.rfind('\n', 0, pos) + 1:pos]
    return '#' in line or '//' in line


def block_end(t, i):
    """t[i] is '{'. Index of the matching '}', skipping strings, comments and heredocs; -1 if none."""
    depth, n = 0, len(t)
    while i < n:
        c = t[i]
        if c == '#' or t.startswith('//', i):
            j = t.find('\n', i)
            i = n if j < 0 else j
            continue
        if t.startswith('/*', i):
            j = t.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue
        heredoc = re.match(r'<<-?([A-Za-z_]\w*)[ \t]*\r?\n', t[i:i + 80]) if t.startswith('<<', i) else None
        if heredoc:
            end = re.compile(r'(?m)^[ \t]*' + re.escape(heredoc.group(1)) + r'[ \t]*\r?$').search(t, i + heredoc.end())
            i = n if end is None else end.end()
            continue
        if c == '"':
            i += 1
            while i < n and t[i] != '"':
                if t[i] == '\\':
                    i += 1
                elif t.startswith('${', i):
                    d = 0
                    while i < n:
                        d += (t[i] == '{') - (t[i] == '}')
                        if d == 0 and t[i] == '}':
                            break
                        i += 1
                i += 1
            i += 1
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


source = re.compile(r'(\bsource\s*=\s*"(?:registry\.opentofu\.org/)?)tehcyx/kind"')
broken_source = re.compile(r'\bsource\s*=\s*"(?:registry\.opentofu\.org/)?hashicorp/kind"')
helm_start = re.compile(r'(?m)^[ \t]*resource\s+"helm_release"\s+"[^"]+"\s*\{')
ns_line = re.compile(r'(?m)^([ \t]*namespace[ \t]*)=[^\n]*?(\r?)$')
chart_line = re.compile(r'(?m)^[ \t]*chart[ \t]*=[^\n]*$')

sources = [(p, m) for p, t in files.items() for m in source.finditer(t) if not in_comment(t, m.start())]
helms = [(p, m) for p, t in files.items() for m in helm_start.finditer(t)]
already = any(broken_source.search(t) for t in files.values())
if len(helms) == 1:
    p, m = helms[0]
    t = files[p]
    end = block_end(t, m.end() - 1)
    body = t[m.end():end] if end > 0 else ''
    already = already or '"courses"' in body or re.search(r'(?m)^[ \t]*chart[ \t]*=.*[^s]chart/course-app', body)

if already:
    refuse("Your infra/ already has the teammate's changes: break.sh has already run here.")
if len(sources) != 1:
    refuse('infra/ needs exactly one source = "tehcyx/kind" in required_providers (Part 1). '
           f'Found {len(sources)}.')
if len(helms) != 1:
    refuse(f'infra/ needs exactly one resource "helm_release" (Part 2). Found {len(helms)}.')
if end < 0:
    refuse(f'{p}: the helm_release block has no closing brace. tofu validate shows where.')
namespaces = list(ns_line.finditer(body))
charts = list(chart_line.finditer(body))
if len(namespaces) != 1:
    refuse('Your helm_release needs exactly one "namespace = ..." line (Part 2).')
if len(charts) != 1 or charts[0].group(0).count('charts/course-app') != 1:
    refuse('Your helm_release needs one "chart = ..." line with the path to charts/course-app (Part 2).')

if mode == 'apply':
    start, (sp, sm) = m.end(), sources[0]
    ns, ch = namespaces[0], charts[0]
    edits = {p: [(start + ns.start(), start + ns.end(), ns.group(1) + '= "courses"' + ns.group(2)),
                 (start + ch.start(), start + ch.end(), ch.group(0).replace('charts/course-app', 'chart/course-app'))]}
    edits.setdefault(sp, []).append((sm.start(), sm.end(), sm.group(1) + 'hashicorp/kind"'))
    for path in sorted(edits):
        text = files[path]
        for a, b, new in sorted(edits[path], reverse=True):     # from the end, so earlier positions stay right
            text = text[:a] + new + text[b:]
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        print(path)
PY
}

edit check
git switch --quiet -c "$BRANCH"
CHANGED=()
while IFS= read -r f; do CHANGED+=("$f"); done < <(edit apply)     # not mapfile: macOS has bash 3.2
git add -- "${CHANGED[@]}"
git commit --quiet -m "$MESSAGE"

cat <<EOF
✔ One commit on the new branch $BRANCH: "$MESSAGE"
  It changes ${CHANGED[*]}.

Next:
  1. git push -u origin HEAD, then open a pull request into main in YOUR fork.
     No check runs on infra/: this time you are the check.
  2. 🔮 Before you plan: what will you see first?
  3. cd infra && tofu plan   (this branch, against the cluster you made in Part 3)
  4. Find all three faults. Fix each in its own commit, plan again, push.
     Read every plan before you type yes.
  5. Merge when tofu plan shows no replacement (-/+), tofu apply works,
     kubectl -n course get deployment api shows 3/3, and GET /api/todos answers through port-forward.
EOF
