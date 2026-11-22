# Lab 10 · Build it from code with OpenTofu

GitHub user: <you> · Fallback chart used: no

<!-- Keep every heading as it is: the grader finds the sections by name. Replace every blank (four underscores). Paste command output inside the ```text blocks. Never paste the password, the state file or the kubeconfig. -->

## 1 · The cluster and the app from code

```text
$ tofu plan                                    (Part 1: the end of the first plan)
____

$ time tofu apply -auto-approve                (Part 2: from zero, the last lines and the time)
____

$ tofu plan                                    (right after that apply)
____

$ grep -c '"result"' terraform.tfstate
____
```

- 🔮 Before the first plan (Part 1): how many resources will it add, and which values will be `known after apply`? I predicted ____ because ____. What happened: ____
- 🔮 Before the second plan (Part 2): what will `tofu plan` say right after `tofu apply`? I predicted ____ because ____. What happened: ____
- 🔮 Where is the database password now? I predicted ____ because ____. What happened: ____

## 2 · Change, drift, rebuild

```text
$ tofu apply -var api_replicas=2               (the plan: the symbol and the value that changes)
____

$ helm history course-app -n course
____

$ tofu plan -var api_replicas=2                (after kubectl -n course delete secret db-secret)
____

$ tofu plan -var api_replicas=2                (after kubectl -n course scale deployment api --replicas=1)
____

$ tofu apply                                   (the plan, and how many API Pods run afterwards)
____

$ time tofu destroy -auto-approve / time tofu apply -auto-approve      (the last lines and the times)
____

$ curl -s localhost:8080/api/todos             (after the rebuild)
____
```

- 🔮 Step 1, `-var api_replicas=2`: which symbol, and which value changes? I predicted ____ because ____. What happened: ____
- 🔮 Step 2, the deleted Secret and the scaled Deployment: what will each plan show? I predicted ____ because ____. What happened: ____
- 🔮 Step 3, a plain `tofu apply`: what will the plan contain, and how many API Pods afterwards? I predicted ____ because ____. What happened: ____
- 🔮 Step 4, after `tofu destroy` and `tofu apply`: is the todo still there? I predicted ____ because ____. What happened: ____

## 3 · What broke and how I found it

- 🔮 Before `tofu plan` on the teammate's branch, I expected this to go wrong first: ____

| # | What I saw | The command, and the line of output that showed it | My fix (commit) |
|--:|------------|-----------------------------------------------------|-----------------|
| 1 | ____ | ____ | ____ |
| 2 | ____ | ____ | ____ |
| 3 | ____ | ____ | ____ |

## 4 · In my own words

- Why `.terraform.lock.hcl` goes into Git and `terraform.tfstate` doesn't: ____
- What `-/+ … # forces replacement` means, and what it would have cost me in Part 4: ____
- What I would lose by ending the day with `kind delete cluster` instead of `tofu destroy`: ____
