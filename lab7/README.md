# Lab 7 · Run it on a cluster

GitHub user: sachidumaleesha · Fallback image used: no

## 1 · Deploy

- 🔮 Before my first `apply`, I predicted that Kubernetes would create 3 Pods and their names would start with `api-`, because the Deployment is named `api` and its desired replica count is 3. What happened: three Pods named `api-54fbfb4744-*` became Ready.

```text
$ kubectl -n course get deploy,rs,pods
NAME                  READY   UP-TO-DATE   AVAILABLE   AGE
deployment.apps/api   3/3     3            3           17s

NAME                             DESIRED   CURRENT   READY   AGE
replicaset.apps/api-54fbfb4744   3         3         3       17s

NAME                       READY   STATUS    RESTARTS   AGE
pod/api-54fbfb4744-2vmxs   1/1     Running   0          17s
pod/api-54fbfb4744-s2nxl   1/1     Running   0          17s
pod/api-54fbfb4744-zjkh7   1/1     Running   0          17s

$ curl -s localhost:8080/
{"name":"course-api","version":"0.1.0"}
```

The Deployment owns the ReplicaSet, and the ReplicaSet keeps the requested number of Pods running. The Service selects those Pods through their shared `app: api` label and translates Service port 80 to the container's port 5000.

## 2 · Heal and scale

- 🔮 Two seconds after deleting one Pod, I expected to still see 3 Pods, with one replacement only a few seconds old, because the ReplicaSet continuously reconciles the actual Pod count with `replicas: 3`. What happened: the deleted Pod disappeared and `api-54fbfb4744-vt2g9` replaced it immediately.

```text
$ kubectl -n course get pods        (after the delete)
NAME                   READY   STATUS    RESTARTS   AGE
api-54fbfb4744-s2nxl   1/1     Running   0          61s
api-54fbfb4744-vt2g9   1/1     Running   0          4s
api-54fbfb4744-zjkh7   1/1     Running   0          61s

$ kubectl -n course get pods        (with replicas: 5)
NAME                   READY   STATUS    RESTARTS   AGE
api-54fbfb4744-lpqgg   1/1     Running   0          1s
api-54fbfb4744-s2nxl   1/1     Running   0          75s
api-54fbfb4744-vt2g9   1/1     Running   0          18s
api-54fbfb4744-zjkh7   1/1     Running   0          75s
api-54fbfb4744-zwzzs   1/1     Running   0          1s
```

Changing the desired state in the Deployment YAML from 3 to 5 caused Kubernetes to create two more Pods. I then restored the manifest to 3 and reapplied it, so the committed state and the cluster both returned to three replicas.

## 3 · Roll and roll back

- 3a: I rolled from tag `0.2.0` to tag `2bbd3a6783d7b43dbe0b46db85d556ed4ba95786`. The new tag is immutable CI output from `main` and includes `linux/amd64` and `linux/arm64` images.

```text
$ kubectl -n course rollout status deployment/api
Waiting for deployment "api" rollout to finish: 1 out of 3 new replicas have been updated...
Waiting for deployment "api" rollout to finish: 2 out of 3 new replicas have been updated...
Waiting for deployment "api" rollout to finish: 1 old replicas are pending termination...
deployment "api" successfully rolled out
```

- 3b: 🔮 With the nonexistent tag `9.9.9`, I predicted that all 3 old Pods would keep running. The default rolling-update strategy allows one extra Pod but rounds `maxUnavailable: 25%` down to zero for three replicas. Because the new Pod could never become Ready, Kubernetes could not safely remove an old one. What happened: exactly three old Pods stayed Running while one extra Pod stalled in `ErrImagePull`.

```text
$ kubectl -n course get pods        (during the stall)
NAME                   READY   STATUS         RESTARTS   AGE
api-786c885f6f-d4gmg   1/1     Running        0          4m31s
api-786c885f6f-vfkqw   1/1     Running        0          4m25s
api-786c885f6f-vq9pl   1/1     Running        0          4m24s
api-bcb7894d9-crn6m    0/1     ErrImagePull   0          30s

$ kubectl -n course rollout undo deployment/api
Warning: resource deployments/api was previously managed with 'kubectl apply'. Rolling back will not update the kubectl.kubernetes.io/last-applied-configuration annotation, which may cause unexpected behavior on future 'kubectl apply' operations. Consider using 'kubectl apply' with your previous configuration file instead.
deployment.apps/api rolled back
```

The warning means `rollout undo` changed the live Deployment but did not change the manifest in Git or the `last-applied-configuration` used by future `kubectl apply` operations. I ran `git restore k8s/` to remove the temporary `9.9.9` edit and then `kubectl apply -f k8s/`, making Git, the apply annotation, and the live cluster agree again.

## 4 · What broke and how I found it

- 🔮 Before applying the teammate's branch, I expected the image to fail first because changing the Deployment immediately starts a new Pod, while the two Service faults only become visible when traffic is sent. That prediction matched what happened.

| # | What I saw | The command, and the line of output that showed it | My fix (commit) |
|--:|------------|-----------------------------------------------------|-----------------|
| 1 | One new Pod entered `ImagePullBackOff`; the three old Pods remained Running. | `kubectl -n course describe pod api-7bc959b457-zlwr7` → `Failed to resolve reference ... api:0.2.O: not found` | Changed the letter `O` to the correct image tag in `b052304` (`fix(k8s): correct API image tag`). |
| 2 | All three Pods were Ready, but the Service had no endpoints. | `kubectl -n course get endpointslices -l kubernetes.io/service-name=api -o wide` → `PORTS <unset>`, `ENDPOINTS <unset>`; `get pods --show-labels` showed `app=api` while the Service selected `app.kubernetes.io/name=api`. | Restored the Service selector to `app: api` in `9f00272` (`fix(k8s): match Service selector to Pods`). |
| 3 | Port-forward accepted a local connection, but the request was refused inside the Pod. | `kubectl -n course port-forward service/api 8080:80` → `failed to connect to localhost:8080 ... connection refused` | Changed `targetPort` from 8080 to 5000 in `799fea5` (`fix(k8s): route Service to API port`). |

After the third fix, `kubectl -n course get deploy,rs,pods` showed `deployment.apps/api 3/3`, and `curl -s localhost:8080/` again returned `{"name":"course-api","version":"0.1.0"}`.

The debug loop was: inspect broad state with `get`, inspect the failing object's details and Events with `describe`, form one hypothesis by comparing the live state with the manifests, make one focused fix, reapply, and verify before moving to the next fault.
