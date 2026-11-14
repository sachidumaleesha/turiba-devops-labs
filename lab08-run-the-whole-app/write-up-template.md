# Lab 8 · Run the whole app

GitHub user: <you> · Fallback image used: no · Fallback Mission 7 files used: no

<!-- Keep every heading as it is: the grader finds the sections by name. Replace every blank (four underscores). Paste command output inside the ```text blocks. Never paste your password, not even the base64 form. -->

## 1 · Database with storage

- 🔮 Before deleting the database Pod: will your todo still be there afterwards? I predicted ____ because ____. What happened: ____

```text
$ kubectl -n course get pvc,pv
____

$ curl -s -X POST -H 'Content-Type: application/json' -d '{"title":"____"}' localhost:8080/api/todos
____

$ kubectl -n course get pods -l app=db        (before the delete)
____

$ kubectl -n course delete pod ____
____

$ kubectl -n course get pods -l app=db        (after the delete)
____

$ curl -s localhost:8080/api/todos
____
```

## 2 · Connect the API

```text
$ kubectl -n course logs deployment/api -c wait-for-db
____

$ kubectl -n course logs deployment/api -c api
____
```

- 🔮 Before looking: will `kubectl -n course get secret db-secret -o yaml` show your password? I predicted ____ because ____. What I saw, in words (don't paste the value): ____

## 3 · Health and resources

- 🔮 On my working copy only, I pointed the **liveness** probe of the API at `/nope` and applied it. Will those Pods get traffic? Will they be restarted? I predicted ____ because ____. What happened: ____

```text
$ kubectl -n course get pods -l app=api       (about a minute later)
____

$ kubectl -n course describe pod ____         (only the Events)
____
```

- How I made Git and the cluster agree again afterwards: ____

## 4 · What broke and how I found it

- 🔮 Before applying the teammate's branch, I expected this to go wrong first: ____

| # | What I saw | The command, and the line of output that showed it | My fix (commit) |
|--:|------------|-----------------------------------------------------|-----------------|
| 1 | ____ | ____ | ____ |
| 2 | ____ | ____ | ____ |
| 3 | ____ | ____ | ____ |
