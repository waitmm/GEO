from scripts.delivery_acceptance import applicable_test_paths, coverage_report, requirement_checks


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
