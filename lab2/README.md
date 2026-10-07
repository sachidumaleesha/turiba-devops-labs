# Lab 2 · Containerize it, then debug it

- **Image:** `ghcr.io/sachidumaleesha/course-api:lab2` (public, `linux/amd64` + `linux/arm64`)
- **Base image digest:** `node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1`

## Part 1 · Images and layers

### 1.1 Base images

| Image | Size | Distro | Default user |
|-------|-----:|--------|--------------|
| `node:24` | 1.66 GB | Debian GNU/Linux 12 (bookworm) | `root`, uid 0 |
| `node:24-slim` | 332 MB | Debian GNU/Linux 12 (bookworm) | `root`, uid 0 |
| `node:24-alpine` | 242 MB | Alpine Linux v3.24 | `root`, uid 0 |

`docker image inspect` showed `Cmd=[node]`, `Entrypoint=[docker-entrypoint.sh]`,
and an empty `User`, which means the default user is root.

### 1.2 Container writable layers

I created `a.html` in one nginx container. It appeared only in that container,
not in the second container created from the same image. `docker diff` reported:

```text
A /usr/share/nginx/html/a.html
```

Each container therefore has its own writable layer above the shared,
read-only image layers.

### 1.3 Deleting a file in a later layer

`cow:bad` = 65.4 MB · `cow:good` = 12.9 MB

The history of `cow:bad` contained a 52.4 MB creation layer followed by a very
small deletion layer. Removing the file in a later layer did not remove its
bytes from the earlier immutable layer.

### 1.4 Build cache

| Build | RUN step CACHED? | Build time |
|-------|------------------|-----------:|
| b · `app.txt` changed | Yes | 1.009 s |
| c · `deps.txt` changed | No | 16.407 s |
| d · `app.txt` changed, wrong order | No | 16.222 s |

Build b reused the dependency-install layer because only application content
after that layer changed. Builds c and d invalidated the slow layer. Build d
shows why frequently changing source files should be copied after dependency
installation.

## Part 2 · The course API image

| Step | Image | Size |
|------|-------|-----:|
| Naive | `course-api:naive` | 1.75 GB |
| `.dockerignore`, `npm ci --omit=dev`, exec form | `course-api:step1` | 1.65 GB |
| Multi-stage, `node:24-alpine`, non-root | `course-api:lab2` | 248 MB |
| Reduction against naive | | 85.8% |

The database warning during these checks was expected because PostgreSQL is
introduced in Session 4. The process and `/healthz` endpoint work without the
database; `/api/todos` returns 500 until a database is available.

### Signals and graceful shutdown

`docker stop` before the SIGTERM handler: **3.394 s, exit code 137** · after:
**0.294 s, exit code 0**.

Docker Desktop on this machine used an approximately three-second stop timeout,
rather than the ten-second default described in the worksheet. Exit code 137
still demonstrates the same forced `SIGKILL` behaviour.

The successful shutdown log ended with:

```text
SIGTERM received, closing the server
```

### Final image checks

Output of `docker run --rm course-api:lab2 id`:

```text
uid=1000(node) gid=1000(node) groups=1000(node),1000(node)
```

Output of `docker ps` showing the health result:

```text
CONTAINER ID   IMAGE             STATUS                    PORTS                                         NAMES
ebfd1a8c1aab   course-api:lab2   Up 25 seconds (healthy)   0.0.0.0:8080->5000/tcp, [::]:8080->5000/tcp   api
```

The `/healthz` endpoint returned:

```json
{"status":"ok"}
```

The final `/app` directory contained no `.env`, `.git`, or `Dockerfile`.
After changing a source comment and rebuilding, the `npm ci --omit=dev` step
said `CACHED`, while the source `COPY` layer rebuilt.

The published OCI image index has digest:

```text
sha256:6596a00b366508d3bf21fa450937ecfd5ce77fd663d5224fbd34f3bea5e4464e
```

`docker buildx imagetools inspect` listed both required platforms:

```text
linux/amd64
linux/arm64
```

## Part 3 · Linux drills

### 3.1 Distribution userspace and kernel

```text
PRETTY_NAME="Ubuntu 24.04.5 LTS"
VERSION_CODENAME=noble
```

```text
6.6.114.1-microsoft-standard-WSL2
```

`/etc/os-release` describes the Ubuntu userspace inside the container.
`uname -r` reports the WSL2 Linux kernel shared with containers on the laptop's
Docker VM.

### 3.2 Text processing with sed

```text
chef tools
ansible tools
docker tools
```

`sed 's/tech/tools/g'` replaced every occurrence of `tech` while leaving the
original file unchanged and writing the result to `newtools.txt`.

### 3.3 Filtering web-server logs

After sending 20 requests for `/nope`, the host command counted:

```text
20
```

The loop generated 20 HTTP 404 responses, and `grep -c` counted the matching
nginx access-log lines.

### 3.4 Linux permissions

```text
-rwxr-x--- 1 root root 7 Oct 7 16:20 /lab/f
```

```text
cat: /lab/f: Permission denied
```

Mode `750` gives the owner read/write/execute, the group read/execute, and
everyone else no permissions. The `student` user belonged to neither the owner
nor the owning group, so it could not read the file. Root can bypass these
normal permission checks.

### 3.5 Exported environment variables

Before export:

```text
child sees:
```

After `export APP_ENV=staging`:

```text
child sees: staging
```

A shell variable stays in the current shell. Exporting it places it in the
environment inherited by child processes.

### 3.6 PID 1 and shutdown

```text
bash
```

`bash` was PID 1 inside the `lab` container. Stopping it took **3.306 s** on
this Docker Desktop configuration because PID 1 did not perform a graceful
SIGTERM shutdown, so Docker waited for its timeout and then killed it.

### 3.7 Container networking and published ports

Inside `lab`:

```text
172.18.0.2      web
HTTP/1.1 200 OK
```

Listening sockets inside `web`:

```text
tcp   0   0 0.0.0.0:80       0.0.0.0:*   LISTEN
tcp   0   0 :::80            :::*        LISTEN
```

From the host:

```text
HTTP/1.1 200 OK
```

Containers on `labnet` use Docker DNS to resolve the service name `web` and
connect directly to port 80. The host uses `localhost:8081`; Docker's published
port mapping forwards host port 8081 to port 80 in the same nginx container.

## Part 4 · Broken containers

### `lab2-broken:2`

- **Symptom:** It exited with code 255 and logged `exec /entrypoint.sh: no such file or directory`, although `/entrypoint.sh` existed and was executable.
- **Cause:** `cat -A` showed `#!/bin/sh^M$`. Windows CRLF line endings made the kernel search for an interpreter named `/bin/sh\r`.
- **Fix:** Save the script with Unix LF line endings. A repository can enforce this with `*.sh text eol=lf` in `.gitattributes`.

### `lab2-broken:3`

- **Symptom:** The container stayed running and port `8082:5000` was published, but the host connection was reset.
- **Cause:** `netstat -ltn` showed the application listening on `127.0.0.1:5000`. That loopback address is reachable only from inside the container.
- **Fix:** Bind the application to `0.0.0.0:5000`, allowing traffic arriving through Docker's network interface.

### `lab2-broken:4`

- **Symptom:** Logs reported `ECONNREFUSED` for `::1:5432` and `127.0.0.1:5432`.
- **Cause:** A `.env` file had been copied into `/app`, causing the application to use localhost for PostgreSQL. Inside a container, localhost means that same container, not a separate database container. The value loaded by the Node process did not appear in a separate `docker exec env` process.
- **Fix:** Exclude `.env` from the image and supply configuration at runtime. On a Docker network, use the database container/service name, for example `DB_HOST=db`.

### `lab2-broken:5`

- **Symptom:** It exited with code 1 and logged `EACCES: permission denied, open '/app/data/todos.log'`.
- **Cause:** The application ran as `uid=1000(node)`, but `/app/data` was owned by `0:0` with mode `755`; only root could create files there.
- **Fix:** Create and own the writable directory before changing users, for example `RUN mkdir -p /app/data && chown -R node:node /app/data`, while continuing to run the application as `USER node`.

### `lab2-broken:6`

- **Symptom:** The API started, but `docker stop` took 3.254 s, produced no graceful-shutdown log, and ended with exit code 137.
- **Cause:** The configured startup was `/bin/sh -c "node server.js"`, and the application did not complete graceful SIGTERM handling. Docker reached its stop timeout and sent `SIGKILL`; 128 + signal 9 gives exit code 137.
- **Fix:** Use exec form, `CMD ["node", "server.js"]`, and handle SIGTERM by stopping the HTTP server, closing the database pool, and exiting with code 0.

### `lab2-broken:7`

- **Symptom:** The container remained `Up (unhealthy)`, although its root endpoint returned HTTP 200.
- **Cause:** Its health check ran `curl`, but `curl` was not installed inside the image. Health history repeatedly reported `/bin/sh: curl: not found`. `wget` was available and successfully reached the API.
- **Fix:** Use an available tool and a real health endpoint. The final image uses `CMD wget -qO- http://127.0.0.1:5000/healthz || exit 1` after adding `/healthz` to the application.

## Answers

1. **Why is `cow:bad` still about 50 MB larger?** Image layers are immutable. The `dd` command stored the 50 MB file in one layer. Deleting it in a later `RUN` added a deletion marker but did not remove the bytes from the earlier layer. `cow:good` creates and deletes the file in the same layer, so those bytes are absent from the final layer.

2. **Why does Dockerfile instruction order affect rebuild time?** Docker evaluates layers in order. When the input to a `COPY` instruction changes, that layer and all later layers lose their cache. Copying dependency manifests first allows the expensive dependency-install step to remain cached when only application source changes.

3. **Why was `docker stop` slow before adding the SIGTERM handler?** Docker sends SIGTERM to PID 1 and waits for it to exit. Without application-level graceful shutdown, the Node process did not exit during the configured grace period. Docker then sent SIGKILL, producing exit code 137. The handler closes the HTTP server and database pool before exiting with code 0.

4. **Three things present in the naive image but absent from `course-api:lab2`:** the secret local `.env` file, development dependencies such as `nodemon`, and build/context files such as the Dockerfile and README files. The final image also replaces the much larger full Debian-based Node image with Alpine and contains only production dependencies copied from the dependency stage.
