#!/usr/bin/env python3
"""Lab 4 self-check (design section 8): what the grader will see, before the grader sees it.

    bash lab04-multi-service-compose/check.sh preflight | stack | writeup | clinic | fresh | all"""
import argparse
import os
import pathlib
import re
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import clinic  # noqa: E402
import gates   # noqa: E402
from common import (CLINIC_IMAGE, COURSE_REPO, NGINX_IMAGE, POSTGRES_IMAGE, Lab4Error,  # noqa: E402
                    config_json, port_busy, run)

GUIDE = "lab04-multi-service-compose/README.md"
LECTURER = " (the grader would send this to the lecturer)"
RE_HOST_PORT = re.compile(r":(\d+)(?:-(\d+))?->")
TITLES = {"G1": "compose.yaml on main of your fork", "G2": "lab4/README.md headings",
          "G3": "three services from the right sources", "G4": "only web publishes 8080 → 80",
          "G5": "service names in DB_HOST and proxy_pass", "G6": "a named volume for PostgreSQL",
          "G7": "health check + service_healthy", "G8": "the password comes from .env",
          "G9": "fresh-clone run test", "G10": "Compose clinic", "G11": "no .env or dumps in the Git history"}


class Report:
    def __init__(self):
        self.failed = 0

    def ok(self, text):
        print(f"  ✔ {text}", flush=True)

    def warn(self, text):
        print(f"  ⚠ {text}", flush=True)

    def bad(self, text):
        lines = [line.strip() for line in str(text).splitlines() if line.strip()]
        print(f"  ✘ {' | '.join(lines[-3:])}", flush=True)       # always one line: the last three say it
        self.failed += 1

    def gate(self, g):
        if g.status == "pass":
            self.ok(f"{g.id} {TITLES.get(g.id, '')}")
        else:
            self.bad(f"{g.id} {TITLES.get(g.id, '')}: {g.detail}{LECTURER if g.status == 'needs_human' else ''}")


def git_env():
    return dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_SSH_COMMAND="ssh -o BatchMode=yes")


def git(root, *args, timeout=60):
    return run(["git", "-C", root, *args], env=git_env(), check=False, timeout=timeout)


def fork_root():
    root = pathlib.Path.cwd()
    if not (root / "lab04-multi-service-compose").is_dir() or not (root / ".git").exists():
        raise Lab4Error("Run this from the root of your fork: cd ~/turiba-devops-labs")
    return root


def preflight(rep):
    root = fork_root()
    print("Preflight (guide step 0.4)")
    if str(root).startswith("/mnt/"):
        rep.warn(f"your fork is on the Windows drive ({root}). It works, but builds are slow. "
                 "Lab 3 put it in ~/turiba-devops-labs")
    if run(["docker", "info"], check=False).returncode != 0:
        rep.bad("Docker is not running: start Rancher Desktop or Docker Desktop, wait until it's ready, try again")
        return
    rep.ok("Docker is running")
    version = run(["docker", "compose", "version", "--short"], check=False).stdout.strip().lstrip("v")
    numbers = tuple(int(x) for x in re.findall(r"\d+", version)[:2]) or (0, 0)
    (rep.ok if numbers >= (2, 24) else rep.bad)(f"Docker Compose {version or 'not found'} (2.24 or newer needed)")
    origin = git(root, "config", "--get", "remote.origin.url").stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(\.git)?$", origin)
    if not m or m.group(1).lower() == "mleitass":
        rep.bad(f"origin is {origin or '(missing)'}: it must be YOUR fork (Lab 3 step 1.2)")
    else:
        rep.ok(f"origin is your fork · GitHub user: {m.group(1).lower()}")
    upstream = git(root, "config", "--get", "remote.upstream.url").stdout.strip()
    if COURSE_REPO not in upstream:
        rep.bad("no upstream remote: git remote add upstream https://github.com/mleitass/turiba-devops-labs.git")
    elif git(root, "fetch", "--quiet", "upstream").returncode or git(root, "fetch", "--quiet", "origin").returncode:
        rep.warn("could not fetch from GitHub (offline?): the sync check was skipped")
    elif git(root, "merge-base", "--is-ancestor", "upstream/main", "origin/main").returncode == 0:
        rep.ok("the Lab 4 material is merged into your fork on GitHub")
    else:
        rep.bad("your fork on GitHub doesn't have the latest course material: open the sync PR in YOUR fork "
                "and merge it (course README, 'From Lab 3 on')")
    api = root / "api"
    dockerfile_problems = gates.dockerfile_problems(api / "Dockerfile", "api") if (api / "Dockerfile").is_file() else []
    if dockerfile_problems:
        rep.bad(f"{dockerfile_problems[0]}. Use lab04-multi-service-compose/reference/Dockerfile as your api/Dockerfile "
                "(step 0.4): the grader only builds the allowed base images")
    elif (api / "Dockerfile").is_file():
        p = run(["docker", "build", "-q", "-t", "lab4-preflight-api", api], check=False, timeout=900)
        if p.returncode:
            last = (p.stderr.strip().splitlines() or ["(no output)"])[-1]
            rep.bad(f"api/Dockerfile doesn't build ({last}). Copy lab04-multi-service-compose/reference/Dockerfile "
                    "to api/ (step 0.4)")
        else:
            rep.ok("api/Dockerfile builds")
            run(["docker", "image", "rm", "-f", "lab4-preflight-api"], check=False)
    else:
        rep.bad("api/Dockerfile is missing: copy lab04-multi-service-compose/reference/Dockerfile to api/ (step 0.4)")
    server = (api / "server.js").read_text(encoding="utf-8", errors="replace") if (api / "server.js").is_file() else ""
    if re.search(r"""['"]/healthz['"]""", server):
        rep.ok("api/server.js has the /healthz route")
    else:
        rep.bad("api/server.js has no /healthz route: add it from lab04-multi-service-compose/reference/healthz.md")
    ignore = (api / ".dockerignore").read_text().splitlines() if (api / ".dockerignore").is_file() else []
    if ".env" in [line.strip() for line in ignore]:
        rep.ok("api/.dockerignore keeps .env out of the image")
    else:
        rep.bad("api/.dockerignore doesn't exclude .env: copy lab04-multi-service-compose/reference/.dockerignore to api/")
    busy = [p for p in [8080, 3000] + list(range(8101, 8109)) if port_busy(p)]
    if busy:
        rep.warn(f"ports in use: {busy}. Old Lab 1 or Lab 2 containers? docker ps, then docker rm -f <name>")
    for image in (POSTGRES_IMAGE, NGINX_IMAGE, CLINIC_IMAGE):
        if run(["docker", "image", "inspect", image], check=False).returncode:
            rep.warn(f"{image} is not pulled yet: docker pull {image}")


def stack(rep):
    root = fork_root()
    print("Stack (your working copy)")
    if not (root / "compose.yaml").is_file():
        rep.bad("no compose.yaml in the root of your fork yet (guide Part 2)")
        return
    for f in (root / "compose.yaml", root / "web" / "nginx.conf"):
        if f.is_file() and "____" in f.read_text(encoding="utf-8", errors="replace"):
            rep.bad(f"{f.relative_to(root)} still has ____ blanks")
    if not (root / ".env").is_file():
        rep.bad("no .env next to compose.yaml: cp .env.example .env, then set a real password in .env")
        return
    for g in gates.static_gates(root):
        if g.id != "G2":
            rep.gate(g)
    try:
        problems = gates.text_problems(root) or gates.shape_problems(
            root, config_json(root, interpolate=False, project="lab4-fresh"))
    except Lab4Error as e:
        problems = [str(e).splitlines()[-1]]
    if problems:
        more = f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""
        rep.bad(f"the grader would not run this compose.yaml (it would go to the lecturer): {problems[0]}{more}")
    else:
        rep.ok("shape: the grader can run this compose.yaml")


def writeup(rep):
    root = fork_root()
    print("Write-up (lab4/README.md)")
    rep.gate(gates.g2_readme(root))
    f = root / "lab4" / "README.md"
    if not f.is_file():
        return
    text = f.read_text(encoding="utf-8", errors="replace")
    rows = set(re.findall(r"^\|\s*(P[1-6])\b", text, re.M))
    (rep.ok if len(rows) == 6 else rep.bad)(f"predictions table: {len(rows)} of 6 rows")
    answers = set(re.findall(r"^#{0,4}\s*\**(A[1-4])\b", text, re.M))
    (rep.ok if len(answers) == 4 else rep.bad)(f"answers: {len(answers)} of A1–A4")
    for n in sorted(set(re.findall(r"^###\s*c([2-7])\b", text, re.M))):
        if not (root / "lab4" / "clinic" / f"c{n}").is_dir():
            rep.bad(f"c{n} is in the write-up, but lab4/clinic/c{n}/ is missing: "
                    "from your fork's root, bash ~/compose-clinic/clinic.sh export")


def clinic_check(rep):
    root = fork_root()
    print("Compose clinic (lab4/clinic/, checked the way the grader does)")
    passed = 0
    for n in range(2, 8):
        d = root / "lab4" / "clinic" / f"c{n}"
        if not d.is_dir():
            continue
        clinic.compose_down(n, volumes=True)      # your own clinic stack for this mission: frees its port
        status, msg = clinic.verify(n, d, isolate=False)
        if status == "pass":
            passed += 1
            rep.ok(f"c{n} passes")
        else:
            rep.bad(f"c{n}: {msg}{LECTURER if status == 'needs_human' else ''}")
    (rep.ok if passed >= 4 else rep.bad)(f"G10 {passed} of c2–c7 pass (4 needed)")


def port_8080_holders():
    """(id, name, compose project) of the running containers that publish HOST port 8080.

    The filter can't tell a Compose stack from an old lab's container, so the Ports column is read instead."""
    out = run(["docker", "ps", "--format",
               '{{.ID}}\t{{.Names}}\t{{.Label "com.docker.compose.project"}}\t{{.Ports}}'], check=False).stdout
    holders = []
    for line in out.splitlines():
        cid, name, project, ports = (line.split("\t") + ["", "", "", ""])[:4]
        if any(int(lo) <= 8080 <= int(hi or lo) for lo, hi in RE_HOST_PORT.findall(ports)):
            holders.append((cid, name, project))
    return holders


def free_port_8080(rep):
    holders = port_8080_holders()
    for _, name, project in holders:
        if not project:
            raise Lab4Error(f"port 8080 is used by the container {name} (an old lab?): "
                            f"docker rm -f {name}, then run check.sh fresh again")
    for cid, name, project in holders:
        run(["docker", "stop", cid], check=False)
        rep.warn(f"stopped {name} (compose project {project}) to free port 8080. Its data is kept. "
                 "Start it again later: docker compose up -d")
    if port_busy(8080):
        raise Lab4Error("port 8080 is used by a program outside Docker. Stop it, then run check.sh fresh again")


def fresh(rep):
    root = fork_root()
    print("Fresh clone of your fork's main on GitHub (what the grader sees)")
    origin = git(root, "config", "--get", "remote.origin.url").stdout.strip()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="lab4-fresh-"))
    clone = tmp / "fork"
    try:
        p = run(["git", "clone", "--quiet", "--depth", "50", "--branch", "main", origin, clone],
                env=git_env(), check=False, timeout=300)
        if p.returncode:
            rep.bad(f"could not clone {origin}: {p.stderr.strip()[-300:]}")
            return
        if not (clone / "compose.yaml").is_file():
            rep.bad("G1 compose.yaml is not on main of your fork on GitHub: is your PR merged, and was it opened "
                    "in YOUR fork?")
            return
        rep.ok("G1 (part) compose.yaml is on main of your fork")
        if (clone / ".env.example").is_file():
            shutil.copyfile(clone / ".env.example", clone / ".env")
        else:
            (clone / ".env").write_text("DB_PASSWORD=check-fallback-123\n")
        for g in gates.static_gates(clone):
            if g.id != "G11":
                rep.gate(g)
        try:
            problems = gates.text_problems(clone) or gates.shape_problems(
                clone, config_json(clone, interpolate=False, project="lab4-fresh"))
        except Lab4Error as e:
            problems = [str(e).splitlines()[-1]]
        if problems:
            rep.bad("the grader would not run this compose.yaml (it goes to the lecturer): " + "; ".join(problems[:3]))
            return
        free_port_8080(rep)
        print("  … building and starting your stack (up to 6 minutes)", flush=True)
        rep.gate(gates.g9_run(clone, "lab4-fresh"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


STEPS = {"preflight": [preflight], "stack": [stack], "writeup": [writeup], "clinic": [clinic_check],
         "fresh": [fresh], "all": [stack, writeup, clinic_check, fresh]}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="check.sh", description="Lab 4 self-check: what the grader will see")
    ap.add_argument("what", choices=list(STEPS))
    a = ap.parse_args(argv)
    rep = Report()
    for step in STEPS[a.what]:
        try:
            step(rep)
        except Lab4Error as e:
            if os.environ.get("LAB4_DEBUG"):
                raise
            rep.bad(str(e))
            if "root of your fork" in str(e):
                break
        except KeyboardInterrupt:
            rep.bad("stopped with Ctrl+C")
            break
        except Exception as e:                      # students get one line, never a traceback
            if os.environ.get("LAB4_DEBUG"):
                raise
            rep.bad(f"unexpected problem in {step.__name__}: {type(e).__name__}: {str(e)[-300:]}. "
                    f"Tell the lecturer, with this line (the lecturer may ask for LAB4_DEBUG=1 bash "
                    f"lab04-multi-service-compose/check.sh {a.what})")
    print()
    print("All checks passed." if not rep.failed
          else f"{rep.failed} item(s) to fix. The guide's troubleshooting table helps: {GUIDE}")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
