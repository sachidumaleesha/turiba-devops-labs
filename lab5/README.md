# Lab 5 · Your first CI pipeline

GitHub user: sachidumaleesha · Reference files used (Lab 2 fallback): no

![ci](https://github.com/sachidumaleesha/turiba-devops-labs/actions/workflows/ci.yml/badge.svg?branch=main)

<!-- Keep every heading as it is: the grader finds the sections by name. Replace every blank (four underscores), and your user name placeholder in the first line and in the badge URL: write your GitHub user name exactly as GitHub shows it. -->

## 1 · Graph predictions

Part 1, step 1.2: fill in this section **before** you run `lab05 graph`. A wrong prediction that you explain earns full marks.

My drawing of the `lab05 graph` jobs, before the first run (boxes and arrows in text are fine):

```text
[graph-build] ──> [graph-test] ──┐
       │                         ├──> [graph-package] ──> [graph-report]
       └─────────────────────────┘             │                ↑
[graph-lint] ──────────────────────────────────┘────────────────┘

graph-report also directly needs graph-build, graph-lint, and graph-test.
```

| # | Question | I predicted, and why | What the run showed |
|---|----------|----------------------|---------------------|
| P1 | Which jobs start together? | `graph-build` and `graph-lint`, because neither job has `needs`. | Run 1 showed both starting at 06:53:34 UTC; both succeeded. |
| P2 | Will `graph-package` find `build.txt`? | No. Jobs have separate runner filesystems, and `graph-package` has no artifact download step. | No. `graph-test` downloaded it and printed `made by graph-build in run 1`; `graph-package` printed `build.txt: not here: jobs don't share files`. |
| P3 | With `break = build`: which jobs run, which fail, which are skipped? | `graph-build` and `graph-lint` run; `graph-build` fails while `graph-lint` succeeds. `graph-test` and then `graph-package` are skipped because their dependencies did not all succeed. `graph-report` still runs and succeeds because it has `if: always()`. | Run 2 matched: `graph-lint` succeeded, `graph-build` failed in `Fail on purpose`, `graph-test` and `graph-package` were skipped, and `graph-report` succeeded. |

## 2 · Pipeline

- B5, before I filled it in: `localhost` or `db`? I predicted `localhost` because the job steps run directly on the GitHub-hosted runner and reach the PostgreSQL service through the published host port `5432`. The service label `db` would be used by another container on the service network.
- My first red run in Part 2 (the job, the first red step, the error line copied from the log): There was no red run. The first `ci` run (#1, run ID `39916380312`) passed all four jobs.
- What I changed to make it green: No follow-up change was required; lint and unit tests passed locally before the branch was pushed, and GitHub Actions also passed the integration and image jobs.
- My lint findings, and how I fixed them (fixed, not silenced): ESLint reported no findings. The existing SIGTERM handler already uses `server`, so no source fix or rule suppression was needed.
- Part 2 pull request (URL): https://github.com/sachidumaleesha/turiba-devops-labs/pull/9
- Part 3: will the PR run push an image? I predicted no: a pull-request run should build the image as a check, but `push` should be false and registry login should be skipped. What happened: the `image` job succeeded, `Log in to GHCR (main only)` was skipped, and the build step completed without publishing.
- My image on GHCR, from the `main` run: `ghcr.io/sachidumaleesha/turiba-devops-labs/api:b5d66daaab9d3b2f4e6985fe0a6bea0ee235b638`

## 3 · Red PR

- Red PR (URL): https://github.com/sachidumaleesha/turiba-devops-labs/pull/10
- The test that failed, with Expected and Received (copied): `DELETE with an id that is not a number answers 404` — `Expected: 404`, `Received: 500`.
- The cause line from "On failure: the API log" (copied): `DELETE /api/todos/abc failed: invalid input syntax for type integer: "abc"`
- The merge box while it was red (the text, copied): `Some checks were not successful` — `1 failing, 1 skipped, 3 successful checks`; the `Merge pull request` button was disabled.
- Which commit did the red check test: your branch alone, or your branch merged with `main`? How do you know? It tested the branch merged with `main`. The checkout log fetched `refs/remotes/pull/10/merge` and reported `HEAD is now at c5c15d7 Merge a51e0d5... into df2e241...`.

## 4 · Answers

**A1.** In my `break: build` run the job list was: `graph-lint` — success, `graph-build` — failure, `graph-test` — skipped, `graph-package` — skipped, and `graph-report` — success. `graph-build` and `graph-lint` had no dependencies, so both started. `graph-test` needed the failed build, and `graph-package` needed successful build, lint, and test jobs, so GitHub skipped them. `graph-report` still ran because it uses `if: always()`, which tells GitHub to evaluate that job even when jobs in its `needs` list fail or are skipped.

**A2.** Every job gets a fresh runner with its own filesystem. `graph-build` uploaded `build.txt` as an artifact, and `graph-test` found it only because its `Download the build` step used `actions/download-artifact`. `graph-package` did not download the artifact, so the file was absent even though the build job had created it. Adding an `actions/download-artifact` step for the same artifact before `graph-package` checks the file would make it available there.

**A3.** The integration commands run directly on the GitHub-hosted runner, while the PostgreSQL service publishes its container port to the runner's port `5432`; therefore the runner connects to `localhost`. In Compose, the API and database are containers on the same Docker network, so Docker DNS resolves the service name `db`. If the whole Actions job used `container: node:24-alpine`, its steps would also be on the container network and `DB_HOST` would be `db`.

**A4.** The required `integration` check failed on the first red run. The workflow tested GitHub's synthetic merge commit `c5c15d7`, which merged my test commit `a51e0d5` with the current `main`, as shown by the checkout of `refs/remotes/pull/10/merge`. The active `protect-main` ruleset required all four checks, so the failed integration check (and consequently skipped image check) disabled merging. On the Part 2 PR the `image` job ran because lint, unit, and integration all succeeded, but it only built the image: registry login was conditional on `main`, and the build used `push: false` for a pull-request event.
