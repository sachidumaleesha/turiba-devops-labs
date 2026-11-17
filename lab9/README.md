# Lab 9 · Package it with Helm

GitHub user: sachidumaleesha · Fallback image used: no · Fallback Mission 8 files used: no

## 1 · The chart

```text
$ helm lint charts/course-app
==> Linting charts/course-app
[INFO] Chart.yaml: icon is recommended

1 chart(s) linted, 0 chart(s) failed

$ helm template course-app charts/course-app -n course --set api.replicas=2 | grep -E 'replicas:|image:'
  replicas: 2
          image: postgres:17-alpine
          image: "ghcr.io/sachidumaleesha/turiba-devops-labs/api:0.2.0"
  replicas: 1
          image: postgres:17-alpine
```

- 🔮 Before running `helm template … --set api.replicas=2`, I predicted that only the API Deployment's `replicas:` line would change from the default 3 to 2. `values.yaml` decides the default, while `--set` has higher precedence. The rendered output matched the prediction; the database remained at one replica and the images did not change.
- The Namespace and Secret are not in the chart because the release depends on them but does not own them. The grader creates both before `helm install`. Helm refuses to adopt an existing object without its ownership metadata, and keeping the Secret outside Git also prevents committing a password.

## 2 · Install, upgrade, rollback

```text
$ helm install course-app charts/course-app -n course
NAME: course-app
NAMESPACE: course
STATUS: deployed
REVISION: 1
DESCRIPTION: Install complete

$ helm upgrade course-app charts/course-app -n course --set api.image.tag=does-not-exist
Release "course-app" has been upgraded. Happy Helming!
STATUS: deployed
REVISION: 2
DESCRIPTION: Upgrade complete

$ kubectl -n course get pods -l app=api        # about 30 seconds later
NAME                   READY   STATUS         RESTARTS   AGE
api-6f88cfb78f-c6pwf   0/1     ErrImagePull   0          25s
api-84db47948d-mqsq2   1/1     Running        0          3m28s
api-84db47948d-tffzr   1/1     Running        0          3m28s
api-84db47948d-vjrrr   1/1     Running        0          10m

$ curl -s localhost:8080/api/todos
[{"id":1,"title":"packaged by helm","done":false,"created_at":"2026-11-17T17:13:04.249Z"}]

$ helm history course-app -n course            # before the rollback
REVISION  STATUS      DESCRIPTION
1         superseded  Install complete
2         deployed    Upgrade complete

$ helm rollback course-app 1 -n course
Rollback was a success! Happy Helming!

$ helm history course-app -n course            # after the rollback
REVISION  STATUS      DESCRIPTION
1         superseded  Install complete
2         superseded  Upgrade complete
3         deployed    Rollback to 1
```

- 🔮 Before the bad-image upgrade, I predicted that `helm upgrade` would report success because Kubernetes could accept the new Deployment even though the registry could not supply the image. I also predicted that `GET /api/todos` would continue to answer because the rolling update would retain the three old ready Pods. Both predictions matched: the new Pod entered `ImagePullBackOff` while the old Pods served the saved todo.
- 🔮 Before the rollback, I predicted that `helm rollback course-app 1` would create revision 3 rather than rewriting revision 1. This matched `helm history`: revision 3 was deployed with `Rollback to 1`, and the earlier revisions were superseded.
- I also replaced the database Pod before uninstalling. The API briefly logged a refused connection while the new database endpoint was starting, then returned the same todo, proving that `db-data` preserved the database independently of the Pod.
- 🔮 Before `helm uninstall` and a new `helm install`, I predicted that the todo would disappear. The PVC belongs to the Helm release, so uninstall deletes it, while the externally created `db-secret` remains. The result matched the prediction.

```text
$ helm uninstall course-app -n course
release "course-app" uninstalled

$ kubectl -n course get pvc,secret
NAME                       STATUS        VOLUME   CAPACITY   ACCESS MODES   STORAGECLASS   AGE
persistentvolumeclaim/db-data   Terminating
NAME              TYPE     DATA   AGE
secret/db-secret  Opaque   1      3m

$ helm install course-app charts/course-app -n course
NAME: course-app
STATUS: deployed
REVISION: 1

$ kubectl -n course get pods
NAME                   READY   STATUS    RESTARTS   AGE
api-84db47948d-hbbqr   1/1     Running   0          12s
api-84db47948d-vjrrr   1/1     Running   0          12s
api-84db47948d-zlb8c   1/1     Running   0          12s
db-864878fdcf-8nd6h    1/1     Running   0          12s

$ curl -s localhost:8080/api/todos             # after uninstall and install
[]
```

## 3 · What broke and how I found it

- 🔮 Before upgrading with the teammate's branch, I expected template rendering to fail first because a missing nested Helm value is evaluated before any object reaches Kubernetes. That is what happened.

| # | What I saw | The command, and the line of output that showed it | My fix (commit) |
| --: | ------------ | ----------------------------------------------------- | ----------------- |
| 1 | The image repository path had changed from `api.image.repository` to the nonexistent `api.images.repository`. | `helm upgrade course-app charts/course-app -n course` → `nil pointer evaluating interface {}.repository` in `api-deployment.yaml`. | Restored `.Values.api.image.repository` in `2223153` (`fix(chart): restore API image value path`). |
| 2 | A new `templates/namespace.yaml` tried to put the pre-existing Namespace under Helm ownership. | `helm upgrade course-app charts/course-app -n course` → `Namespace "course" ... exists and cannot be imported into the current release: invalid ownership metadata`. | Removed the Namespace template in `a17f737` (`fix(chart): keep namespace outside the release`). |
| 3 | `values.yaml` renamed `replicas` to `replicaCount`; Helm rendered an empty replica field and Kubernetes defaulted it to one. | `helm template ... | grep replicas:` printed `replicas:` with no value; after upgrade, `kubectl -n course get deployment api` showed `1/1`. | Restored `api.replicas` in `b63fe47` (`fix(chart): restore API replica value`). |

After all three fixes:

```text
$ helm lint charts/course-app
1 chart(s) linted, 0 chart(s) failed

$ helm upgrade course-app charts/course-app -n course
STATUS: deployed
REVISION: 3
DESCRIPTION: Upgrade complete

$ kubectl -n course get deployment api
NAME   READY   UP-TO-DATE   AVAILABLE   AGE
api    3/3     3            3           7m30s

$ curl -s localhost:8080/api/todos
[]
```
