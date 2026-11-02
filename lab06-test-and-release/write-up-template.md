# Lab 6 · Test what you ship, ship a release

GitHub user: <you> · Reference pipeline used (Part 0 fallback): no

<!-- Keep every heading as it is: the grader finds the sections by name. Replace every blank (four underscores), and <you> in the first line and in section 3. -->

## 1 · Smoke test

- The names of my smoke-test steps in the `image` job: ____
- What my smoke test asks, and what makes it fail: ____
- 🔮 Part 1, before my first run: will my code pass the smoke test? I predicted ____ because ____. What happened: ____
- 🔮 Part 2, before the checks finished: which checks will go red after `break.sh`? I predicted ____ because ____

## 2 · What broke and how I found it

- The check and the step that went red: ____
- The log line that showed the cause (copied from the log):

```text
____
```

- The cause, in my own words: ____
- Why `lint`, `unit` and `integration` stayed green: ____
- My fix, and the commit that made it: ____

## 3 · Release

- Release page: https://github.com/<you>/turiba-devops-labs/releases/tag/v0.2.0
- Image: `ghcr.io/<you>/turiba-devops-labs/api:0.2.0`, platforms (from `docker buildx imagetools inspect`): ____
- One thing in Part 3 that didn't work the first time, and how I fixed it: ____
