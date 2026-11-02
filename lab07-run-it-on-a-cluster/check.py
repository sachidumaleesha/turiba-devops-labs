"""check.py: the Lab 7 self-check. Run it through check.sh, not directly.

It reads your fork through the GitHub REST API, takes the k8s/ folder from your main branch, and does
what the grader does: a fresh kind cluster called lab7-check, ONE `kubectl apply -f k8s/`, the rollout,
and GET / through the Service. Then it deletes that cluster. Your own cluster and your kubectl context
are not touched: the check cluster gets its own kubeconfig file.

Python 3 standard library, plus the kind and kubectl commands.
"""
import argparse
import base64
import getpass
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple

COURSE = 'mleitass/turiba-devops-labs'
LAB_DIR = 'lab07-run-it-on-a-cluster'
BREAK_FILE = f'{LAB_DIR}/break.sh'
BREAK_MESSAGE = 'chore(k8s): tidy up the manifests'
K8S_FILES = ('00-namespace.yaml', 'api-deployment.yaml', 'api-service.yaml')
NAMESPACE = 'course'
FALLBACK_IMAGE = 'ghcr.io/martinsturiba/turiba-devops-labs/api:0.2.0'
CLUSTER = 'lab7-check'
CONTEXT = f'kind-{CLUSTER}'
LOCAL_PORT = 18080
WRITEUP = 'lab7/README.md'
HEADINGS = ('Roll and roll back', 'What broke and how I found it')
ALLOWED_KINDS = ('Namespace', 'Deployment', 'Service')

TITLES = {
    'G1': 'The Lab 7 sync PR is merged',
    'G2': 'k8s/ on main: the three files, the names, your image, the ports',
    'G3': 'One apply on a fresh cluster: 3 Pods ready, GET / answers through the Service',
    'G4': 'Break-fix: a merged PR with the teammate\'s commit and your fixes',
    'G5': 'No password or token in the repository (checked by the grader only)',
    'G6': 'lab7/README.md: "Roll and roll back" and "What broke and how I found it"',
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
            'User-Agent': 'turiba-devops-lab07-check',
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
                raise ApiError("GitHub's rate limit is used up for this network. Run again with a token (see the brief, Part 5).")
            return err.code, body
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise ApiError(f'No connection to GitHub ({getattr(err, "reason", err)}). Check your internet and run again.')


def _json(raw):
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def _must(api, path, what):
    status, body = api.get(path)
    if status != 200 or body is None:
        raise ApiError(f'Could not read {what} (HTTP {status}). Run again in a minute.')
    return body


def run(cmd, timeout=300):
    """Run a command; (exit code, stdout + stderr). A missing program is exit code 127."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return done.returncode, (done.stdout or '') + (done.stderr or '')
    except FileNotFoundError:
        return 127, f'{cmd[0]}: command not found'
    except subprocess.TimeoutExpired:
        return 124, f'{" ".join(cmd[:3])}: timed out after {timeout} s'


def parse_json_stream(text):
    """kubectl prints one JSON object per document, one after the other. A List is flattened."""
    decoder, objs, i = json.JSONDecoder(), [], 0
    while True:
        while i < len(text) and text[i] in ' \t\r\n':
            i += 1
        if i >= len(text):
            return objs
        obj, i = decoder.raw_decode(text, i)
        objs.extend(obj.get('items', []) if obj.get('kind') == 'List' else [obj])


def find(objs, kind, name):
    for obj in objs:
        if obj.get('kind') == kind and (obj.get('metadata') or {}).get('name') == name:
            return obj
    return None


def shape_problems(objs):
    """What the grader refuses to apply. Empty list = OK. Never a reason for 0 points by itself."""
    problems = []
    for obj in objs:
        kind = obj.get('kind')
        meta = obj.get('metadata') or {}
        where = f"{kind} {meta.get('name')}"
        if kind not in ALLOWED_KINDS:
            problems.append(f'{where}: only {", ".join(ALLOWED_KINDS)} belong in k8s/ for Lab 7.')
            continue
        if kind != 'Namespace' and meta.get('namespace') != NAMESPACE:
            problems.append(f'{where}: put it in namespace {NAMESPACE} (metadata.namespace).')
        if kind == 'Service' and (obj.get('spec') or {}).get('type', 'ClusterIP') != 'ClusterIP':
            problems.append(f'{where}: type must be ClusterIP; reach it with kubectl port-forward.')
        if kind == 'Deployment':
            pod = ((obj.get('spec') or {}).get('template') or {}).get('spec') or {}
            for key in ('hostNetwork', 'hostPID', 'hostIPC'):
                if pod.get(key):
                    problems.append(f'{where}: {key} is not allowed.')
            if any('hostPath' in (v or {}) for v in pod.get('volumes') or []):
                problems.append(f'{where}: hostPath volumes are not allowed.')
            for c in (pod.get('containers') or []) + (pod.get('initContainers') or []):
                if ((c.get('securityContext') or {}).get('privileged')):
                    problems.append(f"{where}: container {c.get('name')} must not be privileged.")
                if any(p.get('hostPort') for p in c.get('ports') or []):
                    problems.append(f"{where}: hostPort is not allowed.")
    return problems


def image_ok(image, owner, repo):
    """'' if the image reference is one Lab 7 accepts, else the reason."""
    if image == FALLBACK_IMAGE:
        return ''
    expected = f'ghcr.io/{owner.lower()}/{repo.lower()}/api:'
    if not image.startswith(expected):
        return f'image is "{image}"; use {expected}<tag> (lowercase), or the fallback {FALLBACK_IMAGE}.'
    tag = image[len(expected):]
    if not tag or tag == 'latest' or '@' in tag:
        return f'image tag is "{tag or "(none)"}"; pin a version such as 0.2.0, never latest.'
    return ''


def ghcr_platforms(image, opener=None):
    """Platforms of ghcr.io/NAME:TAG, pulled without logging in. None if it can't be pulled."""
    opener = opener or urllib.request.urlopen
    match = re.fullmatch(r'ghcr\.io/([^:@]+):([\w][\w.-]*)', image)
    if not match:
        return None
    name, tag = match.groups()
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
    if not manifest.get('manifests'):
        return {'(one platform only)'}
    return {f"{(m.get('platform') or {}).get('os')}/{(m.get('platform') or {}).get('architecture')}"
            for m in manifest['manifests'] if (m.get('platform') or {}).get('os') not in (None, 'unknown')}


def fetch_k8s(api, owner, repo, dest):
    """Copy k8s/*.yaml|yml from the fork's main into dest. Returns the file names (sorted)."""
    fork = f'{owner}/{repo}'
    status, listing = api.get(f'/repos/{fork}/contents/k8s?ref=main')
    if status == 404:
        return []
    if status != 200 or not isinstance(listing, list):
        raise ApiError(f'Could not read k8s/ on your main (HTTP {status}).')
    names = []
    for entry in listing:
        name = entry.get('name', '')
        if entry.get('type') == 'file' and name.endswith(('.yaml', '.yml')):
            body = _must(api, f'/repos/{fork}/contents/k8s/{urllib.parse.quote(name)}?ref=main', f'k8s/{name}')
            with open(os.path.join(dest, name), 'wb') as f:
                f.write(base64.b64decode(body.get('content', '')))
            names.append(name)
    return sorted(names)


def g1_sync(api, owner, repo, course=COURSE):
    fork = f'{owner}/{repo}'
    try:
        status, theirs = api.get(f'/repos/{course}/contents/{BREAK_FILE}?ref=main')
        if status == 404:
            return Result('G1', 'unknown', ['The course repo has no Lab 7 files yet. Wait until it is published.'])
        if status != 200:
            raise ApiError(f'Could not read the course repo (HTTP {status}). Run again in a minute.')
        status, mine = api.get(f'/repos/{fork}/contents/{BREAK_FILE}?ref=main')
    except ApiError as err:
        return Result('G1', 'unknown', [str(err)])
    if status == 404:
        return Result('G1', 'fail', [f'Your main has no {LAB_DIR}/ yet: Part 0, the sync PR, merged in YOUR fork.'])
    if status != 200:
        return Result('G1', 'unknown', [f'Could not read your fork (HTTP {status}). Is it public?'])
    if mine.get('sha') != theirs.get('sha'):
        return Result('G1', 'fail', [f'{BREAK_FILE} differs from the course copy. Undo your change to it.'])
    return Result('G1', 'pass', [])


def g2_manifests(files, objs, owner, repo, platforms_fn=ghcr_platforms):
    """files: names in k8s/ on main; objs: the objects kubectl read from them (None if it couldn't)."""
    missing = [f for f in K8S_FILES if f not in files]
    if missing:
        return Result('G2', 'fail', [f"k8s/ on main has no {', '.join(missing)}. Part 1 names the three files."])
    if objs is None:
        return Result('G2', 'unknown', ['kubectl could not read your files. The fresh-cluster step (G3) shows the error.'])
    problems = shape_problems(objs)
    if not find(objs, 'Namespace', NAMESPACE):
        problems.append(f'No Namespace {NAMESPACE}.')
    dep, svc = find(objs, 'Deployment', 'api'), find(objs, 'Service', 'api')
    if not dep:
        problems.append('No Deployment named api.')
    else:
        spec = dep.get('spec') or {}
        template = spec.get('template') or {}
        pod_labels = (template.get('metadata') or {}).get('labels') or {}
        if spec.get('replicas') != 3:
            problems.append(f"Deployment api: replicas is {spec.get('replicas')}, not 3.")
        if ((spec.get('selector') or {}).get('matchLabels') or {}) != {'app': 'api'}:
            problems.append('Deployment api: spec.selector.matchLabels must be exactly app: api.')
        if pod_labels.get('app') != 'api':
            problems.append('Deployment api: the Pod template needs the label app: api.')
        containers = (template.get('spec') or {}).get('containers') or []
        api_c = [c for c in containers if c.get('name') == 'api']
        if len(containers) != 1 or not api_c:
            problems.append('Deployment api: one container, named api.')
        else:
            reason = image_ok(api_c[0].get('image', ''), owner, repo)
            if reason:
                problems.append('Deployment api: ' + reason)
            else:
                found = platforms_fn(api_c[0]['image'])
                if found is None:
                    problems.append(f"Deployment api: {api_c[0]['image']} can't be pulled without logging in. Does the tag exist? Is the package public?")
                elif 'linux/amd64' not in found:
                    problems.append(f"Deployment api: {api_c[0]['image']} has no linux/amd64 (the grader's cluster).")
            if 5000 not in [p.get('containerPort') for p in api_c[0].get('ports') or []]:
                problems.append('Deployment api: containerPort 5000 (the port the API listens on).')
    if not svc:
        problems.append('No Service named api.')
    else:
        spec = svc.get('spec') or {}
        if (spec.get('selector') or {}) != {'app': 'api'}:
            problems.append(f"Service api: selector is {spec.get('selector')}; it must be exactly app: api.")
        ports = spec.get('ports') or []
        if not any(p.get('port') == 80 and p.get('targetPort') == 5000 for p in ports):
            shown = [(p.get('port'), p.get('targetPort')) for p in ports]
            problems.append(f'Service api: needs port 80 → targetPort 5000 (a number, unquoted); found {shown}.')
    return Result('G2', 'fail' if problems else 'pass', problems)


class Cluster:
    """The throwaway kind cluster. Every kubectl call names its own kubeconfig and context."""

    def __init__(self, workdir, runner=run):
        self.kubeconfig = os.path.join(workdir, 'kubeconfig')
        self.run = runner

    def kubectl(self, *args, timeout=300):
        return self.run(['kubectl', '--kubeconfig', self.kubeconfig, '--context', CONTEXT, *args], timeout)

    def create(self):
        self.run(['kind', 'delete', 'cluster', '--name', CLUSTER, '--kubeconfig', self.kubeconfig], 120)
        return self.run(['kind', 'create', 'cluster', '--name', CLUSTER, '--kubeconfig', self.kubeconfig, '--wait', '90s'], 300)

    def delete(self):
        return self.run(['kind', 'delete', 'cluster', '--name', CLUSTER, '--kubeconfig', self.kubeconfig], 120)

    def read(self, k8s_dir):
        code, out = self.kubectl('create', '--dry-run=client', '-o', 'json', '-f', k8s_dir)
        if code != 0:
            return None, out
        try:
            return parse_json_stream(out[out.index('{'):] if '{' in out else ''), ''
        except ValueError as err:
            return None, str(err)

    def get_root(self):
        """GET / through `kubectl port-forward service/api`. Returns the body, or '' if nothing answered."""
        cmd = ['kubectl', '--kubeconfig', self.kubeconfig, '--context', CONTEXT, '-n', NAMESPACE,
               'port-forward', 'service/api', f'{LOCAL_PORT}:80']
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            return ''
        try:
            for _ in range(15):
                time.sleep(1)
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{LOCAL_PORT}/', timeout=3) as response:
                        return response.read().decode('utf-8', errors='replace')
                except (urllib.error.URLError, OSError):
                    continue
            return ''
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def first_error(out):
    lines = [l for l in out.splitlines() if 'error' in l.lower() or 'Error' in l]
    return (lines or out.splitlines() or ['(no output)'])[0][:300]


def g3_fresh(cluster, k8s_dir):
    code, out = cluster.kubectl('apply', '-f', k8s_dir)
    if code != 0:
        lines = ['One `kubectl apply -f k8s/` on a fresh cluster failed: ' + first_error(out)]
        if f'namespaces "{NAMESPACE}" not found' in out:
            lines.append('The Namespace came too late: files are applied in name order. Call it 00-namespace.yaml (slide 10).')
        return Result('G3', 'fail', lines)
    code, out = cluster.kubectl('-n', NAMESPACE, 'rollout', 'status', 'deployment/api', '--timeout=180s', timeout=200)
    if code != 0:
        _, pods = cluster.kubectl('-n', NAMESPACE, 'get', 'pods', '--no-headers')
        states = sorted({line.split()[2] for line in pods.splitlines() if len(line.split()) > 2})
        return Result('G3', 'fail', [f"The rollout didn't finish in 180 s. Pod states: {', '.join(states) or 'none'}. "
                                     'Run the debug loop on your own cluster (slide 13).'])
    body = cluster.get_root()
    if '"course-api"' not in body:
        return Result('G3', 'fail', ['3 Pods are ready, but GET / through the Service got no answer. '
                                     'Compare the Service selector with the Pod labels, and targetPort with 5000.'])
    return Result('G3', 'pass', [])


def g4_breakfix(api, owner, repo, g2_status):
    fork = f'{owner}/{repo}'
    try:
        pulls = _must(api, f'/repos/{fork}/pulls?state=all&base=main&per_page=100', 'your pull requests')
        pulls.sort(key=lambda p: (p.get('head') or {}).get('ref') != 'chore/tidy-manifests')
        for pr in pulls:
            commits = _must(api, f"/repos/{fork}/pulls/{pr['number']}/commits?per_page=100", f"PR #{pr['number']}")
            heads = [c['commit']['message'].split('\n', 1)[0].strip() for c in commits]
            if BREAK_MESSAGE not in heads:
                continue
            number, later = pr['number'], commits[heads.index(BREAK_MESSAGE) + 1:]
            if not pr.get('merged_at'):
                return Result('G4', 'fail', [f'PR #{number} is not merged yet. Fix all three faults on it, then merge.'])
            touching = 0
            for commit in later:
                detail = _must(api, f"/repos/{fork}/commits/{commit['sha']}", 'a commit')
                touching += any(f.get('filename', '').startswith('k8s/') for f in detail.get('files') or [])
            if not touching:
                return Result('G4', 'fail', [f'PR #{number} has no commit after the teammate\'s that changes k8s/. Fix it in your own commits.'])
            if g2_status != 'pass':
                return Result('G4', 'fail', [f'PR #{number} is merged, but k8s/ on main still fails G2: a fault is left.'])
            return Result('G4', 'pass', [])
    except ApiError as err:
        return Result('G4', 'unknown', [str(err)])
    return Result('G4', 'fail', [f"No PR into main has the commit '{BREAK_MESSAGE}'. Part 4: run break.sh, push, open a PR."])


def section(text, heading):
    lines = text.replace('\r\n', '\n').split('\n')
    for i, line in enumerate(lines):
        match = re.match(r'^(#{1,6})\s+(.*)$', line)
        if match and heading.lower() in match.group(2).lower():
            level, body = len(match.group(1)), []
            for rest in lines[i + 1:]:
                other = re.match(r'^(#{1,6})\s', rest)
                if other and len(other.group(1)) <= level:
                    break
                body.append(rest)
            return '\n'.join(body)
    return None


def g6_writeup(api, owner, repo):
    try:
        status, body = api.get(f'/repos/{owner}/{repo}/contents/{WRITEUP}?ref=main')
    except ApiError as err:
        return Result('G6', 'unknown', [str(err)])
    if status == 404:
        return Result('G6', 'fail', [f'No {WRITEUP} on main. Part 5: copy the write-up template and fill it in.'])
    if status != 200 or not body or 'content' not in body:
        return Result('G6', 'unknown', [f'Could not read {WRITEUP} (HTTP {status}).'])
    text = base64.b64decode(body['content']).decode('utf-8', errors='replace')
    problems = []
    for heading in HEADINGS:
        part = section(text, heading)
        if part is None:
            problems.append(f'{WRITEUP} has no heading "{heading}". Keep the template\'s headings.')
        elif '____' in part or not re.sub(r'<!--.*?-->', '', part, flags=re.S).strip():
            problems.append(f'The section "{heading}" still has blanks (____).')
    return Result('G6', 'fail' if problems else 'pass', problems)


def repo_from_origin():
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
    print(f"\nLab 7 self-check for {fork}{'' if token_used else ' (no token: slower, and a shared network may hit the limit)'}\n", file=out)
    for result in sorted(results, key=lambda r: r.gate):
        print(f"  {SYMBOL[result.status]} {result.gate}  {TITLES[result.gate]}", file=out)
        for line in result.lines:
            print(f'        {line}', file=out)
    print(f"  · G5  {TITLES['G5']}", file=out)
    passed = sum(r.status == 'pass' for r in results)
    print(f'\n{passed} of {len(results)} gates pass.', file=out)
    if passed == len(results):
        print('Everything the script can check is done. Submit your fork URL on Evaluentis.', file=out)


def check_all(api, owner, repo, course, fresh, runner=run, platforms_fn=ghcr_platforms, log=print):
    results = [g1_sync(api, owner, repo, course), g6_writeup(api, owner, repo)]
    workdir = tempfile.mkdtemp(prefix='lab7-check-')
    k8s_dir = os.path.join(workdir, 'k8s')
    os.mkdir(k8s_dir)
    cluster = Cluster(workdir, runner)
    created = False
    try:
        try:
            files = fetch_k8s(api, owner, repo, k8s_dir)
        except ApiError as err:
            return results + [Result(g, 'unknown', [str(err)]) for g in ('G2', 'G3', 'G4')]
        if not files:
            missing = Result('G2', 'fail', ['There is no k8s/ folder on your main yet. Part 1: through a PR.'])
            return results + [missing, Result('G3', 'fail', ['Nothing to apply yet.']), g4_breakfix(api, owner, repo, 'fail')]
        if fresh:
            log(f'Creating the throwaway cluster {CLUSTER} (1–2 minutes)…')
            code, out = cluster.create()
            created = True
            if code != 0:
                bad = Result('G3', 'unknown', [f'kind could not create {CLUSTER}: {first_error(out)}'])
                g2 = g2_manifests(files, None, owner, repo, platforms_fn)
                return results + [g2, bad, g4_breakfix(api, owner, repo, g2.status)]
            objs, err = cluster.read(k8s_dir)
            g2 = g2_manifests(files, objs, owner, repo, platforms_fn)
            if objs is None:
                g3 = Result('G3', 'fail', ['kubectl could not read your files: ' + first_error(err)])
            elif shape_problems(objs):
                g3 = Result('G3', 'unknown', ['Not applied: fix the G2 problems marked "not allowed" first. The grader refuses the same.'])
            else:
                log('Applying k8s/ once and waiting for the rollout…')
                g3 = g3_fresh(cluster, k8s_dir)
        else:
            code, out = run(['kubectl', 'create', '--dry-run=client', '-o', 'json', '-f', k8s_dir])
            objs = parse_json_stream(out[out.index('{'):]) if code == 0 and '{' in out else None
            g2 = g2_manifests(files, objs, owner, repo, platforms_fn)
            g3 = Result('G3', 'unknown', ['Skipped (--no-fresh). Run without it before you submit.'])
        return results + [g2, g3, g4_breakfix(api, owner, repo, g2.status)]
    finally:
        if created:
            log(f'Deleting {CLUSTER}…')
            cluster.delete()
        shutil.rmtree(workdir, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='check.sh', description='Lab 7 self-check: reads your fork, tests k8s/ on a throwaway cluster.')
    parser.add_argument('--repo', help='your fork as OWNER/NAME (default: taken from git remote origin)')
    parser.add_argument('--token-stdin', action='store_true', help='read a GitHub token from standard input')
    parser.add_argument('--no-fresh', action='store_true', help="don't create the throwaway cluster (G3 is skipped)")
    parser.add_argument('--course', default=COURSE, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    fork = args.repo or repo_from_origin()
    if not fork or not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9._-]+', fork):
        print('✘ I could not tell which fork to check. Run it in your clone, or add --repo <you>/turiba-devops-labs')
        return 2
    if fork.lower() == COURSE.lower():
        print("✘ origin points to the course repo, not to your fork. Add --repo <you>/turiba-devops-labs")
        return 2
    if not args.no_fresh:
        for tool in ('kind', 'kubectl', 'docker'):
            if shutil.which(tool) is None:
                print(f'✘ {tool} is missing. See "Before Lab 7" in the course README, or add --no-fresh.')
                return 2
        print(f'This creates a second kind cluster, {CLUSTER}, for 1–2 minutes (about 1.5 GB of memory),\n'
              'then deletes it. Your own cluster and kubectl context are not touched. --no-fresh skips it.')
    owner, repo = fork.split('/')
    token = find_token(args.token_stdin)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(130))
    try:
        results = check_all(Api(token), owner, repo, args.course, not args.no_fresh)
    except KeyboardInterrupt:
        print(f'\nStopped. If {CLUSTER} is still there: kind delete cluster --name {CLUSTER}')
        return 130
    report(fork, results, bool(token))
    return 0 if all(r.status == 'pass' for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
