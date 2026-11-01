#!/bin/sh
# Import only two explicitly accepted, completed live cases. Never overwrite history.
set -eu
exec sudo -n python3 - <<'PY'
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import urllib.request

stage = Path('/home/ubuntu/maintenance/smartcomp-generalization-20261101-target')
source = Path('/opt/apps/smartcomp')
output = source / 'output'
state = json.loads((stage / 'promotion-state.json').read_text())
workers_state = json.loads((stage / 'workers-state.json').read_text())
accepted = json.loads((stage / 'generalization-live-acceptance.json').read_text())
record_path = stage / 'import-state.json'

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def docker(*args):
    return subprocess.check_output(['sudo', '-n', 'docker', *args], text=True,
                                   stderr=subprocess.STDOUT).strip()

def inspect(name):
    return json.loads(docker('inspect', name))[0]

def fetch(port, path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=15) as response:
        return json.load(response)

def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as inp:
        for block in iter(lambda: inp.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()

def fingerprint(root):
    result = {}
    require(not root.is_symlink(), 'Symlink root refused')
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'Symlink output refused')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path)
    return result

def city_unchanged():
    c = inspect('ai-city-dm')
    require(c['Image'] == state['city_before']['image'] and
            c['State']['StartedAt'] == state['city_before']['started_at'] and
            c['State'].get('Health', {}).get('Status') == 'healthy' and
            fetch(18080, '/api/health') == {'status': 'ok'}, 'City changed')

def no_active():
    rows = fetch(8000, '/api/tasks')
    require(all(t['status'] in ('completed', 'failed', 'cancelled') for t in rows),
            'Active production tasks; postpone import/reload')
    return {t['id']: t['status'] for t in rows}

def preserved(before):
    for relative, expected in before.items():
        path = output / relative
        require(path.is_file() and digest(path) == expected, 'Old history changed: ' + relative)

def save(record):
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')

require(not record_path.exists(), 'Import record exists; review before another attempt')
require(state['status'] == 'passed' and accepted.get('pass') is True, 'Release/live acceptance must pass')
for key in ('commit', 'candidate_image', 'manifest_sha256'):
    require(accepted.get(key) == state[key], 'Live acceptance mismatch: ' + key)
require(workers_state['commit'] == state['commit'] and workers_state['image'] == state['candidate_image'] and
        workers_state['manifest_sha256'] == state['manifest_sha256'], 'Worker provenance mismatch')
require(digest(stage / 'candidate/candidate-manifest.json') == state['manifest_sha256'], 'Manifest changed')
prod = inspect('smartcomp-app')
require(prod['Image'] == state['candidate_image'] and
        prod['Config'].get('Labels', {}).get('org.opencontainers.image.revision') == state['commit'],
        'Production is not the accepted GitHub SHA/image')
require(json.loads(docker('image', 'inspect', 'smartcomp-engine-smartcomp-app:latest'))[0]['Id'] ==
        state['candidate_image'], 'Latest tag changed; same-image reload would be unsafe')
city_unchanged()
tasks_before = no_active()
before = fingerprint(output)
rows = accepted.get('tasks', [])
require(len(rows) == 2 and {r['worker'] for r in rows} == {'generalization-vacuum-target', 'generalization-hotel-target'},
        'Require exactly the vacuum and hotel acceptances')
require(len({r['task_id'] for r in rows}) == 2, 'Acceptance task IDs must be unique')
workers = {w['name']: w for w in workers_state['workers']}
payload_copies = []
task_copies = []
destinations = set()
new_ids = []
for row in rows:
    require(row.get('pass') is True, 'Individual case acceptance failed')
    worker = workers[row['worker']]
    worker_output = Path(worker['output'])
    require(worker_output == stage / 'workers' / row['worker'] / 'output', 'Unexpected worker output')
    c = inspect(row['worker'])
    require(c['Image'] == state['candidate_image'] and
            c['Config'].get('Labels', {}).get('org.opencontainers.image.revision') == state['commit'] and
            len(c['Mounts']) == 1 and c['Mounts'][0]['Source'] == str(worker_output) and
            c['Mounts'][0]['Destination'] == '/app/output' and c['Mounts'][0]['RW'], 'Worker isolation changed')
    task_id = row['task_id']
    require(isinstance(task_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', task_id), 'Unsafe task ID')
    require(task_id not in tasks_before, 'Task already exists in production')
    summary = fetch(worker['port'], '/api/tasks/' + task_id)
    require(summary['status'] == 'completed' and summary['skip_qa'] is False and
            summary['use_rule_engine'] is False and summary['max_competitors'] == 3 and
            summary.get('llm_provider') == 'mimo' and not summary.get('error'),
            'Only completed real MiMo QA-on count3 cases may be imported')
    require(all(t['status'] in ('completed', 'failed', 'cancelled')
                for t in fetch(worker['port'], '/api/tasks')), 'Worker still has active jobs')
    task_file = worker_output / 'tasks' / (task_id + '.json')
    require(task_file.is_file() and not task_file.is_symlink(), 'Task snapshot missing/symlink')
    task = json.loads(task_file.read_text())
    require(task['id'] == task_id and task['status'] == 'completed' and task.get('report_json'),
            'Persisted task not completed or report missing')
    run = PurePosixPath(task['report_path'])
    require(run.parent == PurePosixPath('/app/output/runs') and
            re.fullmatch(r'[\w.-]{1,180}', run.name) and run.name not in ('.', '..'), 'Unsafe run path')
    html = PurePosixPath(task['html_report_path'])
    require(run in html.parents and '..' not in html.parts and chr(92) not in str(html), 'Unsafe HTML path')
    run_relative = Path('runs') / run.name
    run_source = worker_output / run_relative
    require(run_source.is_dir() and not run_source.is_symlink(), 'Run snapshot missing')
    run_hashes = fingerprint(run_source)
    require(run_hashes and (worker_output / Path(*html.parts[3:])).is_file(), 'Run/HTML incomplete')
    qa_file = run_source / 'qa_timeline.json'
    qa = json.loads(qa_file.read_text())
    final_checks = {}
    for check in qa.get('checks', []):
        previous = final_checks.get(check['phase'])
        if previous is None or check.get('attempt', 1) >= previous.get('attempt', 1):
            final_checks[check['phase']] = check
    require(set(final_checks) >= {'collection', 'product', 'pricing', 'market', 'strategy'},
            'Missing QA phases')
    require(all(c.get('passed') is True and c.get('degraded') is False for c in final_checks.values()),
            'Final QA contains failed/degraded checks; do not treat as passed')
    require(all(c.get('hallucination_status') in ('passed', 'found') for c in final_checks.values()),
            'Final hallucination check failed/skipped/missing; require completed live checks')
    require(all(not any(issue.get('severity') == 'critical' for issue in c.get('issues', []))
                for c in final_checks.values()), 'Final QA still contains a critical issue')
    require(fetch(worker['port'], '/api/tasks/' + task_id + '/report'), 'HTTP report unavailable')
    payload_copies.append((run_source, output / run_relative, run_hashes))
    event_source = task_file.with_name(task_id + '_events.jsonl')
    if event_source.exists():
        require(not event_source.is_symlink(), 'Event snapshot symlink')
        payload_copies.append((event_source, output / 'tasks' / event_source.name, digest(event_source)))
    task_copies.append((task_file, output / 'tasks' / task_file.name, digest(task_file)))
    new_ids.append(task_id)
for src, dest, expected in payload_copies + task_copies:
    require(dest not in destinations and not dest.exists() and not dest.is_symlink(),
            'Import destination exists or duplicates: ' + str(dest))
    require(output.resolve() in dest.resolve().parents, 'Import escaped production output')
    destinations.add(dest)
record = {'status': 'prepared', 'commit': state['commit'], 'candidate_image': state['candidate_image'],
          'manifest_sha256': state['manifest_sha256'], 'tasks': new_ids,
          'history_before': before, 'tasks_before': tasks_before, 'copied_paths': []}
save(record)
try:
    no_active()
    # Copy both complete run trees/events before making either task visible.
    for src, dest, expected in payload_copies + task_copies:
        require(not dest.exists() and not dest.is_symlink(), 'Destination appeared during import')
        if src.is_dir():
            require(fingerprint(src) == expected, 'Worker run changed after acceptance')
            shutil.copytree(src, dest, dirs_exist_ok=False)
            require(fingerprint(dest) == expected, 'Copied run differs')
        else:
            require(digest(src) == expected, 'Worker snapshot changed after acceptance')
            dest.parent.mkdir(parents=True, exist_ok=True)
            with src.open('rb') as inp, dest.open('xb') as out:
                shutil.copyfileobj(inp, out)
            require(digest(dest) == expected, 'Copied snapshot differs')
        record['copied_paths'].append(str(dest))
        save(record)
    preserved(before)
    no_active()
    require(inspect('smartcomp-app')['Image'] == state['candidate_image'], 'Production image changed')
    require(json.loads(docker('image', 'inspect', 'smartcomp-engine-smartcomp-app:latest'))[0]['Id'] ==
            state['candidate_image'], 'Latest tag changed before same-image reload')
    record['status'] = 'reloading_same_image'
    save(record)
    subprocess.run(['sudo', '-n', 'docker', 'compose', '-p', 'smartcomp-engine',
                    '-f', str(source / 'docker-compose.yml'), '-f', str(source / 'docker-compose.production.yml'),
                    'up', '-d', '--no-build', '--no-deps', '--force-recreate',
                    '--wait', '--wait-timeout', '120', 'smartcomp-app'], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    current = inspect('smartcomp-app')
    require(current['Image'] == state['candidate_image'] and current['Mounts'] == prod['Mounts'],
            'Image/mount changed while reloading history')
    require(fetch(8000, '/api/health') == {'status': 'ok'} and
            fetch(80, '/smartcomp/api/health') == {'status': 'ok'}, 'Production health failed')
    after = {t['id']: t['status'] for t in fetch(8000, '/api/tasks')}
    require(all(after.get(k) == v for k, v in tasks_before.items()), 'Old task status changed')
    require(all(after.get(k) == 'completed' for k in new_ids), 'Imported tasks not completed/loaded')
    for task_id in new_ids:
        require(fetch(8000, '/api/tasks/' + task_id + '/report'), 'Imported report missing')
    preserved(before)
    city_unchanged()
    record['status'] = 'passed'
    save(record)
    print(json.dumps({'imported': new_ids, 'history_preserved': len(before),
                      'image': state['candidate_image'], 'commit': state['commit']}))
except BaseException as exc:
    record['status'] = 'failed'
    record['error'] = str(exc)
    save(record)
    # Keep accepted artifacts and explicit failure journal; never delete history.
    raise
PY
