"""check.py: the Lab 6 self-check. Run it through check.sh, not directly.

It only reads: your fork through the GitHub REST API, and your image's manifest from ghcr.io
without logging in. It changes nothing. The grader uses the same gate functions after the deadline.

Python 3 standard library only.
"""
import argparse
import base64
import getpass
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple

COURSE = 'mleitass/turiba-devops-labs'
CHECKS = ('lint', 'unit', 'integration', 'image')
BREAK_MESSAGE = 'feat(api): log a startup banner'
BREAK_FILE = 'lab06-test-and-release/break.sh'
TAG = 'v0.2.0'
VERSION = '0.2.0'
WRITEUP = 'lab6/README.md'
HEADING = 'What broke and how I found it'
PLATFORMS = ('linux/amd64', 'linux/arm64')

TITLES = {
    'G1': 'The Lab 6 sync PR is merged',
    'G2': 'Your image job smoke-tests the image before pushing it',
    'G3': 'Break-fix: a merged PR with a red smoke test, then all four checks green',
    'G4': 'Release v0.2.0: the tag, a Release made by the workflow, api:0.2.0 for amd64 and arm64',
    'G5': 'No password or token in the repository (checked by the grader only)',
    'G6': 'lab6/README.md: "What broke and how I found it"',
}

# status is 'pass', 'fail' or 'unknown'; lines say what was found and what to do
Result = namedtuple('Result', 'gate status lines')


class ApiError(Exception):
    """A call that couldn't be made. The message is one line telling the student what to do."""


class Api:
    """GET-only access to the GitHub REST API. get() returns (status, parsed JSON or None)."""

    def __init__(self, token=None, base='https://api.github.com', opener=None):
        self.token = token
        self.base = base
        self.opener = opener or urllib.request.urlopen

    def get(self, path):
        request = urllib.request.Request(self.base + path, headers={
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'turiba-devops-lab06-check',
        })
        if self.token:
            request.add_header('Authorization', 'Bearer ' + self.token)
        try:
            with self.opener(request, timeout=20) as response:
                return response.status, _json(response.read())
        except urllib.error.HTTPError as err:
            body = _json(err.read())
            if err.code == 401:
                raise ApiError('GitHub refused your token (401). Make a new classic token, or run without one.')
            if err.code in (403, 429) and err.headers.get('x-ratelimit-remaining') == '0':
                raise ApiError("GitHub's rate limit is used up for this network. Run again with a token (see the brief, Part 4).")
            return err.code, body
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise ApiError(f'No connection to GitHub ({getattr(err, "reason", err)}). Check your internet and run again.')


def _json(raw):
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def _must(api, path, what):
    """GET that must answer 200; anything else becomes an ApiError naming `what`."""
    status, body = api.get(path)
    if status != 200 or body is None:
        raise ApiError(f'Could not read {what} (HTTP {status}). Run again in a minute.')
    return body


def _latest(runs):
    """The newest check run per name, from GitHub's check-runs list."""
    newest = {}
    for run in runs:
        name = run.get('name')
        if name not in newest or (run.get('completed_at') or '') > (newest[name].get('completed_at') or ''):
            newest[name] = run
    return newest


def _check_runs(api, repo, sha):
    body = _must(api, f'/repos/{repo}/commits/{sha}/check-runs?per_page=100', f'the checks of commit {sha[:7]}')
    return [r for r in body.get('check_runs', []) if (r.get('app') or {}).get('slug', 'github-actions') == 'github-actions']


def _failed_step(api, repo, job_id):
    job = _must(api, f'/repos/{repo}/actions/jobs/{job_id}', 'a job of your workflow')
    for step in job.get('steps') or []:
        if step.get('conclusion') == 'failure':
            return step.get('name', '')
    return None


def g1_sync(api, owner, repo, course=COURSE):
    fork = f'{owner}/{repo}'
    try:
        status, theirs = api.get(f'/repos/{course}/contents/{BREAK_FILE}?ref=main')
        if status == 404:
            return Result('G1', 'unknown', ['The course repo has no Lab 6 files yet. Wait until it is published.'])
        if status != 200:
            raise ApiError(f'Could not read the course repo (HTTP {status}). Run again in a minute.')
        status, mine = api.get(f'/repos/{fork}/contents/{BREAK_FILE}?ref=main')
    except ApiError as err:
        return Result('G1', 'unknown', [str(err)])
    if status == 404:
        return Result('G1', 'fail', ["Your main has no lab06-test-and-release/ yet: Part 0, the sync PR, merged in YOUR fork."])
    if status != 200:
        return Result('G1', 'unknown', [f'Could not read your fork (HTTP {status}). Is it public?'])
    if mine.get('sha') != theirs.get('sha'):
        return Result('G1', 'fail', ['lab06-test-and-release/break.sh differs from the course copy. Undo your change to it.'])
    return Result('G1', 'pass', [])


def g2_smoke(api, owner, repo):
    fork = f'{owner}/{repo}'
    try:
        body = _must(api, f'/repos/{fork}/actions/workflows/ci.yml/runs?branch=main&event=push&per_page=10',
                     'the ci runs on main')
        done = [r for r in body.get('workflow_runs', []) if r.get('status') == 'completed']
        if not done:
            return Result('G2', 'fail', ['No finished ci run on main yet. Merge your smoke-test PR and wait for the run.'])
        run = done[0]
        if run.get('conclusion') != 'success':
            return Result('G2', 'fail', [f"The newest ci run on main is '{run.get('conclusion')}': {run.get('html_url')}"])
        jobs = _must(api, f"/repos/{fork}/actions/runs/{run['id']}/jobs?per_page=50", 'the jobs of that run')
        image = [j for j in jobs.get('jobs', []) if j.get('name') == 'image']
        if not image:
            return Result('G2', 'fail', ["The newest ci run on main has no job named 'image'. Keep the Lab 5 job names."])
        steps = image[0].get('steps') or []
        smoke = [s for s in steps if 'smoke' in s.get('name', '').lower()]
        if not smoke:
            return Result('G2', 'fail', ["The image job has no step with 'smoke' in its name (Part 1). Name your smoke-test step that way."])
        first = min(smoke, key=lambda s: s.get('number', 0))
        if any(s.get('conclusion') != 'success' for s in smoke):
            return Result('G2', 'fail', ['A smoke step on main did not succeed. Open the run and read the step log.'])
        pushes = [s for s in steps if 'push' in s.get('name', '').lower() and 'smoke' not in s.get('name', '').lower()]
        early = [s for s in pushes if s.get('number', 0) < first.get('number', 0)]
        if early:
            return Result('G2', 'fail', [f"'{early[0].get('name')}' runs before your smoke step. Test first, then push."])
        if not pushes:
            return Result('G2', 'unknown', ["No step in the image job has 'push' in its name, so I can't tell the order. Keep the Lab 5 step name."])
        rules = _must(api, f'/repos/{fork}/rules/branches/main', 'the rules on your main')
    except ApiError as err:
        return Result('G2', 'unknown', [str(err)])
    required = set()
    for rule in rules or []:
        if rule.get('type') == 'required_status_checks':
            for item in (rule.get('parameters') or {}).get('required_status_checks', []):
                required.add(item.get('context'))
    if 'image' not in required:
        return Result('G2', 'fail', ["'image' is not a required check on main any more. Lab 5, step 4.1: the ruleset protect-main."])
    return Result('G2', 'pass', [])


def g3_breakfix(api, owner, repo):
    fork = f'{owner}/{repo}'
    try:
        pulls = _must(api, f'/repos/{fork}/pulls?state=all&base=main&per_page=100', 'your pull requests')
        # The break.sh branch first: it is almost always that one.
        pulls.sort(key=lambda p: (p.get('head') or {}).get('ref') != 'feat/startup-banner')
        found = None
        for pr in pulls:
            commits = _must(api, f"/repos/{fork}/pulls/{pr['number']}/commits?per_page=100", f"PR #{pr['number']}")
            if any(c['commit']['message'].split('\n', 1)[0].strip() == BREAK_MESSAGE for c in commits):
                found = (pr, commits)
                break
        if not found:
            return Result('G3', 'fail', [f"No PR into main has the commit '{BREAK_MESSAGE}'. Part 2: run break.sh, push, open a PR."])
        pr, commits = found
        number = pr['number']
        if not pr.get('merged_at'):
            return Result('G3', 'fail', [f'PR #{number} is not merged yet. Fix it, wait for four green checks, then merge.'])
        red = None
        problems = []
        for commit in commits[:-1]:
            latest = _latest(_check_runs(api, fork, commit['sha']))
            image = latest.get('image')
            if not image or image.get('conclusion') != 'failure':
                continue
            step = _failed_step(api, fork, image['id'])
            if step is None or 'smoke' not in step.lower():
                problems.append(f"On {commit['sha'][:7]} image failed in '{step}', not in your smoke step.")
                continue
            others = [n for n in ('lint', 'unit', 'integration') if (latest.get(n) or {}).get('conclusion') != 'success']
            if others:
                problems.append(f"On {commit['sha'][:7]} {', '.join(others)} weren't green too. The break only stops the image.")
                continue
            red = commit
            break
        if not red:
            return Result('G3', 'fail', problems or [f'In PR #{number}, image never failed in the smoke step. Was the smoke test on main before you ran break.sh?'])
        last = _latest(_check_runs(api, fork, commits[-1]['sha']))
        missing = [n for n in CHECKS if (last.get(n) or {}).get('conclusion') != 'success']
        if missing:
            return Result('G3', 'fail', [f"The last commit of PR #{number} isn't green on: {', '.join(missing)}."])
        if pr['merged_at'] < max(last[n].get('completed_at') or '' for n in CHECKS):
            return Result('G3', 'fail', [f'PR #{number} was merged before its last checks finished.'])
    except ApiError as err:
        return Result('G3', 'unknown', [str(err)])
    return Result('G3', 'pass', [])


def ghcr_platforms(owner_lc, repo_lc, tag, opener=None):
    """The platforms of ghcr.io/OWNER/REPO/api:TAG, pulled without logging in. None if it can't be pulled."""
    opener = opener or urllib.request.urlopen
    name = f'{owner_lc}/{repo_lc}/api'
    try:
        scope = urllib.parse.quote(f'repository:{name}:pull', safe='')
        with opener(f'https://ghcr.io/token?scope={scope}&service=ghcr.io', timeout=20) as response:
            token = json.loads(response.read())['token']
        request = urllib.request.Request(f'https://ghcr.io/v2/{name}/manifests/{tag}', headers={
            'Authorization': 'Bearer ' + token,
            'Accept': ', '.join([
                'application/vnd.oci.image.index.v1+json',
                'application/vnd.docker.distribution.manifest.list.v2+json',
                'application/vnd.oci.image.manifest.v1+json',
                'application/vnd.docker.distribution.manifest.v2+json',
            ]),
        })
        with opener(request, timeout=20) as response:
            manifest = json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return None
    platforms = set()
    for item in manifest.get('manifests') or []:
        platform = item.get('platform') or {}
        if platform.get('os') not in (None, 'unknown'):
            platforms.add(f"{platform.get('os')}/{platform.get('architecture')}")
    return platforms if manifest.get('manifests') else {'(one platform only)'}


def g4_release(api, owner, repo, platforms_fn=ghcr_platforms):
    fork = f'{owner}/{repo}'
    image = f'ghcr.io/{owner.lower()}/{repo.lower()}/api:{VERSION}'
    try:
        status, _ = api.get(f'/repos/{fork}/git/ref/tags/{TAG}')
        if status == 404:
            return Result('G4', 'fail', [f'No tag {TAG} on GitHub. Part 3: git tag {TAG}, then git push origin {TAG}.'])
        runs = _must(api, f'/repos/{fork}/actions/runs?event=push&branch={TAG}&per_page=20', f'the runs for {TAG}')
        tag_runs = [r for r in runs.get('workflow_runs', []) if r.get('head_branch') == TAG]
        if not tag_runs:
            return Result('G4', 'fail', [f'No workflow ran for {TAG}. Was the release workflow on main before you pushed the tag?'])
        if not any(r.get('conclusion') == 'success' for r in tag_runs):
            return Result('G4', 'fail', [f"The release run for {TAG} didn't succeed: {tag_runs[0].get('html_url')}"])
        status, release = api.get(f'/repos/{fork}/releases/tags/{TAG}')
    except ApiError as err:
        return Result('G4', 'unknown', [str(err)])
    if status == 404:
        return Result('G4', 'fail', [f'No GitHub Release for {TAG}. Your release workflow has to create it.'])
    if status != 200 or release is None:
        return Result('G4', 'unknown', [f'Could not read the release (HTTP {status}). Run again in a minute.'])
    problems = []
    if release.get('draft'):
        problems.append(f'Release {TAG} is still a draft.')
    author = (release.get('author') or {}).get('login')
    if author != 'github-actions[bot]':
        problems.append(f'Release {TAG} was made by {author}, not by your workflow. Delete it and let the workflow make it.')
    if 'Full Changelog' not in (release.get('body') or ''):
        problems.append(f'Release {TAG} has no generated notes (--generate-notes, or the action\'s option for it).')
    found = platforms_fn(owner.lower(), repo.lower(), VERSION)
    if found is None:
        problems.append(f"{image} can't be pulled without logging in. Did the release run push it? Is the package public?")
    else:
        lacking = [p for p in PLATFORMS if p not in found]
        if lacking:
            problems.append(f"{image} has no {', '.join(lacking)} (found: {', '.join(sorted(found)) or 'none'}).")
    return Result('G4', 'fail' if problems else 'pass', problems)


def section(text, heading):
    """The body under the first heading that contains `heading`, up to the next heading of the same or higher level."""
    lines = text.replace('\r\n', '\n').split('\n')
    for i, line in enumerate(lines):
        match = re.match(r'^(#{1,6})\s+(.*)$', line)
        if match and heading.lower() in match.group(2).lower():
            level = len(match.group(1))
            body = []
            for rest in lines[i + 1:]:
                other = re.match(r'^(#{1,6})\s', rest)
                if other and len(other.group(1)) <= level:
                    break
                body.append(rest)
            return '\n'.join(body)
    return None


def g6_writeup(api, owner, repo):
    fork = f'{owner}/{repo}'
    try:
        status, body = api.get(f'/repos/{fork}/contents/{WRITEUP}?ref=main')
    except ApiError as err:
        return Result('G6', 'unknown', [str(err)])
    if status == 404:
        return Result('G6', 'fail', [f'No {WRITEUP} on main. Part 4: copy the write-up template and fill it in.'])
    if status != 200 or not body or 'content' not in body:
        return Result('G6', 'unknown', [f'Could not read {WRITEUP} (HTTP {status}).'])
    text = base64.b64decode(body['content']).decode('utf-8', errors='replace')
    part = section(text, HEADING)
    if part is None:
        return Result('G6', 'fail', [f'{WRITEUP} has no heading "{HEADING}". Keep the template\'s headings.'])
    if '____' in part or not re.sub(r'<!--.*?-->', '', part, flags=re.S).strip():
        return Result('G6', 'fail', [f'The section "{HEADING}" still has blanks (____).'])
    return Result('G6', 'pass', [])


def run_all(api, owner, repo, course=COURSE, platforms_fn=ghcr_platforms):
    return [
        g1_sync(api, owner, repo, course),
        g2_smoke(api, owner, repo),
        g3_breakfix(api, owner, repo),
        g4_release(api, owner, repo, platforms_fn),
        g6_writeup(api, owner, repo),
    ]


def repo_from_origin():
    """OWNER/NAME from `git remote get-url origin`, or None."""
    try:
        url = subprocess.run(['git', 'remote', 'get-url', 'origin'], capture_output=True, text=True,
                             timeout=10, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'github\.com[:/]+([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?$', url)
    return f'{match.group(1)}/{match.group(2)}' if match else None


def find_token(from_stdin):
    if from_stdin:
        return sys.stdin.readline().strip() or None
    if os.environ.get('GITHUB_TOKEN'):
        return os.environ['GITHUB_TOKEN'].strip()
    try:
        out = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    if sys.stdin.isatty():
        return getpass.getpass('GitHub token (hidden; press Enter to go on without one): ').strip() or None
    return None


SYMBOL = {'pass': '✔', 'fail': '✘', 'unknown': '?'}


def report(fork, results, token_used, out=sys.stdout):
    print(f"\nLab 6 self-check for {fork}{'' if token_used else ' (no token: slower, and a shared network may hit the limit)'}\n", file=out)
    for result in results:
        print(f"  {SYMBOL[result.status]} {result.gate}  {TITLES[result.gate]}", file=out)
        for line in result.lines:
            print(f'        {line}', file=out)
    print(f"  · G5  {TITLES['G5']}", file=out)
    passed = sum(r.status == 'pass' for r in results)
    print(f'\n{passed} of {len(results)} gates pass.', file=out)
    if passed == len(results):
        print('Everything the script can check is done. Submit your fork URL on Evaluentis.', file=out)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='check.sh', description='Lab 6 self-check: reads your fork, changes nothing.')
    parser.add_argument('--repo', help='your fork as OWNER/NAME (default: taken from git remote origin)')
    parser.add_argument('--token-stdin', action='store_true', help='read a GitHub token from standard input')
    parser.add_argument('--course', default=COURSE, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    fork = args.repo or repo_from_origin()
    if not fork or not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9._-]+', fork):
        print('✘ I could not tell which fork to check. Run it in your clone, or add --repo <you>/turiba-devops-labs')
        return 2
    if fork.lower() == COURSE.lower():
        print("✘ origin points to the course repo, not to your fork. Add --repo <you>/turiba-devops-labs")
        return 2
    owner, repo = fork.split('/')
    token = find_token(args.token_stdin)
    results = run_all(Api(token), owner, repo, args.course)
    report(fork, results, bool(token))
    return 0 if all(r.status == 'pass' for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
