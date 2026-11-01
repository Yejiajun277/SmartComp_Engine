#!/bin/sh
# Build a competitor-only layer and start read-only historical-report validation.
# Upload generalization-manifest.json first. Optional fallback: source.git-archive.tar.gz.
set -eu
exec sudo -n python3 - <<'PY'
import hashlib
import json
import shutil
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import time
import urllib.request

STAGE = Path('/home/ubuntu/maintenance/smartcomp-generalization-20261101-context')
SOURCE = Path('/opt/apps/smartcomp')
BASE = 'sha256:c0b07ac7a535f7b033f5bec8454245b60e0cd2f0030bfa6064aa1e3520cbe2d8'
CITY = 'sha256:2eb8ea3ee70f7ec805c3930bd9085cc002550891c07e8ccfdd855dfc58432f99'
ROLLBACK = 'smartcomp-engine-smartcomp-app:pre-generalization-20261101-context'
TAG = 'smartcomp-engine-smartcomp-app:generalization-20261101-context'
CONTAINER = 'smartcomp-generalization-context-e2e'

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def docker(*args):
    return subprocess.check_output(['sudo', '-n', 'docker', *args], text=True,
                                   stderr=subprocess.STDOUT).strip()

def inspect(name):
    return json.loads(docker('inspect', name))[0]

def api(port, path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=15) as response:
        require('application/json' in response.headers.get('Content-Type', ''), 'Expected JSON')
        return json.load(response)

def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()

def history():
    result = {}
    for p in sorted((SOURCE / 'output').rglob('*')):
        require(not p.is_symlink(), 'Historical output symlink refused')
        if p.is_file():
            result[p.relative_to(SOURCE / 'output').as_posix()] = digest(p)
    return result

require(STAGE.is_dir() and not STAGE.is_symlink(), 'Unexpected staging directory')
require(not (STAGE / 'stage-state.json').exists(), 'Stage record exists; review before rerun')
require(not (STAGE / 'candidate').exists(), 'Candidate directory exists; refuse overwrite')
production = inspect('smartcomp-app')
city = inspect('ai-city-dm')
require(production['Image'] == BASE, 'Production changed since generalization baseline')
require(city['Image'] == CITY and city['State'].get('Health', {}).get('Status') == 'healthy',
        'City baseline unhealthy or changed')
require(api(8000, '/api/health') == {'status': 'ok'} and
        api(18080, '/api/health') == {'status': 'ok'}, 'Production health failed')
require(all(t['status'] in ('completed', 'failed', 'cancelled')
            for t in api(8000, '/api/tasks')), 'Active production task; postpone staging')
require(not subprocess.run(['sudo', '-n', 'docker', 'container', 'inspect', CONTAINER],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0,
        'Candidate container exists; refuse replacement')
before = history()


manifest_path = STAGE / 'generalization-manifest.json'
manifest = json.loads(manifest_path.read_text())
require(manifest.get('repository') == 'Yejiajun277/SmartComp_Engine', 'Unexpected GitHub repository')
commit = manifest.get('commit', '')
require(len(commit) == 40 and all(c in '0123456789abcdef' for c in commit), 'Expected full GitHub SHA')
require(str(manifest.get('baseline', '')).startswith('3621d6f'), 'Wrong user-change baseline commit')
require(str(manifest.get('previous_commit', '')).startswith('bbf83317'), 'Wrong current-production commit')
rows = manifest['files']
files = {row['path']: row['sha256'] for row in rows}
require(len(files) == len(rows) and files, 'Invalid/duplicate manifest files')
require(manifest['runtime'] and len(set(manifest['runtime'])) == len(manifest['runtime']) and
        set(manifest['runtime']) <= files.keys(), 'Invalid runtime source list')
for relative in files:
    p = PurePosixPath(relative)
    require(not p.is_absolute() and p.parts and
            all(part not in ('.', '..', '.env', '.git', 'output', 'tmp', 'node_modules') for part in p.parts) and
            chr(92) not in relative and ':' not in relative and
            p.parts[0] in {'agents', 'core', 'models', 'prompts', 'workflow', 'server',
                           'frontend', 'tests', 'scripts', 'docs', 'CHANGELOG.md', 'README.md'},
            'Unsafe/unapproved manifest path: ' + relative)
archive_path = STAGE / 'source.github.tar.gz'
origin = 'github-codeload-exact-sha'
try:
    with urllib.request.urlopen(
            'https://codeload.github.com/Yejiajun277/SmartComp_Engine/tar.gz/' + commit,
            timeout=30) as response, archive_path.open('xb') as destination:
        shutil.copyfileobj(response, destination)
except Exception as exc:
    archive_path = STAGE / 'source.git-archive.tar.gz'
    require(archive_path.is_file(), 'GitHub download failed; provide same-commit git archive fallback (' +
            type(exc).__name__ + ')')
    origin = 'uploaded-git-archive-exact-sha'
with tarfile.open(archive_path) as archive:
    if origin == 'uploaded-git-archive-exact-sha':
        require(archive.pax_headers.get('comment') == commit,
                'Fallback must be git archive of this exact SHA (pax commit comment)')
    selected = {}
    for member in archive.getmembers():
        raw = member.name.rstrip('/')
        choices = [raw, raw.split('/', 1)[1] if '/' in raw else '']
        relative = next((p for p in choices if p in files), None)
        if relative is None:
            continue
        require(relative not in selected and member.isfile(), 'Duplicate/nonregular selected source')
        selected[relative] = member
    require(set(selected) == set(files), 'GitHub archive is missing approved source files')
    candidate = STAGE / 'candidate'
    candidate.mkdir(exist_ok=False)
    for relative, member in selected.items():
        data = archive.extractfile(member).read()
        require(hashlib.sha256(data).hexdigest() == files[relative], 'Commit source hash mismatch: ' + relative)
        destination = candidate / relative
        require(candidate.resolve() in destination.resolve().parents, 'Archive escaped candidate')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as handle:
            handle.write(data)
    shutil.copyfile(manifest_path, candidate / 'candidate-manifest.json')

# Never overwrite a pre-existing rollback tag with a different image.
probe = subprocess.run(['sudo', '-n', 'docker', 'image', 'inspect', ROLLBACK],
                       capture_output=True, text=True)
if probe.returncode == 0:
    require(json.loads(probe.stdout)[0]['Id'] == BASE, 'Rollback tag points to another image')
else:
    docker('image', 'tag', BASE, ROLLBACK)
lines = ['FROM ' + ROLLBACK,
         'LABEL org.opencontainers.image.revision=' + json.dumps(commit),
         'LABEL org.opencontainers.image.source="https://github.com/Yejiajun277/SmartComp_Engine"',
         'LABEL smartcomp.baseline-image=' + json.dumps(BASE)]
for relative in files:
    # JSON COPY syntax handles valid filenames without Dockerfile interpolation.
    lines.append('COPY ' + json.dumps([relative, '/app/' + relative]))
(candidate / 'Dockerfile.generalization').write_text('\n'.join(lines) + '\n')
with (STAGE / 'generalization-build.log').open('x') as log:
    subprocess.run(['sudo', '-n', 'docker', 'build', '--pull=false',
                    '-f', str(candidate / 'Dockerfile.generalization'), '-t', TAG, str(candidate)],
                   stdout=log, stderr=subprocess.STDOUT, check=True)
candidate_id = json.loads(docker('image', 'inspect', TAG))[0]['Id']
docker('run', '-d', '--name', CONTAINER, '--env-file', str(SOURCE / '.env'),
       '-e', 'PYTHONUNBUFFERED=1', '-p', '127.0.0.1:18081:8000',
       '--mount', 'type=bind,src=' + str(SOURCE / 'output') + ',dst=/app/output,readonly', TAG)
deadline = time.monotonic() + 120
while time.monotonic() < deadline:
    try:
        if api(18081, '/api/health') == {'status': 'ok'}:
            break
    except Exception:
        pass
    time.sleep(2)
else:
    raise RuntimeError('Candidate API health timeout; production untouched')
c = inspect(CONTAINER)
require(c['Image'] == candidate_id and len(c['Mounts']) == 1 and
        c['Mounts'][0]['Source'] == str(SOURCE / 'output') and
        c['Mounts'][0]['Destination'] == '/app/output' and c['Mounts'][0]['RW'] is False,
        'Candidate mount/image mismatch')
require(history() == before, 'Historical output changed during staging')
require(inspect('smartcomp-app')['Image'] == BASE, 'Production image changed')
after_city = inspect('ai-city-dm')
require(after_city['Image'] == CITY and
        after_city['State']['StartedAt'] == city['State']['StartedAt'] and
        api(18080, '/api/health') == {'status': 'ok'}, 'City changed during staging')
record = {'candidate_image': candidate_id, 'baseline_image': BASE,
          'manifest_sha256': digest(candidate / 'candidate-manifest.json'), 'commit': commit,
          'source_origin': origin, 'source_archive_sha256': digest(archive_path),
          'baseline_commit': manifest['baseline'], 'previous_commit': manifest['previous_commit'],
          'history_before': before, 'city_image': CITY,
          'city_started_at': city['State']['StartedAt'], 'status': 'staged_read_only'}
with (STAGE / 'stage-state.json').open('x') as handle:
    json.dump(record, handle, indent=2)
print(json.dumps({'staged': True, 'candidate_image': candidate_id,
                  'production_output_read_only': True, 'history_files': len(before)}))
PY
