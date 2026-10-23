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
- My first red run in Part 2 (the job, the first red step, the error line copied from the log): ____
- What I changed to make it green: ____
- My lint findings, and how I fixed them (fixed, not silenced): ESLint reported no findings. The existing SIGTERM handler already uses `server`, so no source fix or rule suppression was needed.
- Part 2 pull request (URL): ____
- Part 3: will the PR run push an image? I predicted ____. What happened: ____
- My image on GHCR, from the `main` run: `ghcr.io/____/turiba-devops-labs/api:____`

## 3 · Red PR

- Red PR (URL): ____
- The test that failed, with Expected and Received (copied): ____
- The cause line from "On failure: the API log" (copied): ____
- The merge box while it was red (the text, copied): ____
- Which commit did the red check test: your branch alone, or your branch merged with `main`? How do you know? ____

## 4 · Answers

**A1.** ____

**A2.** ____

**A3.** ____

**A4.** ____
