"""Release acceptance orchestration, never a producer of business results."""
from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


def source_fingerprint(root: Path = ROOT) -> str:
    paths = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', '.'], cwd=root).decode().split('\0')
    fingerprint = hashlib.sha256()
    for name in sorted(set(paths) - {''}):
        path = root / name
        fingerprint.update(name.encode())
        fingerprint.update(hashlib.sha256(path.read_bytes()).digest() if path.is_file() else b'DELETED')
    return fingerprint.hexdigest()


def coverage_report(tasks: dict, cases: dict) -> dict:
    requirements = {r for t in tasks['tasks'] if t.get('status') not in {'SUPERSEDED', 'OUT_OF_SCOPE'} for r in t.get('requirements', [])}
    active = [c for c in cases['cases'] + cases['end_to_end'] if c['status'] not in {'SUPERSEDED', 'OUT_OF_SCOPE'}]
    covered = {r for c in active for r in c.get('requirements', [])} | {c['id'] for c in active}
    return {
        'requirements_without_cases': sorted(requirements - covered),
        'not_passed': [{'id': c['id'], 'status': c['status']} for c in active if c['status'] != 'PASS'],
        'pass_without_evidence': [c['id'] for c in active if c['status'] == 'PASS' and not c.get('evidence')],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--checks-only', action='store_true', help='Run engineering checks without claiming complete product acceptance')
    parser.add_argument('--coverage-only', action='store_true')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = ROOT / 'backend/artifacts/acceptance' / stamp
    out.mkdir(parents=True, exist_ok=False)
    git = lambda *a: subprocess.check_output(['git', *a], cwd=ROOT, text=True).strip()
    report = {'batch': stamp, 'commit': git('rev-parse', 'HEAD'), 'worktree': git('status', '--short'),
              'source_fingerprint': source_fingerprint(), 'commands': [], 'external_calls_authorized': False, 'scope': 'OFFLINE', 'finished': False}
    commands = [] if args.coverage_only else [
        ('backend', [sys.executable, '-m', 'pytest', 'tests/test_release_first_slice.py',
                     'tests/test_single_prompt_v2_execution.py', 'tests/test_single_prompt_v2_optimize_delivery.py',
                     'tests/test_single_prompt_v2_delivery_navigation.py', 'tests/test_single_prompt_v2_strategy.py',
                     'tests/test_delivery_acceptance.py', '-q', '--disable-warnings', '--tb=short',
                     'tests/test_observation_delivery.py', 'tests/test_release_scheduling.py',
                     'tests/test_release_access.py', 'tests/test_release_worker_lifecycle.py',
                     'tests/test_automatic_contribution.py', 'tests/test_single_prompt_v2_qualification.py',
                     'tests/test_delivery_generation.py', 'tests/test_deepseek_generation_contract.py',
                     'tests/test_automatic_delivery.py',
                     'tests/test_scheduled_optimization.py',
                     'tests/test_private_site_contract.py',
                     f'--junitxml={out / "backend.xml"}', '-p', 'scripts.delivery_offline_guard']),
        ('frontend', ['npm', 'run', 'test:startup']),
        ('frontend', ['npm', 'run', 'build:release']),
    ]
    for directory, command in commands:
        log = out / f'command-{len(report["commands"])+1}.log'
        started = datetime.now(timezone.utc)
        with log.open('w') as stream:
            try:
                result = subprocess.run(command, cwd=ROOT / directory, stdout=stream, stderr=subprocess.STDOUT,
                                        timeout=1800, env={**os.environ, 'GEO_ACCEPTANCE_OFFLINE': '1'})
                code = result.returncode
            except (OSError, subprocess.TimeoutExpired) as exc:
                stream.write(f'{type(exc).__name__}: {exc}\n')
                code = 124
        report['commands'].append({'cwd': directory, 'command': command, 'exit_code': code,
                                   'started_at': started.isoformat(), 'log': log.name})
    cases = json.loads((ROOT / 'docs/geo-v1.0/acceptance_cases.json').read_text())
    tasks = json.loads((ROOT / 'docs/geo-v1.0/tasks.json').read_text())
    report['coverage'] = coverage_report(tasks, cases)
    junit = out / 'backend.xml'
    if junit.exists():
        suites = ET.parse(junit).getroot()
        report['tests'] = [dict(s.attrib) for s in suites.iter('testsuite')]
    failed = any(c['exit_code'] for c in report['commands'])
    report['source_fingerprint_after'] = source_fingerprint()
    report['source_changed_during_validation'] = report['source_fingerprint'] != report['source_fingerprint_after']
    failed = failed or report['source_changed_during_validation']
    incomplete = any(report['coverage'].values())
    report.update(finished=True, status='FAIL' if failed else 'INCOMPLETE' if incomplete else 'PASS',
                  product_complete=not failed and not incomplete and not args.coverage_only and not args.checks_only)
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'report': str(out / 'report.json'), 'status': report['status'], 'product_complete': report['product_complete']}, ensure_ascii=False))
    return 1 if failed or (incomplete and not args.checks_only) else 0


if __name__ == '__main__':
    raise SystemExit(main())
