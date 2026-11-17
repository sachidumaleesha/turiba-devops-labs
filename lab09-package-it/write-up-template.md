# Lab 9 · Package it with Helm

GitHub user: <you> · Fallback image used: no · Fallback Mission 8 files used: no

<!-- Keep every heading as it is: the grader finds the sections by name. Replace every blank (four underscores). Paste command output inside the ```text blocks. Never paste your password. -->

## 1 · The chart

```text
$ helm lint charts/course-app
____

$ helm template course-app charts/course-app -n course --set api.replicas=2 | grep -E 'replicas:|image:'
____
```

- 🔮 Before running `helm template … --set api.replicas=2`: which lines of the output change, and which file decides that? I predicted ____ because ____. What happened: ____
- In my own words, why the Namespace and the Secret are **not** in the chart: ____

## 2 · Install, upgrade, rollback

```text
$ helm install course-app charts/course-app -n course
____

$ helm upgrade course-app charts/course-app -n course --set api.image.tag=does-not-exist
____

$ kubectl -n course get pods -l app=api        (about 30 seconds later)
____

$ helm history course-app -n course            (before the rollback)
____

$ helm rollback course-app 1 -n course
____

$ helm history course-app -n course            (after the rollback)
____
```

- 🔮 Before the upgrade with a tag that doesn't exist: will `helm upgrade` say it failed? Will `GET /api/todos` still answer? I predicted ____ because ____. What happened: ____
- 🔮 Before the rollback: which revision number will `helm rollback course-app 1` create? I predicted ____ because ____. What happened: ____
- 🔮 Before `helm uninstall` and a new `helm install`: will your todo still be there? I predicted ____ because ____. What happened: ____

```text
$ curl -s localhost:8080/api/todos             (after uninstall and install)
____
```

## 3 · What broke and how I found it

- 🔮 Before upgrading with the teammate's branch, I expected this to go wrong first: ____

| # | What I saw | The command, and the line of output that showed it | My fix (commit) |
|--:|------------|-----------------------------------------------------|-----------------|
| 1 | ____ | ____ | ____ |
| 2 | ____ | ____ | ____ |
| 3 | ____ | ____ | ____ |
