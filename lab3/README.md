# Lab 3 · Branch, review, release

- **Fork:** https://github.com/sachidumaleesha/turiba-devops-labs
- **Release:** https://github.com/sachidumaleesha/turiba-devops-labs/releases/tag/v0.1.0
- **Reviewer:** Not assigned yet

## Part 1 · Set up

Output of `ssh -T git@github.com` (or `gh auth status`):

```text
Hi sachidumaleesha! You've successfully authenticated, but GitHub does not provide shell access.
```

Output of `git remote -v`:

```text
origin  git@github.com:sachidumaleesha/turiba-devops-labs.git (fetch)
origin  git@github.com:sachidumaleesha/turiba-devops-labs.git (push)
upstream        https://github.com/mleitass/turiba-devops-labs.git (fetch)
upstream        https://github.com/mleitass/turiba-devops-labs.git (push)
```

## Part 2 · Playground

The hash in `.git/refs/heads/main` (step 2.3): `e5f73b526643e780d287cf59d066b6d7e6d1d78c`

The first line of `git cat-file -p HEAD` (step 2.3): `tree c277cb61a54fe48ce0c7edeba222c179bcf4963a`

The conflict block you saw in `config/app.env` (step 2.6):

```text
<<<<<<< HEAD
REPLICAS=2
=======
REPLICAS=3
>>>>>>> feature/scale-up
LOG_LEVEL=info
```

Which value you kept, and why: I kept `REPLICAS=3` because the branch was specifically named `feature/scale-up`, so three replicas matched the intended change.

The final `git log --oneline --graph --all` (step 2.6):

```text
*   c28c885 Merge branch 'feature/scale-up'
|\
| * baac9ed feat: scale to 3 replicas
* | c3c4e4a feat: scale to 2 replicas
|/
*   19487b9 Merge branch 'feature/logging'
|\
| * 63c460d feat: add log level
* | 630e5cb docs: add README
|/
* 4910bcc feat: add health message
* e5f73b5 feat: print done after deploy
* 1b01799 feat: add app config
* 6d8764b feat: add deploy script
```

## Part 3 · Rescue missions

### m1 (worked example)

- PASS line: `PASS m1 6978b2eb`
- Symptom: `deploy.sh` contained broken, uncommitted edits and the working tree was dirty.
- Command: `git restore deploy.sh`
- Why this command, and not a more dangerous one: It restored only the affected file from `HEAD`. A hard reset would discard every uncommitted change in the repository, not just this file.

### m2

- PASS line: `PASS m2 9905c539`
- Symptom: Both the legitimate `app.js` change and a password-containing `.env` file were staged.
- Command: `git restore --staged .env`, add `.env` to `.gitignore`, then commit `app.js` and `.gitignore`.
- Why this command, and not a more dangerous one: Unstaging preserved the local `.env` file while keeping it out of Git history. Resetting the whole index could also unstage unrelated correct work.

### m3

- PASS line: `PASS m3 2cdebdba`
- Symptom: The latest unpushed commit had a misspelled message and omitted `CONTRIBUTING.md`.
- Command: `git add CONTRIBUTING.md` followed by `git commit --amend -m "docs: fix typos in README"`.
- Why this command, and not a more dangerous one: Amending replaced only the latest unpushed commit, preserving a clean one-commit result. Rewriting a pushed commit would disrupt collaborators.

### m4

- PASS line: `PASS m4 07615330`
- Symptom: Two unpushed cache commits were accidentally made on `main`.
- Command: Create `feature/cache` at the current tip, switch to `main`, then run `git reset --hard origin/main`.
- Why this command, and not a more dangerous one: The feature branch preserved both commits before `main` was reset. Resetting first could have left the commits reachable only through the reflog.

### m5

- PASS line: `PASS m5 4f6b42c8`
- Symptom: A bad commit setting replicas to zero was already pushed and present in a teammate's clone.
- Command: `git revert HEAD` followed by `git push`.
- Why this command, and not a more dangerous one: Revert added a new inverse commit and preserved shared history. A hard reset plus force push would rewrite the shared branch and make the teammate's history diverge.

### m6

- PASS line: `PASS m6 1b07f048`
- Symptom: Three commits were no longer reachable from `main` after `git reset --hard HEAD~3`.
- Command: Inspect `git reflog`, then create `rescue/lost-work` at `HEAD@{1}`.
- Why this command, and not a more dangerous one: A recovery branch made the lost commits reachable again without moving or overwriting the current branch.

## Part 4 · Protected main and pull requests

The rejected push to `main` (step 4.2):

```text
remote: error: GH013: Repository rule violations found for refs/heads/main.
remote: - Changes must be made through a pull request.
 ! [remote rejected] main -> main (push declined due to repository rule violations)
```

- PR #1 (`.gitignore`): https://github.com/sachidumaleesha/turiba-devops-labs/pull/1
- PR #2 (`/healthz` docs, with the conflict): https://github.com/sachidumaleesha/turiba-devops-labs/pull/2

## Part 5 · Release

- Release: https://github.com/sachidumaleesha/turiba-devops-labs/releases/tag/v0.1.0
- Why `0.1.0` and not `1.0.0`? Version `0.1.0` indicates an early development release whose public API is not yet guaranteed to be stable; `1.0.0` would declare the first stable public API.

## Answers

1. In mission 5, why `git revert` and not `git reset --hard` plus a force push?

   `git revert` preserves the existing shared history and adds a new commit that reverses the bad change. A hard reset followed by a force push rewrites the branch, causing it to diverge from the teammate's existing clone and potentially discarding other work.

2. Why couldn't Git resolve the `CHANGELOG.md` conflict by itself, and how did you decide what to keep?

   Both branches inserted different text at the same location relative to the same original lines. Git could not infer the intended ordering or whether one entry should replace the other. Both entries documented real changes, so I kept both and removed the conflict markers.

3. A colleague says "I'll make a PR to get the latest code." What do they mean, and which command is it?

   They probably mean “pull,” not “pull request.” The command is `git pull`, which fetches remote changes and integrates them into the current branch. A pull request instead proposes merging one branch into another.

4. After `1.0.0`: what is the next version for (a) a bug fix, (b) a new `/api/todos/search` endpoint, (c) renaming `/api/todos` to `/api/tasks`?

   (a) `1.0.1` for the backward-compatible bug fix, (b) `1.1.0` for the new backward-compatible endpoint, and (c) `2.0.0` for the breaking endpoint rename.
