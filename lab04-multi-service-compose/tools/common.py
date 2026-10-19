"""Shared helpers for the Lab 4 tools: check.sh, clinic.sh and the grader.

Docker commands run with a clean environment: a variable exported in the shell can't
silently win over .env (slide 46), and the grader's own tokens never reach a student's
compose.yaml through ${...}."""
import atexit
import json
import os
import pathlib
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

COURSE_REPO = "mleitass/turiba-devops-labs"
CLINIC_IMAGE = "ghcr.io/mleitass/lab4-clinic-api:1"
POSTGRES_IMAGE = "postgres:17-alpine"
NGINX_IMAGE = "nginx:1.30-alpine"
PG_DATA = "/var/lib/postgresql/data"
HOST = os.environ.get("LAB4_HOST", "127.0.0.1")
DOCKER_VARS = ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY")


class Lab4Error(Exception):
    """A problem the student can fix. The message says how."""


_ISOLATED_CONFIG = []        # one folder per process, removed at exit


def isolated_docker_config() -> str:
    """A Docker config folder without credentials or credential helpers.

    Only cliPluginsExtraDirs is copied: Rancher Desktop finds its compose plugin
    through it, and `docker compose` is an unknown command without it.

    It holds one empty entry under auths (an empty auths map is not enough: Docker then
    auto-detects a credential helper, and on WSL it can pick a broken `secretservice` that
    fails every image pull). Pulls are anonymous.

    The folder is created once per process and removed when the process exits."""
    if _ISOLATED_CONFIG and pathlib.Path(_ISOLATED_CONFIG[0], "config.json").is_file():
        return _ISOLATED_CONFIG[0]
    current = pathlib.Path(os.environ.get("DOCKER_CONFIG") or pathlib.Path.home() / ".docker")
    try:
        extra = json.loads((current / "config.json").read_text()).get("cliPluginsExtraDirs", [])
    except (OSError, ValueError):
        extra = []
    folder = tempfile.mkdtemp(prefix="lab4-docker-config-")
    pathlib.Path(folder, "config.json").write_text(json.dumps(
        {"cliPluginsExtraDirs": extra, "auths": {"https://index.docker.io/v1/": {}}}))
    if not _ISOLATED_CONFIG:
        atexit.register(lambda: shutil.rmtree(_ISOLATED_CONFIG[0], ignore_errors=True))
    _ISOLATED_CONFIG[:] = [folder]
    return folder


def clean_env(isolate: bool = False) -> dict:
    """PATH, HOME and the Docker connection settings, nothing else.

    isolate=True (the grader) also swaps in an empty Docker config."""
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
           "HOME": os.environ.get("HOME", "/tmp"), "LANG": "C.UTF-8"}
    env.update({k: os.environ[k] for k in DOCKER_VARS if k in os.environ})
    if isolate:
        env.pop("DOCKER_CONTEXT", None)
        env["DOCKER_CONFIG"] = isolated_docker_config()
    return env


def run(cmd, *, cwd=None, env=None, timeout=600, check=True):
    """Run a command and capture its output. Raises Lab4Error if check and it fails."""
    cmd = [str(c) for c in cmd]
    try:
        p = subprocess.run(cmd, cwd=None if cwd is None else str(cwd),
                           env=clean_env() if env is None else env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except FileNotFoundError:
        raise Lab4Error(f"`{cmd[0]}` was not found. Run this in the Ubuntu (WSL) terminal, "
                        "with Docker running.") from None
    except subprocess.TimeoutExpired:
        raise Lab4Error(f"`{' '.join(cmd[:4])} …` took longer than {timeout} s and was stopped.") from None
    if check and p.returncode != 0:
        tail = (p.stderr.strip() or p.stdout.strip())[-1500:]
        raise Lab4Error(f"`{' '.join(cmd)}` failed (exit {p.returncode}):\n{tail}")
    return p


def compose(project_dir, args, *, files=("compose.yaml",), project=None, env_file=None,
            env=None, timeout=600, check=True):
    """docker compose with explicit files (override files are never picked up by accident)."""
    cmd = ["docker", "compose"]
    for f in files:
        cmd += ["-f", str(f)]
    if project:
        cmd += ["-p", project]
    if env_file:
        cmd += ["--env-file", str(env_file)]
    return run(cmd + list(args), cwd=project_dir, env=env, timeout=timeout, check=check)


def config_json(project_dir, *, interpolate=True, env_file=None, files=("compose.yaml",),
                project=None, env=None, timeout=600) -> dict:
    """`docker compose config` as a dict, normalised, with or without ${...} filled in."""
    if interpolate:
        args = ["config", "--format", "json"]
    else:
        args, env_file = ["config", "--no-interpolate", "--format", "json"], None
    p = compose(project_dir, args, files=files, project=project, env_file=env_file, env=env,
                timeout=timeout)
    return json.loads(p.stdout)


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http(method, url, body=None, timeout=5):
    """(status, text). status is None when nothing answered; text then says why."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return None, str(getattr(e, "reason", e))


def wait_http(method, url, want, body=None, seconds=30):
    """Retry until the status is in want or the time is up. Returns the last (status, text)."""
    deadline = time.monotonic() + seconds
    while True:
        status, text = http(method, url, body)
        if status in want or time.monotonic() > deadline:
            return status, text
        time.sleep(1)


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0
