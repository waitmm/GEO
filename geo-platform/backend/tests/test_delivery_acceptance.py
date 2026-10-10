from scripts.delivery_acceptance import applicable_test_paths, coverage_report, requirement_checks, delivery_gaps


def test_missing_cases_and_evidence_are_not_product_pass():
    tasks = {'tasks': [{'requirements': ['A', 'B']}]}
    cases = {'cases': [{'id': 'a', 'requirements': ['A'], 'status': 'PASS', 'evidence': ''}], 'end_to_end': []}
    report = coverage_report(tasks, cases)
    assert report['requirements_without_cases'] == ['B']
    assert report['pass_without_evidence'] == ['a']


def test_superseded_publication_requirements_are_not_silently_passed():
    tasks = {'tasks': [{'requirements': ['PUB'], 'status': 'OUT_OF_SCOPE'}, {'requirements': ['VAL']}]}
    cases = {'cases': [{'id': 'pub', 'requirements': ['PUB'], 'status': 'SUPERSEDED'},
                        {'id': 'val', 'requirements': ['VAL'], 'status': 'NOT_RUN'}], 'end_to_end': []}
    assert coverage_report(tasks, cases) == {'requirements_without_cases': [], 'not_passed': [{'id': 'val', 'status': 'NOT_RUN'}], 'pass_without_evidence': []}


def test_task_link_to_e2e_case_is_coverage_not_execution_success():
    tasks = {'tasks': [{'requirements': ['E2E-01']}]}
    cases = {'cases': [], 'end_to_end': [{'id': 'E2E-01', 'requirements': [], 'status': 'NOT_RUN'}]}
    result = coverage_report(tasks, cases)
    assert result['requirements_without_cases'] == []
    assert result['not_passed'] == [{'id': 'E2E-01', 'status': 'NOT_RUN'}]


def test_required_release_tests_are_discovered_without_legacy_workflow_suites():
    paths = applicable_test_paths()
    assert paths == sorted(set(paths))
    assert {'tests/test_release_catalog.py', 'tests/test_single_prompt_v2.py',
        'tests/test_answer_semantic.py', 'tests/test_citation_contribution_contract.py',
        'tests/test_delivery_generation.py', 'tests/test_observation_delivery.py'} <= set(paths)
    assert all(path.startswith('tests/') and path.endswith('.py') for path in paths)


def test_requirement_evidence_is_this_run_and_never_promotes_product_acceptance(tmp_path):
    junit = tmp_path / 'tests.xml'
    junit.write_text('''<testsuites><testsuite>
      <testcase classname="tests.sample" name="test_pass"/>
      <testcase classname="tests.sample" name="test_parameter[a]"/>
      <testcase classname="tests.sample" name="test_parameter[b]"><failure/></testcase>
      <testcase classname="tests.sample" name="test_skip"><skipped/></testcase>
    </testsuite></testsuites>''')
    cases = {'cases': [{'id': 'AC-ONE', 'status': 'PARTIAL', 'automated_checks': ['tests.sample::test_pass']},
        {'id': 'AC-TWO', 'status': 'NOT_RUN', 'automated_checks': ['tests.sample::test_parameter',
            'tests.sample::test_skip', 'tests.sample::test_never_run']}], 'end_to_end': []}
    result = requirement_checks(cases, junit)
    assert result['AC-ONE']['status'] == 'PASS'
    assert result['AC-ONE']['product_acceptance_status'] == 'PARTIAL'
    assert [row['status'] for row in result['AC-TWO']['checks']] == ['FAIL', 'SKIPPED', 'NOT_RUN']
    assert result['AC-TWO']['checks'][0]['executed_cases'] == 2
    assert requirement_checks(cases, tmp_path / 'missing.xml')['AC-ONE']['status'] == 'INCOMPLETE'


def test_pass_labels_cannot_hide_unfinished_tasks_missing_code_or_unexecuted_checks(tmp_path):
    (tmp_path / 'implemented.py').write_text('')
    tasks = {'tasks': [
        {'id': 'T1', 'status': 'IN_PROGRESS', 'implementation_files': ['implemented.py']},
        {'id': 'T2', 'status': 'DONE', 'implementation_files': ['missing.py']},
        {'id': 'T3', 'status': 'DONE', 'implementation_files': []},
        {'id': 'T4', 'status': 'OUT_OF_SCOPE', 'implementation_files': ['removed.py']},
    ]}
    cases = {'cases': [{'id': 'AC-1', 'status': 'PASS', 'evidence': 'historical'}], 'end_to_end': []}
    report = delivery_gaps(tasks, cases, {'AC-1': {'status': 'INCOMPLETE'}}, tmp_path)
    assert report['unfinished_tasks'] == [{'id': 'T1', 'status': 'IN_PROGRESS'}]
    assert [item['task_id'] for item in report['missing_implementation']] == ['T2', 'T3']
    assert report['required_checks_not_passed'] == [{'id': 'AC-1', 'status': 'INCOMPLETE'}]


def test_delivery_mapping_rejects_escape_and_keeps_superseded_cases_out(tmp_path):
    tasks = {'tasks': [{'id': 'T1', 'status': 'DONE', 'implementation_files': ['../outside.py']}]}
    cases = {'cases': [{'id': 'AC-old', 'status': 'SUPERSEDED'}], 'end_to_end': []}
    report = delivery_gaps(tasks, cases, {'AC-old': {'status': 'INCOMPLETE'}}, tmp_path)
    assert report['missing_implementation'][0]['reason'] == 'IMPLEMENTATION_FILE_MISSING'
    assert not report['required_checks_not_passed']


def test_task_reading_view_has_same_identity_dependencies_and_status_as_ledger():
    import json
    from pathlib import Path
    docs = Path(__file__).resolve().parents[2] / 'docs/geo-v1.0'
    tasks = json.loads((docs / 'tasks.json').read_text())['tasks']
    text = (docs / '18_项目管理与任务.md').read_text()
    rows = [line for line in text.splitlines() if line.startswith('| T')]
    expected = [f"| {t['id']} | {t['milestone']} | {t['title']} | {t['owner_role']} | {','.join(t['depends_on']) or '无'} | {t['status']} |" for t in tasks]
    assert rows == expected


def test_acceptance_reading_view_matches_canonical_case_statuses():
    import json
    from pathlib import Path
    docs = Path(__file__).resolve().parents[2] / 'docs/geo-v1.0'
    cases = json.loads((docs / 'acceptance_cases.json').read_text())['cases']
    text = (docs / '17_验收矩阵.md').read_text()
    actual = [line.split('|')[1:5] for line in text.splitlines() if line.startswith('| AC-')]
    assert [[value.strip() for value in row] for row in actual] == [
        [c['id'], c['name'], '、'.join(c['requirements']), c['status']] for c in cases]
