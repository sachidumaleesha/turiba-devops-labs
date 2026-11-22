# Lab 10 · Build it from code with OpenTofu

GitHub user: sachidumaleesha · Fallback chart used: no

## 1 · The cluster and the app from code

```text
$ tofu plan                                    (Part 1: the end of the first plan)
Plan: 1 to add, 0 to change, 0 to destroy.

Changes to Outputs:
  + kube_context = (known after apply)

$ time tofu apply -auto-approve                (Part 2: from zero, the last lines and the time)
kind_cluster.course: Creation complete after 38s [id=course-]
kubernetes_namespace_v1.course: Creation complete after 0s [id=course]
kubernetes_secret_v1.db: Creation complete after 0s [id=course/db-secret]
helm_release.course_app: Creation complete after 2m7s [id=course-app]

Apply complete! Resources: 5 added, 0 changed, 0 destroyed.
kube_context = "kind-course"
real 174.17

$ tofu plan                                    (right after that apply)
No changes. Your infrastructure matches the configuration.

$ grep -c '"result"' terraform.tfstate
2
```

- 🔮 Before the first plan (Part 1): how many resources will it add, and which values will be `known after apply`? I predicted one resource because only `kind_cluster.course` existed in the first configuration. I expected its generated credentials, endpoint, context, kubeconfig and the `kube_context` output to be known only after apply. What happened: the plan reported `1 to add`, and those generated attributes plus `kube_context` were marked `known after apply`.
- 🔮 Before the second plan (Part 2): what will `tofu plan` say right after `tofu apply`? I predicted `No changes` because the configuration, state and live cluster should agree after a successful apply. What happened: it printed `No changes. Your infrastructure matches the configuration.`
- 🔮 Where is the database password now? I predicted it would be sensitive in normal command output but present in plain text in `terraform.tfstate`, because state must remember `random_password.db.result`. What happened: `grep -c` found two `result` lines, while `tofu state show` displayed the Secret data only as `(sensitive value)`.

## 2 · Change, drift, rebuild

```text
$ tofu apply -var api_replicas=2               (the plan: the symbol and the value that changes)
~ update in-place
~ value = "3" -> "2"
Plan: 0 to add, 1 to change, 0 to destroy.
Apply complete! Resources: 0 added, 1 changed, 0 destroyed.

$ helm history course-app -n course
REVISION  STATUS      CHART             DESCRIPTION
1         superseded  course-app-0.1.0  Install complete
2         deployed    course-app-0.1.0  Upgrade complete

$ tofu plan -var api_replicas=2                (after kubectl -n course delete secret db-secret)
# kubernetes_secret_v1.db will be created
Plan: 1 to add, 0 to change, 0 to destroy.

$ tofu plan -var api_replicas=2                (after kubectl -n course scale deployment api --replicas=1)
# kubernetes_secret_v1.db will be created
Plan: 1 to add, 0 to change, 0 to destroy.

$ tofu apply                                   (the plan, and how many API Pods run afterwards)
Plan: 1 to add, 1 to change, 0 to destroy.
Apply complete! Resources: 1 added, 1 changed, 0 destroyed.
NAME  READY  UP-TO-DATE  AVAILABLE
api   3/3    3           3

$ time tofu destroy -auto-approve / time tofu apply -auto-approve
Destroy complete! Resources: 5 destroyed.
real 16.41

The first rebuild was interrupted when Docker Desktop stopped. After Docker was restarted,
the orphaned course cluster was verified and removed. PostgreSQL then took more than five
minutes to pull, so Helm reached its 300-second timeout:
Error: Helm release error
context deadline exceeded
real 352.51

All four Pods became Running. The failed, untracked Helm release was then uninstalled and
the next apply completed:
helm_release.course_app: Creation complete after 17s [id=course-app]
Apply complete! Resources: 1 added, 0 changed, 0 destroyed.
No changes. Your infrastructure matches the configuration.

$ curl -s localhost:8080/api/todos             (after the rebuild)
[]
```

- 🔮 Step 1, `-var api_replicas=2`: which symbol, and which value changes? I predicted `~ update in-place` and the Helm `api.replicas` set value changing from `"3"` to `"2"`, because the release can be upgraded without replacing it. What happened: exactly that change appeared, and Helm created revision 2 with two ready API replicas.
- 🔮 Step 2, the deleted Secret and the scaled Deployment: what will each plan show? I predicted the deleted Secret would produce `+ create`, while scaling the Deployment would add nothing because OpenTofu manages the Helm release rather than each object rendered by Helm. What happened: both plans contained only `Plan: 1 to add` for the missing Secret; the manual Deployment scale was invisible.
- 🔮 Step 3, a plain `tofu apply`: what will the plan contain, and how many API Pods afterwards? I predicted one Secret addition and one in-place Helm change from two back to the default three replicas. What happened: the plan showed `1 to add, 1 to change`, and the Deployment finished at `3/3`.
- 🔮 Step 4, after `tofu destroy` and `tofu apply`: is the todo still there? I predicted no because the database PVC belongs to the cluster and is destroyed with it. What happened: after recovering from the Docker stop and slow image pull, the rebuilt API returned `[]`.

## 3 · What broke and how I found it

- 🔮 Before `tofu plan` on the teammate's branch, I expected provider initialization or dependency selection to fail first because provider requirements are resolved before OpenTofu can inspect the Helm chart or live resources.

| # | What I saw | The command, and the line of output that showed it | My fix (commit) |
|--:|------------|-----------------------------------------------------|-----------------|
| 1 | The kind provider source had been changed to a provider that does not exist in the lock file. | `tofu plan`: `Error: Inconsistent dependency lock file` and `provider registry.opentofu.org/hashicorp/kind: required by this configuration but no version is selected` | Restored `tehcyx/kind` in `31ff792` (`fix(infra): restore the kind provider source`). |
| 2 | The Helm chart path used `chart` instead of `charts`. | `tofu plan`: `Error: Error locating chart` and `Unable to locate chart ./../chart/course-app` | Restored `../charts/course-app` in `faa7b46` (`fix(infra): correct the Helm chart path`). |
| 3 | The release namespace had changed from `course` to the nonexistent `courses`, forcing a destructive replacement. | `tofu plan`: `helm_release.course_app must be replaced`, `namespace = "course" -> "courses" # forces replacement`, and `Plan: 1 to add, 0 to change, 1 to destroy.` | Restored the Namespace reference in `282a53f` (`fix(infra): keep the release in the course namespace`). |

## 4 · In my own words

- Why `.terraform.lock.hcl` goes into Git and `terraform.tfstate` doesn't: the lock file records the exact provider versions and checksums selected by `tofu init`, so committing it makes initialization repeatable for teammates and the grader. State records the real resource identities and values needed to reconcile infrastructure, including the random database password and cluster credentials in plain text. It must remain local and protected.
- What `-/+ … # forces replacement` means, and what it would have cost me in Part 4: OpenTofu cannot modify that attribute in place, so it plans to destroy the old resource before creating a replacement. Moving the Helm release to `courses` would have uninstalled the existing release, deleted its PVC and todos, and then failed because that Namespace did not exist.
- What I would lose by ending the day with `kind delete cluster` instead of `tofu destroy`: kind would remove the live cluster without updating OpenTofu state. The state would still contain the cluster, Namespace, Secret and Helm release, so later plans and destroys would fail while trying to refresh resources through a cluster endpoint that no longer exists. `tofu destroy` removes resources in dependency order and updates state consistently.
