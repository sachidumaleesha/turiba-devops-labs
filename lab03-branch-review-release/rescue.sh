#!/usr/bin/env bash
# Lab 3 · Part 3 · Rescue missions
# DevOps (ELE1013M), Turiba University
#
#   bash lab03-branch-review-release/rescue.sh setup <your-github-user>   create the missions
#   bash ~/git-rescue/rescue.sh status                                    which missions pass
#   bash ~/git-rescue/rescue.sh check N                                   check mission N
#   bash ~/git-rescue/rescue.sh reset N                                   create mission N again
#
# Each mission is a small repository in ~/git-rescue/mN with one problem.
# Read ~/git-rescue/mN/MISSION.txt, fix the problem with Git, then run check.
# A solved mission prints "PASS mN <code>": paste that line into lab3/README.md.
# One rule: don't delete .git and start again.
#
# Needs bash 3.2+ and Git 2.23+. Touches nothing outside ~/git-rescue ($RESCUE_ROOT if set).

set -u

ROOT="${RESCUE_ROOT:-$HOME/git-rescue}"
STATE="$ROOT/.state"
REMOTES="$ROOT/.remotes"
SALT="turiba-devops-lab3-2026"
MISSIONS="1 2 3 4 5 6 7 8"

die() { echo "rescue.sh: $*" >&2; exit 2; }

case "$ROOT" in "" | "/" | "$HOME" | "$HOME/") die "RESCUE_ROOT must be a folder of its own, not '$ROOT'" ;; esac

# ---------------------------------------------------------------- helpers

user() {
  [ -s "$ROOT/.user" ] || die "run setup first: bash lab03-branch-review-release/rescue.sh setup <your-github-user>"
  cat "$ROOT/.user"
}

sha8() {
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum | cut -c1-8
  else
    printf '%s' "$1" | shasum -a 256 | cut -c1-8
  fi
}

# The grader recomputes this code from your GitHub username (rubric gate G9).
code() { sha8 "lab3:m$1:$(user):$SALT"; }

pass() { echo "PASS m$1 $(code "$1")"; }
fail() { echo "FAIL m$1: $2"; return 1; }

save() { printf '%s\n' "$2" > "$STATE/$1"; }
load() { cat "$STATE/$1" 2>/dev/null; }

# Git for the setup steps only: a fixed author, no signing, no hooks, LF files,
# whatever the student's own Git config says. Any failure stops the setup:
# exit leaves the setup subshell, and the caller sees the failure.
sg() {
  GIT_AUTHOR_NAME="Lab 3" GIT_AUTHOR_EMAIL="lab3@example.invalid" \
  GIT_COMMITTER_NAME="Lab 3" GIT_COMMITTER_EMAIL="lab3@example.invalid" \
  git -c commit.gpgsign=false -c tag.gpgsign=false -c core.autocrlf=false \
      -c core.hooksPath=/dev/null -c advice.detachedHead=false "$@" ||
    { echo "rescue.sh: setup step failed: git $*" >&2; exit 3; }
}

put() {        # put <file> <line>...   write a file, creating folders
  local f="$1"; shift
  mkdir -p "$(dirname "$f")"
  printf '%s\n' "$@" > "$f"
}

add_line() { printf '%s\n' "$2" >> "$1"; }

newrepo() {    # an empty repository on branch main; MISSION.txt and ANSWER stay out of git status
  rm -rf "$1" && mkdir -p "$1" || return 1
  git init -q "$1" && git -C "$1" symbolic-ref HEAD refs/heads/main || return 1
  printf '%s\n' MISSION.txt ANSWER >> "$1/.git/info/exclude"
}

newremote() {
  rm -rf "$1" && git init -q --bare "$1" && git -C "$1" symbolic-ref HEAD refs/heads/main
}

mission() {    # mission <dir> <line>...   write MISSION.txt
  local d="$1"; shift
  printf '%s\n' "$@" > "$d/MISSION.txt"
}

enter() {
  cd "$ROOT/m$1" 2>/dev/null || { fail "$1" "$ROOT/m$1 is missing: bash ~/git-rescue/rescue.sh reset $1"; return 1; }
}

# ---------------------------------------------------------------- mission 1 · worked example

setup_1() {
  local d="$ROOT/m1"
  newrepo "$d" || return 1
  ( cd "$d" || exit 3
    put deploy.sh '#!/bin/sh' 'set -e' 'echo "Deploying course-api"' 'docker compose pull' 'docker compose up -d'
    sg add deploy.sh
    sg commit -qm "feat: add deploy script"
    put deploy.sh '#!/bin/sh' 'set -e' 'echo "Deploying course-api"' 'docker compsoe pull' 'docker compose up -d --scale api=0' 'sleep 99999'
  ) || return 1
  save m1.head "$(git -C "$d" rev-parse HEAD)"
  mission "$d" \
    "Mission 1 · worked example (Lab 3 guide, step 3.1)" \
    "" \
    "You were \"improving\" deploy.sh and broke it. Nothing is staged or committed." \
    "" \
    "Goal: deploy.sh exactly as in the last commit, and a clean working tree." \
    "" \
    "Start with: git status, git diff" \
    "Check:      bash ~/git-rescue/rescue.sh check 1"
}

check_1() {
  enter 1 || return
  [ "$(git rev-parse HEAD)" = "$(load m1.head)" ] ||
    { fail 1 "HEAD has moved, but this mission needs no commit. Start again: bash ~/git-rescue/rescue.sh reset 1"; return; }
  [ -z "$(git status --porcelain)" ] ||
    { fail 1 "the working tree isn't clean yet. What does git status say about deploy.sh?"; return; }
  pass 1
}

# ---------------------------------------------------------------- mission 2 · .env staged by mistake

setup_2() {
  local d="$ROOT/m2"
  newrepo "$d" || return 1
  ( cd "$d" || exit 3
    put app.js 'const express = require("express");' 'const app = express();' 'app.listen(5000);'
    sg add app.js
    sg commit -qm "feat: add app"
    put app.js 'const express = require("express");' 'const app = express();' 'const PORT = process.env.PORT || 5000;' 'app.listen(PORT);'
    put .env 'DB_PASSWORD=SuperSecret123'
    sg add app.js .env
  ) || return 1
  mission "$d" \
    "Mission 2 · a password in the index" \
    "" \
    "You ran: git add app.js .env" \
    "app.js has a real change: the port now comes from PORT. .env holds a database password." \
    "" \
    "Goal: commit ONLY the app.js change. .env must not be in any commit," \
    "and Git must ignore it from now on." \
    "" \
    "Start with: git status" \
    "Check:      bash ~/git-rescue/rescue.sh check 2"
}

check_2() {
  enter 2 || return
  if git log --branches --format= --name-only | grep -qx '.env'; then
    fail 2 "a commit contains .env. It isn't pushed, so undo that commit and commit again without .env (slide 17)"; return
  fi
  if git ls-files --error-unmatch .env >/dev/null 2>&1; then
    fail 2 ".env is still staged: git status lists it under 'Changes to be committed'"; return
  fi
  git grep -q 'process.env.PORT' HEAD -- app.js 2>/dev/null ||
    { fail 2 "the app.js change isn't committed yet"; return; }
  git check-ignore -q .env ||
    { fail 2 "Git doesn't ignore .env yet: add it to .gitignore"; return; }
  pass 2
}

# ---------------------------------------------------------------- mission 3 · bad message, forgotten file

setup_3() {
  local d="$ROOT/m3"
  newrepo "$d" || return 1
  ( cd "$d" || exit 3
    put README.md '# Course API' '' 'A smal todo servise in Node.js.'
    sg add README.md
    sg commit -qm "docs: add README"
  ) || return 1
  save m3.base "$(git -C "$d" rev-parse HEAD)"
  ( cd "$d" || exit 3
    put README.md '# Course API' '' 'A small todo service in Node.js.'
    sg add README.md
    sg commit -qm "fxi typo"
    put CONTRIBUTING.md '# Contributing' '' 'One change per pull request, please.'
  ) || return 1
  mission "$d" \
    "Mission 3 · a bad commit message and a forgotten file" \
    "" \
    "Your last commit is called \"fxi typo\", and you forgot to add CONTRIBUTING.md to it." \
    "Nothing is pushed." \
    "" \
    "Goal: still ONE commit after \"docs: add README\", with a proper Conventional Commit" \
    "message (for example \"docs: fix typos in README\"), containing both the README fix" \
    "and CONTRIBUTING.md." \
    "" \
    "Start with: git log --oneline, git status" \
    "Check:      bash ~/git-rescue/rescue.sh check 3"
}

check_3() {
  enter 3 || return
  [ "$(git rev-parse -q --verify HEAD~1)" = "$(load m3.base)" ] ||
    { fail 3 "there should be exactly one commit after 'docs: add README' (git log --oneline). Change the last commit instead of adding one (slide 17)"; return; }
  local msg
  msg=$(git log -1 --format=%s)
  case "$msg" in *fxi*) fail 3 "the message still says 'fxi'"; return ;; esac
  printf '%s\n' "$msg" | grep -Eq '^(feat|fix|docs|chore|refactor|test|ci|build|style|perf)(\([^)]*\))?!?: .+' ||
    { fail 3 "'$msg' isn't a Conventional Commit. For example: docs: fix typos in README"; return; }
  git cat-file -e HEAD:CONTRIBUTING.md 2>/dev/null ||
    { fail 3 "CONTRIBUTING.md isn't in the last commit"; return; }
  git show HEAD:README.md | grep -q 'small todo service' ||
    { fail 3 "the README fix is no longer in the last commit"; return; }
  pass 3
}

# ---------------------------------------------------------------- mission 4 · commits on the wrong branch

setup_4() {
  local d="$ROOT/m4" r="$REMOTES/m4.git"
  newremote "$r" && newrepo "$d" || return 1
  ( cd "$d" || exit 3
    put app.js 'console.log("course api");'
    sg add app.js
    sg commit -qm "feat: add app"
    sg remote add origin "$r"
    sg push -q -u origin main
  ) || return 1
  save m4.base "$(git -C "$d" rev-parse HEAD)"
  ( cd "$d" || exit 3
    put cache.env 'CACHE_TTL=60'
    sg add cache.env
    sg commit -qm "feat: add cache settings"
    add_line app.js 'console.log("cache on");'
    sg add app.js
    sg commit -qm "feat: turn on the cache"
  ) || return 1
  save m4.tip "$(git -C "$d" rev-parse HEAD)"
  mission "$d" \
    "Mission 4 · commits on the wrong branch" \
    "" \
    "You made two commits on main, but they belong on a branch called feature/cache." \
    "Nothing is pushed." \
    "" \
    "Goal: feature/cache has both commits, and main is back where origin/main is." \
    "Don't push anything." \
    "" \
    "Start with: git log --oneline --graph --all" \
    "Check:      bash ~/git-rescue/rescue.sh check 4"
}

check_4() {
  enter 4 || return
  git rev-parse -q --verify refs/heads/feature/cache >/dev/null ||
    { fail 4 "there's no branch feature/cache yet"; return; }
  git merge-base --is-ancestor "$(load m4.tip)" feature/cache 2>/dev/null ||
    { fail 4 "feature/cache doesn't have both commits. git reflog shows where they went"; return; }
  [ "$(git rev-parse main)" = "$(git rev-parse origin/main)" ] ||
    { fail 4 "main and origin/main still differ: git log --oneline origin/main..main"; return; }
  [ "$(git --git-dir="$REMOTES/m4.git" rev-parse main)" = "$(load m4.base)" ] ||
    { fail 4 "origin changed, but this mission needs no push. Start again: bash ~/git-rescue/rescue.sh reset 4"; return; }
  pass 4
}

# ---------------------------------------------------------------- mission 5 · a bad commit that is already shared

setup_5() {
  local d="$ROOT/m5" t="$ROOT/m5-teammate" r="$REMOTES/m5.git"
  rm -rf "$t"
  newremote "$r" && newrepo "$d" || return 1
  ( cd "$d" || exit 3
    put config/app.env 'REPLICAS=2' 'LOG_LEVEL=info'
    sg add config/app.env
    sg commit -qm "feat: add app config"
    put README.md '# Deploy config for the course API'
    sg add README.md
    sg commit -qm "docs: add README"
    sg remote add origin "$r"
    sg push -q -u origin main
    put config/app.env 'REPLICAS=0' 'LOG_LEVEL=info'
    sg add config/app.env
    sg commit -qm "feat: set replicas to 0"
    sg push -q
  ) || return 1
  save m5.bad "$(git -C "$d" rev-parse HEAD)"
  sg clone -q "$r" "$t" || return 1
  mission "$d" \
    "Mission 5 · a bad commit that others already have" \
    "" \
    "The commit \"feat: set replicas to 0\" took the app down. It is already pushed to" \
    "the shared repository (origin), and your teammate in ~/git-rescue/m5-teammate has it." \
    "" \
    "Goal: undo it on origin WITHOUT rewriting history, so your teammate can simply pull." \
    "" \
    "Start with: git log --oneline (here, and in ../m5-teammate)" \
    "Check:      bash ~/git-rescue/rescue.sh check 5"
}

check_5() {
  enter 5 || return
  local r="$REMOTES/m5.git" bad
  bad=$(load m5.bad)
  git --git-dir="$r" merge-base --is-ancestor "$bad" main 2>/dev/null ||
    { fail 5 "origin's history was rewritten: the bad commit is gone from it, so your teammate's clone no longer matches. Start again (reset 5) and use a command that ADDS a commit (slide 18)"; return; }
  if git --git-dir="$r" show main:config/app.env | grep -qx 'REPLICAS=0'; then
    if git show HEAD:config/app.env 2>/dev/null | grep -qx 'REPLICAS=2'; then
      fail 5 "fixed here, but not on origin yet. Did you push?"
    else
      fail 5 "origin still has REPLICAS=0"
    fi
    return
  fi
  git --git-dir="$r" log --format=%s "$bad..main" | grep -q '^Revert' ||
    { fail 5 "the value is back, but not through a revert commit. Use git revert (slide 18)"; return; }
  git -C "$ROOT/m5-teammate" pull -q --ff-only >/dev/null 2>&1 ||
    { fail 5 "your teammate can't fast-forward to origin/main"; return; }
  pass 5
}

# ---------------------------------------------------------------- mission 6 · reset --hard "lost" three commits

setup_6() {
  local d="$ROOT/m6"
  newrepo "$d" || return 1
  ( cd "$d" || exit 3
    put app.js 'console.log("course api");'
    sg add app.js
    sg commit -qm "feat: add app"
    put .gitignore 'node_modules/'
    sg add .gitignore
    sg commit -qm "chore: add .gitignore"
    put API.md '# API' '' 'GET /api/todos'
    sg add API.md
    sg commit -qm "docs: add API examples"
    add_line app.js 'if (!title) throw new Error("title required");'
    sg add app.js
    sg commit -qm "fix: handle empty todo title"
    add_line app.js 'console.log(JSON.stringify({ msg: "request" }));'
    sg add app.js
    sg commit -qm "feat: add request logging"
  ) || return 1
  save m6.tip "$(git -C "$d" rev-parse HEAD)"
  sg -C "$d" reset -q --hard HEAD~3 || return 1
  mission "$d" \
    "Mission 6 · three commits \"gone\" after a reset" \
    "" \
    "Someone (you) ran: git reset --hard HEAD~3" \
    "Three commits of work are gone from main: \"docs: add API examples\"," \
    "\"fix: handle empty todo title\" and \"feat: add request logging\"." \
    "" \
    "Goal: all three commits back on main, or safely on another branch." \
    "" \
    "Start with: git log --oneline, then git reflog" \
    "Check:      bash ~/git-rescue/rescue.sh check 6"
}

check_6() {
  enter 6 || return
  [ -n "$(git branch --contains "$(load m6.tip)" 2>/dev/null)" ] ||
    { fail 6 "the three commits aren't on any branch yet. git reflog shows where HEAD was before the reset"; return; }
  pass 6
}

# ---------------------------------------------------------------- mission 7 · stretch · detached HEAD

setup_7() {
  local d="$ROOT/m7"
  newrepo "$d" || return 1
  ( cd "$d" || exit 3
    put app.js 'console.log("course api 1.0");'
    sg add app.js
    sg commit -qm "feat: add app"
    sg tag -a v1.0.0 -m "v1.0.0"
    put search.js 'module.exports = () => [];'
    sg add search.js
    sg commit -qm "feat: add search"
    sg switch -q --detach v1.0.0
    add_line app.js '// validate input before use'
    sg add app.js
    sg commit -qm "fix: validate input in 1.0"
  ) || return 1
  save m7.fix "$(git -C "$d" rev-parse HEAD)"
  mission "$d" \
    "Mission 7 · stretch · a commit on a detached HEAD" \
    "" \
    "You checked out tag v1.0.0 to fix a bug in the released version, and committed the fix." \
    "git status says \"HEAD detached\". If you switch to main now, the fix belongs to no branch." \
    "" \
    "Goal: keep the fix on a branch whose name starts with hotfix/ (for example hotfix/1.0.1)." \
    "" \
    "Start with: git status, git log --oneline --graph --all" \
    "Check:      bash ~/git-rescue/rescue.sh check 7"
}

check_7() {
  enter 7 || return
  [ -n "$(git for-each-ref --contains "$(load m7.fix)" --format='%(refname)' refs/heads/hotfix/ 2>/dev/null)" ] ||
    { fail 7 "no hotfix/… branch contains the fix yet"; return; }
  pass 7
}

# ---------------------------------------------------------------- mission 8 · stretch · git bisect

setup_8() {
  local d="$ROOT/m8"
  newrepo "$d" || return 1
  ( cd "$d" || exit 3
    put app.env 'PORT=5000'
    put test.sh '#!/bin/sh' '# exit code 0 = good, 1 = bad' "grep -qx 'PORT=5000' app.env"
    chmod +x test.sh
    sg add app.env test.sh
    sg update-index --chmod=+x test.sh
    sg commit -qm "chore: add app.env and test.sh"
    i=1
    while [ "$i" -le 20 ]; do
      add_line notes.txt "note $i"
      if [ "$i" -eq 13 ]; then put app.env 'PORT=50000'; fi
      sg add -A
      sg commit -qm "docs: add note $i"
      if [ "$i" -eq 13 ]; then sg rev-parse HEAD > "$STATE/m8.bad"; fi
      i=$((i + 1))
    done
  ) || return 1
  mission "$d" \
    "Mission 8 · stretch · which commit broke the test?" \
    "" \
    "test.sh passed on the first commit and fails now (try: ./test.sh; echo \$?)." \
    "One of the 20 \"docs: add note\" commits broke it, and its message doesn't say so." \
    "" \
    "Goal: find that commit with git bisect, write its hash (at least 7 characters)" \
    "into a file called ANSWER in this folder, and finish with git bisect reset." \
    "" \
    "Start with: git bisect start, git bisect bad, git bisect good <first commit>," \
    "            git bisect run ./test.sh" \
    "Check:      bash ~/git-rescue/rescue.sh check 8"
}

check_8() {
  enter 8 || return
  [ ! -f "$(git rev-parse --git-path BISECT_LOG)" ] ||
    { fail 8 "a bisect is still running: git bisect reset"; return; }
  [ -s ANSWER ] ||
    { fail 8 "write the hash into $ROOT/m8/ANSWER, for example: echo 1a2b3c4 > ANSWER"; return; }
  local a
  a=$(head -n 1 ANSWER | tr -d ' \r\n\t')
  [ "${#a}" -ge 7 ] ||
    { fail 8 "give at least 7 characters of the hash"; return; }
  case "$(load m8.bad)" in
    "$a"*) pass 8 ;;
    *) fail 8 "that isn't the first bad commit. Run the bisect again" ;;
  esac
}

# ---------------------------------------------------------------- commands

need_git() {
  git switch -h 2>&1 | grep -q 'git switch' || die "this needs Git 2.23 or newer (you have: $(git --version))"
}

valid() {
  case "${1:-}" in 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8) ;; *) die "give a mission number from 1 to 8" ;; esac
}

remove() {
  rm -rf "$ROOT/m$1"
  case "$1" in
    4) rm -rf "$REMOTES/m4.git" ;;
    5) rm -rf "$ROOT/m5-teammate" "$REMOTES/m5.git" ;;
  esac
}

case "${1:-help}" in
  setup)
    [ -n "${2:-}" ] || die "usage: bash lab03-branch-review-release/rescue.sh setup <your-github-user>"
    need_git
    mkdir -p "$ROOT" "$STATE" "$REMOTES" || die "can't create $ROOT"
    printf '%s\n' "$2" | tr '[:upper:]' '[:lower:]' > "$ROOT/.user"
    [ "$0" -ef "$ROOT/rescue.sh" ] || cp "$0" "$ROOT/rescue.sh"
    for n in $MISSIONS; do
      if [ -d "$ROOT/m$n" ]; then
        echo "m$n: already there, kept"
      else
        setup_$n || die "creating m$n failed"
        echo "m$n: ready"
      fi
    done
    echo
    echo "Missions are in $ROOT. Start with: cat $ROOT/m1/MISSION.txt"
    echo "Check one with: bash ~/git-rescue/rescue.sh check 1"
    ;;
  check)
    valid "${2:-}"
    user >/dev/null
    ( check_$2 )
    ;;
  reset)
    valid "${2:-}"
    user >/dev/null
    need_git
    remove "$2"
    setup_$2 || die "creating m$2 failed"
    echo "m$2: created again. Read $ROOT/m$2/MISSION.txt"
    ;;
  status)
    user >/dev/null
    for n in $MISSIONS; do ( check_$n ) || true; done
    ;;
  *)
    sed -n '2,15p' "$0"
    exit 1
    ;;
esac
