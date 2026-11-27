# Capstone · What to do, step by step

**The capstone is not a new project. There is no new repository and no new app. It is the fork you have built since Session 1, finished: your missions working together, one tag `v1.0.0`, and one new file, `capstone/README.md`. You hand in the URL of that fork.**

This page explains the [capstone brief](README.md) in plain steps. It doesn't change any rule, level or date: if the two ever disagree, the brief wins. For what a finished write-up looks like, see [the example `capstone/README.md`](example-capstone-readme.md).

| | |
|-|-|
| **Where you work** | Your fork `https://github.com/<you>/turiba-devops-labs`, the same one as in every mission |
| **What's new** | One small chart change, the tag `v1.0.0`, and `capstone/README.md`. For Target: the security gates in CI, and a dashboard |
| **What you hand in** | Only the URL of your fork, on Evaluentis, assignment **CAPSTONE**. No ZIP, no PDF, no video |
| **Deadline** | **Sat 28 Nov 2026, 17:00** (Riga). The snapshot of your fork at 17:05 is what's graded |

---

## 1 · Your fork, before and after

**Most of the capstone is already in your fork.** Each mission added a part. The capstone checks that the parts fit together and adds a few things at the end.

```text
turiba-devops-labs/                 your fork
├── api/                            course API, with your Dockerfile                  Lab 2
├── web/                            course front end, with your nginx.conf            Lab 4
├── compose.yaml, .env.example      the whole app on your laptop                      Lab 4
├── .github/
│   ├── workflows/ci.yml            lint · unit · integration · image                Labs 5–6
│   ├── workflows/release.yml       tag v* → image on GHCR + GitHub Release           Lab 6
│   └── dependabot.yml              ★ NEW (Target T2)
├── k8s/                            plain manifests                                   Missions 7–8 (keep them)
├── charts/course-app/              the Helm chart                                    Mission 9
│   ├── Chart.yaml                  ✎ CHANGE: version up, appVersion "1.0.0"
│   └── values.yaml                 ✎ CHANGE: your image, tag "1.0.0"
├── infra/                          OpenTofu: cluster + chart                         Mission 10 (Target T1)
├── observability/dashboard.json    ★ NEW (Target T3)
├── lab1/ … lab10/                  your mission write-ups                            keep them
├── lab01-ship-it/ … capstone-brief/   course folders                                 don't edit
└── capstone/
    └── README.md                   ★ NEW: your capstone write-up
```

**Some parts are not files.** They live on GitHub, next to your code:

| On GitHub | Where you see it | From |
|-----------|------------------|------|
| The ruleset that protects `main` | Settings → Rules → Rulesets | Lab 3, Lab 5 |
| Your pull requests | the **Pull requests** tab of your fork | every mission |
| CI runs and their checks | the **Actions** tab, and the ✓ next to each commit | Labs 5–6 |
| The tag `v1.0.0` | **Code** tab → branch menu → **Tags** | ★ NEW |
| The Release `v1.0.0` | **Code** tab → right sidebar → **Releases** | ★ NEW (made by `release.yml`) |
| The image `api:1.0.0` | **Code** tab → right sidebar → **Packages** | ★ NEW (made by `release.yml`) |

---

## 2 · The steps for Minimum (up to 70 points)

Do the steps in this order. Each step ends with what you should see. If you don't see it, fix that first, because the next step depends on it.

### Step 1 · Check that GitHub Actions runs (10 min)

Open your fork → **Actions**. You want a run for your latest push to `main`, at the time you pushed.

**No run?**
1. Look for a banner in the Actions tab, such as *"Workflows aren't being run on this forked repository"*, and follow it.
2. **Settings → Actions → General:** select "Allow all actions and reusable workflows", then **Save**.
3. Test it: push an empty commit on a branch and open a PR in your fork:

   ```bash
   git switch main && git pull
   git switch -c ci/check-actions
   git commit --allow-empty -m "ci: check that GitHub Actions runs"
   git push -u origin ci/check-actions
   ```

4. Still no run after 2 minutes? Ask the lecturer, or post in BATIS **now**, not on Saturday.

✅ **You see:** a run for each push, and on `main` the four checks `lint`, `unit`, `integration` and `image`, all green.

### Step 2 · Close the gaps from the missions

Every mission that works is a capstone part that works. If one is missing or broken (for example, no chart from Mission 9), fix it now.

- **Behind on a mission?** You may use the course's reference or fallback files from the mission folders. Say so in `## What is where` in your write-up. At the exam you explain every line of them.
- **One thing you can't borrow:** the image. The chart must run `api:1.0.0` built by **your own** `release.yml`, never `ghcr.io/martinsturiba/…`.

### Step 3 · PR 1: the chart runs release 1.0.0 (15 min)

```bash
git switch main && git pull
git switch -c feat/chart-1.0.0
```

Change two files:

| File | Change |
|------|--------|
| `charts/course-app/values.yaml` | `repository: ghcr.io/<you>/turiba-devops-labs/api` (your GitHub name in **lowercase**) and `tag: "1.0.0"` (with the quotes) |
| `charts/course-app/Chart.yaml` | raise `version` (for example `0.1.0` → `0.2.0`) and set `appVersion: "1.0.0"` |

```bash
git add charts/course-app
git commit -m "feat(chart): run release 1.0.0"
git push -u origin feat/chart-1.0.0
```

On GitHub, click **Compare & pull request**.

> ⚠️ **Check the base repository.** GitHub suggests `mleitass/turiba-devops-labs`. Change it to **`<you>/turiba-devops-labs`**, base `main`. A PR in the course repository earns nothing.

Wait for the four checks, then **Merge**. Then, on your laptop: `git switch main && git pull`.

- **The image `1.0.0` doesn't exist yet.** That's fine: CI never installs the chart. Step 4 makes the image.
- **Why raise `version`?** OpenTofu installs a new chart only when its `version` changes. With the same version, `tofu apply` says `No changes`.

✅ **You see:** the PR merged in your fork, and `main` green.

### Step 4 · Tag v1.0.0 and let `release.yml` ship it (10 min)

```bash
git switch main && git pull
git tag v1.0.0
git push origin v1.0.0
```

Open **Actions**: the release workflow runs for the tag and takes about a minute. Then check:

| Where | What you want |
|-------|---------------|
| **Code** → sidebar → **Releases** | `v1.0.0`, made by `github-actions[bot]`, with generated notes |
| **Code** → sidebar → **Packages** → `turiba-devops-labs/api` | the tag `1.0.0` |
| Your terminal | `docker logout ghcr.io`, then `docker pull ghcr.io/<you>/turiba-devops-labs/api:1.0.0` works |

- **`denied` on the pull?** The package is private. Open the package → **Package settings** → Danger Zone → **Change visibility → Public** (as in Lab 5).
- **The release run is red?** Read the log, fix the cause in a PR, then tag **`v1.0.1`** and point the chart at `"1.0.1"` in one more small PR. Don't delete or move tags: the grader uses your highest `v1.x.y`.

✅ **You see:** the Release `v1.0.0` and a public image `api:1.0.0`.

### Step 5 · Run it from zero, and write down every command (45 min)

This is the most important test, because the grader does the same thing: a new folder, a new cluster, and only your instructions.

1. Delete your clusters: `tofu destroy` in your old `infra/`, or `kind delete cluster` for a cluster you made with kind. `kind get clusters` then says `No kind clusters found.`
2. Clone your fork into a **new folder**:

   ```bash
   git clone https://github.com/<you>/turiba-devops-labs.git capstone-check
   cd capstone-check
   ```

3. Start the app with Compose, then on the cluster with your chart (or with `tofu apply`). **Write down every command you type, in a text file.** That list becomes your `## Run it from zero`.
4. Check that the cluster runs **your** image:

   ```bash
   kubectl -n course get deploy api -o jsonpath='{.spec.template.spec.containers[0].image}'; echo
   ```

5. Save a todo, delete the database Pod, and read the todo again. Then try `helm upgrade` and `helm rollback` once (Mission 9).

✅ **You see:** `ghcr.io/<you>/turiba-devops-labs/api:1.0.0`, four Pods `1/1 Running`, and your todo still there after the database Pod was replaced.

### Step 6 · PR 2: `capstone/README.md` (1–2 h)

```bash
git switch main && git pull
git switch -c docs/capstone
mkdir -p capstone
```

Write `capstone/README.md` with the headings from the brief, section 6, **in this order**. Use [the example](example-capstone-readme.md) to see how each part looks, but write your own commands, links and sentences.

```bash
git add capstone
git commit -m "docs(capstone): add the capstone write-up"
git push -u origin docs/capstone
```

Open the PR **in your fork**, wait for green, and merge.

- **Commits after the tag are fine if they change only documentation.** Changed something in `api/` (including the Dockerfile)? Tag `v1.0.1` and move the chart to `"1.0.1"`.

✅ **You see:** `capstone/README.md` on GitHub, with every heading, and every link in it opens the right page.

### Step 7 · Check and submit

1. Go through the checklist in the brief, section 10.
2. Submit the URL of your fork on Evaluentis, assignment **CAPSTONE**: `https://github.com/<you>/turiba-devops-labs`.
3. **Submit early** (Friday is fine). You can keep improving your fork until **Sat 28 Nov, 17:00**. The snapshot at 17:05 is graded, not the moment you submitted.

---

## 3 · Target (up to 20 more points)

Only after Minimum works. **One PR per item**, each merged with green checks. After each one, add a row to `## Level and evidence` in your write-up.

| Item | What you add | Where to learn it |
|------|--------------|-------------------|
| **T1** · Infrastructure as code | Nothing new if Mission 10 passed. After Step 3, run `tofu apply` in `infra/` (it shows `~ version` and installs `1.0.0`), then `tofu destroy` and `tofu apply` once more | Mission 10 brief |
| **T2** · Security gates | A `gitleaks` job in `ci.yml` (and add it to your ruleset's required checks); a Trivy step in the `image` job before the push; `.github/dependabot.yml` plus one Dependabot PR merged or closed with a reason; every third-party action pinned to a full commit SHA | Brief sections 4 and 9; S11 slides 9–10 (BATIS) |
| **T3** · Observability | kube-prometheus-stack with `helm install`, one dashboard with four panels, exported to `observability/dashboard.json`, and a screenshot plus 2–3 sentences about your own numbers in `capstone/README.md` | Brief section 9; S11 slide 11 (BATIS) |

- **Keep the four check names** `lint`, `unit`, `integration` and `image`. Add new jobs or steps; don't rename the old ones.
- **Dependabot is off on forks** until you enable it: Settings → Advanced Security → Dependabot version updates → **Enable**.
- **A screenshot:** commit it next to your write-up (for example `capstone/dashboard.png`) and show it with `![My dashboard](dashboard.png)`.

**Excellent (up to 10 more):** one extension from brief section 5, only when all of Target works.

---

## 4 · How to get the evidence links

`## Level and evidence` needs a link for every item you claim. Open the page on GitHub, then copy the address from the browser.

| Evidence | Where you find it | The link looks like |
|----------|-------------------|---------------------|
| A pull request | **Pull requests** → **Closed** → the PR | `https://github.com/<you>/turiba-devops-labs/pull/12` |
| A workflow run | **Actions** → the run | `https://github.com/<you>/turiba-devops-labs/actions/runs/19876543210` |
| The checks on a commit | **Commits** → the ✓ next to the commit | `https://github.com/<you>/turiba-devops-labs/commit/<SHA>` |
| The Release | **Releases** → `v1.0.0` | `https://github.com/<you>/turiba-devops-labs/releases/tag/v1.0.0` |
| The image | **Packages** → `turiba-devops-labs/api` | `https://github.com/<you>/turiba-devops-labs/pkgs/container/turiba-devops-labs%2Fapi` |
| A file | **Code** → the file | `https://github.com/<you>/turiba-devops-labs/blob/main/charts/course-app/values.yaml` |
| One line in a file | click the line number, then copy the address | `…/blob/main/.github/workflows/ci.yml#L42` |
| Your ruleset | open `https://github.com/<you>/turiba-devops-labs/rules`, then the ruleset | `https://github.com/<you>/turiba-devops-labs/rules/12345678` |

- **Test your links while logged out** (a private browser window). The grader isn't logged in as you.

---

## 5 · Questions students ask

| Question | Answer |
|----------|--------|
| Do I make a new repository? | **No.** Your existing fork is the capstone |
| Do I write a new app or new features? | **No.** For Minimum: two small chart changes, one tag and one Markdown file. Target adds CI and monitoring work |
| Is there a `lab11/` or a `check.sh` for the capstone? | No. The write-up goes in `capstone/README.md`. To check yourself, use the brief's section 10 and the commands in S11 slides 6–7 (BATIS) |
| Can I write the capstone text in the root `README.md`? | No. The root `README.md` belongs to the course. Use `capstone/README.md` |
| What exactly do I submit? | Only your fork's URL on Evaluentis, **CAPSTONE**. Everything else is read from your fork |
| Something doesn't work. Should I leave it out? | Put it under `## Known issues`, with what you tried. A claimed item that doesn't work loses points in Documentation too; an honest gap doesn't |
| I'm behind on a mission. Am I out? | No. Catch up with the course's reference files, and say so in `## What is where`. The image must still be your own |
| Do I need the `web` front end on Kubernetes? | No. On the cluster you run the API and PostgreSQL. `web` runs in Compose |
| Can I delete `k8s/`, `lab1/`–`lab10/` or old tags? | No. The earlier mission checks run again on your snapshot |
| May I use AI tools? | Yes, within the course rules from S1. Write what they helped with under `## AI use`. At the exam you explain every line yourself |
| My PR went to `mleitass/turiba-devops-labs`. | Close it there, and open it again with base repository `<you>/turiba-devops-labs` |
| Can I work with a classmate? | Explaining and debugging together are fine. Every fork is individual work: don't copy files |

**Stuck for 20 minutes?** Post in BATIS: the command, its **exact** output, and what you expected.
