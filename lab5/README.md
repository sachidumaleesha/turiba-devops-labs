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
| P1 | Which jobs start together? | `graph-build` and `graph-lint`, because neither job has `needs`. | Pending the first run. |
| P2 | Will `graph-package` find `build.txt`? | No. Jobs have separate runner filesystems, and `graph-package` has no artifact download step. | Pending the first run. |
| P3 | With `break = build`: which jobs run, which fail, which are skipped? | Pending prediction before the second run. | Pending the second run. |

## 2 · Pipeline

- B5, before I filled it in: `localhost` or `db`? I predicted ____ because ____
- My first red run in Part 2 (the job, the first red step, the error line copied from the log): ____
- What I changed to make it green: ____
- My lint findings, and how I fixed them (fixed, not silenced): ____
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
