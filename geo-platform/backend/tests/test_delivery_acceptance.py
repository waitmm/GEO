from scripts.delivery_acceptance import coverage_report


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
