# Turiba DevOps labs

Lab guides for **Software Development and IT Operations (DevOps)**, course ELE1013M, Turiba University.

## Labs

| Lab | Session | Guide | You hand in |
|----:|---------|-------|-------------|
| 1 | S1 · From virtualization to containers | [Ship it](lab01-ship-it/README.md) | A public image on GHCR and `lab1/README.md` in your fork |
| 2 | S2 · Container images & the Linux survival kit | [Containerize it, then debug it](lab02-containerize-and-debug/README.md) | `api/Dockerfile`, `api/.dockerignore`, a public API image on GHCR and `lab2/README.md` in your fork. Due Wed 7 Oct, 22:00 |

The next lab guide is published here before its session.

## What is in this repository

| Folder | What it is |
|--------|------------|
| `lab0N-…/` | The lab guides. Read them; don't change them |
| `api/` | The **course API**, a small todo service in Node.js. You containerize it in Lab 2 and keep improving it all semester ([details](api/README.md)) |
| `lab1/`, `lab2/`, … | Created by you in your fork: your write-up for each lab |

## Get updates into your fork

New guides and new parts of the app arrive here during the semester. To get them:

1. On GitHub, open **your fork** → **Sync fork** → **Update branch**.
2. On your laptop, in your clone: `git pull`.

Your own folders (`lab1/`, `lab2/`, …) are not touched. If GitHub reports a conflict, ask in class before discarding anything.

## How the labs work

- **You work on your own laptop, in your fork of this repository.** No cloud account or payment card is needed.
- **Each guide has the same parts:** goal and time, steps with ✅ checkpoints, a troubleshooting table, stretch tasks and a command summary.
- **You submit on Evaluentis.** Each lab has an assignment where you paste a link to the file, pull request or tag in your repository. Labs are checked pass/fail against the checklist at the end of each guide.
- **Commands are written for bash.**
  - Windows: use the Ubuntu (WSL) terminal.
  - macOS / Linux: use Terminal.
  - Where PowerShell needs something different, the guide says so.
- **Placeholders:** `<you>` means your GitHub username in lowercase.

## Before Lab 1

Finish the pre-course setup:
- Docker Desktop (or Rancher Desktop) installed and running
- Git and VS Code installed
- a GitHub account with two-factor authentication
- the course repository forked and cloned

Check with:

```bash
docker run --rm hello-world
git --version
```

## Before Lab 2 (at home, before Wednesday 7 October)

Do [Part 0 of the Lab 2 guide](lab02-containerize-and-debug/README.md#part-0--before-class-at-home-15-min): sync your fork to get `api/`, and pull the base images. The classroom shares one Docker Hub pull limit, and `node:24` alone is over 1 GB.

## Stuck?

1. Read the checkpoint you just failed. It says what you should see.
2. Look up your error in the **Troubleshooting** table at the end of the guide.
3. Ask in class, and bring the exact error message.
