#!/usr/bin/env python3
"""Lab 4 Compose clinic (design section 7): eight small stacks, one fault each.

    bash clinic.sh setup [--force] | check N | hint N | reset N | down N | status | export | clean

`check` starts a mission's stack and tests its behaviour. The grader calls verify() on the
files students export to lab4/clinic/cN/, using its own trusted copy of this file."""
import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import (CLINIC_IMAGE, HOST, NGINX_IMAGE, PG_DATA, POSTGRES_IMAGE, Lab4Error,  # noqa: E402
                    clean_env, compose, config_json, run, wait_http)
from gates import RE_HIDDEN_KEYS, _env_dict, _svc, hidden_key_problems, variables  # noqa: E402

C8_MARKER = "c8 marker: keep me"
IMAGES = {"web": NGINX_IMAGE, "api": CLINIC_IMAGE, "db": POSTGRES_IMAGE, "migrate": POSTGRES_IMAGE}
CLINIC_KEYS = {"image", "ports", "environment", "depends_on", "healthcheck", "networks", "volumes",
               "restart", "command", "entrypoint"}
C6_ENTRYPOINT = ["sh", "-c", "sleep 8 && exec docker-entrypoint.sh postgres"]
C6_COMMAND = ["psql", "-h", "db", "-U", "todo", "-d", "todo", "-v", "ON_ERROR_STOP=1", "-c",
              "CREATE TABLE IF NOT EXISTS todos (id SERIAL PRIMARY KEY, title TEXT NOT NULL, "
              "done BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT now()); "
              "INSERT INTO todos (title) VALUES ('seeded by migrate');"]
TOP_KEYS = {"name", "services", "networks", "volumes"}
HEALTHCHECK_KEYS = {"test", "interval", "timeout", "retries", "start_period", "start_interval"}
RE_PG_ARG = re.compile(r"^[A-Za-z0-9_.-]+$")
RE_PG_SHELL = re.compile(r"^pg_isready(?: -[hUdp] [A-Za-z0-9_.-]+| -q)*$")
RE_ABS_API = re.compile(r"""https?://[^'"`\s]*(api|localhost|127\.0\.0\.1)(:\d+)?/api""")

BASE_COMPOSE = """\
# Compose clinic, mission c{n}. Investigate with the usual docker compose commands in this folder.
name: clinic-c{n}

services:
  web:
    image: nginx:1.30-alpine
    ports:
      - "{port}:80"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./public:/usr/share/nginx/html:ro
    depends_on:
      api:
        condition: service_started
        restart: true
    networks: [front]

  api:
    image: ghcr.io/mleitass/lab4-clinic-api:1
    environment:
      DB_HOST: db
      DB_USER: todo
      DB_NAME: todo
      DB_PASSWORD: ${DB_PASSWORD:?set DB_PASSWORD in .env}
    depends_on:
      db:
        condition: service_healthy
    networks: [front, back]

  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_USER: todo
      POSTGRES_DB: todo
      POSTGRES_PASSWORD: ${DB_PASSWORD:?set DB_PASSWORD in .env}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-h", "localhost", "-U", "todo", "-d", "todo"]
      interval: 2s
      timeout: 3s
      retries: 15
      start_period: 5s
    networks: [back]

networks:
  front:
  back:

volumes:
  pgdata:
"""

C6_COMPOSE = """\
# Compose clinic, mission c6. Investigate with the usual docker compose commands in this folder.
name: clinic-c6

services:
  web:
    image: nginx:1.30-alpine
    ports:
      - "8106:80"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./public:/usr/share/nginx/html:ro
    depends_on:
      api:
        condition: service_started
        restart: true
    networks: [front]

  api:
    image: ghcr.io/mleitass/lab4-clinic-api:1
    environment:
      DB_HOST: db
      DB_USER: todo
      DB_NAME: todo
      DB_PASSWORD: ${DB_PASSWORD:?set DB_PASSWORD in .env}
    depends_on:
      migrate:
        condition: service_completed_successfully
    networks: [front, back]

  migrate:                     # creates the table and adds a first todo, then exits
    image: postgres:17-alpine
    command: {command}
    environment:
      PGPASSWORD: ${DB_PASSWORD:?set DB_PASSWORD in .env}
    depends_on: [db]
    networks: [back]

  db:
    image: postgres:17-alpine
    entrypoint: {entrypoint}   # simulates a slow server: leave it
    environment:
      POSTGRES_USER: todo
      POSTGRES_DB: todo
      POSTGRES_PASSWORD: ${DB_PASSWORD:?set DB_PASSWORD in .env}
    volumes:
      - pgdata:/var/lib/postgresql/data
    networks: [back]

networks:
  front:
  back:

volumes:
  pgdata:
""".replace("{command}", json.dumps(C6_COMMAND)).replace("{entrypoint}", json.dumps(C6_ENTRYPOINT))

NGINX_CONF = """\
server {
    listen {listen};
    root /usr/share/nginx/html;

    location /api/ {
        proxy_pass http://api:5000;
    }
}
"""

INDEX_HTML = """\
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Compose clinic</title></head>
<body><h1>Todos</h1>
<form id="add"><input id="title" required> <button>Add</button></form>
<p id="status"></p><ul id="list"></ul>
<script src="app.js"></script></body></html>
"""

APP_JS = """\
// Runs in your browser. It calls the API at the address below.
const API = '{api}';
const list = document.getElementById('list');
const statusLine = document.getElementById('status');

async function load() {
  try {
    const res = await fetch(API);
    if (!res.ok) throw new Error(`GET ${API} answered ${res.status}`);
    list.replaceChildren(...(await res.json()).map((t) => {
      const li = document.createElement('li');
      li.textContent = t.title;
      return li;
    }));
    statusLine.textContent = '';
  } catch (err) {
    statusLine.textContent = err.message;
  }
}

document.getElementById('add').onsubmit = async (e) => {
  e.preventDefault();
  const input = document.getElementById('title');
  await fetch(API, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                     body: JSON.stringify({ title: input.value }) }).catch(() => {});
  input.value = '';
  load();
};

load();
"""

ENV_TEXT = {n: f"DB_PASSWORD=clinic-c{n}-pass\n" for n in range(1, 8)}
ENV_TEXT[8] = "DB_PASSWORD=clinic-c8-new\n"


# ---------------------------------------------------------------- behaviour

def _last_line(err):
    lines = [line for line in str(err).splitlines() if line.strip()]
    return lines[-1] if lines else str(err)


def _get_ok(port, path):
    status, _ = wait_http("GET", f"http://{HOST}:{port}{path}", {200}, seconds=15)
    return (True, "") if status == 200 else (False, f"GET http://localhost:{port}{path} answered {status or 'nothing'}")


def _up(mdir, kw, timeout=90):
    compose(mdir, ["up", "-d", "--wait", "--wait-timeout", str(timeout)], **kw)


def b_default(n, mdir, kw):
    compose(mdir, ["down", "--remove-orphans"], check=False, **kw)
    try:
        _up(mdir, kw)
    except Lab4Error as e:
        return False, f"the stack doesn't start cleanly: {_last_line(e)}"
    return _get_ok(MISSIONS[n]["port"], "/api/todos")


def b_c2(n, mdir, kw):
    ok, msg = b_default(n, mdir, kw)
    return _get_ok(8102, "/") if ok else (ok, msg)


def b_c4(n, mdir, kw):
    ok, msg = b_default(n, mdir, kw)
    return _get_ok(8104, "/app.js") if ok else (ok, msg)


def b_c5(n, mdir, kw):
    ok, msg = b_default(n, mdir, kw)
    if not ok:
        return ok, msg
    marker = f"c5 marker {os.urandom(3).hex()}"
    status, _ = wait_http("POST", f"http://{HOST}:8105/api/todos", {201}, {"title": marker}, seconds=15)
    if status != 201:
        return False, f"POST /api/todos answered {status or 'nothing'}"
    compose(mdir, ["down"], **kw)
    _up(mdir, kw)
    _, text = wait_http("GET", f"http://{HOST}:8105/api/todos", {200}, seconds=15)
    return (True, "") if marker in text else (False, "the todo is gone after docker compose down and up")


def _ps(mdir, kw):
    out = compose(mdir, ["ps", "-a", "--format", "json"], check=False, **kw).stdout.strip()
    if not out:
        return []
    try:
        data = json.loads(out)
        return data if isinstance(data, list) else [data]
    except ValueError:
        return [json.loads(line) for line in out.splitlines() if line.strip()]


def b_c6(n, mdir, kw):
    compose(mdir, ["down", "-v", "--remove-orphans"], check=False, **kw)
    try:
        _up(mdir, kw, timeout=120)
    except Lab4Error:
        pass                                    # judged by migrate's exit code below
    mig = {c.get("Service"): c for c in _ps(mdir, kw)}.get("migrate", {})
    if mig.get("State") != "exited" or str(mig.get("ExitCode")) != "0":
        return False, (f"migrate did not succeed on a fresh start (state {mig.get('State')}, exit code "
                       f"{mig.get('ExitCode')}). Look at: docker compose logs migrate")
    _, text = wait_http("GET", f"http://{HOST}:8106/api/todos", {200}, seconds=15)
    return (True, "") if "seeded by migrate" in text else (False, "the API doesn't serve the seeded todo")


def b_c8(n, mdir, kw):
    try:
        _up(mdir, kw)
    except Lab4Error as e:
        return False, f"the stack doesn't start cleanly: {_last_line(e)}"
    status, text = wait_http("GET", f"http://{HOST}:8108/api/todos", {200}, seconds=15)
    if status != 200:
        return False, f"GET http://localhost:8108/api/todos answered {status or 'nothing'}"
    return (True, "") if C8_MARKER in text else (False, f"the todo '{C8_MARKER}' is gone: the data had to survive")


# ---------------------------------------------------------------- rules (after the behaviour passed)

def _env(raw, name):
    """A service's environment as a dict, whether the file wrote it as a map or as KEY=VALUE items."""
    return _env_dict(_svc(raw, name).get("environment"))


def r_c1(mdir, raw):
    return [] if _env(raw, "api").get("DB_HOST") == "db" else ["api must reach the database by its service name (slide 24)"]


def r_c2(mdir, raw):
    p = []
    if (mdir / "nginx.conf").read_text() != NGINX_CONF.replace("{listen}", "3000"):
        p.append("nginx.conf must stay as it was: this mission is about the port mapping")
    if [(str(x.get("published")), x.get("target")) for x in _svc(raw, "web").get("ports") or []] != [("8102", 3000)]:
        p.append("web must publish 8102 on your laptop to 3000 in the container")
    return p


def r_c3(mdir, raw):
    shared = set(_svc(raw, "web").get("networks") or {}) & set(_svc(raw, "db").get("networks") or {})
    return ["web and db now share a network, so web could reach the database: keep web off back (slide 27)"] if shared else []


def r_c4(mdir, raw):
    js = (mdir / "public" / "app.js").read_text(encoding="utf-8", errors="replace")
    p = []
    if RE_ABS_API.search(js):
        p.append("app.js still calls the API directly: the browser can only use addresses your laptop knows (slide 26)")
    if not re.search(r"""['"`]/api/todos""", js):
        p.append("app.js must call /api/todos on the same origin (slide 26)")
    return p


def r_c5(mdir, raw):
    declared = raw.get("volumes") or {}
    ok = any(v.get("type") == "volume" and v.get("source") in declared and v.get("target") == PG_DATA
             for v in _svc(raw, "db").get("volumes") or [])
    return [] if ok else [f"db needs a named volume at {PG_DATA} (slide 30)"]


def r_c6(mdir, raw):
    p = []
    hc = _svc(raw, "db").get("healthcheck") or {}
    if not hc.get("test") or hc.get("disable"):
        p.append("db needs a health check that says when PostgreSQL accepts connections (slide 37)")
    if ((_svc(raw, "migrate").get("depends_on") or {}).get("db") or {}).get("condition") != "service_healthy":
        p.append("migrate must wait for db with condition: service_healthy (slide 37)")
    return p


def r_c7(mdir, raw):
    p = [f"{svc} {key} must be filled in from DB_PASSWORD in .env (slide 46)"
         for svc, key in (("db", "POSTGRES_PASSWORD"), ("api", "DB_PASSWORD"))
         if "${DB_PASSWORD" not in str(_env(raw, svc).get(key, ""))]
    if (mdir / ".env").read_text() != ENV_TEXT[7]:
        p.append(".env must stay as it was")
    if "clinic-c7-pass" in (mdir / "compose.yaml").read_text():
        p.append("the password is written in compose.yaml: it would end up in Git (slide 47)")
    if "POSTGRES_HOST_AUTH_METHOD" in _env(raw, "db"):
        p.append("POSTGRES_HOST_AUTH_METHOD switches the password off: remove it")
    return p


def r_c8(mdir, raw):
    return [] if (mdir / ".env").read_text() == ENV_TEXT[8] else [".env must keep the new password"]


# ---------------------------------------------------------------- the missions

MISSIONS = {
    1: dict(title="Worked example: the API can't reach the database", port=8101,
            faults=[("      DB_HOST: db\n", "      DB_HOST: localhost\n")],
            overlay=["compose.yaml"], behaviour=b_default, rules=r_c1,
            symptom="The page on http://localhost:8101 loads, but /api/todos answers 500.",
            goal="GET http://localhost:8101/api/todos answers 200.",
            change="compose.yaml",
            hints=["`docker compose logs api`: find the line with ECONNREFUSED. Which address and port did the API try?",
                   "Inside the api container, which machine is localhost? Which name does Docker's DNS answer for "
                   "the database? (slide 24)",
                   "Set `DB_HOST: db`, then `docker compose up -d`: Compose recreates only api. Publishing db's port "
                   "would also 'work', but it opens a door into the database: the check rejects it."]),
    2: dict(title="Nothing answers on the app's address", port=8102, listen=3000,
            faults=[('      - "8102:80"\n', '      - "3000:8102"\n')],
            overlay=["compose.yaml"], behaviour=b_c2, rules=r_c2,
            symptom="nginx in this stack listens on port 3000 (see nginx.conf). The app should open on "
                    "http://localhost:8102, but nothing answers there.",
            goal="http://localhost:8102 shows the page, and /api/todos answers 200.",
            change="compose.yaml (nginx.conf stays as it is)",
            hints=["`docker compose ps`: read the PORTS column (laptop side -> container side). Then try "
                   "`curl -v localhost:8102` and `curl -v localhost:3000`. What does each say?",
                   "In HOST:CONTAINER the left number is the door on your laptop, and the right number is where "
                   "nginx listens inside the container. nginx.conf says where it listens. (slide 25)",
                   'Use `- "8102:3000"`. Changing nginx.conf to listen on 8102 also works, but this mission is '
                   "about the mapping: nginx.conf must stay as it is."]),
    3: dict(title="web can't find the API", port=8103,
            faults=[("    networks: [front, back]\n", "    networks: [back]\n")],
            overlay=["compose.yaml"], behaviour=b_default, rules=r_c3,
            symptom="`docker compose ps -a` shows web exited or restarting.",
            goal="http://localhost:8103/api/todos answers 200, and web still can't reach db.",
            change="compose.yaml",
            hints=["`docker compose logs web`: what can't nginx find? Then `docker compose config` and compare "
                   "the networks of web, api and db.",
                   "Docker's DNS only answers for services on a network you share. Who has to be on which network "
                   "so that web reaches api, but not db? (slides 24, 26a, 27)",
                   "Put api on both networks: `networks: [front, back]`. Moving web onto back works too, but then "
                   "web could reach the database: the check rejects it."]),
    4: dict(title="The page loads, the list stays empty", port=8104, app_api="http://api:5000/api/todos",
            overlay=["compose.yaml", "public/app.js"], behaviour=b_c4, rules=r_c4,
            symptom="http://localhost:8104 loads, but the list stays empty and adding a todo does nothing. Open "
                    "the browser's developer tools (F12) -> Console.",
            goal="The page lists and adds todos in your browser.",
            change="public/app.js and compose.yaml",
            hints=["Open http://localhost:8104 and press F12 -> Console and Network. Which URL does the page call, "
                   "and what does the browser say?",
                   "Where does app.js run: in a container, or in your browser? Can your laptop resolve the name "
                   "api? (slide 26)",
                   "In public/app.js use `const API = '/api/todos';`. The browser calls the same origin, and nginx "
                   "forwards /api/ to api:5000. Publishing 5000 and calling localhost:5000 opens a second door and "
                   "runs into CORS: the check rejects it."]),
    5: dict(title="Todos disappear", port=8105,
            faults=[("    volumes:\n      - pgdata:/var/lib/postgresql/data\n", ""), ("\nvolumes:\n  pgdata:\n", "\n")],
            overlay=["compose.yaml"], behaviour=b_c5, rules=r_c5,
            symptom="Todos disappear after `docker compose down` and `docker compose up -d`.",
            goal="Todos survive down and up.",
            change="compose.yaml",
            hints=["Add a todo, then `docker compose down` and `docker compose up -d`. Run `docker volume ls` "
                   "before and after: what is new each time?",
                   "A container's writable layer goes with the container. Which kind of mount outlives it, and "
                   "where does PostgreSQL 17 keep its files? (slides 28-30)",
                   "Under db add `volumes: - pgdata:/var/lib/postgresql/data`, and at the bottom of the file "
                   "`volumes:` with `pgdata:` under it. A bind mount to a laptop folder also keeps the data, but "
                   "database files belong on a named volume (slide 29): the check rejects the bind mount."]),
    6: dict(title="The first start fails", port=8106, services=("web", "api", "db", "migrate"),
            fixed={"db": {"entrypoint": C6_ENTRYPOINT}, "migrate": {"command": C6_COMMAND}},
            overlay=["compose.yaml"], behaviour=b_c6, rules=r_c6,
            symptom="migrate (it creates the table and adds a first todo) exits with an error, so api never "
                    "starts. db starts PostgreSQL after 8 seconds: that simulates a slow server, leave it.",
            goal="From an empty database (docker compose down -v, then up -d), migrate succeeds every time, and "
                 "the API shows 'seeded by migrate'.",
            change="compose.yaml",
            hints=["`docker compose ps -a` and `docker compose logs migrate`. What did psql say, and was db already "
                   "accepting connections at that moment?",
                   "`depends_on: [db]` waits for what, exactly? What tells Compose that PostgreSQL is ready? (slide 37)",
                   "Give db a health check (the one from your own compose.yaml: pg_isready -h localhost -U todo -d todo, "
                   "interval 5s, retries 10, start_period 10s) and make migrate wait with "
                   "`depends_on: db: condition: service_healthy`. A sleep or a retry loop hides the problem instead "
                   "of declaring readiness: the check rejects them."]),
    7: dict(title="db stops right after it starts", port=8107,
            faults=[("${DB_PASSWORD:?set DB_PASSWORD in .env}", "${DB_PASS}")],
            overlay=["compose.yaml"], behaviour=b_default, rules=r_c7,
            symptom="db stops right after it starts, and Compose prints a warning.",
            goal="The stack runs with the password from .env, and /api/todos answers 200.",
            change="compose.yaml (.env stays as it is)",
            hints=["Run `docker compose up -d` and read the WARN line. Then `docker compose logs db`. Compare the "
                   "variable name in compose.yaml with the name in .env.",
                   "Compose fills ${...} from .env by name. What does it put in when the name doesn't exist? "
                   "(slides 34, 46)",
                   "Use `${DB_PASSWORD:?set DB_PASSWORD in .env}` in both places. Writing the password into "
                   "compose.yaml, or POSTGRES_HOST_AUTH_METHOD=trust, also starts db, but puts a secret in Git or "
                   "switches the password off: the check rejects both."]),
    8: dict(title="Stretch: the password was rotated", port=8108,
            overlay=[], behaviour=b_c8, rules=r_c8,
            symptom="The team rotated the database password: .env now holds the new one. Since then the API "
                    "can't log in.",
            goal=f"The API works with the NEW password from .env, and the todo '{C8_MARKER}' is still there. "
                 "Don't delete the volume.",
            change="no files: the fix is a command",
            hints=["`docker compose logs api` and `docker compose logs db`: which login fails?",
                   "POSTGRES_PASSWORD is used only when the volume is empty (slide 30). Where does the old password "
                   "still live?",
                   "docker compose exec db psql -U todo -d todo -c \"ALTER USER todo PASSWORD 'clinic-c8-new'\" "
                   "(inside the container, local connections need no password). `down -v` also 'works', and "
                   "deletes every todo."]),
}


# ---------------------------------------------------------------- files and checks

def root():
    return pathlib.Path(os.environ.get("CLINIC_ROOT") or pathlib.Path.home() / "compose-clinic")


def compose_text(n):
    m = MISSIONS[n]
    text = (C6_COMPOSE if n == 6 else BASE_COMPOSE).replace("{n}", str(n)).replace("{port}", str(m["port"]))
    for old, new in m.get("faults", []):
        if old not in text:
            raise AssertionError(f"c{n}: fault does not apply: {old!r}")
        text = text.replace(old, new)
    return text


def mission_text(n):
    m = MISSIONS[n]
    return (f"Compose clinic · c{n} · {m['title']}\n\n"
            f"What you see\n  {m['symptom']}\n\nGoal\n  {m['goal']}\n\nYou may change\n  {m['change']}\n\n"
            f"Check   bash ~/compose-clinic/clinic.sh check {n}\n"
            f"Hint    bash ~/compose-clinic/clinic.sh hint {n}    (free, one level at a time)\n")


def write_mission(n, mdir):
    m, mdir = MISSIONS[n], pathlib.Path(mdir)
    shutil.rmtree(mdir, ignore_errors=True)
    (mdir / "public").mkdir(parents=True)
    (mdir / "compose.yaml").write_text(compose_text(n), encoding="utf-8")
    (mdir / ".env").write_text(ENV_TEXT[n], encoding="utf-8")
    (mdir / "nginx.conf").write_text(NGINX_CONF.replace("{listen}", str(m.get("listen", 80))), encoding="utf-8")
    (mdir / "public" / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (mdir / "public" / "app.js").write_text(APP_JS.replace("{api}", m.get("app_api", "/api/todos")), encoding="utf-8")
    (mdir / "MISSION.txt").write_text(mission_text(n), encoding="utf-8")


def _healthcheck_problems(name, svc):
    hc = svc.get("healthcheck")
    if hc is None:
        return []
    if name != "db":
        return [f"services.{name}.healthcheck is not allowed in the clinic (only db has one)"]
    hc = hc if isinstance(hc, dict) else {}
    p = [f"services.db.healthcheck.{k} is not allowed" for k in sorted(set(hc) - HEALTHCHECK_KEYS)]
    test = hc.get("test")
    cmd_form = (isinstance(test, list) and len(test) >= 2 and test[0] == "CMD" and test[1] == "pg_isready"
                and all(RE_PG_ARG.match(str(a)) for a in test[2:]))
    shell_form = (isinstance(test, list) and len(test) == 2 and test[0] == "CMD-SHELL"
                  and bool(RE_PG_SHELL.match(str(test[1]))))
    if not (cmd_form or shell_form):
        p.append("services.db.healthcheck.test must be a pg_isready command")
    return p


def _web_port_problems(n, web):
    m = MISSIONS[n]
    allowed = {str(m["port"])} | ({str(m["listen"])} if m.get("listen") else set())
    ports = web.get("ports") or []
    ok = (len(ports) == 1 and str(ports[0].get("published")) in allowed
          and ports[0].get("host_ip") in (None, "", "127.0.0.1") and ports[0].get("protocol") in (None, "tcp"))
    return [] if ok else [f"web may publish exactly one port, {m['port']} on localhost (127.0.0.1 or no address)"]


def _variable_problems(raw):
    bad = variables(raw) - {"DB_PASSWORD"}
    return [f"only ${{DB_PASSWORD}} may be filled in from .env (found {sorted(bad)})"] if bad else []


def mission_shape_problems(n, mdir, raw):
    """The mission's exact shape, with the variable check. Anything else is refused (when grading:
    sent to the lecturer)."""
    return _shape_problems(n, mdir, raw) + _variable_problems(raw)


def _shape_problems(n, mdir, raw):
    """Everything about the shape that running the stack can't judge (the variable check is separate:
    the behaviour says more about a wrong variable name than a rule would)."""
    mdir, m = pathlib.Path(mdir).resolve(), MISSIONS[n]
    text = (mdir / "compose.yaml").read_text(encoding="utf-8", errors="replace")
    p = [f"compose.yaml uses `{k}:`" for k in sorted(set(RE_HIDDEN_KEYS.findall(text)))]
    p += [f"compose.yaml has a top-level `{k}:`, which is not part of the clinic" for k in sorted(set(raw) - TOP_KEYS)]
    services = raw.get("services") or {}
    expected = set(m.get("services", ("web", "api", "db")))
    if set(services) != expected:
        p.append(f"the services must stay {', '.join(sorted(expected))}")
    if "web" in services:
        p += _web_port_problems(n, services["web"] or {})
    binds = {str(mdir / "nginx.conf"): "/etc/nginx/conf.d/default.conf", str(mdir / "public"): "/usr/share/nginx/html"}
    mounts_msg = "only named volumes (and web's own nginx.conf and public/, read-only) are allowed"
    for name, svc in services.items():
        svc = svc or {}
        p += [f"services.{name}.{k} is not allowed in the clinic" for k in sorted(set(svc) - CLINIC_KEYS)]
        p += _healthcheck_problems(name, svc)
        if svc.get("image") != IMAGES.get(name) or "build" in svc:
            p.append(f"services.{name}.image must stay {IMAGES.get(name)}")
        fixed = m.get("fixed", {}).get(name, {})
        for key in ("command", "entrypoint"):
            if svc.get(key) != fixed.get(key):
                p.append(f"services.{name}.{key} must stay as it was")
        if name != "web" and svc.get("ports"):
            p.append(f"only web may publish a port ({name} publishes one)")
        for net, val in (svc.get("networks") or {}).items():
            if val not in (None, {}):
                p.append(f"services.{name}.networks.{net}: network options are not allowed")
        for vol in svc.get("volumes") or []:
            if vol.get("type") == "bind":
                if name != "web" or binds.get(vol.get("source")) != vol.get("target") or not vol.get("read_only"):
                    p.append(f"services.{name}: {mounts_msg}")
            elif vol.get("type") != "volume" or vol.get("source") not in (raw.get("volumes") or {}):
                p.append(f"services.{name}: {mounts_msg}")
    project = raw.get("name", "")
    for kind, allowed in (("networks", {"name", "internal"}), ("volumes", {"name"})):
        for key, val in (raw.get(kind) or {}).items():
            val = val or {}
            if set(val) - allowed or val.get("name", f"{project}_{key}") != f"{project}_{key}":
                p.append(f"{kind}.{key}: only a plain {kind[:-1]} is allowed")
    return p


def run_override_text(raw):
    """Added by the grader (untrusted runs), in the style of run-override.yaml: only web is reachable and
    only from this machine, every service has limits and never restarts. Needs a shape that passed."""
    web = raw["services"]["web"]["ports"][0]
    lines = ["# Generated by clinic.py for the grader's run.", "services:"]
    for name in raw["services"]:
        lines.append(f"  {name}:")
        if name == "web":
            lines += ["    ports: !override", f'      - "127.0.0.1:{web["published"]}:{web["target"]}"']
        else:
            lines.append("    ports: !reset []")
        lines += ['    restart: "no"', f"    mem_limit: {'256m' if name == 'web' else '512m'}",
                  "    cpus: 1", "    pids_limit: 200"]
    return "\n".join(lines) + "\n"


def check_mission(n, mdir, *, untrusted=False, isolate=False, project=None):
    """(status, message): status is pass, fail or needs_human (only when untrusted).

    An unexpected error never escapes: when grading it is needs_human, for a student it is a fail."""
    try:
        return _check_mission(n, mdir, untrusted, isolate, project)
    except Exception as e:                                  # noqa: BLE001
        text = f"the check hit an unexpected problem: {type(e).__name__}: {_last_line(e)}"
        return ("needs_human", text) if untrusted else ("fail", text)


def _check_mission(n, mdir, untrusted, isolate, project):
    mdir = pathlib.Path(mdir).resolve()
    env = clean_env(isolate)
    kw = dict(project=project or f"clinic-c{n}", env_file=".env", env=env, timeout=400)
    # Before Docker reads the file at all: the gates' byte-level check (symlink, BOM, backslash,
    # YAML tags and directives, and the words include, extends, env_file, … anywhere).
    hidden = hidden_key_problems(mdir)
    if hidden:
        return ("needs_human", "; ".join(hidden)) if untrusted else ("fail", hidden[0])
    try:
        raw = config_json(mdir, interpolate=False, project=kw["project"], env=env)
    except Lab4Error as e:
        return "fail", f"compose.yaml is not valid: {_last_line(e)}"
    # The shape comes first: a bind mount at db's data folder may or may not keep the data on a given
    # Docker host, so the behaviour alone can't tell the student what is wrong with it. A student still
    # finds a wrong variable name by running the stack, so that one is reported after the behaviour.
    if untrusted:
        problems = mission_shape_problems(n, mdir, raw)
        if problems:
            return "needs_human", "; ".join(problems)
    else:
        problems = _shape_problems(n, mdir, raw)
        if problems:
            return "fail", problems[0]
    scratch = None
    try:
        if untrusted:
            scratch = pathlib.Path(tempfile.mkdtemp(prefix="clinic-override-"))
            (scratch / "run-override.yaml").write_text(run_override_text(raw), encoding="utf-8")
            kw["files"] = ("compose.yaml", str(scratch / "run-override.yaml"))
        ok, msg = MISSIONS[n]["behaviour"](n, mdir, kw)
        if not ok:
            return "fail", msg
        problems = _variable_problems(raw) + MISSIONS[n]["rules"](mdir, raw)
        return ("fail", problems[0]) if problems else ("pass", "")
    except Lab4Error as e:
        return "fail", _last_line(e)
    finally:
        down = ["down"] if (n == 8 and not untrusted) else ["down", "-v", "--remove-orphans"]
        compose(mdir, down, check=False, **kw)
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)


def verify(n, fix_dir, *, isolate=True, project=None):
    """Grader and check.sh clinic: rebuild mission n from this file, overlay the exported files, check."""
    try:
        return _verify(n, pathlib.Path(fix_dir), isolate, project)
    except Exception as e:                                  # noqa: BLE001
        return "needs_human", f"the check hit an unexpected problem: {type(e).__name__}: {_last_line(e)}"


def _verify(n, fix_dir, isolate, project):
    if fix_dir.is_symlink():
        return "needs_human", f"lab4/clinic/c{n} is a symlink"
    base = pathlib.Path.home() / ".lab4-tmp"
    base.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"verify-c{n}-", dir=base) as tmp:
        mdir = pathlib.Path(tmp) / f"c{n}"
        write_mission(n, mdir)
        for rel in MISSIONS[n]["overlay"]:
            src = fix_dir / rel
            if not src.exists() and not src.is_symlink():
                return "fail", f"lab4/clinic/c{n}/{rel} is missing: run clinic.sh export again"
            if src.is_symlink() or not src.resolve().is_relative_to(fix_dir.resolve()):
                return "needs_human", f"lab4/clinic/c{n}/{rel} is a symlink or sits behind one"
            if not src.is_file():
                return "fail", f"lab4/clinic/c{n}/{rel} is missing: run clinic.sh export again"
            shutil.copyfile(src, mdir / rel)
        return check_mission(n, mdir, untrusted=True, isolate=isolate, project=project or f"lab4-verify-c{n}")


# ---------------------------------------------------------------- state and commands

def _state_file():
    return root() / ".state.json"


def load_state():
    try:
        return json.loads(_state_file().read_text())
    except (OSError, ValueError):
        return {"hints": {}, "passed": {}}


def save_state(state):
    _state_file().write_text(json.dumps(state, indent=1))


def digest(mdir, files):
    h = hashlib.sha256()
    for rel in files:
        h.update(rel.encode())
        h.update((pathlib.Path(mdir) / rel).read_bytes())
    return h.hexdigest()


def _remove_by_label(n, volumes):
    """Last resort when `compose down` can't parse the mission's files (a student's broken edit)."""
    label = f"label=com.docker.compose.project=clinic-c{n}"
    for kind, listing, remove in (("containers", ["ps", "-aq"], ["rm", "-f"]),
                                  ("networks", ["network", "ls", "-q"], ["network", "rm"]),
                                  ("volumes", ["volume", "ls", "-q"], ["volume", "rm"])):
        if kind == "volumes" and not volumes:
            continue
        ids = run(["docker"] + listing + ["--filter", label], check=False).stdout.split()
        if ids:
            run(["docker"] + remove + ids, check=False)


def compose_down(n, volumes):
    """Tear mission n down through its own folder and compose file (never the student's cwd)."""
    mdir = root() / f"c{n}"
    done = False
    if (mdir / "compose.yaml").is_file():
        try:
            done = compose(mdir, ["down", "--remove-orphans"] + (["-v"] if volumes else []),
                           project=f"clinic-c{n}", env_file=".env", check=False, timeout=400).returncode == 0
        except Lab4Error:
            done = False
    if volumes or not done:
        _remove_by_label(n, volumes)       # with -v: also sweeps what `down` missed, by the exact project label


def prepare_c8(mdir):
    """c8 needs a volume made with the OLD password and a todo in it; .env then gets the new one."""
    kw = dict(project="clinic-c8", env_file=".env", env=clean_env(), timeout=400)
    fail = "c8 could not be prepared{}. Is Docker running? Try again: bash ~/compose-clinic/clinic.sh reset 8"
    (mdir / ".env").write_text("DB_PASSWORD=clinic-c8-old\n")
    try:
        compose(mdir, ["down", "-v", "--remove-orphans"], check=False, **kw)
        _up(mdir, kw, timeout=120)
        status, _ = wait_http("POST", f"http://{HOST}:8108/api/todos", {201}, {"title": C8_MARKER}, seconds=30)
        compose(mdir, ["down"], **kw)
    except Lab4Error as e:
        compose_down(8, volumes=True)
        raise Lab4Error(fail.format(f" ({_last_line(e)[:150]})")) from None
    finally:
        (mdir / ".env").write_text(ENV_TEXT[8])
    if status != 201:
        compose_down(8, volumes=True)
        raise Lab4Error(fail.format(""))


def cmd_setup(force=False):
    r = root()
    if r.exists() and HERE.is_relative_to(r.resolve()):
        raise Lab4Error("Run setup from your fork: bash lab04-multi-service-compose/clinic.sh setup --force")
    if r.exists() and any(r.glob("c*/compose.yaml")):
        if not force:
            raise Lab4Error(f"{r} already exists. One mission again: bash ~/compose-clinic/clinic.sh reset N. "
                            "Everything again (your fixes are lost): "
                            "bash lab04-multi-service-compose/clinic.sh setup --force")
        cmd_clean(quiet=True)
    r.mkdir(parents=True, exist_ok=True)
    shutil.copytree(HERE, r / "tools", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(HERE.parent / "clinic.sh", r / "clinic.sh")
    for n in MISSIONS:
        write_mission(n, r / f"c{n}")
    save_state({"hints": {}, "passed": {}})
    print("Preparing c8 (about 30 seconds)…", flush=True)
    prepare_c8(r / "c8")
    print(f"✔ Eight missions are ready in {r}.\n  Start with the worked example: cat {r}/c1/MISSION.txt")
    return 0


def cmd_check(n):
    mdir = root() / f"c{n}"
    print(f"Checking c{n}: the stack starts from scratch; this takes up to a minute…", flush=True)
    status, msg = check_mission(n, mdir)
    state = load_state()
    hints = state["hints"].get(str(n), 0)
    if status == "pass":
        state["passed"][str(n)] = digest(mdir, MISSIONS[n]["overlay"])
        save_state(state)
        print(f"✔ c{n} passes · hints used: {hints}")
        if n not in (1, 8):
            print("  Write it up in lab4/README.md. When you're done with the clinic, from your fork's root: "
                  "bash ~/compose-clinic/clinic.sh export")
        return 0
    state["passed"].pop(str(n), None)
    save_state(state)
    print(f"✘ c{n}: {msg}\n  Stuck? bash ~/compose-clinic/clinic.sh hint {n}")
    return 1


def cmd_hint(n):
    state = load_state()
    level = min(3, state["hints"].get(str(n), 0) + 1)
    state["hints"][str(n)] = level
    save_state(state)
    label = ["🔎 Look", "💡 Think", "🛠 Fix"][level - 1]
    print(f"Hint {level} of 3 for c{n} · {label}\n  {MISSIONS[n]['hints'][level - 1]}")
    if level < 3:
        print("\n  Still stuck? Run the same command again for the next hint.")
    return 0


def cmd_reset(n):
    mdir = root() / f"c{n}"
    compose_down(n, volumes=True)
    write_mission(n, mdir)
    if n == 8:
        prepare_c8(mdir)
    state = load_state()
    state["passed"].pop(str(n), None)
    save_state(state)
    print(f"✔ c{n} is back to how it was at setup. Hints you used stay counted.")
    return 0


def cmd_down(n):
    compose_down(n, volumes=(n != 8))
    print(f"✔ c{n} stopped.")
    return 0


def cmd_status():
    state = load_state()
    for n, m in MISSIONS.items():
        done = "✔ passed " if str(n) in state["passed"] else "· not yet"
        print(f"  c{n} {done} · hints used: {state['hints'].get(str(n), 0)} · {m['title']}")
    passed = sum(1 for n in range(2, 8) if str(n) in state["passed"])
    print(f"\n  {passed} of c2–c7 passed (4 needed).")
    return 0


def cmd_export():
    dest = pathlib.Path.cwd()
    if not (dest / "lab04-multi-service-compose").is_dir():
        raise Lab4Error("Run export from the root of your fork: cd ~/turiba-devops-labs")
    state, exported, changed = load_state(), 0, 0
    for n in range(2, 8):
        if str(n) not in state["passed"]:
            continue
        mdir, files = root() / f"c{n}", MISSIONS[n]["overlay"]
        try:
            same = digest(mdir, files) == state["passed"][str(n)]
        except OSError:
            same = False                    # a file is gone: that is a change too
        if not same:
            changed += 1
            print(f"  ✘ c{n} changed after it passed: run clinic.sh check {n} again first")
            continue
        for rel in files:
            out = dest / "lab4" / "clinic" / f"c{n}" / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(mdir / rel, out)
        exported += 1
        print(f"  ✔ c{n} → lab4/clinic/c{n}/")
    if not exported:
        print("\n  Nothing exported. Run the checks above again." if changed else
              "\n  Nothing to export. Pass a mission first: bash ~/compose-clinic/clinic.sh check N (N is 2 to 7).")
        return 1
    print(f"\n  {exported} mission(s) exported. Commit lab4/clinic with your other Lab 4 files.")
    return 0


def cmd_clean(quiet=False):
    for n in MISSIONS:
        compose_down(n, volumes=True)
    shutil.rmtree(root(), ignore_errors=True)
    if not quiet:
        print(f"✔ Removed the clinic's containers, volumes and {root()}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="clinic.sh", description="Lab 4 Compose clinic")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup").add_argument("--force", action="store_true")
    for name in ("check", "hint", "reset", "down"):
        sub.add_parser(name).add_argument("n", type=int, choices=sorted(MISSIONS))
    for name in ("status", "export", "clean"):
        sub.add_parser(name)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "setup":
            return cmd_setup(a.force)
        if a.cmd in ("check", "hint", "reset", "status", "export") and not (root() / "c1").is_dir():
            raise Lab4Error("Run setup first, from your fork: bash lab04-multi-service-compose/clinic.sh setup")
        if a.cmd in ("check", "hint", "reset", "down"):
            return {"check": cmd_check, "hint": cmd_hint, "reset": cmd_reset, "down": cmd_down}[a.cmd](a.n)
        return {"status": cmd_status, "export": cmd_export, "clean": cmd_clean}[a.cmd]()
    except Lab4Error as e:
        print(f"✘ {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
