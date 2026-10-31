#!/bin/sh
# Restore the saved competitor image and changed sources only. No output rollback.
set -eu
exec sudo -n python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request

stage = Path('/home/ubuntu/maintenance/smartcomp-generalization-20261101-sources')
source = Path('/opt/apps/smartcomp')
record = stage / 'promotion-state.json'
state = json.loads(record.read_text())
backup = Path(state['backup'])
assert backup.parent == stage and backup.name.startswith('promotion-backup-')
assert state['old_image'] == 'sha256:c50a4cfe2a32fd673992ea877b47f41712764b768b62c3120c3e152b2c8b0781'

def run(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()

def docker(*args):
    return run(['sudo', '-n', 'docker', *args])

def fetch(port, path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=15) as response:
        return json.load(response)

def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as inp:
        for block in iter(lambda: inp.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()

tasks = fetch(8000, '/api/tasks')
assert all(t['status'] in ('completed', 'failed', 'cancelled') for t in tasks), 'Active tasks; postpone rollback'
current = json.loads(docker('inspect', 'smartcomp-app'))[0]
assert current['Image'] in (state['old_image'], state['candidate_image']), 'Another release is running'
for relative, expected in state['source_before'].items():
    src = backup / relative
    dst = source / relative
    assert backup.resolve() in src.resolve().parents and source.resolve() in dst.resolve().parents
    # Reject symlink ancestors too, including parents of newly introduced files.
    for root, path in ((backup, src), (source, dst)):
        cursor = path
        while cursor != root:
            assert not cursor.is_symlink(), 'Source symlink refused'
            cursor = cursor.parent
    if expected is None:
        assert not src.exists(), 'Unexpected backup for new source'
        assert not dst.exists() or (dst.is_file() and digest(dst) == state['source_after'][relative]), \
            'New source changed after release; refuse removal'
    else:
        assert src.is_file() and digest(src) == expected, 'Source backup damaged'
        assert dst.is_file() and digest(dst) in (expected, state['source_after'][relative]), \
            'Source changed after release'
for relative, expected in state['source_before'].items():
    dst = source / relative
    if expected is None:
        if dst.exists():
            dst.unlink()
    else:
        shutil.copy2(backup / relative, dst)
docker('image', 'tag', state['old_image'], 'smartcomp-engine-smartcomp-app:latest')
run(['sudo', '-n', 'docker', 'compose', '-p', 'smartcomp-engine',
     '-f', str(source / 'docker-compose.yml'), '-f', str(source / 'docker-compose.production.yml'),
     'up', '-d', '--no-build', '--no-deps', '--force-recreate', '--wait', '--wait-timeout', '120', 'smartcomp-app'])
assert fetch(8000, '/api/health') == {'status': 'ok'}
assert fetch(80, '/smartcomp/api/health') == {'status': 'ok'}
restored = json.loads(docker('inspect', 'smartcomp-app'))[0]
assert restored['Image'] == state['old_image'], 'Rollback image mismatch'
assert restored['Mounts'] == state['production_mounts'], 'Production output mount changed'
task_statuses = {t['id']: t['status'] for t in fetch(8000, '/api/tasks')}
assert all(task_statuses.get(k) == v for k, v in state['tasks_before'].items()), 'Historical task status changed'
for relative, expected in state['history_before'].items():
    path = source / 'output' / relative
    assert path.is_file() and digest(path) == expected, 'Existing history changed: ' + relative
city = json.loads(docker('inspect', 'ai-city-dm'))[0]
assert city['Image'] == state['city_before']['image']
assert city['State']['StartedAt'] == state['city_before']['started_at']
assert city['State'].get('Health', {}).get('Status') == 'healthy'
assert fetch(18080, '/api/health') == {'status': 'ok'}
state['status'] = 'rolled_back'
temp = record.with_name(record.name + '.writing')
temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
os.replace(temp, record)
print(json.dumps({'rolled_back': True, 'image': state['old_image'],
                  'note': 'No output or historical report files modified'}))
PY
