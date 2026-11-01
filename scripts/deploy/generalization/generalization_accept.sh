#!/bin/sh
# Offline tests use a disposable container; historical APIs remain GET-only.
set -eu
exec sudo -n python3 - <<'PY'
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote
import urllib.request

stage = Path('/home/ubuntu/maintenance/smartcomp-generalization-20261101-target')
output = Path('/opt/apps/smartcomp/output')
staged = json.loads((stage / 'stage-state.json').read_text())
manifest_path = stage / 'candidate/candidate-manifest.json'
manifest = json.loads(manifest_path.read_text())
acceptance_path = stage / 'generalization-acceptance.json'

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def docker(*args):
    return subprocess.check_output(['sudo', '-n', 'docker', *args], text=True,
                                   stderr=subprocess.STDOUT).strip()

def inspect(name):
    return json.loads(docker('inspect', name))[0]

def get(port, path, as_json=True):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=20) as response:
        content_type = response.headers.get('Content-Type', '')
        require(('application/json' if as_json else 'text/html') in content_type, 'Wrong response type')
        return json.load(response) if as_json else response.read().decode('utf-8')

def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as inp:
        for block in iter(lambda: inp.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()

def json_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()

class ReportScan(HTMLParser):
    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.links = []
        self.text = []
        self.hidden = 0
        self.feed(markup)
        self.close()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.ids.add(attrs['id'])
        if tag == 'a' and attrs.get('name'):
            self.ids.add(attrs['name'])
        if tag == 'a' and attrs.get('href', '').startswith('#'):
            self.links.append(unquote(attrs['href'][1:]))
        if tag in ('script', 'style'):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, text):
        if not self.hidden:
            self.text.append(text)

    def verify(self):
        require(not [target for target in self.links if target and target not in self.ids],
                'Broken internal report anchor')
        raw = re.findall(r'\[[^\[\]\r\n<>]+:(?:q\d+|intro_sup_\d+|sup_[a-z_]+_\d+):r\d+[^\[\]\r\n<>]*\]',
                         ''.join(self.text))
        require(not raw, 'Visible raw citation identifiers remain')

require(not acceptance_path.exists(), 'Acceptance record exists; refuse overwrite')
manifest_sha = digest(manifest_path)
require(manifest_sha == staged['manifest_sha256'] and manifest['commit'] == staged['commit'],
        'Staged manifest changed')
candidate = inspect('smartcomp-generalization-target-e2e')
image = staged['candidate_image']
require(candidate['Image'] == image and
        candidate['Config'].get('Labels', {}).get('org.opencontainers.image.revision') == staged['commit'],
        'Candidate image/SHA mismatch')
require(len(candidate['Mounts']) == 1 and candidate['Mounts'][0]['Source'] == str(output) and
        candidate['Mounts'][0]['Destination'] == '/app/output' and candidate['Mounts'][0]['RW'] is False,
        'Candidate history mount must remain read-only')
require(inspect('smartcomp-app')['Image'] == staged['baseline_image'], 'Production changed before acceptance')
require(get(8000, '/api/health') == {'status': 'ok'} and get(18081, '/api/health') == {'status': 'ok'},
        'Production/candidate health failed')
rows = get(8000, '/api/tasks')
require(all(t['status'] in ('completed', 'failed', 'cancelled') for t in rows), 'Active production tasks')
expected = {r['path']: r['sha256'] for r in manifest['files']}
code = ('import hashlib,json,pathlib; files=json.loads(' + repr(json.dumps(list(expected))) + '); '
        'print(json.dumps({p:hashlib.sha256((pathlib.Path("/app")/p).read_bytes()).hexdigest() for p in files}))')
actual = json.loads(docker('exec', 'smartcomp-generalization-target-e2e', 'python', '-c', code))
require(actual == expected, 'Candidate image contents differ from approved GitHub manifest')

# Bind offline Linux suite evidence to this exact image, SHA, manifest and log.
test_record_path = stage / 'linux-tests.json'
test_log_path = stage / 'generalization-target-linux-tests.log'
if test_record_path.exists():
    tests = json.loads(test_record_path.read_text())
else:
    with test_log_path.open('x') as log:
        result = subprocess.run(['sudo', '-n', 'docker', 'run', '--rm', '--network', 'none',
                                 '--name', 'generalization-target-linux-tests',
                                 '--tmpfs', '/app/output:rw,mode=1777',
                                 '-e', 'PYTHONDONTWRITEBYTECODE=1', image,
                                 'python', '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
                                stdout=log, stderr=subprocess.STDOUT)
    text = test_log_path.read_text(errors='replace')
    counts = re.findall(r'Ran (\d+) tests? in ', text)
    tests = {'pass': result.returncode == 0 and bool(counts) and int(counts[-1]) > 0,
             'returncode': result.returncode, 'test_count': int(counts[-1]) if counts else 0,
             'candidate_image': image, 'commit': staged['commit'], 'manifest_sha256': manifest_sha,
             'log_sha256': digest(test_log_path), 'production_output_mounted': False}
    with test_record_path.open('x') as handle:
        json.dump(tests, handle, indent=2)
require(tests.get('pass') is True and tests.get('returncode') == 0 and tests.get('test_count', 0) > 0 and
        tests.get('candidate_image') == image and tests.get('commit') == staged['commit'] and
        tests.get('manifest_sha256') == manifest_sha and tests.get('log_sha256') == digest(test_log_path) and
        tests.get('production_output_mounted') is False, 'Offline Linux suite did not pass for this exact release')

complete = {t['id'] for t in rows if t['status'] == 'completed'}
selected = [i for i in ('3c8db547', '12a5277c') if i in complete]
selected += [i for i in sorted(complete) if i not in selected][:3-len(selected)]
require(len(selected) == 3, 'Need three completed historical reports')
comparisons = []
for task_id in selected:
    path = '/api/tasks/' + task_id
    production_report = get(8000, path + '/report')
    candidate_report = get(18081, path + '/report')
    require(production_report == candidate_report, 'Historical report JSON changed: ' + task_id)
    production_facts = get(8000, path + '/artifacts/collection')
    require(production_facts == get(18081, path + '/artifacts/collection'),
            'Historical collection facts changed: ' + task_id)
    ReportScan(get(18081, path + '/report.html', as_json=False)).verify()
    comparisons.append({'task_id': task_id, 'report_json_sha256': json_hash(production_report),
                        'collection_facts_sha256': json_hash(production_facts),
                        'raw_visible_citations': 0, 'broken_internal_anchors': 0})
for relative, expected_hash in staged['history_before'].items():
    path = output / relative
    require(path.is_file() and digest(path) == expected_hash, 'Historical output changed: ' + relative)
city = inspect('ai-city-dm')
require(city['Image'] == staged['city_image'] and city['State']['StartedAt'] == staged['city_started_at'] and
        city['State'].get('Health', {}).get('Status') == 'healthy' and
        get(18080, '/api/health') == {'status': 'ok'}, 'City changed')
require(inspect('smartcomp-app')['Image'] == staged['baseline_image'], 'Production changed during acceptance')
acceptance = {'pass': True, 'commit': staged['commit'], 'candidate_image': image,
              'manifest_sha256': manifest_sha, 'linux_tests': tests,
              'historical_comparisons': comparisons, 'history_files_preserved': len(staged['history_before']),
              'live_case_qa_rule': {'attempt': 'final_per_phase', 'passed': True, 'degraded': False,
                                   'hallucination_status': ['passed', 'found'], 'critical_issues': 0},
              'source_origin': staged['source_origin'], 'source_archive_sha256': staged['source_archive_sha256']}
with acceptance_path.open('x') as handle:
    json.dump(acceptance, handle, ensure_ascii=False, indent=2)
print(json.dumps({'pass': True, 'commit': staged['commit'], 'candidate_image': image,
                  'test_count': tests['test_count'], 'historical_task_ids': selected}))
PY
