# Lab 3 · Branch, review, release

<!-- Copy this file to lab3/README.md (Lab 3, step 1.4) and fill it in as you go.
     Keep the headings exactly as they are: the grader looks for them by name.
     Put command output in the ```text blocks. -->

- **Fork:** https://github.com/<you>/turiba-devops-labs
- **Release:** https://github.com/<you>/turiba-devops-labs/releases/tag/v0.1.0
- **Reviewer:** @<reviewer>

## Part 1 · Set up

Output of `ssh -T git@github.com` (or `gh auth status`):

```text

```

Output of `git remote -v`:

```text

```

## Part 2 · Playground

The hash in `.git/refs/heads/main` (step 2.3):

The first line of `git cat-file -p HEAD` (step 2.3):

The conflict block you saw in `config/app.env` (step 2.6):

```text

```

Which value you kept, and why:

The final `git log --oneline --graph --all` (step 2.6):

```text

```

## Part 3 · Rescue missions

### m1 (worked example)

- PASS line: `PASS m1 …`
- Symptom:
- Command:
- Why this command, and not a more dangerous one:

### m2

- PASS line:
- Symptom:
- Command:
- Why this command, and not a more dangerous one:

### m3

- PASS line:
- Symptom:
- Command:
- Why this command, and not a more dangerous one:

### m4

- PASS line:
- Symptom:
- Command:
- Why this command, and not a more dangerous one:

### m5

- PASS line:
- Symptom:
- Command:
- Why this command, and not a more dangerous one:

### m6

- PASS line:
- Symptom:
- Command:
- Why this command, and not a more dangerous one:

<!-- Stretch: add ### m7 and ### m8 the same way if you solved them. -->

## Part 4 · Protected main and pull requests

The rejected push to `main` (step 4.2):

```text

```

- PR #… (`.gitignore`):
- PR #… (`/healthz` docs, with the conflict):

## Part 5 · Release

- Release:
- Why `0.1.0` and not `1.0.0`?

## Answers

1. In mission 5, why `git revert` and not `git reset --hard` plus a force push?

2. Why couldn't Git resolve the `CHANGELOG.md` conflict by itself, and how did you decide what to keep?

3. A colleague says "I'll make a PR to get the latest code." What do they mean, and which command is it?

4. After `1.0.0`: what is the next version for (a) a bug fix, (b) a new `/api/todos/search` endpoint, (c) renaming `/api/todos` to `/api/tasks`?
