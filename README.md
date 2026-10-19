# Turiba DevOps labs

Lab guides for **Software Development and IT Operations (DevOps)**, course ELE1013M, Turiba University.

## Labs

| Lab | Session | Guide | You hand in |
|----:|---------|-------|-------------|
| 1 | S1 · From virtualization to containers | [Ship it](lab01-ship-it/README.md) | A public image on GHCR and `lab1/README.md` in your fork |
| 2 | S2 · Container images & the Linux survival kit | [Containerize it, then debug it](lab02-containerize-and-debug/README.md) | `api/Dockerfile`, `api/.dockerignore`, a public API image on GHCR and `lab2/README.md` in your fork. Due Wed 7 Oct, 22:00 |
| 3 | S3 · Git & GitHub collaboration | [Branch, review, release](lab03-branch-review-release/README.md) | The URL of your fork on Evaluentis: two merged PRs, a protected `main`, release `v0.1.0`, and `lab3/README.md` in PR #3. Due 22:00 on the session day |
| 4 | S4 · Multi-service apps with Docker Compose | [Multi-service app with Compose](lab04-multi-service-compose/README.md) | The URL of your fork on Evaluentis: compose.yaml, .env.example, web/nginx.conf, lab4/README.md and lab4/clinic/ on main, merged through a PR in your fork. Due Tue 20 Oct, 22:00 |

The next lab guide is published here before its session.

## What is in this repository

| Folder | What it is |
|--------|------------|
| `lab0N-…/` | The lab guides. Read them; don't change them |
| `api/` | The **course API**, a small todo service in Node.js. You containerize it in Lab 2 and keep improving it all semester ([details](api/README.md)) |
| `lab1/`, `lab2/`, … | Created by you in your fork: your write-up for each lab |

## Get updates into your fork

New guides and new parts of the app arrive here during the semester.

**Before Lab 3** (your `main` is not protected yet):

1. On GitHub, open **your fork** → **Sync fork** → **Update branch**.
2. On your laptop, in your clone: `git pull`.

**From Lab 3 on** (your `main` is protected, so updates come in through a pull request):

```bash
git switch main && git pull
git fetch upstream
git switch -c chore/sync-upstream
git merge upstream/main
git push -u origin HEAD
```

Open the PR in **your fork** and merge it with **Create a merge commit** (not squash), then `git switch main && git pull`. Lab 3 sets up the `upstream` remote.

Your own folders (`lab1/`, `lab2/`, …) are not touched. If you get a conflict, ask in class before discarding anything.

## How the labs work

- **You work on your own laptop, in your fork of this repository.** No cloud account or payment card is needed.
- **Each guide has the same parts:** goal and time, steps with ✅ checkpoints, a troubleshooting table, stretch tasks and a command summary.
- **You submit on Evaluentis.** Each lab has an assignment. For Labs 1–2 you paste a link to a file in your repository; from Lab 3 on, you paste the URL of your fork. Labs are checked pass/fail against the checklist at the end of each guide, and the result and feedback come back on Evaluentis.
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

## Before Lab 3 (at home)

Do [Part 0 of the Lab 3 guide](lab03-branch-review-release/README.md#part-0--before-class-at-home-10-min): make sure Lab 2 is on GitHub, and set the five `git config` settings. Then sync your fork once more the old way (**Sync fork** → **Update branch**, then `git pull`) to get the Lab 3 material.

## Before Lab 4 (at home)

Do [Part 0 of the Lab 4 guide](lab04-multi-service-compose/README.md#part-0--before-class-at-home-20-min): bring the Lab 4 material into your fork through a pull request (the "From Lab 3 on" steps above), pull three images, and run `bash lab04-multi-service-compose/check.sh preflight`.

## Stuck?

1. Read the checkpoint you just failed. It says what you should see.
2. Look up your error in the **Troubleshooting** table at the end of the guide.
3. Ask in class, and bring the exact error message.
