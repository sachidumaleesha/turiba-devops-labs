# Lab 8 · Run the whole app

GitHub user: sachidumaleesha · Fallback image used: no · Fallback Mission 7 files used: no

<!-- Keep every heading as it is: the grader finds the sections by name. Replace every blank (four underscores). Paste command output inside the ```text blocks. Never paste your password, not even the base64 form. -->

## 1 · Database with storage

- 🔮 Before deleting the database Pod: will your todo still be there afterwards? I predicted yes because PostgreSQL stores its data on the `db-data` PVC, whose lifecycle is independent of the Pod. What happened: pending cluster test.

```text
$ kubectl -n course get pvc,pv
Pending cluster test.

$ curl -s -X POST -H 'Content-Type: application/json' -d '{"title":"persist across a database Pod replacement"}' localhost:8080/api/todos
Pending cluster test.

$ kubectl -n course get pods -l app=db        (before the delete)
Pending cluster test.

$ kubectl -n course delete pod <database-pod>
Pending cluster test.

$ kubectl -n course get pods -l app=db        (after the delete)
Pending cluster test.

$ curl -s localhost:8080/api/todos
Pending cluster test.
```

## 2 · Connect the API

```text
$ kubectl -n course logs deployment/api -c wait-for-db
Pending cluster test.

$ kubectl -n course logs deployment/api -c api
Pending cluster test.
```

- 🔮 Before looking: will `kubectl -n course get secret db-secret -o yaml` show your password? I predicted that it would show the password only as base64-encoded data, because a Kubernetes Secret is encoded but not inherently encrypted in its YAML representation. What I saw, in words (don't paste the value): pending cluster test.

## 3 · Health and resources

- 🔮 On my working copy only, I pointed the **liveness** probe of the API at `/nope` and applied it. Will those Pods get traffic? Will they be restarted? I predicted that readiness would initially allow traffic because its `/healthz` check remained valid, but the failed liveness check would eventually restart each API container. What happened: pending cluster test.

```text
$ kubectl -n course get pods -l app=api       (about a minute later)
Pending cluster test.

$ kubectl -n course describe pod <api-pod>    (only the Events)
Pending cluster test.
```

- How I made Git and the cluster agree again afterwards: pending cluster test.

## 4 · What broke and how I found it

- 🔮 Before applying the teammate's branch, I expected the API rollout to stop first because the configuration changes could prevent its init or application container from becoming ready.

| # | What I saw | The command, and the line of output that showed it | My fix (commit) |
|--:|------------|-----------------------------------------------------|-----------------|
| 1 | Pending break-fix test. | Pending break-fix test. | Pending commit. |
| 2 | Pending break-fix test. | Pending break-fix test. | Pending commit. |
| 3 | Pending break-fix test. | Pending break-fix test. | Pending commit. |
