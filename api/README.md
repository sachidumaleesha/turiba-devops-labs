# Course API

A small REST API for todos, written in Node.js (Express) with PostgreSQL. It is the app you build on all semester: you containerize it in Lab 2, run it next to its database with Compose in S4, build it in CI from S5, and deploy it to Kubernetes from S7.

| File | What it is |
|------|------------|
| `server.js` | The routes and the web server. Lab 2 adds `/healthz` and a SIGTERM handler at the two marked comments |
| `db.js` | The PostgreSQL connection pool and the `todos` table |
| `validate.js` | Input checks, kept apart so they can be unit-tested |
| `test/` | Unit tests (Jest) |
| `package.json`, `package-lock.json` | Dependencies, pinned exactly by the lockfile. Never edit the lockfile by hand |
| `.env.example` | The settings the API reads, with example values |

## Endpoints

| Method and path | Does |
|-----------------|------|
| `GET /` | Name and version: `{"name":"course-api","version":"0.1.0"}` |
| `GET /api/todos` | All todos |
| `POST /api/todos` | Create one: `{"title":"Buy milk"}` → `201` |
| `PATCH /api/todos/:id` | Change `title` and/or `done` |
| `DELETE /api/todos/:id` | Delete one → `204` |

## Settings

All from environment variables. A `.env` file in this folder is read at start for local runs; it is ignored by Git and must never go into an image.

| Variable | Default | Meaning |
|----------|---------|---------|
| `PORT` | `5000` | Port the API listens on |
| `DB_HOST` | `db` | Database host; `db` is the database's name in Compose (S4) |
| `DB_PORT` | `5432` | Database port |
| `DB_USER` | `todo` | Database user |
| `DB_PASSWORD` | (none) | Database password |
| `DB_NAME` | `todo` | Database name |

**Without a database** the API still starts. It logs `Database not reachable (…)` once and answers `500` on `/api/todos`. That is expected until S4.

## Run it

You don't need Node.js on your laptop. Lab 2 builds and runs the API as a container image.

To run the unit tests in a container, from this folder:

```bash
docker run --rm -v "$PWD":/src:ro node:24-alpine sh -c "cp -r /src /app && cd /app && npm ci && npm test"
```

With Node.js 24 installed locally: `npm ci`, then `npm test`, `npm start` or `npm run dev` (restarts on every change).
