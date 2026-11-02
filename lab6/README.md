# Lab 6 · Test what you ship, ship a release

GitHub user: sachidumaleesha · Reference pipeline used (Part 0 fallback): no

<!-- Keep every heading as it is: the grader finds the sections by name. -->

## 1 · Smoke test

- The names of my smoke-test steps in the `image` job: `Build for the smoke test (amd64, kept on the runner)` and `Smoke test the image`
- What my smoke test asks, and what makes it fail: It sends an HTTP GET request to `http://localhost:5000/` using `curl` with retries (`--retry 10 --retry-delay 1 --retry-all-errors`). It fails if the container does not respond with a successful HTTP status within 10 retries, upon which it outputs an error message, dumps the container logs using `docker logs smoke`, and exits with code 1.
- 🔮 Part 1, before my first run: will my code pass the smoke test? I predicted yes because the root path `/` answers without needing a PostgreSQL database connection and `api/Dockerfile` copies all necessary application code into the image. What happened: the smoke test passed on the first run, successfully returning HTTP 200 with the API metadata JSON (`{"name":"course-api","version":"0.1.0"}`).
- 🔮 Part 2, before the checks finished: which checks will go red after `break.sh`? I predicted only `image` (in the `Smoke test the image` step) would fail, while `lint`, `unit`, and `integration` would stay green, because `break.sh` adds `banner.js` to `.dockerignore`, which prevents it from being copied into the Docker image, whereas the file remains available in the runner workspace for source tests.

## 2 · What broke and how I found it

- The check and the step that went red: Check `image`, step `Smoke test the image`
- The log line that showed the cause (copied from the log):

```text
Error: Cannot find module './banner'
Require stack:
- /app/server.js
```

- The cause, in my own words: During application startup, `server.js` requires `./banner`. The teammate's commit added `banner.js` to `api/.dockerignore`. When Docker executed the build context copy (`COPY --chown=node:node . .`), Docker ignored `banner.js`, leaving the file out of the resulting image. When the smoke test started the container with `node server.js`, Node crashed immediately with `MODULE_NOT_FOUND`, preventing `GET /` from answering curl.
- Why `lint`, `unit` and `integration` stayed green: `lint`, `unit`, and `integration` ran directly on the runner VM from the repository workspace files where `api/banner.js` physically existed on the local filesystem. They did not run inside or test the Docker image itself.
- My fix, and the commit that made it: I removed `banner.js` from `api/.dockerignore` so that Docker includes `banner.js` in the build context and image, committed in `eb513ab` (`fix(api): keep banner.js in the image`).

## 3 · Release

- Release page: https://github.com/sachidumaleesha/turiba-devops-labs/releases/tag/v0.2.0
- Image: `ghcr.io/sachidumaleesha/turiba-devops-labs/api:0.2.0`, platforms (from `docker buildx imagetools inspect`): `linux/amd64, linux/arm64`
- One thing in Part 3 that didn't work the first time, and how I fixed it: Direct pushes to the `main` branch are blocked by repository protection rules (`protect-main`). To introduce the new `release.yml` workflow cleanly before pushing the release tag, I created a dedicated branch `ci/release-workflow` and PR #15, waited for the 4 CI checks to pass, merged it to `main`, and only then tagged and pushed `v0.2.0` so GitHub Actions could execute the tag-triggered release workflow.
