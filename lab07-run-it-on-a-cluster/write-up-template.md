# Lab 7 · Run it on a cluster

GitHub user: <you> · Fallback image used: no

<!-- Keep every heading as it is: the grader finds the sections by name. Replace every blank (four underscores). Paste command output inside the ```text blocks. -->

## 1 · Deploy

- 🔮 Before my first `apply`: how many Pods, and what their names start with? I predicted ____ because ____. What happened: ____

```text
$ kubectl -n course get deploy,rs,pods
____

$ curl -s localhost:8080/
____
```

## 2 · Heal and scale

- 🔮 After deleting one Pod, two seconds later I expected to see ____ because ____. What happened: ____

```text
$ kubectl -n course get pods        (after the delete)
____

$ kubectl -n course get pods        (with replicas: 5)
____
```

## 3 · Roll and roll back

- 3a: I rolled from the tag ____ to the tag ____.

```text
$ kubectl -n course rollout status deployment/api
____
```

- 3b: 🔮 With the tag 9.9.9, I predicted that ____ old Pods keep running, because ____. What happened: ____

```text
$ kubectl -n course get pods        (during the stall)
____

$ kubectl -n course rollout undo deployment/api
____
```

- What the `rollout undo` warning means, in my own words, and what I did so that Git and the cluster agree again: ____

## 4 · What broke and how I found it

- 🔮 Before applying the teammate's branch, I expected this to go wrong first: ____

| # | What I saw | The command, and the line of output that showed it | My fix (commit) |
|--:|------------|-----------------------------------------------------|-----------------|
| 1 | ____ | ____ | ____ |
| 2 | ____ | ____ | ____ |
| 3 | ____ | ____ | ____ |
