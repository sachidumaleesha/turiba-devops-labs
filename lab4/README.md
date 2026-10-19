# Lab 4 · Multi-service app with Compose

GitHub user: sachidumaleesha · Reference files used (Lab 2 fallback): no

## 1 · Architecture

```mermaid
flowchart LR
  B["Browser on your laptop"]
  subgraph front["network: front"]
    W["web: nginx :80"]
  end
  A["api :5000 · networks: front, back"]
  subgraph back["network: back"]
    D[("db :5432")]
  end
  V[("volume pgdata")]
  B -->|"HTTP localhost:8080"| W
  W -->|"HTTP api:5000"| A
  A -->|"PostgreSQL db:5432"| D
  D --- V
```

Which arrow crosses from your laptop into Docker: Browser → web over `localhost:8080`.

## 2 · Predictions and what happened

| # | I predicted | What I saw (command → the deciding output line) | Match? | If not: why |
|---|-------------|--------------------------------------------------|--------|-------------|
| P1 | b — `web` and `db` will be on different networks, so Docker DNS should not expose `db` to `web`. | `docker compose exec web getent hosts db` → no output (exit 2) | Yes | |
| P2 | b — PostgreSQL will not have a published host port, so the laptop connection should be refused. | `nc -zv -w 3 localhost 5432` → `failed: Connection refused` | Yes | |
| P3 | a — the todo should remain in the named volume when containers are removed. | `docker compose down && docker compose up -d --wait`, then `curl` → `sachidumaleesha: survive me` remained | Yes | |
| P4 | c — `down -v` should delete the named volume, including both the table and its rows. | after `down -v`, `select count(*) from todos` → `ERROR: relation "todos" does not exist` | Yes | |
| P5 | a — the API process health check should remain healthy, but a database request should return 500. | `docker compose ps api` → `(healthy)`; `curl -i` → `HTTP/1.1 500 Internal Server Error` | Yes | |
| P6 | b — the browser is outside Docker and cannot resolve the Compose service name `api`. | `getent hosts api` on the laptop → no result; the working page calls `/api/todos` through nginx | Yes | |

## 3 · Backup and restore

```text
$ mkdir -p backup
$ docker compose exec -T db pg_dump -U todo -d todo > backup/todo.sql
$ grep 'survive me' backup/todo.sql
3  sachidumaleesha: survive me  f  2026-10-19 17:18:47.133821+00

$ docker compose down -v
Container course-app-web-1 Removed
Container course-app-api-1 Removed
Container course-app-db-1 Removed
Volume course-app_pgdata Removed

$ docker compose up -d --wait db
Container course-app-db-1 Healthy

$ docker compose exec db psql -U todo -d todo -c 'select count(*) from todos'
ERROR:  relation "todos" does not exist
LINE 1: select count(*) from todos

$ docker compose exec -T db psql -U todo -d todo < backup/todo.sql
SET
CREATE TABLE
CREATE SEQUENCE
COPY 3
ALTER TABLE

$ docker compose up -d --wait
Container course-app-db-1 Healthy
Container course-app-api-1 Healthy
Container course-app-web-1 Healthy

$ curl -s localhost:8080/api/todos
[{"id":1,"title":"sachidumaleesha: browser todo","done":false},{"id":2,"title":"sachidumaleesha: first","done":false},{"id":3,"title":"sachidumaleesha: survive me","done":false}]
```

Why the restore must run before `api` starts: the API calls `ensureSchema()` during startup and creates the `todos` table. The SQL dump also creates that table. Restoring while only `db` is running avoids `relation "todos" already exists` errors and makes it clear that the restored dump, rather than API startup, recreated the schema and rows.

## 4 · Compose clinic

### c1 (worked example)
- Error line (copied): `connect ECONNREFUSED 127.0.0.1:5432`
- Checkpoint: port, inside `api`
- Fix: `DB_HOST: db`
- Why this fix, and not the tempting one: inside `api`, `localhost` is `api` itself, and nothing listens on 5432 there. Docker's DNS answers `db` with the database container's address. Publishing `db`'s port would "work" by opening a door into the database.
- Hints used: 0

## 5 · Run in one command

```bash
git clone https://github.com/sachidumaleesha/turiba-devops-labs.git && cd turiba-devops-labs
cp .env.example .env
docker compose up -d --wait
```

## 6 · Answers

### A1

`127.0.0.1` was the loopback address of the `api` container itself. Each container has its own network namespace, so port 5432 was not PostgreSQL from the API's point of view. `db` works because Compose DNS resolves that service name to the database container on their shared `back` network.

### A2

The browser sends `POST /api/todos` to `localhost:8080`. Docker publishes that host port to nginx in `web` on port 80. nginx proxies the request across the `front` network to `api:5000`. The API then connects across the `back` network to `db:5432`. `db` has no `ports:` because only the API needs database access; publishing 5432 would unnecessarily expose PostgreSQL to the laptop and its surrounding network.

### A3

The todos were stored in the `course-app_pgdata` named volume mounted at `/var/lib/postgresql/data`. `docker compose down` removes containers and networks while retaining named volumes. `docker compose down -v` additionally removes the Compose project's declared named volumes, so PostgreSQL's tables and rows disappear with `pgdata`.

### A4

The API health check calls its `/healthz` endpoint, which proves that the Node process can answer HTTP; it does not query PostgreSQL. The process therefore stayed healthy while `/api/todos` returned 500 because that route needed the stopped database. `condition: service_healthy` protects initial startup by delaying the API until the database is ready. It does not continuously monitor the dependency, change API health, or restart the API when the database later stops.
