#!/usr/bin/env bash
# ghcr-check.sh: check your GitHub Container Registry (GHCR) setup before Lab 5.
# Draft for Turiba DevOps v02, Session 5 (written 2026-10-16).
#
# Run it in the Ubuntu (WSL) terminal:
#   bash ghcr-check.sh                  check only (the default). Changes nothing.
#   bash ghcr-check.sh --delete NAME    delete ONE of your container packages.
#                                         You must type the package name to confirm.
#
# It asks for a GitHub token (classic) and hides what you paste. Your Lab 1 token works
# if it has not expired. The token stays in memory only. It is never printed, logged or
# saved, and it is sent only to api.github.com.
#
# Exit code: 0 = no problems, 1 = problems found (see the list at the end), 2 = wrong usage.
set -euo pipefail

COURSE_REPO="mleitass/turiba-devops-labs"
REPO="turiba-devops-labs"
CI_IMAGE=""
DELETE_NAME=""
TOKEN_STDIN=0

API="https://api.github.com"
GHCR="https://ghcr.io"
RAW="https://raw.githubusercontent.com"
# Only for testing against a local mock server. A real run never sets this.
if [[ -n "${GHCR_CHECK_TEST_BASE:-}" ]]; then
  case "$GHCR_CHECK_TEST_BASE" in
    http://127.0.0.1:*|http://localhost:*)
      API="$GHCR_CHECK_TEST_BASE/api"; GHCR="$GHCR_CHECK_TEST_BASE/ghcr"; RAW="$GHCR_CHECK_TEST_BASE/raw" ;;
    *) echo "✘ GHCR_CHECK_TEST_BASE must start with http://127.0.0.1: or http://localhost:"; exit 2 ;;
  esac
fi

usage() {
  cat <<'EOF'
Check your GHCR packages before Lab 5. By default it only reads and reports.

  bash ghcr-check.sh                  check only. Changes nothing.
  bash ghcr-check.sh --delete NAME    delete ONE of your container packages
                                        (asks you to type the name to confirm)

Options:
  --repo NAME       the name of your fork (default: turiba-devops-labs)
  --ci-image NAME   the package your Lab 5 workflow pushes to (default: <repo>/api)
  --delete NAME     delete the container package NAME. The token needs delete:packages.
  --token-stdin     read the token from standard input instead of asking, e.g.
                      gh auth token | bash ghcr-check.sh --token-stdin
  -h, --help        show this help

The token must be a GitHub token (classic) with read:packages (write:packages
includes it). Fine-grained tokens don't work with GitHub Packages.
EOF
}

die_usage() { echo "✘ $1"; echo "  Run: bash ghcr-check.sh --help"; exit 2; }

while (($#)); do
  case "$1" in
    --repo)        [[ $# -ge 2 ]] || die_usage "--repo needs a name."; REPO=$2; shift 2 ;;
    --ci-image)    [[ $# -ge 2 ]] || die_usage "--ci-image needs a name."; CI_IMAGE=$2; shift 2 ;;
    --delete)      [[ $# -ge 2 ]] || die_usage "--delete needs a package name."; DELETE_NAME=$2; shift 2 ;;
    --token-stdin) TOKEN_STDIN=1; shift ;;
    -h|--help)     usage; exit 0 ;;
    *)             die_usage "Unknown option: $1" ;;
  esac
done

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) echo "✘ Use the Ubuntu (WSL) terminal, not Git Bash or PowerShell."; exit 2 ;;
esac
for tool in curl python3; do
  command -v "$tool" >/dev/null || { echo "✘ $tool is missing. In Ubuntu: sudo apt install -y $tool"; exit 2; }
done

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

RE_PKG='^[a-z0-9]+([._-]+[a-z0-9]+)*(/[a-z0-9]+([._-]+[a-z0-9]+)*)*$'
[[ $REPO =~ ^[A-Za-z0-9._-]+$ ]] || die_usage "That is not a repository name: $REPO"
[[ -n $CI_IMAGE ]] || CI_IMAGE="$(lower "$REPO")/api"
[[ $CI_IMAGE =~ $RE_PKG ]] || die_usage "Package names are lowercase letters, digits, '.', '_', '-' and '/': $CI_IMAGE"
if [[ -n $DELETE_NAME && ! $DELETE_NAME =~ $RE_PKG ]]; then
  die_usage "Package names are lowercase letters, digits, '.', '_', '-' and '/': $DELETE_NAME"
fi

PROBLEMS=0
WARNINGS=0
TODO=()     # browser steps to do now
LATER=()    # checks after the first push in Lab 5
DELETED=0

section() { printf '\n%s\n' "$*"; }
ok()      { printf '  ✔ %s\n' "$*"; }
warn()    { WARNINGS=$((WARNINGS + 1)); printf '  ⚠ %s\n' "$*"; }
bad()     { PROBLEMS=$((PROBLEMS + 1)); printf '  ✘ %s\n' "$*"; }
info()    { printf '    %s\n' "$*"; }
todo()    { TODO+=("$1"); }
later()   { LATER+=("$1"); }
numbered() { # numbered TITLE ITEM...
  local title=$1 n=0 item
  shift
  printf '\n%s\n' "$title"
  for item in "$@"; do
    n=$((n + 1))
    printf '  %d. %s\n\n' "$n" "$item"
  done
}

TMP=$(mktemp -d)
chmod 700 "$TMP"
TOKEN=""
trap 'TOKEN=""; rm -rf "$TMP"' EXIT

tty_ok() { { : </dev/tty; } 2>/dev/null; }

# ---------------------------------------------------------------- the token
if ((TOKEN_STDIN)); then
  IFS= read -r TOKEN || true
else
  tty_ok || { echo "✘ No terminal to ask for the token. Use --token-stdin."; exit 2; }
  cat <<'EOF'
GHCR check for Lab 5. It only reads, unless you used --delete.

Paste a GitHub token (classic) with the read:packages scope.
Your Lab 1 token (devops-course-ghcr) works if it has not expired.
Nothing appears while you paste. That's normal. Then press Enter.
EOF
  printf 'Token: '
  IFS= read -rs TOKEN </dev/tty || true
  printf '\n'
fi
TOKEN=${TOKEN//[[:space:]]/}

if [[ -z $TOKEN ]]; then
  echo "✘ No token. Run the script again and paste the token."; exit 1
fi
case $TOKEN in
  github_pat_*)
    echo "✘ This is a fine-grained token. GitHub Packages only accepts tokens (classic)."
    echo "  Make one: Lab 1, Part 4.1 (tick write:packages). Then run this script again."
    exit 1 ;;
esac
if [[ ! $TOKEN =~ ^[A-Za-z0-9_]{20,255}$ ]]; then
  echo "✘ That doesn't look like a GitHub token (they start with ghp_). Copy it again."; exit 1
fi

# ---------------------------------------------------------------- helpers
# api METHOD PATH: prints the HTTP status code. Body goes to $TMP/body, headers to $TMP/headers.
# The token goes to curl on a pipe (-K -), so it never shows up in the process list.
api() {
  local code
  code=$(printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" |
    curl -sS --max-time 30 -K - -X "$1" -H "Accept: application/vnd.github+json" \
      -D "$TMP/headers" -o "$TMP/body" -w '%{http_code}' "$API$2" 2>"$TMP/curl-error") || code="000"
  printf '%s' "$code"
}

header_value() { # header_value NAME: the value of a response header from the last api call
  { grep -i "^$1:" "$TMP/headers" || true; } | tail -n 1 | cut -d: -f2- | tr -d '\r' | sed 's/^ *//'
}

# pyjson MODE FILE [ARG]: read GitHub JSON and print tab-separated lines.
pyjson() {
  python3 -I -c '
import json, sys
mode, path = sys.argv[1], sys.argv[2]
arg = sys.argv[3] if len(sys.argv) > 3 else ""
with open(path, encoding="utf-8") as f:
    data = json.load(f)
def row(*xs):
    print("\t".join(str(x).replace("\t", " ").replace("\n", " ") for x in xs))
if mode == "login":
    print(data.get("login", ""))
elif mode == "repo":
    row(str(bool(data.get("fork"))).lower(), (data.get("parent") or {}).get("full_name") or "-",
        str(bool(data.get("private"))).lower())
elif mode == "packages":
    for p in data:
        row(p.get("name", ""), p.get("visibility", ""), (p.get("repository") or {}).get("full_name") or "-")
elif mode == "workflows":
    for w in data.get("workflows", []):
        row(w.get("path", ""), w.get("state", ""))
elif mode == "prs":
    for pr in data:
        if ((pr.get("user") or {}).get("login") or "").lower() == arg.lower():
            row(pr.get("number", ""), pr.get("html_url", ""))
elif mode == "tags":
    tags = []
    for v in data:
        tags += ((v.get("metadata") or {}).get("container") or {}).get("tags") or []
    print(" ".join(tags) if tags else "(no tags)")
    print(len(data))
' "$@"
}

urlencode() { python3 -I -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"; }

# anon_pull OWNER/NAME: succeeds if anyone can pull the image without logging in.
# That is what kind needs in S7 when there is no imagePullSecret.
anon_pull() {
  local body tok code
  body=$(curl -sS --max-time 20 "$GHCR/token?scope=repository:$1:pull" 2>/dev/null) || return 1
  tok=$(printf '%s' "$body" | python3 -I -c '
import json, sys
try:
    print(json.load(sys.stdin).get("token", ""))
except Exception:
    print("")')
  [[ -n $tok ]] || return 1
  code=$(printf 'header = "Authorization: Bearer %s"\n' "$tok" |
    curl -sS --max-time 20 -K - -o /dev/null -w '%{http_code}' "$GHCR/v2/$1/tags/list" 2>/dev/null) || return 1
  [[ $code == 200 ]]
}

pkg_get() { # pkg_get NAME COLUMN: 1 name, 2 visibility, 3 connected repository, 4 anonymous pull
  awk -F '\t' -v n="$1" -v c="$2" '$1 == n { print $c; exit }' "$TMP/packages.tsv"
}
pkg_exists() { [[ -n "$(pkg_get "$1" 1)" ]]; }

ui_packages_page() { printf 'github.com → your picture (top right) → Your profile → Packages → %s → Package settings (right side)' "$1"; }
ui_make_public() {
  printf 'Make %s public: %s → Danger Zone → Change visibility → Public → type the name → confirm. (Same as Lab 1, Part 4.5.)' \
    "$1" "$(ui_packages_page "$1")"
}
ui_actions_access() {
  printf '%s\n     If "Inherited access" shows "Inherit access from repository" ticked and your fork is listed, stop: nothing to do.\n     Otherwise, under "Manage Actions access": Add repository → %s → Role: Write.' \
    "Give your fork's workflow write access to $1: $(ui_packages_page "$1")." "$REPO"
}
ui_delete() {
  printf 'Delete %s in the browser: %s → Danger zone → Delete this package → type the name → confirm.' \
    "$1" "$(ui_packages_page "$1")"
}

# ---------------------------------------------------------------- 1. account
section "1. Your token and account"
code=$(api GET /user)
case $code in
  200) ;;
  401) bad "GitHub says the token is wrong or has expired."
       info "Make a new token (classic) with write:packages: Lab 1, Part 4.1. Then run this script again."
       exit 1 ;;
  000) bad "Can't reach api.github.com. Check your internet connection."; exit 1 ;;
  *)   bad "GitHub answered HTTP $code to the account check. Try again in a minute."; exit 1 ;;
esac
LOGIN=$(pyjson login "$TMP/body")
SCOPES=$(header_value x-oauth-scopes | tr -d ' ')
EXPIRES=$(header_value github-authentication-token-expiration)
has_scope() { [[ ",$SCOPES," == *",$1,"* ]]; }

if ! has_scope read:packages && ! has_scope write:packages; then
  bad "The token can't read packages. Its scopes: ${SCOPES:-none}."
  info "Make a new token (classic) with write:packages: Lab 1, Part 4.1. Then run this script again."
  exit 1
fi
ok "The token works. You are $LOGIN."
[[ -z $EXPIRES ]] || info "The token expires: $EXPIRES"

LC=$(lower "$LOGIN")
FORK="$LOGIN/$REPO"
if [[ $LC != "$LOGIN" ]]; then
  warn "Your username has capital letters: $LOGIN. Image names must be lowercase."
  info "Docker refuses capitals with: repository name must be lowercase"
  info "Always write it like this: $LC"
fi

# ---------------------------------------------------------------- 2. names
section "2. The image name for Lab 5 and S7"
ok "Your workflow pushes to: ghcr.io/$LC/$CI_IMAGE:<commit SHA>"
info "In S7, kind pulls exactly this name."
if [[ $CI_IMAGE == "$(lower "$REPO")/api" ]]; then
  info "In the workflow, bash makes it lowercase: ghcr.io/\${GITHUB_REPOSITORY,,}/api"
fi

# ---------------------------------------------------------------- 3. fork
section "3. Your fork"
FORK_FOUND=0
code=$(api GET "/repos/$FORK")
if [[ $code == 200 ]]; then
  FORK_FOUND=1
  IFS=$'\t' read -r is_fork parent is_private < <(pyjson repo "$TMP/body") || true
  if [[ $is_fork == true && $(lower "$parent") == "$COURSE_REPO" ]]; then
    ok "$FORK is a fork of $COURSE_REPO."
  else
    warn "$FORK is not a fork of $COURSE_REPO (parent: $parent)."
  fi
  if [[ $is_private == true ]]; then
    warn "$FORK is private. Images built there can be private too, and the grader can't see your work."
  fi
elif [[ $code == 404 ]]; then
  bad "There is no repository called $FORK."
  info "If your fork has another name, run: bash ghcr-check.sh --repo <its name>"
else
  warn "Couldn't read $FORK (HTTP $code)."
fi

# ---------------------------------------------------------------- 4. packages
section "4. Your container packages on ghcr.io"
code=$(api GET "/user/packages?package_type=container&per_page=100")
if [[ $code != 200 ]]; then
  bad "Couldn't list your packages (HTTP $code)."
  info "The token needs read:packages. Make a new one: Lab 1, Part 4.1."
  exit 1
fi
pyjson packages "$TMP/body" >"$TMP/packages.raw"
: >"$TMP/packages.tsv"
while IFS=$'\t' read -r name vis repo; do
  if anon_pull "$LC/$name"; then pull=yes; else pull=no; fi
  printf '%s\t%s\t%s\t%s\n' "$name" "$vis" "$repo" "$pull" >>"$TMP/packages.tsv"
done <"$TMP/packages.raw"

if [[ ! -s $TMP/packages.tsv ]]; then
  info "You have no container packages yet."
else
  printf '    %-28s %-11s %-34s %s\n' "PACKAGE" "VISIBILITY" "CONNECTED REPOSITORY" "PULL WITHOUT LOGIN"
  while IFS=$'\t' read -r name vis repo pull; do
    printf '    %-28s %-11s %-34s %s\n' "$name" "$vis" "$repo" "$pull"
  done <"$TMP/packages.tsv"
  echo
fi

# Lab 1 and Lab 2 images: hand-ins. Lab 5 doesn't need them, so they stay as they are.
for pair in "lab1-web:Lab 1" "course-api:Lab 2"; do
  name=${pair%%:*}
  lab=${pair#*:}
  [[ $name != "$CI_IMAGE" ]] || continue
  if ! pkg_exists "$name"; then
    info "$name: not found. That only matters if your $lab hand-in uses it."
  elif [[ $(pkg_get "$name" 2) == public && $(pkg_get "$name" 4) == yes ]]; then
    ok "$name is public ($lab hand-in). Lab 5 doesn't use it. Keep it."
  else
    warn "$name is $(pkg_get "$name" 2). Your $lab hand-in needs it public."
    todo "$(ui_make_public "$name")"
  fi
done

# The package the Lab 5 workflow pushes to.
if ! pkg_exists "$CI_IMAGE"; then
  ok "$CI_IMAGE doesn't exist yet. Good: your first push to main creates it with GITHUB_TOKEN"
  info "and connects it to your fork automatically."
  later "When the workflow on main is green, run this script again. It checks that ghcr.io/$LC/$CI_IMAGE
     can be pulled without logging in. If not, make it public, or kind can't pull it in S7:
     $(ui_make_public "$CI_IMAGE")"
else
  repo=$(pkg_get "$CI_IMAGE" 3)
  if [[ $(lower "$repo") == "$(lower "$FORK")" ]]; then
    ok "$CI_IMAGE exists and is connected to your fork."
    if [[ $CI_IMAGE == lab1-web || $CI_IMAGE == course-api ]]; then
      warn "$CI_IMAGE was pushed from your laptop. A script can't see if your workflow may push to it."
      info "If not, the push fails with: denied: permission_denied: write_package"
      todo "$(ui_actions_access "$CI_IMAGE")"
    fi
    if [[ $(pkg_get "$CI_IMAGE" 4) == yes ]]; then
      ok "$CI_IMAGE is public. kind can pull it in S7."
    else
      warn "$CI_IMAGE is $(pkg_get "$CI_IMAGE" 2). kind can't pull it in S7 (ImagePullBackOff)."
      todo "$(ui_make_public "$CI_IMAGE")"
    fi
  else
    if [[ $repo == "-" ]]; then repo="no repository"; fi
    bad "$CI_IMAGE exists, but it isn't connected to your fork (connected to: $repo)."
    info "Your workflow's push will probably fail with: denied: permission_denied: write_package"
    info "Fix 1 (if nothing in it matters): bash ghcr-check.sh --delete $CI_IMAGE, then push again."
    info "Fix 2: give your fork write access in the browser (see the steps at the end)."
    todo "$(ui_actions_access "$CI_IMAGE")"
  fi
fi

# ---------------------------------------------------------------- 5. workflows
section "5. GitHub Actions in your fork"
WORKFLOWS=0
if ((FORK_FOUND)); then
  code=$(api GET "/repos/$FORK/actions/workflows?per_page=100")
  if [[ $code == 200 ]]; then
    pyjson workflows "$TMP/body" >"$TMP/workflows.tsv"
    if [[ ! -s $TMP/workflows.tsv ]]; then
      info "No workflow files yet. That's normal before Lab 5."
    fi
    while IFS=$'\t' read -r path state; do
      WORKFLOWS=$((WORKFLOWS + 1))
      case $state in
        active) ok "$path is active." ;;
        disabled_fork)
          bad "$path is switched off because this is a fork."
          todo "Switch on Actions in your fork: open https://github.com/$FORK/actions and click
     \"I understand my workflows, go ahead and enable them\"." ;;
        *)
          warn "$path is $state."
          todo "Switch on $path: https://github.com/$FORK/actions → click the workflow on the left → Enable workflow." ;;
      esac
    done <"$TMP/workflows.tsv"
  else
    warn "Couldn't read the workflow list (HTTP $code)."
  fi
else
  info "Skipped: fork not found."
fi
if ((WORKFLOWS == 0)); then
  later "Open https://github.com/$FORK/actions after you push ci.yml. If GitHub says
     \"Workflows aren't being run on this forked repository\", click
     \"I understand my workflows, go ahead and enable them\", then push again."
fi

# ---------------------------------------------------------------- 6. course repo PRs
section "6. Pull requests in the course repo"
code=$(api GET "/repos/$COURSE_REPO/pulls?state=open&per_page=100")
if [[ $code == 200 ]]; then
  pyjson prs "$TMP/body" "$LOGIN" >"$TMP/prs.tsv"
  if [[ ! -s $TMP/prs.tsv ]]; then
    ok "You have no open pull requests in $COURSE_REPO. Good."
  fi
  while IFS=$'\t' read -r number url; do
    warn "Pull request #$number is open in the COURSE repo, not in your fork: $url"
    info "There, your workflow gets a read-only token and no secrets, and it may wait for the lecturer's approval."
    todo "Close pull request #$number in the course repo: $url → Close pull request.
     Open it again in your fork: base repository $FORK, base main."
  done <"$TMP/prs.tsv"
else
  warn "Couldn't read the course repo's pull requests (HTTP $code)."
fi

# ---------------------------------------------------------------- 7. Dockerfile label
section "7. The source label in api/Dockerfile"
want="https://github.com/$(lower "$FORK")"
dcode=$(curl -sS --max-time 20 -o "$TMP/Dockerfile" -w '%{http_code}' "$RAW/$FORK/HEAD/api/Dockerfile" 2>/dev/null) || dcode="000"
if [[ $dcode == 200 ]]; then
  label=$({ grep -i 'org.opencontainers.image.source' "$TMP/Dockerfile" || true; } | head -n 1 | tr -d '\r' | sed 's/[[:space:]]*$//')
  if [[ -z $label ]]; then
    warn "api/Dockerfile has no org.opencontainers.image.source label (Lab 2, step 2.5)."
  elif [[ $(lower "$label") == *"$want\""* || $(lower "$label") == *"$want" ]]; then
    ok "The label points to your fork."
  else
    warn "The label doesn't point to your fork: $label"
    info "It should be: LABEL org.opencontainers.image.source=\"https://github.com/$FORK\""
  fi
elif [[ $dcode == 404 ]]; then
  warn "No api/Dockerfile on the default branch of $FORK (Lab 2 adds it)."
else
  warn "Couldn't read api/Dockerfile (HTTP $dcode)."
fi

# ---------------------------------------------------------------- delete (only with --delete)
if [[ -n $DELETE_NAME ]]; then
  section "Delete a package: $DELETE_NAME"
  if ! pkg_exists "$DELETE_NAME"; then
    bad "You have no container package called $DELETE_NAME. Nothing was deleted."
  elif ! has_scope delete:packages; then
    bad "Your token can't delete packages. Its scopes: ${SCOPES:-none}."
    info "Easiest: delete it in the browser (see the steps at the end)."
    info "Or make a new token (classic) with read:packages and delete:packages, expiry 7 days."
    todo "$(ui_delete "$DELETE_NAME")"
  elif ! tty_ok; then
    bad "No terminal to type the confirmation. Nothing was deleted."
  else
    enc=$(urlencode "$DELETE_NAME")
    tags="(couldn't read the tags)"
    versions="?"
    code=$(api GET "/user/packages/container/$enc/versions?per_page=100")
    if [[ $code == 200 ]]; then
      { IFS= read -r tags; IFS= read -r versions; } < <(pyjson tags "$TMP/body") || true
    fi
    info "Package:    ghcr.io/$LC/$DELETE_NAME"
    info "Visibility: $(pkg_get "$DELETE_NAME" 2). Connected to: $(pkg_get "$DELETE_NAME" 3)"
    info "Versions:   $versions. Tags: $tags"
    info "ALL versions and tags go. Anyone who pulls this image gets an error."
    case $DELETE_NAME in
      lab1-web)   info "This is your Lab 1 hand-in image. Its pull check will fail after this." ;;
      course-api) info "This is your Lab 2 hand-in image (course-api:lab2). Its pull check will fail after this." ;;
    esac
    info "You can restore it for 30 days: Settings → Packages → Deleted packages → Restore."
    info "That only works while no new package with the same name exists."
    printf '\n  Type the package name to delete it, or just press Enter to cancel: '
    answer=""
    IFS= read -r answer </dev/tty || true
    if [[ $answer == "$DELETE_NAME" ]]; then
      code=$(api DELETE "/user/packages/container/$enc")
      case $code in
        204) DELETED=1
             ok "Deleted $DELETE_NAME. Run this script again to see the new state." ;;
        403) bad "GitHub refused (HTTP 403). The token may lack delete:packages. Nothing was deleted." ;;
        404) bad "GitHub didn't find it (HTTP 404). Nothing was deleted." ;;
        *)   bad "GitHub answered HTTP $code. Nothing was deleted." ;;
      esac
    else
      info "Cancelled. Nothing was deleted."
    fi
  fi
fi

# ---------------------------------------------------------------- summary
section "Summary"
if ((PROBLEMS == 0 && WARNINGS == 0)); then
  ok "No problems found."
else
  info "$PROBLEMS problem(s), $WARNINGS warning(s)."
fi
if ((${#TODO[@]} > 0)); then
  numbered "Do these steps in the browser now. A script can't do them:" "${TODO[@]}"
fi
if ((${#LATER[@]} > 0)); then
  numbered "After your first push to main in Lab 5:" "${LATER[@]}"
fi
((DELETED)) || echo "Nothing was changed on GitHub."
((PROBLEMS == 0)) || exit 1
exit 0
