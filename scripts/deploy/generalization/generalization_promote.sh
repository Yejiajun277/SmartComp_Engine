#!/bin/sh
# Reviewable competitor-only release. Run on the server; never source this file.
set -eu
exec sudo -n python3 - "$@" <<'PY'
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import time
import urllib.request

STAGE = Path('/home/ubuntu/maintenance/smartcomp-generalization-20261101-target')
SOURCE = Path('/opt/apps/smartcomp')
CANDIDATE = STAGE / 'candidate'
OUTPUT = SOURCE / 'output'
STATE = STAGE / 'promotion-state.json'
TAG = 'smartcomp-engine-smartcomp-app:generalization-20261101-target'
ROLLBACK = 'smartcomp-engine-smartcomp-app:pre-generalization-20261101-target'
LATEST = 'smartcomp-engine-smartcomp-app:latest'
ORIGINAL = 'sha256:0e347bb6969e0b4bcb8c558582ffb78c29e922740e5c9e818dd2cac58c2eaa11'
COMPOSE = ['sudo', '-n', 'docker', 'compose', '-p', 'smartcomp-engine',
           '-f', str(SOURCE / 'docker-compose.yml'),
           '-f', str(SOURCE / 'docker-compose.production.yml')]

def run(argv):
    return subprocess.check_output(argv, text=True, stderr=subprocess.STDOUT).strip()

def docker(*argv):
    return run(['sudo', '-n', 'docker', *argv])

def inspect(name):
    return json.loads(docker('inspect', name))[0]

def fetch(port, path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=15) as response:
        if 'application/json' not in response.headers.get('Content-Type', ''):
            raise RuntimeError('Expected JSON at ' + path)
        return json.load(response)

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()

def safe(root, relative):
    value = PurePosixPath(relative)
    require(not value.is_absolute() and value.parts and
            all(p not in ('.', '..', '.env', '.git', 'output') for p in value.parts)
            and '\\' not in relative and ':' not in relative,
            'Unsafe source member: ' + relative)
    path = root.joinpath(*value.parts)
    require(root.resolve() in path.resolve().parents, 'Path escaped root')
    cursor = path
    while cursor != root:
        require(not cursor.is_symlink(), 'Symlink refused: ' + str(cursor))
        cursor = cursor.parent
    return path

def fingerprint(root):
    result = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'Output symlink refused: ' + str(path))
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path)
    return result

def preserved(before):
    for relative, expected in before.items():
        path = OUTPUT / relative
        require(path.is_file() and digest(path) == expected,
                'Existing history changed: ' + relative)

def no_active():
    tasks = fetch(8000, '/api/tasks')
    require(isinstance(tasks, list), 'Unexpected task list')
    require(all(t['status'] in ('completed', 'failed', 'cancelled') for t in tasks),
            'Active/unknown production tasks; postpone release')
    return {t['id']: t['status'] for t in tasks}

def atomic_json(path, value):
    temp = path.with_name(path.name + '.writing')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    os.replace(temp, path)

def wait_health(port):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            if fetch(port, '/api/health') == {'status': 'ok'}:
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError(f'Health timeout on {port}')

def city_check(city_before):
    city = inspect('ai-city-dm')
    require(city['Image'] == city_before['image'] and
            city['State']['StartedAt'] == city_before['started_at'],
            'City container changed')
    require(city['State']['Status'] == 'running' and
            city['State'].get('Health', {}).get('Status') == 'healthy',
            'City health changed')
    require(fetch(18080, '/api/health') == {'status': 'ok'}, 'City API unhealthy')

# Preflight is read-only. Do not overwrite an earlier promotion/rollback record.
require(not STATE.exists(), 'Promotion state already exists; review it before another release')
require(SOURCE.is_dir() and not SOURCE.is_symlink(), 'Unexpected source directory')
manifest_path = CANDIDATE / 'candidate-manifest.json'
manifest = json.loads(manifest_path.read_text())
rows = manifest['files']
image_listed = {row['path']: row['sha256'] for row in rows}
require(len(image_listed) == len(rows), 'Duplicate image manifest entries')
listed = image_listed
require(str(manifest.get('baseline', '')).startswith('3621d6f'), 'Unexpected user-change baseline')
require(str(manifest.get('previous_commit', '')).startswith('d13266e1'), 'Unexpected production commit')
runtime = manifest['runtime']
require(runtime and len(set(runtime)) == len(runtime), 'Invalid runtime file list')
for relative, expected in listed.items():
    path = safe(CANDIDATE, relative)
    require(path.is_file() and digest(path) == expected, 'Candidate hash mismatch: ' + relative)
for relative in runtime:
    require(relative in listed and PurePosixPath(relative).parts[0] in
            {'agents', 'core', 'models', 'prompts', 'workflow', 'server', 'frontend', 'tests', 'scripts', 'docs', 'CHANGELOG.md', 'README.md'},
            'Unapproved runtime member: ' + relative)
    safe(SOURCE, relative)

accepted = json.loads((STAGE / 'generalization-acceptance.json').read_text())
candidate_image = json.loads(docker('image', 'inspect', TAG))[0]
candidate_id = candidate_image['Id']
commit = manifest.get('commit', '')
require(len(commit) == 40 and all(c in '0123456789abcdef' for c in commit), 'Expected explicit GitHub SHA')
require(candidate_image['Config'].get('Labels', {}).get('org.opencontainers.image.revision') == commit,
        'Candidate image commit label mismatch')
require(accepted.get('commit') == commit and accepted.get('manifest_sha256') == digest(manifest_path),
        'Acceptance commit/manifest mismatch')
staged = json.loads((STAGE / 'stage-state.json').read_text())
require(staged['commit'] == commit and staged['candidate_image'] == candidate_id and
        staged['manifest_sha256'] == digest(manifest_path), 'Stage record mismatch')
require(accepted.get('pass') is True and accepted.get('candidate_image') == candidate_id,
        'Acceptance does not pass for this exact image')
test_container = inspect('smartcomp-generalization-target-e2e')
require(test_container['Image'] == candidate_id, 'E2E container is not the accepted image')
require(test_container['State']['Status'] == 'running', 'E2E container stopped')
require(len(test_container['Mounts']) == 1 and
        test_container['Mounts'][0]['Destination'] == '/app/output' and
        test_container['Mounts'][0]['Source'] == str(OUTPUT) and
        test_container['Mounts'][0]['RW'] is False,
        'E2E output must be the production bind mounted read-only')
require(fetch(18081, '/api/health') == {'status': 'ok'}, 'Candidate unhealthy')
image_hashes = json.loads(docker('exec', 'smartcomp-generalization-target-e2e', 'python', '-c',
    'import hashlib,json,pathlib; files=json.loads(' + repr(json.dumps(list(image_listed))) + '); '
    'print(json.dumps({p:hashlib.sha256((pathlib.Path("/app")/p).read_bytes()).hexdigest() for p in files}))'))
require(image_hashes == image_listed, 'Candidate image contents differ from manifest')
production = inspect('smartcomp-app')
require(production['Image'] == ORIGINAL, 'Production image changed since baseline')
require(json.loads(docker('image', 'inspect', ROLLBACK))[0]['Id'] == ORIGINAL,
        'Rollback tag changed')
city = inspect('ai-city-dm')
require(city['Image'] == 'sha256:2eb8ea3ee70f7ec805c3930bd9085cc002550891c07e8ccfdd855dfc58432f99',
        'Unexpected city baseline image')
city_before = {'image': city['Image'], 'started_at': city['State']['StartedAt']}
city_check(city_before)
tasks_before = no_active()
before = fingerprint(OUTPUT)
run(COMPOSE + ['config', '-q'])

backup = STAGE / ('promotion-backup-' + time.strftime('%Y%m%d-%H%M%S'))
backup.mkdir(exist_ok=False)
source_before = {}
for relative in runtime:
    source = safe(SOURCE, relative)
    require(not source.exists() or source.is_file(), 'Unexpected source type: ' + relative)
    if source.exists():
        target = safe(backup, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        source_before[relative] = digest(source)
    else:
        source_before[relative] = None
state = {'status': 'prepared', 'backup': str(backup), 'old_image': ORIGINAL,
         'candidate_image': candidate_id, 'commit': commit, 'manifest_sha256': digest(manifest_path),
         'source_before': source_before, 'source_after': {p: listed[p] for p in runtime},
         'history_before': before, 'tasks_before': tasks_before, 'city_before': city_before,
         'production_mounts': production['Mounts']}
atomic_json(STATE, state)

def restore_source():
    # Validate the entire restore first. Never remove or replace a later user edit.
    for relative, expected in source_before.items():
        current = safe(SOURCE, relative)
        saved = safe(backup, relative)
        if expected is not None:
            require(saved.is_file() and digest(saved) == expected,
                    'Rollback source backup damaged: ' + relative)
            require(current.is_file() and digest(current) in (expected, listed[relative]),
                    'Source changed after release: ' + relative)
        else:
            require(not saved.exists(), 'Unexpected backup for newly introduced source')
            require(not current.exists() or
                    (current.is_file() and digest(current) == listed[relative]),
                    'New source changed after release; refuse removal: ' + relative)
    for relative, expected in source_before.items():
        current = safe(SOURCE, relative)
        if expected is None:
            if current.exists():
                current.unlink()
        else:
            shutil.copy2(safe(backup, relative), current)

def rollback():
    # Never restore output from a snapshot: existing history is authoritative.
    restore_source()
    docker('image', 'tag', ORIGINAL, LATEST)
    run(COMPOSE + ['up', '-d', '--no-build', '--no-deps', '--force-recreate',
                   '--wait', '--wait-timeout', '120', 'smartcomp-app'])
    wait_health(8000)
    preserved(before)
    city_check(city_before)
    state['status'] = 'rolled_back'
    atomic_json(STATE, state)

try:
    for relative in runtime:
        destination = safe(SOURCE, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(safe(CANDIDATE, relative), destination)
    state['status'] = 'source_updated'
    atomic_json(STATE, state)
    no_active()  # Recheck immediately before container replacement.
    preserved(before)
    docker('image', 'tag', candidate_id, LATEST)
    state['status'] = 'switching'
    atomic_json(STATE, state)
    run(COMPOSE + ['up', '-d', '--no-build', '--no-deps', '--force-recreate',
                   '--wait', '--wait-timeout', '120', 'smartcomp-app'])
    wait_health(8000)
    current = inspect('smartcomp-app')
    require(current['Image'] == candidate_id, 'Wrong promoted image')
    require(current['Mounts'] == production['Mounts'], 'Production output mount changed')
    require(fetch(80, '/smartcomp/api/health') == {'status': 'ok'}, 'Nginx health failed')
    tasks_after = {t['id']: t['status'] for t in fetch(8000, '/api/tasks')}
    require(all(tasks_after.get(k) == v for k, v in tasks_before.items()), 'Old task states changed')
    preserved(before)
    city_check(city_before)
    for relative in runtime:
        require(digest(safe(SOURCE, relative)) == listed[relative], 'Promoted source differs')
    state['status'] = 'passed'
    atomic_json(STATE, state)
    print(json.dumps({'pass': True, 'image': candidate_id, 'history_preserved': len(before),
                      'state': str(STATE)}))
except BaseException as exc:
    state['failure'] = str(exc)
    try:
        atomic_json(STATE, state)
    except OSError:
        pass  # A journal write failure must not prevent source/image rollback.
    try:
        # Before switching, avoid restarting production (especially if tasks appeared).
        if state['status'] in ('prepared', 'source_updated'):
            restore_source()
            docker('image', 'tag', ORIGINAL, LATEST)
            state['status'] = 'source_restored_without_restart'
            atomic_json(STATE, state)
        else:
            rollback()
    except BaseException as rollback_exc:
        state['rollback_failure'] = str(rollback_exc)
        atomic_json(STATE, state)
    raise
PY
