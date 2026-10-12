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


def applicable_test_paths(root: Path = ROOT) -> list[str]:
    patterns = ['test_single_prompt_v2*.py', 'test_answer_semantic.py', 'test_citation_contribution_contract.py',
                'test_release*.py', 'test_automatic*.py', 'test_delivery*.py', 'test_deepseek_generation_contract.py',
                'test_observation_delivery.py', 'test_scheduled_optimization.py', 'test_private_site_contract.py']
    return sorted({str(path.relative_to(root / 'backend')) for pattern in patterns
                   for path in (root / 'backend/tests').glob(pattern)})


def requirement_checks(cases: dict, junit: Path) -> dict:
    """Match explicit assertions to this run, without promoting product acceptance."""
    executed = {}
    if junit.exists():
        for case in ET.parse(junit).getroot().iter('testcase'):
            key = case.get('classname', '') + '::' + case.get('name', '').split('[', 1)[0]
            state = 'FAIL' if case.find('failure') is not None or case.find('error') is not None else 'SKIPPED' if case.find('skipped') is not None else 'PASS'
            executed.setdefault(key, []).append(state)
    results = {}
    for case in cases['cases'] + cases['end_to_end']:
        refs = case.get('automated_checks') or []
        if not refs:
            continue
        checks = []
        for ref in refs:
            states = executed.get(ref, [])
            status = 'NOT_RUN' if not states else 'FAIL' if 'FAIL' in states else 'SKIPPED' if 'SKIPPED' in states else 'PASS'
            checks.append({'test': ref, 'status': status, 'executed_cases': len(states)})
        results[case['id']] = {'checks': checks,
            'status': 'PASS' if all(row['status'] == 'PASS' for row in checks) else 'INCOMPLETE',
            'product_acceptance_status': case['status']}
    return results


def delivery_gaps(tasks: dict, cases: dict, checks: dict, root: Path = ROOT) -> dict:
    active_tasks = [t for t in tasks['tasks'] if t.get('status') not in {'SUPERSEDED', 'OUT_OF_SCOPE'}]
    active_cases = {c['id'] for c in cases['cases'] + cases['end_to_end']
                    if c.get('status') not in {'SUPERSEDED', 'OUT_OF_SCOPE'}}
    missing = []
    for task in active_tasks:
        paths = task.get('implementation_files') or []
        if not paths:
            missing.append({'task_id': task['id'], 'path': None, 'reason': 'NO_IMPLEMENTATION_MAPPING'})
        for value in paths:
            path = (root / value).resolve()
            if root.resolve() not in path.parents or not path.is_file():
                missing.append({'task_id': task['id'], 'path': value, 'reason': 'IMPLEMENTATION_FILE_MISSING'})
    return {
        'unfinished_tasks': [{'id': t['id'], 'status': t.get('status', 'NOT_STARTED')}
                             for t in active_tasks if t.get('status') != 'DONE'],
        'missing_implementation': missing,
        'required_checks_not_passed': [{'id': key, 'status': value['status']}
                                      for key, value in checks.items()
                                      if key in active_cases and value['status'] != 'PASS'],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--checks-only', action='store_true', help='Run engineering checks without claiming complete product acceptance')
    parser.add_argument('--coverage-only', action='store_true')
    parser.add_argument('--skip-browser', action='store_true', help='Engineering-only check; cannot report product complete')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = ROOT / 'backend/artifacts/acceptance' / stamp
    out.mkdir(parents=True, exist_ok=False)
    git = lambda *a: subprocess.check_output(['git', *a], cwd=ROOT, text=True).strip()
    report = {'batch': stamp, 'commit': git('rev-parse', 'HEAD'), 'worktree': git('status', '--short'),
              'source_fingerprint': source_fingerprint(), 'commands': [], 'external_calls_authorized': False, 'scope': 'OFFLINE', 'finished': False}
    commands = [] if args.coverage_only else [
        ('backend', [sys.executable, '-m', 'pytest', *applicable_test_paths(), '-q', '--disable-warnings', '--tb=short',
                     f'--junitxml={out / "backend.xml"}', '-p', 'scripts.delivery_offline_guard']),
        ('frontend', ['npm', 'run', 'test:startup']),
        ('frontend', ['npm', 'run', 'test:client']),
        ('frontend', ['npm', 'run', 'build:release']),
    ]
    if not args.coverage_only and not args.skip_browser:
        commands.extend(('backend', [sys.executable, 'scripts/delivery_browser_check.py', *mode])
                        for mode in [[], ['--observe'], ['--optimize'], ['--optimize', '--official-facts'],
                                     ['--optimize', '--brand-context'], ['--optimize', '--supplemental-source'],
                                     ['--optimize', '--truth-correction'], ['--access']])
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
    report['requirement_checks'] = requirement_checks(cases, junit)
    report['delivery_gaps'] = delivery_gaps(tasks, cases, report['requirement_checks'])
    if junit.exists():
        suites = ET.parse(junit).getroot()
        report['tests'] = [dict(s.attrib) for s in suites.iter('testsuite')]
    failed = any(c['exit_code'] for c in report['commands'])
    report['source_fingerprint_after'] = source_fingerprint()
    report['source_changed_during_validation'] = report['source_fingerprint'] != report['source_fingerprint_after']
    failed = failed or report['source_changed_during_validation']
    incomplete = any(report['coverage'].values()) or any(report['delivery_gaps'].values())
    report.update(finished=True, status='FAIL' if failed else 'INCOMPLETE' if incomplete else 'PASS',
                  engineering_status='FAIL' if failed else 'NOT_RUN' if args.coverage_only else 'PASS',
                  product_complete=not failed and not incomplete and not args.coverage_only and not args.checks_only and not args.skip_browser,
                  browser_required_executed=not args.coverage_only and not args.skip_browser)
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'report': str(out / 'report.json'), 'status': report['status'], 'product_complete': report['product_complete']}, ensure_ascii=False))
    return 1 if failed or (incomplete and not args.checks_only) else 0


if __name__ == '__main__':
    raise SystemExit(main())
