# Lab 8 · Run the whole app

GitHub user: sachidumaleesha · Fallback image used: no · Fallback Mission 7 files used: no

<!-- Keep every heading as it is: the grader finds the sections by name. Replace every blank (four underscores). Paste command output inside the ```text blocks. Never paste your password, not even the base64 form. -->

## 1 · Database with storage

- 🔮 Before deleting the database Pod: will your todo still be there afterwards? I predicted yes because PostgreSQL stores its data on the `db-data` PVC, whose lifecycle is independent of the Pod. What happened: the replacement Pod mounted the same claim and the API returned the original todo.

```text
$ kubectl -n course get pvc,pv
NAME      STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
db-data   Bound    pvc-034f51cd-5b58-4feb-ba55-b6945c7febc3   1Gi        RWO            standard       111s
NAME                                       CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS   CLAIM            STORAGECLASS   AGE
pvc-034f51cd-5b58-4feb-ba55-b6945c7febc3   1Gi        RWO            Delete           Bound    course/db-data   standard       107s

$ curl -s -X POST -H 'Content-Type: application/json' -d '{"title":"persist across a database Pod replacement"}' localhost:8080/api/todos
{"id":1,"title":"persist across a database Pod replacement","done":false,"created_at":"2026-11-14T07:28:32.162Z"}

$ kubectl -n course get pods -l app=db        (before the delete)
NAME                  READY   STATUS    RESTARTS   AGE
db-864878fdcf-g5rld   1/1     Running   0          111s

$ kubectl -n course delete pod db-864878fdcf-g5rld
pod "db-864878fdcf-g5rld" deleted from course namespace

$ kubectl -n course get pods -l app=db        (after the delete)
NAME                  READY   STATUS    RESTARTS   AGE
db-864878fdcf-kzz72   1/1     Running   0          9s

$ curl -s localhost:8080/api/todos
[{"id":1,"title":"persist across a database Pod replacement","done":false,"created_at":"2026-11-14T07:28:32.162Z"}]
```

## 2 · Connect the API

```text
$ kubectl -n course logs deployment/api -c wait-for-db
db:5432 - no response
waiting for the database
db:5432 - no response
waiting for the database
db:5432 - accepting connections

$ kubectl -n course logs deployment/api -c api
course-api 0.1.0 starting (Node.js v24.21.0)
API listening on port 5000
Database ready
```

- 🔮 Before looking: will `kubectl -n course get secret db-secret -o yaml` show your password? I predicted that it would show the password only as base64-encoded data, because a Kubernetes Secret is encoded but not inherently encrypted in its YAML representation. What I saw, in words (don't paste the value): the object contained a `data` entry for the `password` key, represented as base64 text rather than readable plaintext. I did not copy the value.

## 3 · Health and resources

- 🔮 On my working copy only, I pointed the **liveness** probe of the API at `/nope` and applied it. Will those Pods get traffic? Will they be restarted? I predicted that readiness would initially allow traffic because its `/healthz` check remained valid, but the failed liveness check would eventually restart each API container. What happened: all three Pods became Ready, then each container was restarted after the liveness endpoint repeatedly returned HTTP 404.

```text
$ kubectl -n course get pods -l app=api       (about a minute later)
NAME                   READY   STATUS    RESTARTS      AGE
api-64755456df-6h9qj   1/1     Running   1 (14s ago)   54s
api-64755456df-b29rg   1/1     Running   1 (12s ago)   52s
api-64755456df-zfbjz   1/1     Running   1 (10s ago)   50s

$ kubectl -n course describe pod api-64755456df-6h9qj    (only the Events)
Events:
  Type     Reason     Age                From               Message
  ----     ------     ----               ----               -------
  Normal   Scheduled  63s                default-scheduler  Successfully assigned course/api-64755456df-6h9qj to lab8-work-control-plane
  Normal   Pulled     63s                kubelet            spec.initContainers{wait-for-db}: Container image "postgres:17-alpine" already present on machine and can be accessed by the pod
  Normal   Created    62s                kubelet            spec.initContainers{wait-for-db}: Container created
  Normal   Started    62s                kubelet            spec.initContainers{wait-for-db}: Container started
  Normal   Pulled     23s (x2 over 62s)  kubelet            spec.containers{api}: Container image already present on machine and can be accessed by the pod
  Normal   Created    23s (x2 over 62s)  kubelet            spec.containers{api}: Container created
  Normal   Started    23s (x2 over 62s)  kubelet            spec.containers{api}: Container started
  Normal   Killing    23s                kubelet            spec.containers{api}: Container api failed liveness probe, will be restarted
  Warning  Unhealthy  3s (x5 over 43s)   kubelet            spec.containers{api}: Liveness probe failed: HTTP probe failed with statuscode: 404
```

- How I made Git and the cluster agree again afterwards: I restored the liveness path to `/healthz` from the committed version, applied `k8s/` again, waited for `deployment/api` to finish its rollout, and confirmed that `git diff` was empty.

## 4 · What broke and how I found it

- 🔮 Before applying the teammate's branch, I expected the API rollout to stop first because the configuration changes could prevent its init or application container from becoming ready.

| # | What I saw | The command, and the line of output that showed it | My fix (commit) |
|--:|------------|-----------------------------------------------------|-----------------|
| 1 | A new API Pod remained at `Init:0/1`; the old Ready Pods kept serving during the rolling update. | `kubectl -n course logs api-5f8d7547bf-qqxc9 -c wait-for-db` → `database:5432 - no response` | `738b134 fix(k8s): restore database service hostname` |
| 2 | After correcting the hostname and restarting the rollout, the API container could not be created. | `kubectl -n course describe pod api-6656956d85-vx4lf` → `Error: couldn't find key pasword in Secret course/db-secret` | `7b3fa1e fix(k8s): correct database secret key` |
| 3 | The new API Pod ran but stayed `0/1` because it was never Ready. | `kubectl -n course describe pod api-84fb9787cd-x87wc` → `Readiness probe failed: Get "http://10.244.0.19:5001/healthz": ... connection refused` | `6813124 fix(k8s): restore API readiness probe port` |
