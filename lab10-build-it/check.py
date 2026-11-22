"""check.py: the Lab 10 self-check. Run it through check.sh, not directly.

It reads your fork through the GitHub REST API and copies infra/ and charts/course-app/ from your main branch into
a temporary folder. It never uses your working copy, your state or your cluster. Then it does what the grader does:
- it reads every .tf file and refuses to run anything outside the Mission 10 allowlist;
- tofu fmt -check, tofu init, tofu validate and tofu plan (no cluster needed), and checks the fixed names in the plan;
- from zero on a throwaway cluster called lab10-check: tofu apply, the Pods, a todo saved and read back, a plan that
  says "No changes", tofu destroy, tofu apply again, and tofu destroy at the end.
The check cluster gets its own kubeconfig file, and every tofu command names it with -var cluster_name=lab10-check,
so your own cluster, your kubectl context and ~/.kube/config are not touched.

Python 3 standard library, plus the tofu, kind, kubectl and docker commands.
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
LAB_DIR = 'lab10-build-it'
BREAK_FILE = f'{LAB_DIR}/break.sh'
BREAK_BRANCH = 'chore/tidy-infra'
BREAK_MESSAGE = 'chore(infra): tidy up providers and paths'
INFRA = 'infra'
CHART = 'charts/course-app'
CLUSTER = 'lab10-check'          # read at call time everywhere, so a test harness can change it
NAMESPACE = 'course'
RELEASE = 'course-app'
WRITEUP = 'lab10/README.md'
HEADINGS = ('Change, drift, rebuild', 'What broke and how I found it')
LOCAL_PORT = 18100
APPLY_TIMEOUT = 360
REGISTRY = 'registry.opentofu.org'
PROVIDERS = {
    'kind': ('tehcyx/kind', '~> 0.13.0'),
    'kubernetes': ('hashicorp/kubernetes', '~> 3.5'),
    'helm': ('hashicorp/helm', '~> 3.3'),
    'random': ('hashicorp/random', '~> 3.9'),
}
ADDRESSES = ('kind_cluster.course', 'kubernetes_namespace_v1.course', 'random_password.db',
             'kubernetes_secret_v1.db', 'helm_release.course_app')
RESOURCE_TYPES = ('kind_cluster', 'kubernetes_namespace_v1', 'kubernetes_secret_v1', 'random_password', 'helm_release')
ALLOWED_BLOCKS = ('terraform', 'provider', 'variable', 'output', 'locals', 'resource')
NEVER_NESTED = ('provisioner', 'connection', 'dynamic', 'precondition', 'postcondition')
# Functions that read files on the computer that runs tofu (the grader's, too). Mission 10 needs none.
FILE_FUNCTIONS = re.compile(r'\b(file\w*|templatefile|pathexpand|abspath)\s*\(')
KIND_CONFIG_ALLOWED = {'kind_config': ({'kind', 'api_version'}, {'node'}),
                       'node': ({'role'}, {'extra_port_mappings'}),
                       'extra_port_mappings': ({'container_port', 'host_port', 'listen_address', 'protocol'}, set())}
CONNECTION = ('host', 'client_certificate', 'client_key', 'cluster_ca_certificate')
REFUSED_SUFFIXES = ('.tofu', '.tf.json', '.tofu.json')
GITIGNORE = ('.terraform/', '*.tfstate', '*.tfstate.*', '*-config')
MAX_FILES, MAX_BYTES = 40, 300_000
PLUGIN_CACHE = os.path.join('~', '.cache', 'lab10-tofu-plugins')

TITLES = {
    'G1': 'The Lab 10 sync PR is merged',
    'G2': 'infra/ on main: the allowlist, fmt, validate, the fixed names in the plan',
    'G3': 'From zero, twice: tofu apply, the app works, no changes, tofu destroy, tofu apply again',
    'G4': 'Break-fix: a merged PR with the teammate\'s commit and your fixes',
    'G5': 'No password, token, state or kubeconfig in the repository (checked by the grader only)',
    'G6': 'lab10/README.md: "Change, drift, rebuild" and "What broke and how I found it"',
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
            'User-Agent': 'turiba-devops-lab10-check',
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


def first_error(out):
    lines = [l for l in out.splitlines() if 'error' in l.lower()]
    return (lines or out.splitlines() or ['(no output)'])[0].strip()[:300]


# --- Reading .tf files without running anything ------------------------------------------------------

class HclError(Exception):
    """A .tf file the scanner can't read. The message is '<file>:<line>: what'."""


# One block: its type, its labels, its attributes (name -> the expression's raw text) and its nested blocks.
Block = namedtuple('Block', 'type labels attrs blocks line')
IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_-]*')
HEREDOC = re.compile(r'<<-?([^\W\d][\w-]*)[ \t]*\r?\n')    # allowlist() refuses every '<<' anyway


class _Scanner:
    """Just enough HCL to find blocks and attributes: strings, templates, heredocs, comments and brackets."""

    def __init__(self, text, filename):
        self.t, self.name, self.n = text, filename, len(text)

    def fail(self, i, what):
        raise HclError(f'{self.name}:{self.t.count(chr(10), 0, i) + 1}: {what}')

    def is_comment(self, i):
        return self.t[i] == '#' or self.t.startswith('//', i) or self.t.startswith('/*', i)

    def comment_end(self, i):
        """The index after a comment. A line comment stops before its newline."""
        if self.t.startswith('/*', i):
            j = self.t.find('*/', i + 2)
            if j < 0:
                self.fail(i, 'a /* comment without its */')
            return j + 2
        j = self.t.find('\n', i)
        return self.n if j < 0 else j

    def string_end(self, i):
        """t[i] is '"'. The index after the closing quote. ${…} and %{…} may hold quotes and braces."""
        t, j = self.t, i + 1
        while j < self.n:
            if t[j] == '\\':
                j += 2
            elif t[j] == '"':
                return j + 1
            elif t[j] == '\n':
                self.fail(i, 'a string without its closing "')
            elif t.startswith('$${', j) or t.startswith('%%{', j):
                j += 3
            elif t.startswith('${', j) or t.startswith('%{', j):
                j = self.expr_end(j + 2, newline_ends=False) + 1
            else:
                j += 1
        self.fail(i, 'a string without its closing "')

    def heredoc_end(self, i):
        m = HEREDOC.match(self.t, i)
        if not m:
            return None
        end = re.compile(r'(?m)^[ \t]*' + re.escape(m.group(1)) + r'[ \t]*\r?$').search(self.t, m.end())
        if end is None:
            self.fail(i, f'a heredoc without its closing {m.group(1)}')
        return end.end()

    def expr_end(self, i, newline_ends=True, stops=''):
        """Where an expression starting at i ends: a newline or line comment at depth 0 (if newline_ends), a
        closing bracket it didn't open, or a character from stops at depth 0."""
        t, depth = self.t, 0
        while i < self.n:
            c = t[i]
            if c == '"':
                i = self.string_end(i)
                continue
            if t.startswith('<<', i):
                end = self.heredoc_end(i)
                if end is not None:
                    i = end
                    continue
            if self.is_comment(i):
                if depth == 0 and newline_ends and not t.startswith('/*', i):
                    return i
                i = self.comment_end(i)
                continue
            if c in '([{':
                depth += 1
            elif c in ')]}':
                if depth == 0:
                    return i
                depth -= 1
            elif depth == 0 and ((c == '\n' and newline_ends) or c in stops):
                return i
            i += 1
        return i

    def skip(self, i, newlines=True):
        while i < self.n:
            if self.t[i] in ' \t\r' or (newlines and self.t[i] == '\n'):
                i += 1
            elif self.is_comment(i):
                i = self.comment_end(i)
            else:
                break
        return i

    def body(self, i, top):
        attrs, blocks = {}, []
        while True:
            i = self.skip(i)
            if i >= self.n:
                if top:
                    return i, attrs, blocks
                self.fail(i, 'a { without its }')
            if self.t[i] == '}':
                if top:
                    self.fail(i, 'a } without its {')
                return i + 1, attrs, blocks
            m = IDENT.match(self.t, i)
            if not m:
                self.fail(i, f'unexpected {self.t[i]!r}')
            name, start = m.group(0), i
            i = self.skip(m.end(), newlines=False)
            if self.t.startswith('=', i) and not self.t.startswith('==', i):
                j = self.expr_end(i + 1)
                attrs[name] = self.t[i + 1:j].strip()
                i = j
                continue
            labels = []
            while True:
                i = self.skip(i, newlines=False)
                label = IDENT.match(self.t, i)
                if i < self.n and self.t[i] == '"':
                    j = self.string_end(i)
                    labels.append(self.t[i + 1:j - 1])
                    i = j
                elif label:
                    labels.append(label.group(0))
                    i = label.end()
                elif i < self.n and self.t[i] == '{':
                    i, a, b = self.body(i + 1, False)
                    blocks.append(Block(name, tuple(labels), a, b, self.t.count('\n', 0, start) + 1))
                    break
                else:
                    self.fail(i, f'expected "=" or "{{" after {name}')


def scan_hcl(text, filename):
    """The top-level blocks of one .tf file. Raises HclError for unbalanced braces or an unclosed string."""
    return _Scanner(text, filename).body(0, True)[2]


def string_value(raw):
    """The inside of a single quoted string (with ${…} kept), or None if the expression is anything else."""
    raw = (raw or '').strip()
    if not raw.startswith('"'):
        return None
    try:
        end = _Scanner(raw, '').string_end(0)
    except HclError:
        return None
    return raw[1:end - 1] if end == len(raw) else None


def object_items(raw):
    """The top-level items of an object constructor { key = value, … }: key -> the value's raw text."""
    raw = (raw or '').strip()
    if not (raw.startswith('{') and raw.endswith('}')):
        return {}
    s, items, i, end = _Scanner(raw, ''), {}, 1, len(raw) - 1
    try:
        while True:
            i = s.skip(i)
            while i < end and raw[i] == ',':
                i = s.skip(i + 1)
            if i >= end:
                return items
            if raw[i] == '"':
                j = s.string_end(i)
                key = raw[i + 1:j - 1]
            else:
                m = IDENT.match(raw, i)
                if not m:
                    return items
                key, j = m.group(0), m.end()
            j = s.skip(j, newlines=False)
            if j >= end or raw[j] not in '=:':
                return items
            k = s.expr_end(j + 1, stops=',')
            items[key] = raw[j + 1:k].strip()
            i = k
    except HclError:
        return items


def object_keys(raw):
    return list(object_items(raw))


def _walk(block):
    for inner in block.blocks:
        yield inner
        yield from _walk(inner)


def _terraform_block(name, b, refusals, blockers):
    at = f'{name}:{b.line}'
    for key in b.attrs:
        if key != 'required_version':
            refusals.append(f'{at}: "{key}" in the terraform block. Only required_version and required_providers belong there.')
    for inner in b.blocks:
        if inner.type != 'required_providers':
            refusals.append(f'{name}:{inner.line}: a "{inner.type}" block in the terraform block. Mission 10 keeps '
                            'the state local: only required_version and required_providers belong there.')
            continue
        for local, raw in inner.attrs.items():
            source = string_value(object_items(raw).get('source')) if raw.startswith('{') else None
            source = source or f'hashicorp/{local}'
            parts = source.lower().split('/')
            host = parts[0] if len(parts) == 3 else REGISTRY
            if parts[-1] not in PROVIDERS:
                refusals.append(f'{name}:{inner.line}: the provider {source}. Mission 10 uses only '
                                + ', '.join(p[0] for p in PROVIDERS.values()) + '.')
            elif (host, '/'.join(parts[-2:])) != (REGISTRY, PROVIDERS[parts[-1]][0]):
                blockers.append(f'{name}:{inner.line}: required_providers has {source} for {local}. It must be '
                                f'{PROVIDERS[parts[-1]][0]}, from the OpenTofu registry. Nothing is run until that is fixed.')


def _connection(at, where, attrs, blocks, refusals):
    extra = [k for k in attrs if k not in CONNECTION] + [b.type for b in blocks]
    elsewhere = [k for k in CONNECTION if k in attrs and
                 not re.fullmatch(rf'kind_cluster\.course\.{KIND_ATTR[k]}', attrs[k].strip())]
    if extra:
        refusals.append(f'{at}: {where} has {", ".join(extra)}. It may only use host, client_certificate, client_key '
                        'and cluster_ca_certificate from kind_cluster.course, so it can never reach another cluster.')
    elif elsewhere:
        refusals.append(f'{at}: {where} takes {", ".join(elsewhere)} from somewhere other than kind_cluster.course, '
                        'so it could reach another cluster.')


def _provider_block(name, b, refusals):
    at, kind = f'{name}:{b.line}', (b.labels or ('',))[0]
    if kind not in PROVIDERS:
        refusals.append(f'{at}: provider "{kind}". Mission 10 uses only kind, kubernetes, helm and random.')
    elif 'alias' in b.attrs:
        refusals.append(f'{at}: an alias in provider "{kind}". Mission 10 needs exactly one of each provider.')
    elif kind == 'kubernetes':
        _connection(at, 'provider "kubernetes"', b.attrs, b.blocks, refusals)
    elif kind == 'helm':
        extra = [k for k in b.attrs if k not in ('kubernetes', 'experiments')] + [x.type for x in b.blocks if x.type != 'kubernetes']
        if extra:
            refusals.append(f'{at}: provider "helm" has {", ".join(extra)}. It needs only kubernetes = {{ … }}.')
        elif 'kubernetes' in b.attrs and not b.attrs['kubernetes'].startswith('{'):
            refusals.append(f'{at}: provider "helm" has kubernetes = {b.attrs["kubernetes"][:60]}. Write the object out: '
                            'kubernetes = { host = kind_cluster.course.endpoint, … }.')
        elif 'kubernetes' in b.attrs:
            _connection(at, 'provider "helm" kubernetes = { … }', object_items(b.attrs['kubernetes']), [], refusals)
        for old in b.blocks:          # the Helm provider 2.x syntax: tofu validate explains it, but check it too
            _connection(at, 'provider "helm" kubernetes { … }', old.attrs, old.blocks, refusals)
    elif b.attrs or b.blocks:
        refusals.append(f'{at}: provider "{kind}" needs no settings in Mission 10.')


def _resource_block(name, b, refusals):
    at, rtype = f'{name}:{b.line}', (b.labels or ('',))[0]
    if rtype not in RESOURCE_TYPES:
        refusals.append(f'{at}: a resource of type {rtype}. Mission 10 uses only ' + ', '.join(RESOURCE_TYPES) + '.')
    elif rtype == 'kind_cluster':
        # The kind provider runs a privileged container on this computer: only the settings the brief uses.
        extra = [k for k in b.attrs if k not in ('name', 'wait_for_ready', 'depends_on')]
        for inner in b.blocks:
            if inner.type == 'lifecycle':
                continue
            if inner.type != 'kind_config':
                extra.append(inner.type)
                continue
            for part in [inner] + list(_walk(inner)):
                attrs_ok, blocks_ok = KIND_CONFIG_ALLOWED.get(part.type, (set(), set()))
                extra += [k for k in part.attrs if k not in attrs_ok] + [x.type for x in part.blocks if x.type not in blocks_ok]
        if extra:
            refusals.append(f'{at}: kind_cluster has {", ".join(extra)}. Mission 10 allows only name, wait_for_ready '
                            'and a kind_config with nodes and extra_port_mappings.')
    elif rtype == 'helm_release':
        bad = [k for k in b.attrs if k.startswith('repository') or k == 'postrender']
        chart = string_value(b.attrs.get('chart'))
        if bad:
            refusals.append(f'{at}: {", ".join(bad)} in helm_release. Mission 10 installs your own chart from '
                            f'{CHART} only.')
        elif 'chart' in b.attrs and chart is None:
            refusals.append(f'{at}: chart = {b.attrs["chart"][:60]}. Write the chart path as a plain string: '
                            f'"${{path.module}}/../{CHART}".')
        elif chart and ('://' in chart or chart.startswith('oci:')):
            refusals.append(f'{at}: the chart {chart} comes from outside your repository. Mission 10 installs your '
                            f'own chart from {CHART} only.')


def allowlist(files, blocks, errors=(), texts=None):
    """(refusals, blockers) for infra/. files: the paths inside infra/; blocks: (file, Block) for every .tf file;
    errors: the HclError messages of files that couldn't be read; texts: file name -> text.
    A refusal is something the grader never runs (the lecturer looks at it). A blocker is a mistake that would make
    tofu download or run code from somewhere else: G2 fails, and nothing is run.
    This is the first of three gates. check_all() also checks what tofu init installed (installed_refusals) and what
    the plan contains (plan_refusals) before anything is applied, so a file this scanner misreads can't get past."""
    blockers = []
    refusals = [f'{e}. check.py can\'t read this file, so nothing was run. If tofu validate passes on it, the lecturer '
                'looks at it.' for e in errors]
    for name in files:
        if '/' not in name and name.endswith(REFUSED_SUFFIXES):
            refusals.append(f'{name}: OpenTofu reads this file too. Mission 10 allows only .tf files in infra/.')
    for name, text in sorted((texts or {}).items()):
        if name.endswith('.tf') and '<<' in text:
            refusals.append(f'{name}:{text[:text.index("<<")].count(chr(10)) + 1}: a heredoc (<<). Mission 10 needs '
                            "none, and check.py can't check what is inside one.")
    for name, b in blocks:
        for part in [b] + list(_walk(b)):
            for key, raw in part.attrs.items():
                used = sorted(set(FILE_FUNCTIONS.findall(raw)))
                if used:
                    refusals.append(f'{name}:{part.line}: {key} uses {", ".join(used)}(). Functions that read files on '
                                    'the computer running tofu are not allowed in Mission 10.')
    for name, b in blocks:
        if b.type not in ALLOWED_BLOCKS:
            refusals.append(f'{name}:{b.line}: a "{b.type}" block. Mission 10 uses only terraform, provider, variable, '
                            'output, locals and resource blocks.')
            continue
        for inner in _walk(b):
            if inner.type in NEVER_NESTED:
                refusals.append(f'{name}:{inner.line}: a "{inner.type}" block in {b.type} '
                                + ' '.join(f'"{l}"' for l in b.labels) + '. Not allowed in Mission 10.')
        if b.type == 'terraform':
            _terraform_block(name, b, refusals, blockers)
        elif b.type == 'provider':
            _provider_block(name, b, refusals)
        elif b.type == 'resource':
            _resource_block(name, b, refusals)
    return refusals, blockers


# --- Fetching infra/ and the chart from main ---------------------------------------------------------

def _never_copied(parts):
    """State, the provider's kubeconfig and .terraform/ are never copied: they would point at YOUR cluster."""
    base = parts[-1]
    return '.terraform' in parts[:-1] or '.tfstate' in base or base.endswith('-config')


def fetch_tree(api, owner, repo):
    """Every entry on the fork's main ([] if the repo or main is empty)."""
    status, tree = api.get(f'/repos/{owner}/{repo}/git/trees/main?recursive=1')
    if status in (404, 409):
        return []
    if status != 200 or not isinstance(tree, dict):
        raise ApiError(f'Could not read the files on your main (HTTP {status}).')
    return tree.get('tree') or []


def fetch_files(api, owner, repo, tree, prefix, dest, top_only=False):
    """Copy the files under prefix/ on main into dest. Returns their paths inside prefix/ (sorted).
    top_only: only the files directly in prefix/ (for infra/: OpenTofu reads no subfolder, and terraform.d/plugins/
    would be a local provider mirror)."""
    pre = prefix.rstrip('/') + '/'
    blobs = []
    for entry in tree:
        path = str(entry.get('path', ''))
        if entry.get('type') != 'blob' or entry.get('mode') == '120000' or not path.startswith(pre):
            continue
        parts = path[len(pre):].split('/')
        if any(p in ('', '.', '..') for p in parts) or _never_copied(parts) or (top_only and len(parts) > 1):
            continue
        blobs.append((entry, parts))
    if len(blobs) > MAX_FILES or sum(e.get('size') or 0 for e, _ in blobs) > MAX_BYTES:
        raise ApiError(f'{prefix}/ on your main has more than {MAX_FILES} files or {MAX_BYTES // 1000} kB. '
                       'Is something committed there that should be ignored?')
    names = []
    for entry, parts in blobs:
        body = _must(api, f"/repos/{owner}/{repo}/git/blobs/{entry['sha']}", entry['path'])
        target = os.path.join(dest, *parts)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'wb') as f:
            f.write(base64.b64decode(body.get('content', '')))
        names.append('/'.join(parts))
    return sorted(names)


def committed_secrets(tree):
    """Paths on main that must never be committed: state files, .terraform/ and the provider's kubeconfig."""
    found = set()
    for entry in tree:
        path = str(entry.get('path', ''))
        parts = path.split('/')
        if '.terraform' in parts:
            found.add('/'.join(parts[:parts.index('.terraform') + 1]) + '/')
        elif '.tfstate' in parts[-1] or (parts[0] == INFRA and parts[-1].endswith('-config')):
            found.add(path)
    return sorted(found)


ENV_KEPT = {'PATH', 'HOME', 'USER', 'LOGNAME', 'SHELL', 'LANG', 'TERM', 'TMPDIR', 'TZ', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
            'http_proxy', 'https_proxy', 'no_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY'}
ENV_KEPT_PREFIXES = ('LC_', 'DOCKER_', 'XDG_')
CLI_CONFIG = 'provider_installation {\n  direct {}\n}\n'     # providers from the registry only, no local mirrors


def isolate_env(environ, tmp, cache):
    """The environment for tofu, kind and kubectl: only what they need. Your settings can't change what gets created
    or where, and no token or key reaches the code that is checked."""
    env = {k: v for k, v in environ.items() if k in ENV_KEPT or k.startswith(ENV_KEPT_PREFIXES)}
    env.update({'KUBECONFIG': os.path.join(tmp, 'kubeconfig'), 'TF_PLUGIN_CACHE_DIR': cache,
                'TF_CLI_CONFIG_FILE': os.path.join(tmp, 'tofu.rc'), 'TF_IN_AUTOMATION': '1', 'TF_INPUT': '0'})
    for var in ('HELM_CONFIG_HOME', 'HELM_CACHE_HOME', 'HELM_DATA_HOME'):
        env[var] = os.path.join(tmp, var.lower())
    return env


# --- G2: infra/ on main ------------------------------------------------------------------------------

class Tofu:
    """tofu in the copied infra/ folder. Every method returns (exit code, output)."""

    def __init__(self, infra_dir, runner, workdir):
        self.infra, self.run, self.workdir = infra_dir, runner, workdir

    def cmd(self, *args):
        return ['tofu', f'-chdir={self.infra}'] + list(args)

    @staticmethod
    def cluster_var():
        return ['-var', f'cluster_name={CLUSTER}']

    def fmt(self):
        return self.run(self.cmd('fmt', '-check', '-recursive', '-no-color'), 60)

    def init(self):
        return self.run(self.cmd('init', '-input=false', '-no-color'), 300)

    def validate(self):
        return self.run(self.cmd('validate', '-no-color'), 120)

    def plan_json(self):
        """(code, plan output, the plan as JSON or None). Needs no cluster."""
        plan_file = os.path.join(self.workdir, 'tfplan')
        code, out = self.run(self.cmd('plan', '-input=false', '-no-color', '-lock=false', f'-out={plan_file}',
                                      *self.cluster_var()), 300)
        if code != 0:
            return code, out, None
        shown_code, shown = self.run(self.cmd('show', '-json', plan_file), 120)
        return 0, out, _json(shown) if shown_code == 0 else None

    def apply(self):
        return self.run(self.cmd('apply', '-input=false', '-no-color', '-auto-approve', *self.cluster_var()), APPLY_TIMEOUT)

    def plan_exitcode(self):
        """0 = no changes, 2 = changes, 1 = error."""
        return self.run(self.cmd('plan', '-input=false', '-no-color', '-detailed-exitcode', *self.cluster_var()), 300)

    def destroy(self):
        return self.run(self.cmd('destroy', '-input=false', '-no-color', '-auto-approve', *self.cluster_var()), 300)


TOFU_HINTS = (
    (r'does not have a provider named', 'Check source = in required_providers: the kind provider is tehcyx/kind.'),
    (r'Inconsistent dependency lock file', "The lock file doesn't match required_providers. Check the sources, then "
                                           'tofu init and commit .terraform.lock.hcl.'),
    (r'locate chart', 'Check chart = in helm_release: "${path.module}/../charts/course-app".'),
    (r'Blocks of type "kubernetes" are not expected|argument named "kubernetes" is not expected',
     'Helm provider 3.x: kubernetes = { … } with an equals sign (old tutorials show a block).'),
    (r'Reference to undeclared', 'A name is misspelled: compare it with the fixed names in the brief.'),
    (r'namespaces? "[^"]+" not found', "The release's namespace must be kubernetes_namespace_v1.course.metadata[0].name."),
    (r'context deadline exceeded', 'The Pods were not ready in time. In a second terminal: kubectl -n course get pods '
                                   'while it waits.'),
    (r'cannot re-use a name that is still in use', 'A failed install is left over: helm uninstall course-app -n course, '
                                                   'then tofu apply.'),
    (r'could not locate any control plane nodes', 'The cluster was deleted with kind, not tofu destroy: delete '
                                                  'terraform.tfstate and terraform.tfstate.backup, then tofu apply.'),
)


def tofu_error(out):
    """'Error title: the first explaining paragraph', from tofu's -no-color output."""
    lines = [re.sub(r'^[│╷╵ \t]+', '', l).rstrip() for l in out.replace('\r\n', '\n').split('\n')]
    for i, line in enumerate(lines):
        if line.startswith('Error: '):
            paragraphs, current = [], []
            for rest in lines[i + 1:] + ['']:
                if rest.startswith('Error: '):
                    break
                if rest.strip():
                    current.append(rest.strip())
                elif current:
                    paragraphs.append(current)
                    current = []
            text = next((' '.join(p) for p in paragraphs if not p[0].startswith(('with ', 'on '))), '')
            return (line + (': ' + text if text else ''))[:400]
    return first_error(out)


def tofu_failed(what, out):
    flat = ' '.join(out.split())
    return [f'{what} fails: {tofu_error(out)}'] + [hint for pattern, hint in TOFU_HINTS if re.search(pattern, flat)]


def _satisfies(version, constraint):
    """version meets a '~> X.Y[.Z]' constraint."""
    m = re.fullmatch(r'\s*~>\s*([\d.]+)\s*', constraint)
    if not m:
        return True
    floor = [int(x) for x in m.group(1).split('.')]
    have = [int(x) for x in re.findall(r'\d+', version)[:3]] + [0, 0, 0]
    upper = floor[:-1]
    upper[-1] += 1
    return have[:len(floor)] >= floor and have[:len(upper)] < upper


def lock_problems(text):
    """infra/.terraform.lock.hcl on main must hold the four providers at versions that meet the constraints."""
    fix = 'Run tofu init in infra/ and commit .terraform.lock.hcl.'
    if text is None:
        return [f'infra/.terraform.lock.hcl is not on main. {fix}']
    try:
        blocks = scan_hcl(text, 'infra/.terraform.lock.hcl')
    except HclError as err:
        return [f'{err}. {fix}']
    locked = {b.labels[0]: string_value(b.attrs.get('version')) or '' for b in blocks if b.type == 'provider' and b.labels}
    problems = []
    for source, constraint in PROVIDERS.values():
        version = locked.get(f'{REGISTRY}/{source}')
        if version is None:
            problems.append(f'infra/.terraform.lock.hcl has no {source}. {fix}')
        elif not _satisfies(version, constraint):
            problems.append(f'infra/.terraform.lock.hcl has {source} {version}, which is not {constraint}. '
                            'Run tofu init -upgrade in infra/ and commit .terraform.lock.hcl.')
    return problems


def _gitignore_has(lines, pattern):
    if pattern in ('*.tfstate', '*.tfstate.*') and '*.tfstate*' in lines:
        return True
    return pattern.strip('/') in {l.strip('/') for l in lines}


def static_problems(blocks, texts):
    """What the .tf files and infra/.gitignore must say, read without running anything."""
    problems = []
    terraform = [(n, b) for n, b in blocks if b.type == 'terraform']
    versions = [(n, string_value(b.attrs['required_version'])) for n, b in terraform if 'required_version' in b.attrs]
    if not versions:
        problems.append(f'infra/{terraform[0][0] if terraform else "versions.tf"}: the terraform block needs '
                        'required_version = ">= 1.10" (Part 1).')
    for name, value in versions:
        m = re.fullmatch(r'>=\s*(\d+)\.(\d+)(?:\.\d+)?', (value or '').strip())
        if not m or (int(m.group(1)), int(m.group(2))) > (1, 10):
            problems.append(f'infra/{name}: required_version is {value!r}. Mission 10 uses ">= 1.10".')
    seen = {}
    for name, b in terraform:
        for inner in b.blocks:
            if inner.type == 'required_providers':
                for local, raw in inner.attrs.items():
                    items = object_items(raw)
                    kind = (string_value(items.get('source')) or f'hashicorp/{local}').lower().split('/')[-1]
                    if kind in PROVIDERS:
                        seen[kind] = (name, string_value(items.get('version')))
    for kind, (source, constraint) in PROVIDERS.items():
        if kind not in seen:
            problems.append(f'infra/: required_providers has no {kind} = {{ source = "{source}", version = '
                            f'"{constraint}" }}.')
        elif ' '.join((seen[kind][1] or '').split()) != constraint:
            problems.append(f'infra/{seen[kind][0]}: {source} has version = {seen[kind][1]!r}. Mission 10 uses '
                            f'"{constraint}".')
    for name, b in blocks:
        if b.type == 'resource' and b.labels == ('kubernetes_secret_v1', 'db') and object_keys(b.attrs.get('data')) != ['password']:
            problems.append(f'infra/{name}: kubernetes_secret_v1.db needs data = {{ password = random_password.db.result }}. '
                            'The chart reads the key password.')
    text = texts.get('.gitignore')
    if text is None:
        problems.append('infra/.gitignore is not on main. It needs ' + ', '.join(GITIGNORE) + ' (Part 1).')
    else:
        lines = {l.strip() for l in text.splitlines()}
        missing = [p for p in GITIGNORE if not _gitignore_has(lines, p)]
        if missing:
            problems.append(f'infra/.gitignore is missing {", ".join(missing)}. Without it, git add can commit the '
                            'state (the DB password) or the kubeconfig (the cluster key).')
    return problems


def _refs(expr):
    return (expr or {}).get('references') or [] if isinstance(expr, dict) else []


KIND_ATTR = {'host': 'endpoint', 'client_certificate': 'client_certificate', 'client_key': 'client_key',
             'cluster_ca_certificate': 'cluster_ca_certificate'}


def plan_problems(plan):
    """The fixed names, read from `tofu show -json` of the plan. Never prints a value of the Secret."""
    problems = []
    if plan.get('errored'):
        problems.append('tofu plan reported an error. Run tofu plan in infra/ and read the first Error.')
    changes = {r['address']: (r.get('change') or {}).get('after') or {}
               for r in plan.get('resource_changes') or [] if r.get('mode', 'managed') == 'managed'}
    root = (plan.get('configuration') or {}).get('root_module') or {}
    configs = {r.get('address'): r for r in root.get('resources') or []}
    missing = [a for a in ADDRESSES if a not in changes]
    extra = sorted(a for a in changes if a not in ADDRESSES)
    if missing:
        problems.append('The plan has no ' + ', '.join(missing) + '. Use exactly the resource names in the brief.')
    if extra:
        problems.append('The plan has ' + ', '.join(extra) + ", which Mission 10 doesn't have. It needs exactly: "
                        + ', '.join(ADDRESSES) + '.')

    def expr(address, *path):
        node = (configs.get(address) or {}).get('expressions') or {}
        for key in path:
            node = (node[0] if isinstance(node, list) and node else node) or {}
            node = node.get(key) if isinstance(node, dict) else None
        return node

    def meta(address):
        return ((changes.get(address) or {}).get('metadata') or [{}])[0] or {}

    if 'kind_cluster.course' in changes:
        after = changes['kind_cluster.course']
        if after.get('name') != CLUSTER:
            problems.append(f'kind_cluster.course: name must be var.cluster_name. The check sets cluster_name = '
                            f'{CLUSTER}, but the plan has {after.get("name")!r}.')
        if after.get('wait_for_ready') is not True:
            problems.append('kind_cluster.course: wait_for_ready = true is missing.')
    if 'kubernetes_namespace_v1.course' in changes and meta('kubernetes_namespace_v1.course').get('name') != NAMESPACE:
        problems.append(f'kubernetes_namespace_v1.course: the Namespace must be named {NAMESPACE}.')
    if 'random_password.db' in changes:
        after = changes['random_password.db']
        if after.get('length') != 24 or after.get('special') is not False:
            problems.append('random_password.db: length = 24 and special = false.')
    if 'kubernetes_secret_v1.db' in changes:
        if meta('kubernetes_secret_v1.db').get('name') != 'db-secret':
            problems.append('kubernetes_secret_v1.db: the Secret must be named db-secret.')
        if 'kubernetes_namespace_v1.course' not in _refs(expr('kubernetes_secret_v1.db', 'metadata', 'namespace')):
            problems.append('kubernetes_secret_v1.db: namespace = kubernetes_namespace_v1.course.metadata[0].name '
                            '(by reference, so the Namespace is made first).')
        if 'random_password.db.result' not in _refs(expr('kubernetes_secret_v1.db', 'data')):
            problems.append("kubernetes_secret_v1.db: data = { password = random_password.db.result }. The password "
                            'must come from random_password.db.result, never be written in the code.')
    if 'helm_release.course_app' in changes:
        after, address = changes['helm_release.course_app'], 'helm_release.course_app'
        if after.get('name') != RELEASE:
            problems.append(f'{address}: name = "{RELEASE}".')
        if 'kubernetes_namespace_v1.course' not in _refs(expr(address, 'namespace')):
            problems.append(f'{address}: namespace must be kubernetes_namespace_v1.course.metadata[0].name (by '
                            f'reference). The plan has {after.get("namespace")!r}.')
        chart = str(after.get('chart') or '')
        if '://' in chart or os.path.normpath(chart).replace(os.sep, '/') != '../charts/course-app':
            problems.append(f'{address}: chart = "${{path.module}}/../charts/course-app". The plan has {chart!r}.')
        if not any(s.get('name') == 'api.replicas' and s.get('value') == '3' for s in after.get('set') or []):
            problems.append(f'{address}: set api.replicas from var.api_replicas (with the default 3, the plan must '
                            'show api.replicas = "3").')
        elif 'var.api_replicas' not in _refs(expr(address, 'set')):
            problems.append(f'{address}: api.replicas must come from var.api_replicas.')
        if 'kubernetes_secret_v1.db' not in ((configs.get(address) or {}).get('depends_on') or []):
            problems.append(f'{address}: depends_on = [kubernetes_secret_v1.db] is missing. Without it the release '
                            'can start before the Secret exists.')
    variables = root.get('variables') or {}
    for name, vtype, default in (('cluster_name', 'string', 'course'), ('api_replicas', 'number', 3)):
        v = variables.get(name)
        if v is None or v.get('default') != default or v.get('type', vtype) != vtype:
            problems.append(f'variable "{name}": type = {vtype}, default = {json.dumps(default)}.')
    if 'kind_cluster.course.context_name' not in _refs(((root.get('outputs') or {}).get('kube_context') or {}).get('expression')):
        problems.append('output "kube_context" with value = kind_cluster.course.context_name is missing.')
    providers = (plan.get('configuration') or {}).get('provider_config') or {}
    k8s = (providers.get('kubernetes') or {}).get('expressions') or {}
    wrong = [a for a, k in KIND_ATTR.items() if f'kind_cluster.course.{k}' not in _refs(k8s.get(a))]
    if wrong:
        problems.append('provider "kubernetes": ' + ', '.join(f'{a} = kind_cluster.course.{KIND_ATTR[a]}' for a in wrong) + '.')
    helm_refs = _refs(((providers.get('helm') or {}).get('expressions') or {}).get('kubernetes'))
    if any(f'kind_cluster.course.{k}' not in helm_refs for k in KIND_ATTR.values()):
        problems.append('provider "helm": kubernetes = { … } with host, client_certificate, client_key and '
                        'cluster_ca_certificate from kind_cluster.course.')
    return problems


ALLOWED_PROVIDERS = {f'{REGISTRY}/{source}' for source, _ in PROVIDERS.values()}


def installed_refusals(infra_dir):
    """The second gate, after tofu init and before anything runs a provider: what init installed. A provider or a
    module that the scanner missed shows up here, whatever the .tf files looked like."""
    problems = []
    if os.path.isdir(os.path.join(infra_dir, '.terraform', 'modules')):
        problems.append('tofu init downloaded modules. Mission 10 uses none, so nothing more was run.')
    try:
        with open(os.path.join(infra_dir, '.terraform.lock.hcl'), encoding='utf-8-sig') as f:
            locked = [b.labels[0] for b in scan_hcl(f.read(), '.terraform.lock.hcl') if b.type == 'provider' and b.labels]
    except OSError:
        locked = []
    except HclError as err:
        return problems + [f'{err}: the lock file after tofu init is unreadable, so nothing more was run.']
    providers_dir = os.path.join(infra_dir, '.terraform', 'providers')
    if os.path.isdir(providers_dir):
        for host in os.listdir(providers_dir):
            for namespace in os.listdir(os.path.join(providers_dir, host)):
                for ptype in os.listdir(os.path.join(providers_dir, host, namespace)):
                    locked.append(f'{host}/{namespace}/{ptype}')
    extra = sorted({p for p in locked if p.lower() not in ALLOWED_PROVIDERS})
    if extra:
        problems.append(f'tofu init installed {", ".join(extra)}, which Mission 10 does not use, so nothing more was run.')
    return problems


def plan_refusals(plan):
    """The third gate, after tofu plan and before tofu apply: modules, provisioners, data sources, other resource
    types or providers in the plan itself."""
    config = plan.get('configuration') or {}
    root = config.get('root_module') or {}
    problems = []
    if root.get('module_calls'):
        problems.append('The plan calls modules (' + ', '.join(sorted(root['module_calls'])) + '). Mission 10 uses none.')
    resources = list(root.get('resources') or []) + list(plan.get('resource_changes') or [])
    for r in resources:
        address = r.get('address', '?')
        if r.get('mode', 'managed') != 'managed' or r.get('type') not in RESOURCE_TYPES:
            problems.append(f'The plan has {address}, which Mission 10 does not allow.')
        if r.get('provisioners'):
            problems.append(f'The plan has a provisioner in {address}. Mission 10 does not allow provisioners.')
    for name, provider in (config.get('provider_config') or {}).items():
        full = str(provider.get('full_name') or name).lower()
        if full not in ALLOWED_PROVIDERS:
            problems.append(f'The plan uses the provider {full}, which Mission 10 does not use.')
    return sorted(set(problems), key=problems.index)


def g3_blockers(plan):
    """Reasons not to apply this plan on the check's cluster, even when the allowlist passed (G2 shows the details)."""
    reasons = []
    names = [((r.get('change') or {}).get('after') or {}).get('name') for r in plan.get('resource_changes') or []
             if r.get('address') == 'kind_cluster.course']
    if names != [CLUSTER]:
        reasons.append(f'the cluster name must come from var.cluster_name. The check only ever touches the cluster it '
                       f'names, {CLUSTER}')
    charts = [str(((r.get('change') or {}).get('after') or {}).get('chart') or '') for r in plan.get('resource_changes') or []
              if r.get('address') == 'helm_release.course_app']
    if not charts or os.path.normpath(charts[0]).replace(os.sep, '/') != '../charts/course-app':
        reasons.append(f'the chart must be ../{CHART}')
    providers = (plan.get('configuration') or {}).get('provider_config') or {}
    k8s = (providers.get('kubernetes') or {}).get('expressions') or {}
    helm_refs = _refs(((providers.get('helm') or {}).get('expressions') or {}).get('kubernetes'))
    if any(f'kind_cluster.course.{k}' not in _refs(k8s.get(a)) or f'kind_cluster.course.{k}' not in helm_refs
           for a, k in KIND_ATTR.items()):
        reasons.append('the kubernetes and helm providers must connect to kind_cluster.course')
    return reasons


def g2_infra(files, refusals, blockers, static, lock, fmt, init, validate, plan):
    """files: what was fetched from infra/; static, lock: problem lines; fmt, init, validate: (code, out) or None
    when not run; plan: (code, out, plan JSON or None) or None."""
    if not files:
        return Result('G2', 'fail', ['No infra/ on your main yet. Parts 1–2: infra/ merged by a PR.'])
    if refusals:
        return Result('G2', 'unknown', [f'Not run: {r}' for r in refusals] +
                      ['Nothing in infra/ was run. The grader does the same and marks it for the lecturer to look at.'])
    problems = list(blockers) + list(static) + list(lock)
    if blockers:
        return Result('G2', 'fail', problems + ['Nothing else was checked: no tofu command runs until that is fixed.'])
    if fmt and fmt[0] != 0:
        names = [l.strip() for l in fmt[1].splitlines() if l.strip().endswith('.tf')]
        problems.append(f'tofu fmt -check: {", ".join(names) or "some files"} need formatting. Run tofu fmt in '
                        'infra/ and commit.')
    for what, step in (('tofu init', init), ('tofu validate', validate)):
        if step is not None and step[0] != 0:
            return Result('G2', 'fail', problems + tofu_failed(what, step[1]))
    if plan is not None:
        if plan[0] != 0:
            problems += tofu_failed('tofu plan', plan[1])
        elif plan[2] is None:
            problems.append('tofu show -json could not read the plan. Run check.sh again.')
        else:
            problems += plan_problems(plan[2])
    return Result('G2', 'fail' if problems else 'pass', problems)


# --- G3: from zero, twice ----------------------------------------------------------------------------

def http_call(method, path, data=None, port=None):
    """One request to the port-forward on localhost. (status, body); status 0 if nothing answered."""
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(f'http://127.0.0.1:{port or LOCAL_PORT}{path}', data=body, method=method,
                                     headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode('utf-8', errors='replace')
    except (urllib.error.URLError, OSError):
        return 0, ''


class Cluster:
    """The throwaway kind cluster that tofu makes. Every kubectl and kind call names the check's own kubeconfig."""

    def __init__(self, workdir, runner=run):
        self.kubeconfig = os.path.join(workdir, 'kubeconfig')
        self.run = runner

    @staticmethod
    def context():
        return f'kind-{CLUSTER}'

    def kubectl(self, *args, timeout=120):
        return self.run(['kubectl', '--kubeconfig', self.kubeconfig, '--context', self.context(), *args], timeout)

    def clusters(self):
        code, out = self.run(['kind', 'get', 'clusters'], 60)
        return [line.strip() for line in out.splitlines() if line.strip() and ' ' not in line.strip()] if code == 0 else []

    def listed(self):
        return CLUSTER in self.clusters()

    def others(self):
        """Other kind clusters on this computer. Two at once hit WSL's inotify limit: kube-proxy and the storage
        provisioner of the second one fail with "too many open files", so its Pods never start."""
        return [name for name in self.clusters() if name != CLUSTER]

    def delete(self):
        return self.run(['kind', 'delete', 'cluster', '--name', CLUSTER, '--kubeconfig', self.kubeconfig], 180)

    def pod_states(self):
        _, pods = self.kubectl('-n', NAMESPACE, 'get', 'pods', '--no-headers')
        return sorted({f'{line.split()[0].rsplit("-", 2)[0]}: {line.split()[2]}'
                       for line in pods.splitlines() if len(line.split()) > 2 and not line.startswith('{')})

    def api_hint(self):
        """The last line of the API's log that says why a request failed, or ''."""
        _, logs = self.kubectl('-n', NAMESPACE, 'logs', 'deployment/api', '-c', 'api', '--tail=30')
        lines = [l for l in logs.splitlines() if 'failed:' in l or 'not reachable' in l]
        return lines[-1][:300] if lines else ''

    def replicas(self, deploy):
        """(spec.replicas, ready, updated, total) of a Deployment, or None."""
        code, out = self.kubectl('-n', NAMESPACE, 'get', 'deployment', deploy, '-o', 'json')
        if code != 0 or '{' not in out:
            return None
        try:
            dep = json.loads(out[out.index('{'):])
        except ValueError:
            return None
        spec, status = dep.get('spec') or {}, dep.get('status') or {}
        return (spec.get('replicas'), status.get('readyReplicas', 0), status.get('updatedReplicas', 0),
                status.get('replicas', 0))

    def wait_ready(self, deploy, want, timeout=180):
        """(ok, seen): wait until the Deployment wants `want` Pods and exactly that many are ready and up to date."""
        deadline, seen = time.monotonic() + timeout, None
        while True:
            seen = self.replicas(deploy)
            if seen == (want, want, want, want):
                return True, seen
            if time.monotonic() >= deadline:
                return False, seen
            time.sleep(3)

    @contextlib.contextmanager
    def forward(self):
        """`kubectl port-forward service/api`; yields http(method, path, data=None) -> (status, body)."""
        cmd = ['kubectl', '--kubeconfig', self.kubeconfig, '--context', self.context(), '-n', NAMESPACE,
               'port-forward', 'service/api', f'{LOCAL_PORT}:80']
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            proc = None
        try:
            for _ in range(15):
                time.sleep(1)
                if http_call('GET', '/')[0]:
                    break
            yield http_call
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


def first_change(out):
    """The first '# <address> will be …' line of a plan."""
    for line in out.splitlines():
        if re.search(r'#\s+\S+\s+(will|must) be', line):
            return line.strip().lstrip('#').strip()
    return first_error(out)


def g3_fresh(tofu, cluster):
    """From zero, twice. The caller destroys whatever is left, also when this stops early."""
    code, out = tofu.apply()
    if code != 0:
        states = cluster.pod_states()
        return Result('G3', 'fail', tofu_failed('tofu apply from zero', out) +
                      ([f'Pods: {", ".join(states)}'] if states else []))
    for deploy, want in (('api', 3), ('db', 1)):
        ok, seen = cluster.wait_ready(deploy, want)
        if not ok:
            return Result('G3', 'fail', [f'tofu apply worked, but Deployment {deploy} has (wanted, ready, updated, total) '
                                         f'= {seen}, not {want} ready. Pods: {", ".join(cluster.pod_states()) or "none"}.'])
    title = f'lab10-check {secrets.token_hex(4)}'
    with cluster.forward() as http:
        saved = retry(lambda: http('POST', '/api/todos', {'title': title})[0] == 201, tries=5)
        found = saved and retry(lambda: title in http('GET', '/api/todos')[1], tries=5)
    if not saved:
        hint = cluster.api_hint()
        return Result('G3', 'fail', ['Every Pod is ready, but saving a todo (POST /api/todos) failed.'] +
                      ([f'The API log says: {hint}'] if hint else []))
    if not found:
        return Result('G3', 'fail', ['A todo was saved, but GET /api/todos did not read it back.'])
    code, out = tofu.plan_exitcode()
    if code == 2:
        return Result('G3', 'fail', [f'Right after tofu apply, tofu plan still wants a change: {first_change(out)}. '
                                     'After an apply, the plan must say "No changes".'])
    if code != 0:
        return Result('G3', 'fail', tofu_failed('tofu plan right after apply', out))
    code, out = tofu.destroy()
    if code != 0:
        return Result('G3', 'fail', tofu_failed('tofu destroy', out))
    code, out = tofu.apply()
    if code != 0:
        return Result('G3', 'fail', [f'The first apply worked, but tofu apply after tofu destroy fails: '
                                     f'{tofu_error(out)}'] + tofu_failed('', out)[1:])
    ok, seen = cluster.wait_ready('api', 3)
    if not ok:
        return Result('G3', 'fail', [f'After tofu destroy and tofu apply, Deployment api has (wanted, ready, updated, '
                                     f'total) = {seen}, not 3 ready.'])
    return Result('G3', 'pass', [])


# --- G1, G4, G6 --------------------------------------------------------------------------------------

def g1_sync(api, owner, repo, course=COURSE):
    fork = f'{owner}/{repo}'
    try:
        status, theirs = api.get(f'/repos/{course}/contents/{BREAK_FILE}?ref=main')
        if status == 404:
            return Result('G1', 'unknown', ['The course repo has no Lab 10 files yet. Wait until it is published.'])
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
                if any(f.get('filename', '').startswith(INFRA + '/') for f in detail.get('files') or []):
                    touching += 1
                    reverts += commit['commit']['message'].startswith(f'Revert "{BREAK_MESSAGE}')
            if not touching:
                return Result('G4', 'fail', [f"PR #{number} has no commit after the teammate's that changes {INFRA}/. "
                                             'Fix it in your own commits.'])
            if touching == reverts:
                return Result('G4', 'fail', [f"PR #{number} reverts the teammate's commit instead of fixing it. Find each "
                                             'fault and fix it in its own commit (Part 4).'])
            if g2_status == 'unknown':
                return Result('G4', 'unknown', [f'PR #{number} is merged with your fixes. Whether a fault is left depends '
                                                'on G2, which could not be checked.'])
            if g2_status != 'pass':
                return Result('G4', 'fail', [f'PR #{number} is merged, but {INFRA}/ on main still fails G2: a fault is left.'])
            return Result('G4', 'pass', [])
    except ApiError as err:
        return Result('G4', 'unknown', [str(err)])
    return Result('G4', 'fail', [f"No PR into main has the commit '{BREAK_MESSAGE}'. Part 4: run break.sh, push, open a PR."])


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


# --- The write-up and the command line ---------------------------------------------------------------

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


def report(fork, results, token_used, g5_lines, out=sys.stdout):
    print(f"\nLab 10 self-check for {fork}{'' if token_used else ' (no token: slower, and a shared network may hit the limit)'}\n", file=out)
    for result in sorted(results, key=lambda r: r.gate):
        print(f"  {SYMBOL[result.status]} {result.gate}  {TITLES[result.gate]}", file=out)
        for line in result.lines:
            print(f'        {line}', file=out)
    print(f"  · G5  {TITLES['G5']}", file=out)
    for path in g5_lines:
        print(f'        ! {path} is on main. git rm -r --cached {path.rstrip("/")}, check infra/.gitignore, commit.', file=out)
    if any('.tfstate' in p for p in g5_lines):
        print('        ! A state file holds the DB password, so it is public now: after the commit, '
              'tofu destroy, then tofu apply, makes a new password and a fresh database '
              '(the old database would keep its first password).', file=out)
    if any(p.endswith('-config') for p in g5_lines):
        print("        ! The kubeconfig holds your cluster's key: tofu destroy, then tofu apply, makes a new cluster.", file=out)
    if g5_lines:
        print('        ! The grader checks every commit, also ones removed later: write in lab10/README.md what was '
              'committed and how you replaced the password or the key.', file=out)
    passed = sum(r.status == 'pass' for r in results)
    print(f'\n{passed} of {len(results)} gates pass.', file=out)
    if passed == len(results) and not g5_lines:
        print('Everything the script can check is done. Submit your fork URL on Evaluentis.', file=out)


def check_all(api, owner, repo, course, fresh, runner=run, log=print, tofu_cls=Tofu, cluster_cls=Cluster, workdir=None):
    """(results, g5_lines). workdir is where infra/, charts/ and the kubeconfig go (a new temp dir if None)."""
    results = [g1_sync(api, owner, repo, course), g6_writeup(api, owner, repo)]
    own_workdir = workdir is None
    workdir = workdir or tempfile.mkdtemp(prefix='lab10-check-')
    infra_dir, chart_dir = os.path.join(workdir, INFRA), os.path.join(workdir, *CHART.split('/'))
    os.makedirs(infra_dir, exist_ok=True)
    os.makedirs(chart_dir, exist_ok=True)
    with open(os.path.join(workdir, 'tofu.rc'), 'w', encoding='utf-8') as f:     # TF_CLI_CONFIG_FILE (isolate_env)
        f.write(CLI_CONFIG)
    tofu, cluster = tofu_cls(infra_dir, runner, workdir), cluster_cls(workdir, runner)
    applied = False
    try:
        try:
            tree = fetch_tree(api, owner, repo)
            files = fetch_files(api, owner, repo, tree, INFRA, infra_dir, top_only=True)
            fetch_files(api, owner, repo, tree, CHART, chart_dir)
        except ApiError as err:
            return results + [Result(g, 'unknown', [str(err)]) for g in ('G2', 'G3', 'G4')], []
        texts = {}
        for name in files:
            with open(os.path.join(infra_dir, name), encoding='utf-8-sig', errors='replace') as f:
                texts[name] = f.read()
        blocks, errors = [], []
        for name in sorted(n for n in texts if n.endswith('.tf')):
            try:
                blocks += [(name, b) for b in scan_hcl(texts[name], name)]
            except HclError as err:
                errors.append(str(err))
        refusals, blockers = allowlist(files, blocks, errors, texts=texts)
        static = static_problems(blocks, texts) if files and not errors else []
        lock = lock_problems(texts.get('.terraform.lock.hcl')) if files else []
        fmt = init = validate = plan = None
        if files and not refusals and not blockers:
            log('tofu fmt, init, validate and plan (the first run downloads about 170 MB of providers)…')
            fmt, init = tofu.fmt(), tofu.init()
            if init[0] == 0:
                refusals = installed_refusals(infra_dir)
                if not refusals:
                    validate = tofu.validate()
                    if validate[0] == 0:
                        plan = tofu.plan_json()
                        if plan[0] == 0 and plan[2] is not None:
                            refusals = plan_refusals(plan[2])
        g2 = g2_infra(files, refusals, blockers, static, lock, fmt, init, validate, plan)
        if not files:
            g3 = Result('G3', 'fail', ['Nothing to apply yet.'])
        elif refusals:
            g3 = Result('G3', 'unknown', ['Not run: see G2. The grader refuses the same.'])
        elif blockers:
            g3 = Result('G3', 'fail', ['Not run: fix G2 first. Nothing was run.'])
        elif not plan or plan[0] != 0 or plan[2] is None:
            g3 = Result('G3', 'fail', ['Not run: tofu init, validate or plan fails (see G2), so tofu apply would fail '
                                       'the same way.'])
        elif g3_blockers(plan[2]):
            g3 = Result('G3', 'fail', [f'Not run: {"; ".join(g3_blockers(plan[2]))} (see G2).'])
        elif not fresh:
            g3 = Result('G3', 'unknown', ['Skipped (--no-fresh). Run without it before you submit.'])
        elif cluster.others():
            g3 = Result('G3', 'unknown', [
                f'Not run: the kind cluster {", ".join(cluster.others())} is running. A second cluster next to it fails '
                'for the wrong reason (a Linux limit: "too many open files"), so the check builds its own only when '
                'no other kind cluster runs.',
                'In infra/: tofu destroy (about 15 s), run check.sh again, then tofu apply. A cluster you made with '
                'kind: kind delete cluster --name <name>.'])
        else:
            if cluster.listed():
                log(f'{CLUSTER} is left over from an earlier run: deleting it first…')
                cluster.delete()
            log(f'tofu apply from zero ({CLUSTER}), the app, tofu plan, tofu destroy, tofu apply again '
                '(about 5 minutes)…')
            applied = True
            g3 = g3_fresh(tofu, cluster)
        return results + [g2, g3, g4_breakfix(api, owner, repo, g2.status)], committed_secrets(tree)
    finally:
        if applied:
            log(f'tofu destroy ({CLUSTER})…')
            tofu.destroy()
            if cluster.listed():
                cluster.delete()
        if own_workdir:
            shutil.rmtree(workdir, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='check.sh', description='Lab 10 self-check: reads your fork, plans infra/ '
                                     'and builds it from zero on a throwaway cluster.')
    parser.add_argument('--repo', help='your fork as OWNER/NAME (default: taken from git remote origin)')
    parser.add_argument('--token-stdin', action='store_true', help='read a GitHub token from standard input')
    parser.add_argument('--no-fresh', action='store_true', help="don't build the throwaway cluster (G3 is skipped)")
    parser.add_argument('--course', default=COURSE, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    fork = args.repo or repo_from_origin()
    if not fork or not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9._-]+', fork):
        print('✘ I could not tell which fork to check. Run it in your clone, or add --repo <you>/turiba-devops-labs')
        return 2
    if fork.lower() == COURSE.lower():
        print("✘ origin points to the course repo, not to your fork. Add --repo <you>/turiba-devops-labs")
        return 2
    tools = ('tofu',) if args.no_fresh else ('tofu', 'kind', 'kubectl', 'docker')
    for tool in tools:
        if shutil.which(tool) is None:
            where = '"Before Lab 10"' if tool == 'tofu' else '"Before Lab 7"'
            print(f'✘ {tool} is missing. See {where} in the course README.')
            return 2
    if not args.no_fresh:
        print(f'This builds its own kind cluster, {CLUSTER}, from your infra/ for about 5 minutes (about 1.5 GB of memory),\n'
              'then destroys it. It does that only when no other kind cluster runs: tofu destroy yours first.\n'
              'Your state, your kubectl context and ~/.kube/config are not touched. --no-fresh skips the cluster part.')
    owner, repo = fork.split('/')
    token = find_token(args.token_stdin)
    workdir = tempfile.mkdtemp(prefix='lab10-check-')
    cache = os.path.expanduser(PLUGIN_CACHE)
    os.makedirs(cache, exist_ok=True)
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(isolate_env(saved, workdir, cache))   # KUBECONFIG = <workdir>/kubeconfig, as Cluster uses
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(130))
    try:
        results, g5_lines = check_all(Api(token), owner, repo, args.course, not args.no_fresh, workdir=workdir)
    except KeyboardInterrupt:
        print(f'\nStopped. If {CLUSTER} is still there: kind delete cluster --name {CLUSTER}')
        return 130
    finally:
        os.environ.clear()
        os.environ.update(saved)
        shutil.rmtree(workdir, ignore_errors=True)
    report(fork, results, bool(token), g5_lines)
    return 0 if all(r.status == 'pass' for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
