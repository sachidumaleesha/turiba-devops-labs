"""check.py: the Lab 9 self-check. Run it through check.sh, not directly.

It reads your fork through the GitHub REST API, takes charts/course-app/ from your main branch, and does what
the grader does: `helm lint` and `helm template`, then a fresh kind cluster called lab9-check with the
Namespace course and a Secret db-secret made by the script, ONE `helm install`, the rollouts, a todo saved
through the API, the database Pod deleted and the todo read back, then `helm upgrade --set api.replicas=2`
and `helm rollback course-app 1`. Then it deletes that cluster. Your own cluster and your kubectl context are
not touched: the check cluster gets its own kubeconfig file.

Python 3 standard library, plus the kind, kubectl and helm commands.
"""
import argparse
import base64
import contextlib
import getpass
import json
import os
import re
import secrets
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
LAB_DIR = 'lab09-package-it'
BREAK_FILE = f'{LAB_DIR}/break.sh'
BREAK_BRANCH = 'chore/tidy-chart'
BREAK_MESSAGE = 'chore(chart): tidy up values and templates'
CHART = 'charts/course-app'
CHART_NAME = 'course-app'
TEMPLATES = ('app-config.yaml', 'db-pvc.yaml', 'db-deployment.yaml', 'db-service.yaml',
             'api-deployment.yaml', 'api-service.yaml')
EXTRA_OK = ('NOTES.txt', '_helpers.tpl')
RELEASE = 'course-app'
NAMESPACE = 'course'
FALLBACK_IMAGES = (
    'ghcr.io/martinsturiba/turiba-devops-labs/api:0.2.0',
    'ghcr.io/martinsturiba/turiba-devops-labs/api:a24ab0775c358e9a3fe77bfc8bc0379148a5af1b',
)
DB_IMAGE = 'postgres:17-alpine'
DB_MOUNT = '/var/lib/postgresql/data'
CONFIG = {'DB_HOST': 'db', 'DB_PORT': '5432', 'DB_USER': 'todo', 'DB_NAME': 'todo'}
CONFIGMAP = 'app-config'
SECRET, SECRET_KEY = 'db-secret', 'password'
PVC = 'db-data'
INIT = 'wait-for-db'
PROBE_PATHS = ('/healthz', '/')
DEFAULT_REPLICAS = 3
# `helm template --set …` with these values must show up in the api Deployment: proof that the template uses them.
PROBE_SET = (('api.replicas', '2'), ('api.image.repository', 'example.com/lab9/api'), ('api.image.tag', 'lab9-probe'))
PROBE_IMAGE, PROBE_REPLICAS = 'example.com/lab9/api:lab9-probe', 2
UPGRADE_REPLICAS = 2
CLUSTER = 'lab9-check'
CONTEXT = f'kind-{CLUSTER}'
LOCAL_PORT = 18090
WRITEUP = 'lab9/README.md'
HEADINGS = ('Install, upgrade, rollback', 'What broke and how I found it')
CHART_KINDS = ('ConfigMap', 'PersistentVolumeClaim', 'Deployment', 'Service')
# Wrong in a chart, but the grader can still install it and show what goes wrong (a G2 problem, not a refusal).
WRONG_KINDS = ('Namespace', 'Secret')
MAX_FILES, MAX_BYTES = 40, 300_000

TITLES = {
    'G1': 'The Lab 9 sync PR is merged',
    'G2': 'charts/course-app on main: lint, the values, the objects',
    'G3': 'helm install on a fresh cluster works, the data survives, upgrade and rollback work',
    'G4': 'Break-fix: a merged PR with the teammate\'s commit and your fixes',
    'G5': 'No password or token in the repository (checked by the grader only)',
    'G6': 'lab9/README.md: "Install, upgrade, rollback" and "What broke and how I found it"',
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
            'User-Agent': 'turiba-devops-lab09-check',
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


def pod_spec(dep):
    return (((dep or {}).get('spec') or {}).get('template') or {}).get('spec') or {}


def first_error(out):
    lines = [l for l in out.splitlines() if 'error' in l.lower()]
    return (lines or out.splitlines() or ['(no output)'])[0].strip()[:300]


# --- Fetching and rendering the chart ----------------------------------------------------------------

def fetch_chart(api, owner, repo, dest):
    """Copy charts/course-app/ from the fork's main into dest. Returns the paths inside the chart (sorted)."""
    fork = f'{owner}/{repo}'
    status, tree = api.get(f'/repos/{fork}/git/trees/main?recursive=1')
    if status in (404, 409):
        return []
    if status != 200 or not isinstance(tree, dict):
        raise ApiError(f'Could not read the files on your main (HTTP {status}).')
    prefix = CHART + '/'
    blobs = [e for e in tree.get('tree') or []
             if e.get('type') == 'blob' and e.get('mode') != '120000' and str(e.get('path', '')).startswith(prefix)]
    if len(blobs) > MAX_FILES or sum(e.get('size') or 0 for e in blobs) > MAX_BYTES:
        raise ApiError(f'{CHART}/ on your main has more than {MAX_FILES} files or {MAX_BYTES // 1000} kB. '
                       'It should hold Chart.yaml, values.yaml and templates/ only.')
    names = []
    for entry in blobs:
        rel = entry['path'][len(prefix):]
        parts = rel.split('/')
        if any(p in ('', '.', '..') for p in parts):
            continue
        body = _must(api, f"/repos/{fork}/git/blobs/{entry['sha']}", entry['path'])
        target = os.path.join(dest, *parts)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'wb') as f:
            f.write(base64.b64decode(body.get('content', '')))
        names.append(rel)
    return sorted(names)


def render(runner, chart_dir, out_dir, sets=()):
    """`helm template` into out_dir (one file per template). (exit code, output)."""
    shutil.rmtree(out_dir, ignore_errors=True)
    cmd = ['helm', 'template', RELEASE, chart_dir, '--namespace', NAMESPACE, '--output-dir', out_dir]
    for key, value in sets:
        cmd += ['--set', f'{key}={value}']
    return runner(cmd, 120)


def helm_error(out):
    """The line of Helm's output that says what is wrong, with the indented lines that continue it."""
    lines = [l.rstrip() for l in out.splitlines() if l.strip()]
    for marker in ('[ERROR]', 'Error:', 'error'):
        hits = [i for i, l in enumerate(lines) if marker in l]
        if hits:
            i = hits[0]
            more = []
            for rest in lines[i + 1:i + 3]:
                if not rest[:1].isspace():
                    break
                more.append(rest.strip())
            return ' '.join([lines[i].strip()] + more)[:400]
    return (lines or ['(no output)'])[0].strip()[:400]


def helm_hints(out):
    """Extra lines that turn a Helm error into a next step."""
    hints = []
    if 'nil pointer evaluating' in out:
        hints.append('A template asks for a value that values.yaml doesn\'t have. The error names the file, the line '
                     'and the value: compare it with values.yaml, letter by letter.')
    if 'invalid ownership metadata' in out or 'cannot be imported into the current release' in out:
        hints.append('The chart tries to create an object that already exists and isn\'t Helm\'s: the Namespace '
                     'course or the Secret db-secret. Both stay outside the chart (Part 1).')
    if 'mapping values are not allowed' in out or 'did not find expected' in out or 'could not find expected' in out:
        hints.append('A template renders broken YAML. Run helm template and read the lines around the one named.')
    if "doesn't match" in out or 'must match' in out:
        hints.append('Chart.yaml name must be course-app, the same as the folder.')
    return hints


# --- G1 -------------------------------------------------------------------------------------------

def g1_sync(api, owner, repo, course=COURSE):
    fork = f'{owner}/{repo}'
    try:
        status, theirs = api.get(f'/repos/{course}/contents/{BREAK_FILE}?ref=main')
        if status == 404:
            return Result('G1', 'unknown', ['The course repo has no Lab 9 files yet. Wait until it is published.'])
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


# --- G2: the chart -----------------------------------------------------------------------------------

def file_problems(files):
    """(missing, other problems) for the paths inside the chart."""
    missing = [f for f in ('Chart.yaml', 'values.yaml') if f not in files]
    missing += [f'templates/{t}' for t in TEMPLATES if f'templates/{t}' not in files]
    problems = []
    for f in files:
        if f.startswith(('charts/', 'crds/')):
            problems.append(f'{CHART}/{f}: no subcharts or CRDs in Lab 9. Remove it.')
        elif f.startswith('templates/') and f[len('templates/'):] not in TEMPLATES + EXTRA_OK:
            problems.append(f'{CHART}/{f}: templates/ holds the six files from Part 1 (plus NOTES.txt or '
                            '_helpers.tpl if you like). Stretch work goes in stretch/.')
    return missing, problems


def chart_yaml_problems(text):
    problems = []
    if not re.search(r'''(?m)^apiVersion:\s*["']?v2["']?\s*(#.*)?$''', text):
        problems.append('Chart.yaml: apiVersion must be v2.')
    if not re.search(rf'''(?m)^name:\s*["']?{CHART_NAME}["']?\s*(#.*)?$''', text):
        problems.append(f'Chart.yaml: name must be {CHART_NAME}, the same as the folder.')
    if re.search(r'(?m)^dependencies:', text):
        problems.append('Chart.yaml: no dependencies in Lab 9. Remove the dependencies list.')
    return problems


def refusals(objs):
    """What the grader refuses to install. Empty list = OK. Never a reason for 0 points by itself."""
    problems = []
    for obj in objs:
        kind = obj.get('kind')
        meta = obj.get('metadata') or {}
        where = f"{kind} {meta.get('name')}"
        if kind not in CHART_KINDS + WRONG_KINDS:
            problems.append(f'{where}: only {", ".join(CHART_KINDS)} belong in the chart for Lab 9. Stretch work goes in stretch/.')
            continue
        if kind == 'Deployment':
            pod = pod_spec(obj)
            for key in ('hostNetwork', 'hostPID', 'hostIPC'):
                if pod.get(key):
                    problems.append(f'{where}: {key} is not allowed.')
            if any('hostPath' in (v or {}) for v in pod.get('volumes') or []):
                problems.append(f'{where}: hostPath volumes are not allowed.')
            for c in (pod.get('containers') or []) + (pod.get('initContainers') or []):
                if (c.get('securityContext') or {}).get('privileged'):
                    problems.append(f"{where}: container {c.get('name')} must not be privileged.")
                if any(p.get('hostPort') for p in c.get('ports') or []):
                    problems.append(f'{where}: hostPort is not allowed.')
    return problems


def object_problems(objs):
    """Objects that are in the wrong place: a Namespace or a Secret in the chart, a namespace other than course."""
    problems = []
    for obj in objs:
        kind = obj.get('kind')
        meta = obj.get('metadata') or {}
        where = f"{kind} {meta.get('name')}"
        if kind == 'Namespace':
            problems.append(f'{where}: the Namespace stays outside the chart. Helm installs into it with -n {NAMESPACE} (Part 1).')
        elif kind == 'Secret':
            problems.append(f'{where}: a Secret never goes into the chart. You make it with a command; the grader makes its own.')
        elif meta.get('namespace') not in (None, NAMESPACE):
            problems.append(f"{where}: its namespace is {meta.get('namespace')}. Leave metadata.namespace out; helm install -n {NAMESPACE} puts it there.")
        if kind == 'Service' and (obj.get('spec') or {}).get('type', 'ClusterIP') != 'ClusterIP':
            problems.append(f'{where}: type must be ClusterIP; reach it with kubectl port-forward.')
    return problems


def image_ok(image, owner, repo):
    """'' if the image reference is one Lab 9 accepts, else the reason."""
    if image in FALLBACK_IMAGES:
        return ''
    expected = f'ghcr.io/{owner.lower()}/{repo.lower()}/api:'
    if not image.startswith(expected):
        return f'image is "{image}"; set api.image.repository to {expected[:-1]} (lowercase), or use the fallback {FALLBACK_IMAGES[0]}.'
    tag = image[len(expected):]
    if not tag or tag == 'latest' or '@' in tag:
        return f'image tag is "{tag or "(none)"}"; set api.image.tag to a version such as "0.2.0", never latest.'
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


def env_map(c):
    """{name: env entry} for a container's env list."""
    return {e.get('name'): e for e in c.get('env') or [] if e.get('name')}


def from_configmap(c, var, key):
    """True if variable var comes from ConfigMap app-config, key `key` (env or envFrom)."""
    entry = env_map(c).get(var)
    if entry is not None:
        ref = (entry.get('valueFrom') or {}).get('configMapKeyRef') or {}
        return ref.get('name') == CONFIGMAP and ref.get('key') == key
    return var == key and any(((s.get('configMapRef') or {}).get('name') == CONFIGMAP and not s.get('prefix'))
                              for s in c.get('envFrom') or [])


def from_secret(c, var):
    ref = ((env_map(c).get(var) or {}).get('valueFrom') or {}).get('secretKeyRef') or {}
    return ref.get('name') == SECRET and ref.get('key') == SECRET_KEY


def probe_problems(where, c, http_port=None):
    problems = []
    for kind in ('readinessProbe', 'livenessProbe'):
        probe = c.get(kind)
        if not probe:
            problems.append(f'{where}: no {kind}.')
            continue
        if http_port is not None:
            get = probe.get('httpGet') or {}
            if get.get('port') != http_port or get.get('path') not in PROBE_PATHS:
                problems.append(f'{where}: {kind} must be httpGet on port {http_port}, path /healthz (or / if your image has no /healthz).')
    return problems


def resource_problems(where, c):
    res = c.get('resources') or {}
    requests, limits = res.get('requests') or {}, res.get('limits') or {}
    missing = [f'requests.{k}' for k in ('cpu', 'memory') if k not in requests]
    missing += ['limits.memory'] if 'memory' not in limits else []
    return [f"{where}: resources need {', '.join(missing)}."] if missing else []


def check_config(objs, problems):
    cm = find(objs, 'ConfigMap', CONFIGMAP)
    if not cm:
        problems.append(f'No ConfigMap named {CONFIGMAP}.')
        return
    data = cm.get('data') or {}
    wrong = [f'{k}: {v}' for k, v in CONFIG.items() if data.get(k) != v]
    if wrong:
        problems.append(f"ConfigMap {CONFIGMAP}: data must have {', '.join(wrong)} (DB_PORT as a quoted string).")


def check_pvc(objs, problems):
    pvc = find(objs, 'PersistentVolumeClaim', PVC)
    if not pvc:
        problems.append(f'No PersistentVolumeClaim named {PVC}.')
        return
    spec = pvc.get('spec') or {}
    if 'ReadWriteOnce' not in (spec.get('accessModes') or []):
        problems.append(f'PersistentVolumeClaim {PVC}: accessModes must include ReadWriteOnce.')
    if not ((spec.get('resources') or {}).get('requests') or {}).get('storage'):
        problems.append(f'PersistentVolumeClaim {PVC}: resources.requests.storage, e.g. 1Gi.')
    if spec.get('storageClassName') not in (None, 'standard'):
        problems.append(f"PersistentVolumeClaim {PVC}: storageClassName {spec.get('storageClassName')} doesn't exist on kind; leave it out.")


def check_db(objs, problems):
    dep = find(objs, 'Deployment', 'db')
    if not dep:
        problems.append('No Deployment named db.')
    else:
        spec = dep.get('spec') or {}
        template = spec.get('template') or {}
        where = 'Deployment db'
        if spec.get('replicas', 1) != 1:
            problems.append(f"{where}: replicas is {spec.get('replicas')}; one database Pod, so 1.")
        if (spec.get('strategy') or {}).get('type') != 'Recreate':
            problems.append(f'{where}: strategy.type must be Recreate (Lab 8).')
        if ((spec.get('selector') or {}).get('matchLabels') or {}) != {'app': 'db'}:
            problems.append(f'{where}: spec.selector.matchLabels must be exactly app: db.')
        if ((template.get('metadata') or {}).get('labels') or {}).get('app') != 'db':
            problems.append(f'{where}: the Pod template needs the label app: db.')
        pod = pod_spec(dep)
        containers = pod.get('containers') or []
        pg = [c for c in containers if c.get('name') == 'postgres']
        if len(containers) != 1 or not pg:
            problems.append(f'{where}: one container, named postgres.')
        else:
            c = pg[0]
            if c.get('image') != DB_IMAGE:
                problems.append(f"{where}: image is {c.get('image')}; use {DB_IMAGE}, as in Lab 8.")
            if 5432 not in [p.get('containerPort') for p in c.get('ports') or []]:
                problems.append(f'{where}: containerPort 5432.')
            if not from_secret(c, 'POSTGRES_PASSWORD'):
                problems.append(f'{where}: POSTGRES_PASSWORD must come from Secret {SECRET}, key {SECRET_KEY} (secretKeyRef), never a value in the chart.')
            env = env_map(c)
            for var, key in (('POSTGRES_USER', 'DB_USER'), ('POSTGRES_DB', 'DB_NAME')):
                if env.get(var, {}).get('value') != 'todo' and not from_configmap(c, var, key):
                    problems.append(f'{where}: {var} must be todo (a value, or {key} from ConfigMap {CONFIGMAP}).')
            volumes = {v.get('name'): v for v in pod.get('volumes') or []}
            mounted = [m for m in c.get('volumeMounts') or [] if m.get('mountPath') == DB_MOUNT]
            claim = ((volumes.get(mounted[0].get('name')) or {}).get('persistentVolumeClaim') or {}).get('claimName') if mounted else None
            if claim != PVC:
                problems.append(f'{where}: mount the PVC {PVC} at {DB_MOUNT} (a volume with persistentVolumeClaim.claimName: {PVC}).')
            problems += probe_problems(where, c)
            problems += resource_problems(where, c)
    svc = find(objs, 'Service', 'db')
    if not svc:
        problems.append('No Service named db.')
    else:
        spec = svc.get('spec') or {}
        if (spec.get('selector') or {}) != {'app': 'db'}:
            problems.append(f"Service db: selector is {spec.get('selector')}; it must be exactly app: db.")
        if not any(p.get('port') == 5432 and p.get('targetPort', 5432) == 5432 for p in spec.get('ports') or []):
            problems.append('Service db: needs port 5432 → targetPort 5432.')


def api_container(objs):
    containers = pod_spec(find(objs, 'Deployment', 'api')).get('containers') or []
    found = [c for c in containers if c.get('name') == 'api']
    return found[0] if len(containers) == 1 and found else None


def check_api(objs, owner, repo, platforms_fn, problems):
    dep = find(objs, 'Deployment', 'api')
    if not dep:
        problems.append('No Deployment named api.')
    else:
        spec = dep.get('spec') or {}
        template = spec.get('template') or {}
        where = 'Deployment api'
        if spec.get('replicas') != DEFAULT_REPLICAS:
            shown = 'empty' if spec.get('replicas') is None else spec.get('replicas')
            problems.append(f'{where}: with the values in values.yaml, replicas is {shown}, not {DEFAULT_REPLICAS}. '
                            'Run helm template and look at the line; then compare values.yaml with the template.')
        if ((spec.get('selector') or {}).get('matchLabels') or {}) != {'app': 'api'}:
            problems.append(f'{where}: spec.selector.matchLabels must be exactly app: api.')
        if ((template.get('metadata') or {}).get('labels') or {}).get('app') != 'api':
            problems.append(f'{where}: the Pod template needs the label app: api.')
        c = api_container(objs)
        if c is None:
            problems.append(f'{where}: one container, named api.')
        else:
            reason = image_ok(c.get('image', ''), owner, repo)
            if reason:
                problems.append(f'{where}: ' + reason)
            else:
                found = platforms_fn(c['image'])
                if found is None:
                    problems.append(f"{where}: {c['image']} can't be pulled without logging in. Does the tag exist? Is the package public?")
                elif 'linux/amd64' not in found:
                    problems.append(f"{where}: {c['image']} has no linux/amd64 (the grader's cluster).")
            if 5000 not in [p.get('containerPort') for p in c.get('ports') or []]:
                problems.append(f'{where}: containerPort 5000 (the port the API listens on).')
            missing = [k for k in CONFIG if not from_configmap(c, k, k)]
            if missing:
                problems.append(f"{where}: {', '.join(missing)} must come from ConfigMap {CONFIGMAP} (envFrom configMapRef).")
            if not from_secret(c, 'DB_PASSWORD'):
                problems.append(f'{where}: DB_PASSWORD must come from Secret {SECRET}, key {SECRET_KEY} (secretKeyRef).')
            problems += probe_problems(where, c, http_port=5000)
            problems += resource_problems(where, c)
        if not [i for i in pod_spec(dep).get('initContainers') or [] if i.get('name') == INIT]:
            problems.append(f'{where}: an init container named {INIT} that waits until the database answers (Lab 8).')
    svc = find(objs, 'Service', 'api')
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


def values_problems(probe_objs):
    """The api Deployment rendered with PROBE_SET must show those values."""
    if probe_objs is None:
        return []
    dep = find(probe_objs, 'Deployment', 'api')
    if not dep:
        return []
    problems = []
    if (dep.get('spec') or {}).get('replicas') != PROBE_REPLICAS:
        problems.append('templates/api-deployment.yaml must take replicas from the value api.replicas: '
                        f'with --set api.replicas={PROBE_REPLICAS} the Deployment still has {(dep.get("spec") or {}).get("replicas")}.')
    c = api_container(probe_objs)
    if c is not None and c.get('image') != PROBE_IMAGE:
        problems.append('templates/api-deployment.yaml must build the image from api.image.repository and '
                        f'api.image.tag: with --set, the image should be {PROBE_IMAGE}, but it is {c.get("image")}.')
    return problems


def g2_chart(files, chart_yaml, lint, rendered, objs, probe_objs, owner, repo, platforms_fn=ghcr_platforms,
             probe_rendered=(0, ''), read_error=''):
    """files: paths inside the chart; lint, rendered, probe_rendered: (exit code, output) of helm lint, helm template
    and helm template --set …; objs / probe_objs: the objects kubectl read from the default render and the --set
    render (None if it couldn't); read_error: what kubectl said when it couldn't."""
    if not files:
        return Result('G2', 'fail', [f'There is no {CHART}/ on your main yet. Parts 1–2: through a PR.'])
    missing, problems = file_problems(files)
    if missing:
        return Result('G2', 'fail', [f"{CHART}/ on main has no {', '.join(missing)}. Parts 1–2 name the files."] + problems)
    problems += chart_yaml_problems(chart_yaml)
    if lint[0] != 0:
        problems.append('helm lint fails: ' + helm_error(lint[1]))
    if rendered[0] != 0:
        problems.append('helm template fails: ' + helm_error(rendered[1]))
        problems += helm_hints(rendered[1])
        return Result('G2', 'fail', problems)
    if objs is None:
        if 'does not match the namespace' in read_error:
            return Result('G2', 'fail', problems + [f'A template sets metadata.namespace to something other than {NAMESPACE}. '
                                                    f'Leave metadata.namespace out; helm install -n {NAMESPACE} puts it there (Part 1).'])
        return Result('G2', 'unknown', problems + ['kubectl could not read what helm template made. With --no-fresh, kubectl needs '
                                                   'your own cluster running (kind create cluster); without it, G3 shows the error.'])
    if probe_rendered[0] != 0:
        problems.append(f'helm template with --set api.replicas={PROBE_REPLICAS} --set api.image.tag=… fails: {helm_error(probe_rendered[1])}')
    problems += refusals(objs) + object_problems(objs)
    check_config(objs, problems)
    check_pvc(objs, problems)
    check_db(objs, problems)
    check_api(objs, owner, repo, platforms_fn, problems)
    problems += values_problems(probe_objs)
    return Result('G2', 'fail' if problems else 'pass', problems)


# --- G3: the fresh cluster ---------------------------------------------------------------------------

def http_call(method, path, data=None, port=LOCAL_PORT):
    """One request to the port-forward on localhost. (status, body); status 0 if nothing answered."""
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=body, method=method,
                                     headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode('utf-8', errors='replace')
    except (urllib.error.URLError, OSError):
        return 0, ''


class Cluster:
    """The throwaway kind cluster. Every kubectl and helm call names its own kubeconfig and context."""

    def __init__(self, workdir, runner=run):
        self.kubeconfig = os.path.join(workdir, 'kubeconfig')
        self.run = runner

    def kubectl(self, *args, timeout=300):
        return self.run(['kubectl', '--kubeconfig', self.kubeconfig, '--context', CONTEXT, *args], timeout)

    def helm(self, *args, timeout=300):
        return self.run(['helm', '--kubeconfig', self.kubeconfig, '--kube-context', CONTEXT, *args], timeout)

    def create(self):
        self.run(['kind', 'delete', 'cluster', '--name', CLUSTER, '--kubeconfig', self.kubeconfig], 120)
        return self.run(['kind', 'create', 'cluster', '--name', CLUSTER, '--kubeconfig', self.kubeconfig, '--wait', '90s'], 300)

    def delete(self):
        return self.run(['kind', 'delete', 'cluster', '--name', CLUSTER, '--kubeconfig', self.kubeconfig], 120)

    def read(self, folder):
        # -n course: an object without metadata.namespace lands where `helm install -n course` puts it.
        code, out = self.kubectl('-n', NAMESPACE, 'create', '--dry-run=client', '-o', 'json', '-R', '-f', folder)
        if code != 0:
            return None, out
        try:
            return parse_json_stream(out[out.index('{'):] if '{' in out else ''), ''
        except ValueError as err:
            return None, str(err)

    def pod_states(self):
        _, pods = self.kubectl('-n', NAMESPACE, 'get', 'pods', '--no-headers')
        return sorted({f'{line.split()[0].rsplit("-", 2)[0]}: {line.split()[2]}'
                       for line in pods.splitlines() if len(line.split()) > 2})

    def api_hint(self):
        """The first line of the API's log that says why a request failed, or ''."""
        _, logs = self.kubectl('-n', NAMESPACE, 'logs', 'deployment/api', '-c', 'api', '--tail=30')
        lines = [l for l in logs.splitlines() if 'failed:' in l or 'not reachable' in l]
        return lines[-1][:300] if lines else ''

    def restarts(self):
        """{pod: restarts of its app containers}, from `get pods -o json`."""
        code, out = self.kubectl('-n', NAMESPACE, 'get', 'pods', '-o', 'json')
        if code != 0 or '{' not in out:
            return {}
        try:
            items = json.loads(out[out.index('{'):]).get('items') or []
        except ValueError:
            return {}
        return {(p.get('metadata') or {}).get('name'): sum(s.get('restartCount', 0)
                for s in (p.get('status') or {}).get('containerStatuses') or []) for p in items}

    def wait_db_ready(self, timeout=180):
        """After the db Pod was deleted: wait until a new one exists and is Ready."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            code, _ = self.kubectl('-n', NAMESPACE, 'wait', '--for=condition=Ready', 'pod', '-l', 'app=db',
                                   '--timeout=30s', timeout=40)
            if code == 0:
                return True
            time.sleep(2)
        return False

    def api_replicas(self):
        """(spec.replicas, ready, updated, total) of Deployment api, or None."""
        code, out = self.kubectl('-n', NAMESPACE, 'get', 'deployment', 'api', '-o', 'json')
        if code != 0 or '{' not in out:
            return None
        try:
            dep = json.loads(out[out.index('{'):])
        except ValueError:
            return None
        spec, status = dep.get('spec') or {}, dep.get('status') or {}
        return (spec.get('replicas'), status.get('readyReplicas', 0), status.get('updatedReplicas', 0),
                status.get('replicas', 0))

    def wait_api_replicas(self, want, timeout=180):
        """Wait until Deployment api wants `want` Pods and exactly that many are ready and up to date."""
        deadline = time.monotonic() + timeout
        seen = None
        while time.monotonic() < deadline:
            seen = self.api_replicas()
            if seen and seen[0] == want and seen[1] == want and seen[2] == want and seen[3] == want:
                return True, seen
            time.sleep(3)
        return False, seen

    def history(self):
        """helm history as a list of {revision, status, description}, or None."""
        code, out = self.helm('history', RELEASE, '-n', NAMESPACE, '-o', 'json', timeout=60)
        if code != 0 or '[' not in out:
            return None
        try:
            return json.loads(out[out.index('['):])
        except ValueError:
            return None

    @contextlib.contextmanager
    def forward(self):
        """`kubectl port-forward service/api`; yields http(method, path, data=None) -> (status, body)."""
        cmd = ['kubectl', '--kubeconfig', self.kubeconfig, '--context', CONTEXT, '-n', NAMESPACE,
               'port-forward', 'service/api', f'{LOCAL_PORT}:80']
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            proc = None
        http = http_call
        try:
            for _ in range(15):
                time.sleep(1)
                if http('GET', '/')[0]:
                    break
            yield http
        finally:
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()


def retry(fn, tries=10, pause=3):
    """Call fn() until it returns something truthy, at most `tries` times."""
    for i in range(tries):
        value = fn()
        if value:
            return value
        if i < tries - 1:
            time.sleep(pause)
    return None


def g3_fresh(cluster, chart_dir):
    code, out = cluster.kubectl('create', 'namespace', NAMESPACE)
    password = secrets.token_hex(12)
    if code == 0:
        code, out = cluster.kubectl('-n', NAMESPACE, 'create', 'secret', 'generic', SECRET,
                                    f'--from-literal={SECRET_KEY}={password}')
    if code != 0:
        return Result('G3', 'unknown', [f'Could not prepare the Namespace and the Secret: {first_error(out)}. Run again.'])
    code, out = cluster.helm('install', RELEASE, chart_dir, '-n', NAMESPACE)
    if code != 0:
        return Result('G3', 'fail', [f'helm install {RELEASE} on a fresh cluster (with the Namespace {NAMESPACE} and the '
                                     f'Secret {SECRET} already there) failed: {helm_error(out)}'] + helm_hints(out))
    for name in ('db', 'api'):
        code, _ = cluster.kubectl('-n', NAMESPACE, 'rollout', 'status', f'deployment/{name}', '--timeout=240s', timeout=260)
        if code != 0:
            return Result('G3', 'fail', [f"Deployment {name} didn't finish its rollout in 240 s. Pods: {', '.join(cluster.pod_states()) or 'none'}. "
                                         'Run the debug loop on your own cluster (Lab 8, slide 14).'])
    title = f'lab9-check {password[:8]}'
    with cluster.forward() as http:
        status, _ = retry(lambda: (lambda r: r if r[0] == 201 else None)(http('POST', '/api/todos', {'title': title})), tries=5) or (0, '')
    if status != 201:
        hint = cluster.api_hint()
        lines = ['Every Pod is ready, but saving a todo (POST /api/todos) failed.']
        if hint:
            lines.append(f'The API log says: {hint}')
        if 'does not exist' in hint:
            lines.append('The API started before the database and never made its table: the init container (Lab 8, Part 2).')
        elif 'ENOTFOUND' in hint or 'EAI_AGAIN' in hint:
            lines.append(f'DB_HOST in ConfigMap {CONFIGMAP} must be the name of the database Service: db.')
        elif 'password authentication failed' in hint:
            lines.append(f'The API and PostgreSQL must both take the password from Secret {SECRET}.')
        return Result('G3', 'fail', lines)
    cluster.kubectl('-n', NAMESPACE, 'delete', 'pod', '-l', 'app=db', '--wait=true', timeout=120)
    time.sleep(3)
    if not cluster.wait_db_ready():
        return Result('G3', 'fail', [f"After the database Pod was deleted, no new one became ready in 180 s. Pods: {', '.join(cluster.pod_states())}."])
    with cluster.forward() as http:
        found = retry(lambda: title in http('GET', '/api/todos')[1], tries=10)
    if not found:
        return Result('G3', 'fail', ['The todo was gone after the database Pod was replaced. '
                                     f'Is PostgreSQL\'s data on the PVC {PVC}, mounted at {DB_MOUNT}? (Lab 8, Part 1)'])
    restarted = {pod: n for pod, n in cluster.restarts().items() if n >= 2}
    if restarted:
        shown = ', '.join(f'{pod} ({n})' for pod, n in sorted(restarted.items()))
        return Result('G3', 'fail', [f'The app works, but containers keep restarting: {shown}. Check the liveness probes (Lab 8, Part 3).'])
    # The app works. Now the release: upgrade with a value, then roll back to revision 1.
    code, out = cluster.helm('upgrade', RELEASE, chart_dir, '-n', NAMESPACE, '--set', f'api.replicas={UPGRADE_REPLICAS}')
    if code != 0:
        return Result('G3', 'fail', [f'The app works, but helm upgrade --set api.replicas={UPGRADE_REPLICAS} failed: {helm_error(out)}'] + helm_hints(out))
    ok, seen = cluster.wait_api_replicas(UPGRADE_REPLICAS)
    if not ok:
        return Result('G3', 'fail', [f'The app works, but after helm upgrade --set api.replicas={UPGRADE_REPLICAS} the Deployment api '
                                     f'shows (wanted, ready, updated, total) = {seen}. Does templates/api-deployment.yaml use .Values.api.replicas?'])
    code, out = cluster.helm('rollback', RELEASE, '1', '-n', NAMESPACE)
    if code != 0:
        return Result('G3', 'fail', [f'The app works and the upgrade too, but helm rollback {RELEASE} 1 failed: {helm_error(out)}'])
    ok, seen = cluster.wait_api_replicas(DEFAULT_REPLICAS)
    if not ok:
        return Result('G3', 'fail', [f'The app works and the upgrade too, but after helm rollback {RELEASE} 1 the Deployment api '
                                     f'shows (wanted, ready, updated, total) = {seen}, not {DEFAULT_REPLICAS} ready Pods.'])
    history = cluster.history()
    if not history or len(history) != 3 or (history[-1].get('status') != 'deployed'):
        shown = [(h.get('revision'), h.get('status')) for h in history or []]
        return Result('G3', 'fail', [f'The app works, but helm history after install, upgrade and rollback is {shown}; '
                                     'expected 3 revisions, the last one deployed.'])
    return Result('G3', 'pass', [])


# --- G4, G6 ------------------------------------------------------------------------------------------

def g4_breakfix(api, owner, repo, g2_status):
    fork = f'{owner}/{repo}'
    try:
        pulls = _must(api, f'/repos/{fork}/pulls?state=all&base=main&per_page=100', 'your pull requests')
        pulls.sort(key=lambda p: (p.get('head') or {}).get('ref') != BREAK_BRANCH)
        for pr in pulls:
            commits = _must(api, f"/repos/{fork}/pulls/{pr['number']}/commits?per_page=100", f"PR #{pr['number']}")
            heads = [c['commit']['message'].split('\n', 1)[0].strip() for c in commits]
            if BREAK_MESSAGE not in heads:
                continue
            number, later = pr['number'], commits[heads.index(BREAK_MESSAGE) + 1:]
            if not pr.get('merged_at'):
                return Result('G4', 'fail', [f'PR #{number} is not merged yet. Fix all three faults on it, then merge.'])
            touching, reverts = 0, 0
            for commit in later:
                detail = _must(api, f"/repos/{fork}/commits/{commit['sha']}", 'a commit')
                if any(f.get('filename', '').startswith(CHART + '/') for f in detail.get('files') or []):
                    touching += 1
                    reverts += commit['commit']['message'].startswith(f'Revert "{BREAK_MESSAGE}')
            if not touching:
                return Result('G4', 'fail', [f'PR #{number} has no commit after the teammate\'s that changes {CHART}/. Fix it in your own commits.'])
            if touching == reverts:
                return Result('G4', 'fail', [f'PR #{number} reverts the teammate\'s commit instead of fixing it. Find each fault and fix it in its own commit (Part 4).'])
            if g2_status == 'unknown':
                return Result('G4', 'unknown', [f'PR #{number} is merged with your fixes. Whether a fault is left depends on G2, which could not be checked.'])
            if g2_status != 'pass':
                return Result('G4', 'fail', [f'PR #{number} is merged, but {CHART}/ on main still fails G2: a fault is left.'])
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
    print(f"\nLab 9 self-check for {fork}{'' if token_used else ' (no token: slower, and a shared network may hit the limit)'}\n", file=out)
    for result in sorted(results, key=lambda r: r.gate):
        print(f"  {SYMBOL[result.status]} {result.gate}  {TITLES[result.gate]}", file=out)
        for line in result.lines:
            print(f'        {line}', file=out)
    print(f"  · G5  {TITLES['G5']}", file=out)
    passed = sum(r.status == 'pass' for r in results)
    print(f'\n{passed} of {len(results)} gates pass.', file=out)
    if passed == len(results):
        print('Everything the script can check is done. Submit your fork URL on Evaluentis.', file=out)


def read_local(runner, folder):
    """Without the throwaway cluster: kubectl (your current context) reads the rendered files, if it can."""
    code, out = runner(['kubectl', '-n', NAMESPACE, 'create', '--dry-run=client', '-o', 'json', '-R', '-f', folder], 120)
    if code != 0 or '{' not in out:
        return None, out
    try:
        return parse_json_stream(out[out.index('{'):]), ''
    except ValueError as err:
        return None, str(err)


def check_all(api, owner, repo, course, fresh, runner=run, platforms_fn=ghcr_platforms, log=print, cluster_cls=Cluster):
    results = [g1_sync(api, owner, repo, course), g6_writeup(api, owner, repo)]
    workdir = tempfile.mkdtemp(prefix='lab9-check-')
    chart_dir = os.path.join(workdir, CHART_NAME)       # helm lint wants the folder named like the chart
    os.mkdir(chart_dir)
    cluster = cluster_cls(workdir, runner)
    created = False
    try:
        try:
            files = fetch_chart(api, owner, repo, chart_dir)
        except ApiError as err:
            return results + [Result(g, 'unknown', [str(err)]) for g in ('G2', 'G3', 'G4')]
        if not files:
            g2 = g2_chart(files, '', (1, ''), (1, ''), None, None, owner, repo, platforms_fn)
            return results + [g2, Result('G3', 'fail', ['Nothing to install yet.']), g4_breakfix(api, owner, repo, 'fail')]
        chart_yaml = ''
        if 'Chart.yaml' in files:
            with open(os.path.join(chart_dir, 'Chart.yaml'), encoding='utf-8', errors='replace') as f:
                chart_yaml = f.read()
        lint = runner(['helm', 'lint', chart_dir], 120)
        rendered_dir, probe_dir = os.path.join(workdir, 'rendered'), os.path.join(workdir, 'probe')
        rendered = render(runner, chart_dir, rendered_dir)
        probe = render(runner, chart_dir, probe_dir, PROBE_SET)
        objs = probe_objs = None
        g3, err = None, ''
        if fresh and rendered[0] == 0:
            log(f'Creating the throwaway cluster {CLUSTER} (1–2 minutes)…')
            code, out = cluster.create()
            created = True
            if code != 0:
                g3 = Result('G3', 'unknown', [f'kind could not create {CLUSTER}: {first_error(out)}'])
            else:
                objs, err = cluster.read(rendered_dir)
                probe_objs = cluster.read(probe_dir)[0] if probe[0] == 0 else None
                if objs is None:
                    g3 = Result('G3', 'fail', ['kubectl could not read what helm template made: ' + first_error(err)])
                elif refusals(objs):
                    g3 = Result('G3', 'unknown', ['Not installed: fix the G2 problems marked "not allowed" or "only … belong" first. The grader refuses the same.'])
                else:
                    log('helm install, the Secret, the rollouts, the data, then helm upgrade and helm rollback (3–5 minutes)…')
                    g3 = g3_fresh(cluster, chart_dir)
        elif rendered[0] == 0:
            objs, err = read_local(runner, rendered_dir)
            probe_objs = read_local(runner, probe_dir)[0] if probe[0] == 0 else None
            g3 = Result('G3', 'unknown', ['Skipped (--no-fresh). Run without it before you submit.'])
        else:
            g3 = Result('G3', 'fail', ['helm template fails (see G2), so helm install fails the same way.'])
        g2 = g2_chart(files, chart_yaml, lint, rendered, objs, probe_objs, owner, repo, platforms_fn,
                      probe_rendered=probe, read_error=err)
        return results + [g2, g3, g4_breakfix(api, owner, repo, g2.status)]
    finally:
        if created:
            log(f'Deleting {CLUSTER}…')
            cluster.delete()
        shutil.rmtree(workdir, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='check.sh', description='Lab 9 self-check: reads your fork, tests charts/course-app on a throwaway cluster.')
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
    tools = ('helm',) if args.no_fresh else ('helm', 'kind', 'kubectl', 'docker')
    for tool in tools:
        if shutil.which(tool) is None:
            where = '"Before Lab 9"' if tool == 'helm' else '"Before Lab 7"'
            print(f'✘ {tool} is missing. See {where} in the course README.')
            return 2
    if not args.no_fresh:
        print(f'This creates a second kind cluster, {CLUSTER}, for 3–5 minutes (about 1.5 GB of memory),\n'
              'then deletes it. Your own cluster and kubectl context are not touched. --no-fresh skips it.')
    owner, repo = fork.split('/')
    token = find_token(args.token_stdin)
    # Helm's own settings and cache go to a temporary folder, so your Helm setup is left alone.
    helm_home = tempfile.mkdtemp(prefix='lab9-helm-')
    for var in ('HELM_CONFIG_HOME', 'HELM_CACHE_HOME', 'HELM_DATA_HOME'):
        os.environ[var] = os.path.join(helm_home, var.lower())
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(130))
    try:
        results = check_all(Api(token), owner, repo, args.course, not args.no_fresh)
    except KeyboardInterrupt:
        print(f'\nStopped. If {CLUSTER} is still there: kind delete cluster --name {CLUSTER}')
        return 130
    finally:
        shutil.rmtree(helm_home, ignore_errors=True)
    report(fork, results, bool(token))
    return 0 if all(r.status == 'pass' for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
