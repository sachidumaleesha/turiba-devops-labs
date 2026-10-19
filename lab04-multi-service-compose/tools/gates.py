"""Lab 4 gates (design section 10) and the shape allowlist (design section 8).

check.sh runs them on a student's laptop; the grader runs them on a snapshot, always with
its own copy of this file from the course repo, never the student's copy."""
import pathlib
import re
import sys
import time
import uuid
from dataclasses import dataclass

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import (HOST, PG_DATA, Lab4Error, clean_env, compose, config_json, port_busy, run,  # noqa: E402,F401
                    wait_http)

RE_POSTGRES = re.compile(r"^postgres:17(\.\d+)*(-alpine[\d.]*|-bookworm|-trixie)?(@sha256:[0-9a-f]{64})?$")
RE_FROM = {
    "api": re.compile(r"^(docker\.io/(library/)?)?node:24(\.\d+)*(-alpine[\d.]*|-slim|-bookworm-slim|-trixie-slim)?"
                      r"(@sha256:[0-9a-f]{64})?$"),
    "web": re.compile(r"^(docker\.io/(library/)?)?nginx:1\.30(\.\d+)?-alpine[\d.]*(@sha256:[0-9a-f]{64})?$"),
}
RE_SYNTAX = re.compile(r"^#\s*syntax\s*=\s*(\S+)", re.I)
RE_SYNTAX_OK = re.compile(r"^docker/dockerfile:1(\.\d+)*$")
RE_PROXY = re.compile(r"^[ \t]*proxy_pass[ \t]+http://api:5000[ \t]*;", re.M)
RE_VAR = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)|([A-Za-z_][A-Za-z0-9_]*))")
RE_ENV_LINE = re.compile(r"^DB_PASSWORD=\S")
# Keys that Compose follows to other files, or resolves away, so the allowlist on `docker compose config`
# can't see them. Matched as words anywhere in the file (quoted keys, flow maps and comments included).
RE_HIDDEN_KEYS = re.compile(r"\b(include|extends|env_file|label_file|secrets|configs)\b")
RE_YAML_TAG = re.compile(r"!\S")          # !!binary, !<…>, !e!…, !reset, !override: a tag can spell a key
RE_YAML_DIRECTIVE = re.compile(r"^%", re.M)   # %TAG, %YAML
RE_FORBIDDEN_FILE = re.compile(r"(^|/)(\.env|[^/]*\.sql|[^/]*\.dump)$")
README_SECTIONS = ["Architecture", "Predictions", "Backup and restore", "Compose clinic",
                   "Run in one command", "Answers"]
PLACEHOLDERS = ["<you>", "____", "TODO"]
SERVICE_KEYS = {"build", "image", "ports", "environment", "depends_on", "healthcheck", "networks",
                "volumes", "restart", "command", "entrypoint"}
RUN_OVERRIDE = pathlib.Path(__file__).resolve().with_name("run-override.yaml")
GIT = ["git", "-c", "core.quotePath=false"]       # non-ASCII file names stay readable


@dataclass
class Gate:
    id: str
    points: float
    max: float
    detail: str = ""
    status: str = ""          # pass | partial | fail | needs_human

    def __post_init__(self):
        if not self.status:
            self.status = "pass" if self.points >= self.max else "partial" if self.points > 0 else "fail"


def _read(path) -> str:
    return pathlib.Path(path).read_text(encoding="utf-8-sig", errors="replace")   # a BOM is accepted


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def _env_dict(env) -> dict:
    """An environment as a dict: with --no-interpolate Compose keeps the KEY=VALUE list form as a list."""
    if isinstance(env, list):
        return {k: v for k, _, v in (str(item).partition("=") for item in env)}
    return env if isinstance(env, dict) else {}


def variables(raw: dict) -> set:
    """Every ${VAR} or $VAR that Compose would fill in ($$ is a literal $)."""
    found = set()
    for s in _strings(raw):
        for braced, bare in RE_VAR.findall(s.replace("$$", "")):
            found.add(braced or bare)
    return found


def dockerfile_problems(path, service) -> list:
    path = pathlib.Path(path)
    if not path.is_file():
        return [f"{service}/Dockerfile is missing"]
    problems, stages = [], set()
    for line in _read(path).splitlines():
        m = RE_SYNTAX.match(line.strip())
        if m and not RE_SYNTAX_OK.match(m.group(1)):
            problems.append(f"{service}/Dockerfile: syntax directive {m.group(1)} is not allowed")
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0].upper() == "FROM":
            args, skip = [], False
            for a in parts[1:]:
                if skip:
                    skip = False
                elif a == "--platform":
                    skip = True                      # FROM --platform $BUILDPLATFORM image
                elif not a.startswith("--"):
                    args.append(a)
            if not args:
                problems.append(f"{service}/Dockerfile: a FROM line has no image")
                continue
            image = args[0]
            if image not in stages and not RE_FROM[service].match(image):
                problems.append(f"{service}/Dockerfile: base image {image} is not allowed")
            if len(args) >= 3 and args[1].upper() == "AS":
                stages.add(args[2])
    return problems


def env_example_problems(repo) -> list:
    f = pathlib.Path(repo) / ".env.example"
    if not f.is_file():
        return [".env.example is missing"]
    return [f".env.example line {n}: only DB_PASSWORD=… is expected"
            for n, line in enumerate(_read(f).splitlines(), 1)
            if line.strip() and not line.strip().startswith("#") and not RE_ENV_LINE.match(line.strip())]


def hidden_key_problems(repo) -> list:
    """Why Compose must not read compose.yaml at all. Works on the raw bytes, before any Docker call.

    Compose follows env_file, include, extends … to host files, reads symlinks, and decodes escaped
    key names. So the file must be a plain file, UTF-8 without BOM, with no backslash, and none of
    the words include, extends, env_file, label_file, secrets, configs anywhere (comments count)."""
    compose_file = pathlib.Path(repo) / "compose.yaml"
    if compose_file.is_symlink():
        return ["compose.yaml is a symbolic link, which is not allowed"]
    if not compose_file.is_file():
        return []
    data, p = compose_file.read_bytes(), []
    if data.startswith(b"\xef\xbb\xbf"):
        p.append("compose.yaml must be UTF-8 without a BOM (save it as plain UTF-8)")
        data = data[3:]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return p + ["compose.yaml must be UTF-8 (it looks like UTF-16 or another encoding)"]
    if "\x00" in text:
        p.append("compose.yaml must be UTF-8 (it contains NUL bytes)")
    if "\\" in text:
        p.append("compose.yaml contains a backslash, which is not part of the Lab 4 shape")
    if RE_YAML_TAG.search(text):
        p.append("YAML tags (!!binary, !reset, !override …) are not allowed in compose.yaml, "
                 "not even in a comment")
    if RE_YAML_DIRECTIVE.search(text):
        p.append("a YAML directive (a line starting with %) is not allowed in compose.yaml")
    p += [f"compose.yaml contains `{k}`, which is not part of the Lab 4 shape (even in a comment)"
          for k in sorted(set(RE_HIDDEN_KEYS.findall(text)))]
    return p


def text_problems(repo) -> list:
    """Checks that need no Docker: hidden keys, .env.example, Dockerfiles, tracked symlinks.

    The grader runs these first: `docker compose config` itself reads env_file and include."""
    repo = pathlib.Path(repo)
    if not (repo / "compose.yaml").is_file():
        return ["compose.yaml is missing"]
    p = hidden_key_problems(repo)
    p += env_example_problems(repo)
    p += dockerfile_problems(repo / "web" / "Dockerfile", "web")
    p += dockerfile_problems(repo / "api" / "Dockerfile", "api")
    listing = run(GIT + ["-C", repo, "ls-files", "-s"], check=False).stdout
    p += [f"symlink not allowed: {line.split(chr(9), 1)[1]}"
          for line in listing.splitlines() if line.startswith("120000 ")]
    return p


def shape_problems(repo, raw: dict) -> list:
    """Everything that differs from the exact Lab 4 shape. [] means the grader may run it.

    raw is `docker compose config --no-interpolate --format json` for compose.yaml alone."""
    repo = pathlib.Path(repo).resolve()
    p = text_problems(repo)
    extra = set(raw) - {"name", "services", "networks", "volumes"}
    if extra:
        p.append(f"top-level keys not allowed: {sorted(extra)}")
    project, services = raw.get("name", ""), raw.get("services") or {}
    if set(services) != {"web", "api", "db"}:
        p.append(f"services must be exactly web, api, db (found {sorted(services)})")
    for name, svc in services.items():
        for key in sorted(set(svc) - SERVICE_KEYS):
            p.append(f"services.{name}.{key} is not allowed in compose.yaml "
                     "(stretch work goes into compose.override.yaml)")
        for key in ("command", "entrypoint"):
            if svc.get(key) is not None:
                p.append(f"services.{name}.{key} is not allowed")
        if name in ("web", "api"):
            build = svc.get("build")
            if not isinstance(build, dict) or "image" in svc:
                p.append(f"services.{name} must be built from ./{name} (build:, no image:)")
            else:
                if set(build) - {"context", "dockerfile"}:
                    p.append(f"services.{name}.build may only have context and dockerfile")
                if pathlib.Path(build.get("context", "")).resolve() != repo / name:
                    p.append(f"services.{name}.build.context must be ./{name}")
                if build.get("dockerfile", "Dockerfile") != "Dockerfile":
                    p.append(f"services.{name}.build.dockerfile must be Dockerfile")
        elif "build" in svc or not RE_POSTGRES.match(str(svc.get("image", ""))):
            p.append(f"services.{name}.image must be postgres:17…")
        for port in svc.get("ports") or []:
            if set(port) - {"mode", "target", "published", "protocol", "host_ip"}:
                p.append(f"services.{name}.ports: only HOST:CONTAINER mappings are allowed")
        for net, val in (svc.get("networks") or {}).items():
            if val not in (None, {}):
                p.append(f"services.{name}.networks.{net}: network options are not allowed")
        for vol in svc.get("volumes") or []:
            if vol.get("type") != "volume" or vol.get("source") not in (raw.get("volumes") or {}):
                p.append(f"services.{name}.volumes: only named volumes declared at the bottom are allowed")
            elif set(vol) - {"type", "source", "target", "volume", "read_only"}:
                p.append(f"services.{name}.volumes: volume options are not allowed")
    for kind, allowed in (("networks", {"name", "internal"}), ("volumes", {"name"})):
        for key, val in (raw.get(kind) or {}).items():
            val = val or {}
            if set(val) - allowed or val.get("name", f"{project}_{key}") != f"{project}_{key}":
                p.append(f"{kind}.{key}: only a plain {kind[:-1]} is allowed")
    bad = variables(raw) - {"DB_PASSWORD"}
    if bad:
        p.append(f"only ${{DB_PASSWORD}} may be filled in from .env (found {sorted(bad)})")
    return p


def g2_readme(repo) -> Gate:
    f = pathlib.Path(repo) / "lab4" / "README.md"
    if not f.is_file():
        return Gate("G2", 0, 5, "lab4/README.md is missing")
    text = _read(f)
    headings = [line.lower() for line in text.splitlines() if line.startswith("## ")]
    missing = [s for s in README_SECTIONS if not any(s.lower() in h for h in headings)]
    left = [ph for ph in PLACEHOLDERS if ph in text]
    points = max(0, 5 - len(missing) - (1 if left else 0))
    notes = ([f"missing headings: {', '.join(missing)}"] if missing else []) + \
            ([f"placeholders left: {', '.join(left)}"] if left else [])
    return Gate("G2", points, 5, "; ".join(notes))


def _svc(cfg, name):
    return (cfg.get("services") or {}).get(name) or {}


def g3_services(repo, cfg) -> Gate:
    repo, problems = pathlib.Path(repo).resolve(), []
    for name in ("web", "api"):
        context = (_svc(cfg, name).get("build") or {}).get("context")
        if not context or pathlib.Path(context).resolve() != repo / name:
            problems.append(f"{name} is not built from ./{name}")
    if "db" not in (cfg.get("services") or {}):
        return Gate("G3", 0, 6, "; ".join(problems + ["there is no db service"]))
    image = str(_svc(cfg, "db").get("image", ""))
    if problems:
        return Gate("G3", 0, 6, "; ".join(problems))
    if not RE_POSTGRES.match(image):
        return Gate("G3", 3, 6, f"db image {image or '(none)'} is not postgres:17…")
    return Gate("G3", 6, 6)


def _published(svc):
    return [p for p in svc.get("ports") or [] if p.get("published")]


def g4_ports(cfg) -> Gate:
    if _published(_svc(cfg, "db")):
        return Gate("G4", 0, 6, "db publishes a port: the database must not be reachable from outside (slide 25)")
    if _published(_svc(cfg, "api")):
        return Gate("G4", 3, 6, "api publishes a port: only web is the door in (slide 25)")
    web = _published(_svc(cfg, "web"))
    if not (len(web) == 1 and web[0].get("target") == 80 and str(web[0].get("published")) == "8080"
            and web[0].get("host_ip") in (None, "", "127.0.0.1", "0.0.0.0")):
        return Gate("G4", 3, 6, "web must publish exactly 8080 → 80 (HOST:CONTAINER, slide 25)")
    return Gate("G4", 6, 6)


def g5_names(repo, cfg) -> Gate:
    points, notes = 0, []
    host = str((_svc(cfg, "api").get("environment") or {}).get("DB_HOST", ""))
    if host == "db":
        points += 3
    else:
        notes.append(f"api DB_HOST is {host or '(not set)'}, not the service name db (slide 24)")
    conf = pathlib.Path(repo) / "web" / "nginx.conf"
    if conf.is_file() and RE_PROXY.search(_read(conf)):
        points += 3
    else:
        notes.append("web/nginx.conf: proxy_pass must be http://api:5000; (slide 35)")
    return Gate("G5", points, 6, "; ".join(notes))


def g6_volume(cfg) -> Gate:
    declared = cfg.get("volumes") or {}
    for v in _svc(cfg, "db").get("volumes") or []:
        if v.get("type") == "volume" and v.get("source") in declared and v.get("target") == PG_DATA:
            return Gate("G6", 6, 6)
    return Gate("G6", 0, 6, f"db has no named volume at {PG_DATA} (slide 30)")


def g7_health(cfg) -> Gate:
    hc = _svc(cfg, "db").get("healthcheck") or {}
    has_hc = bool(hc.get("test")) and hc.get("test") != ["NONE"] and not hc.get("disable")
    cond = ((_svc(cfg, "api").get("depends_on") or {}).get("db") or {}).get("condition")
    notes = ([] if has_hc else ["db has no health check (slide 37)"]) + \
            ([] if cond == "service_healthy" else ["api doesn't wait for db with condition: service_healthy (slide 37)"])
    return Gate("G7", (3 if has_hc else 0) + (3 if cond == "service_healthy" else 0), 6, "; ".join(notes))


def g8_config(repo, raw, cfg) -> Gate:
    repo, notes = pathlib.Path(repo), []
    for svc, key in (("db", "POSTGRES_PASSWORD"), ("api", "DB_PASSWORD")):
        if "${DB_PASSWORD" not in str(_env_dict(_svc(raw, svc).get("environment")).get(key, "")):
            notes.append(f"{svc} {key} must come from ${{DB_PASSWORD}} in .env (slide 46)")
    tracked = set(run(GIT + ["-C", repo, "ls-files"], check=False).stdout.splitlines())
    if ".env.example" not in tracked:
        notes.append(".env.example is not committed")
    if ".env" in tracked:
        notes.append(".env is committed: git rm --cached .env, and change the password (slide 47)")
    value = str((_svc(cfg, "db").get("environment") or {}).get("POSTGRES_PASSWORD", ""))
    if len(value) >= 6 and value in _read(repo / "compose.yaml"):
        notes.append("the password itself is written in compose.yaml")
    return Gate("G8", max(0, 5 - len(notes)), 5, "; ".join(notes))


def g11_history(repo) -> Gate:
    out = run(GIT + ["-C", repo, "log", "--all", "--format=", "--name-only", "--diff-filter=AM"],
              check=False).stdout
    bad = sorted({f for f in out.splitlines() if RE_FORBIDDEN_FILE.search(f)})
    if bad:
        return Gate("G11", 0, 3, f"in the Git history: {', '.join(bad[:5])}. It stays there even "
                                 "after deleting it (slides 31, 47)")
    return Gate("G11", 3, 3)


def static_gates(repo, env_file=".env", env=None) -> list:
    """G2–G8 and the history part of G11, for a working copy or a fresh clone.

    `docker compose config` follows env_file, extends and include, so it is never run
    on a compose.yaml that uses one of those keys."""
    repo = pathlib.Path(repo)
    gates = [g2_readme(repo)]
    compose_file = repo / "compose.yaml"
    reason = None
    hidden = hidden_key_problems(repo)          # raw bytes, symlink, encoding, words: no Docker call yet
    if hidden:
        reason = "; ".join(hidden)
    elif not compose_file.is_file():
        reason = "there is no compose.yaml"
    else:
        try:
            raw = config_json(repo, interpolate=False, env=env)
            cfg = config_json(repo, env_file=env_file, env=env)
        except Lab4Error as e:
            reason = f"docker compose config fails: {e}"
    if reason:
        status = "needs_human" if hidden else ""       # a refusal is the lecturer's call, never an automatic 0
        gates += [Gate(g, 0, m, reason, status=status) for g, m in
                  (("G3", 6), ("G4", 6), ("G5", 6), ("G6", 6), ("G7", 6), ("G8", 5))]
    else:
        gates += [g3_services(repo, cfg), g4_ports(cfg), g5_names(repo, cfg), g6_volume(cfg),
                  g7_health(cfg), g8_config(repo, raw, cfg)]
    gates.append(g11_history(repo))
    return gates


def _tail(error, lines=3) -> str:
    """The last lines of an error message, on one line."""
    return " | ".join(str(error).splitlines()[-lines:])[-600:]


def _g9_needs_human(detail) -> Gate:
    return Gate("G9", 0, 12, detail, status="needs_human")


def g9_run(repo, project, *, isolate=False, timeout=240, keep=False, budget=360) -> Gate:
    """The fresh-clone run test: up, POST a todo on :8080, down, up, the todo is still there.

    Expects .env in repo (copied from .env.example). Always adds run-override.yaml.
    Grader faults, unsafe files, names outside the project and a run longer than `budget`
    seconds are needs_human, never 0. The teardown never raises."""
    deadline = time.monotonic() + budget
    left = lambda: max(10, deadline - time.monotonic())          # noqa: E731
    too_slow = lambda: _g9_needs_human("run took longer than 6 minutes")   # noqa: E731
    repo = pathlib.Path(repo)
    if not RUN_OVERRIDE.is_file():
        return _g9_needs_human("grader: run-override.yaml missing")
    if port_busy(8080):
        return _g9_needs_human("grader: port 8080 busy")
    problems = hidden_key_problems(repo)       # the raw file, before Compose reads it at all
    if problems:
        return _g9_needs_human("compose.yaml is not safe to run: " + "; ".join(problems))
    files = ("compose.yaml", str(RUN_OVERRIDE))
    env = clean_env(isolate)
    kw = dict(files=files, project=project, env_file=".env", env=env)
    try:
        cfg = config_json(repo, timeout=left(), **kw)
    except Lab4Error as e:
        return too_slow() if time.monotonic() > deadline else \
            Gate("G9", 0, 12, f"docker compose config fails: {_tail(e)}")
    outside = sorted(str((v or {}).get("name", "")) or f"{kind}.{key}"
                     for kind in ("volumes", "networks") for key, v in (cfg.get(kind) or {}).items()
                     if not str((v or {}).get("name", "")).startswith(f"{project}_"))
    if outside:
        return _g9_needs_human(f"volume or network names outside the project ({project}_…): "
                               f"{', '.join(outside)}")

    def up():
        wait = str(int(min(timeout, left())))
        return compose(repo, ["up", "-d", "--build", "--wait", "--wait-timeout", wait],
                       timeout=left(), **kw)

    def steps() -> Gate:
        marker = f"lab4 check {uuid.uuid4().hex[:8]}"
        url = "http://127.0.0.1:8080/api/todos"             # the override binds loopback only
        try:
            try:
                up()
            except Lab4Error as e:
                return too_slow() if time.monotonic() > deadline else \
                    Gate("G9", 0, 12, f"the stack does not start: {_tail(e)}")
            if time.monotonic() > deadline:
                return too_slow()
            status, text = wait_http("POST", url, {201, 400}, {"title": marker},
                                     seconds=min(20, left()))
            if status != 201:
                return too_slow() if time.monotonic() > deadline else \
                    Gate("G9", 0, 12, f"POST /api/todos on port 8080 answered {status or 'nothing'}: {text[:200]}")
            compose(repo, ["down"], timeout=left(), **kw)
            up()
            if time.monotonic() > deadline:
                return too_slow()
            status, text = wait_http("GET", url, {200}, seconds=min(20, left()))
            if time.monotonic() > deadline:
                return too_slow()
            if status == 200 and marker in text:
                return Gate("G9", 12, 12)
            return Gate("G9", 6, 12, "the stack starts and saves a todo, but after down + up the todo is gone (slide 30)")
        except Lab4Error as e:
            return too_slow() if time.monotonic() > deadline else \
                Gate("G9", 0, 12, f"the stack failed during the test: {_tail(e)}")

    def teardown() -> str:
        """Never raises. Returns a note when the teardown did not finish cleanly."""
        try:
            p = compose(repo, ["down", "-v", "--rmi", "local", "--remove-orphans"], check=False,
                        timeout=180, **kw)
        except Lab4Error as e:
            return f"teardown failed, check for leftovers of {project}: {_tail(e)}"
        if p.returncode != 0:
            return f"teardown exited {p.returncode}, check for leftovers of {project}: " \
                   f"{_tail(p.stderr.strip() or p.stdout.strip())}"
        return ""

    note = ""
    try:
        gate = steps()
    finally:
        if not keep:
            note = teardown()
    if note:
        gate.detail = f"{gate.detail}; {note}" if gate.detail else note
    return gate
