#!/bin/sh
# Starts independent processes only. Root submits one real QA-on task per worker.
set -eu
exec sudo -n python3 - <<'PY'
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.request

stage = Path('/home/ubuntu/maintenance/smartcomp-generalization-20261101')
source = Path('/opt/apps/smartcomp')
state = json.loads((stage / 'promotion-state.json').read_text())
manifest_path = stage / 'candidate/candidate-manifest.json'
def require(ok, message):
    if not ok:
        raise RuntimeError(message)
require(state['status'] == 'passed', 'Release must pass before workers start')
require(hashlib.sha256(manifest_path.read_bytes()).hexdigest() == state['manifest_sha256'], 'Manifest changed')

def docker(*args):
    return subprocess.check_output(['sudo', '-n', 'docker', *args], text=True,
                                   stderr=subprocess.STDOUT).strip()

def inspect(name):
    return json.loads(docker('inspect', name))[0]

def fetch(port, path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=15) as response:
        return json.load(response)

production = inspect('smartcomp-app')
require(production['Image'] == state['candidate_image'], 'Production is not the released image')
require(production['Config'].get('Labels', {}).get('org.opencontainers.image.revision') == state['commit'],
        'Production SHA label mismatch')
city = inspect('ai-city-dm')
require(city['Image'] == state['city_before']['image'] and
        city['State']['StartedAt'] == state['city_before']['started_at'] and
        fetch(18080, '/api/health') == {'status': 'ok'}, 'City changed')
record_path = stage / 'workers-state.json'
require(not record_path.exists(), 'Worker record exists; refuse replacement')
workers = [('generalization-vacuum', 18082), ('generalization-hotel', 18083)]
for name, _ in workers:
    require(subprocess.run(['sudo', '-n', 'docker', 'container', 'inspect', name],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0,
            'Worker container already exists: ' + name)
    require(not (stage / 'workers' / name).exists(), 'Worker directory exists: ' + name)
record = {'commit': state['commit'], 'image': state['candidate_image'],
          'manifest_sha256': state['manifest_sha256'], 'workers': []}
for name, port in workers:
    root = stage / 'workers' / name
    root.mkdir(parents=True, exist_ok=False)
    output = root / 'output'
    output.mkdir()
    docker('run', '-d', '--name', name, '--env-file', str(source / '.env'),
           '-e', 'PYTHONUNBUFFERED=1', '-p', f'127.0.0.1:{port}:8000',
           '--mount', f'type=bind,src={output},dst=/app/output', state['candidate_image'])
    container = inspect(name)
    require(container['Image'] == state['candidate_image'] and
            len(container['Mounts']) == 1 and container['Mounts'][0]['Source'] == str(output) and
            container['Mounts'][0]['Destination'] == '/app/output' and container['Mounts'][0]['RW'],
            'Worker image/output isolation mismatch')
    record['workers'].append({'name': name, 'port': port, 'output': str(output),
                              'image': state['candidate_image']})
    record_path.write_text(json.dumps(record, indent=2) + '\n')
for worker in record['workers']:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            if fetch(worker['port'], '/api/health') == {'status': 'ok'}:
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        raise RuntimeError('Worker unhealthy: ' + worker['name'])
    runtime = fetch(worker['port'], '/api/runtime')
    require(runtime['llm']['provider'] == 'mimo' and runtime['llm']['configured'] and
            runtime['search']['provider'] == 'tavily' and runtime['search']['configured'],
            'Worker live APIs not configured')
    require(fetch(worker['port'], '/api/tasks') == [], 'Worker must start with empty history')
require(inspect('smartcomp-app')['Image'] == state['candidate_image'], 'Production image changed')
print(json.dumps({'workers_ready': True, 'commit': state['commit'],
                  'image': state['candidate_image'], 'ports': [18082, 18083]}))
PY
