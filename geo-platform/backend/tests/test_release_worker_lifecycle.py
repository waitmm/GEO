from sqlalchemy import create_engine
import pytest

from app.core.release_worker_lifecycle import worker_ownership, worker_status
from test_automatic_delivery import scene


def test_exclusive_worker_and_readonly_health(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "test.db"}')
    assert worker_status(engine)['status'] == 'NOT_RUNNING'
    assert list(tmp_path.iterdir()) == []
    with worker_ownership(engine):
        assert worker_status(engine)['status'] == 'RUNNING'
        with pytest.raises(RuntimeError, match='already owns'):
            with worker_ownership(engine):
                pytest.fail('Second worker must not run')
        assert worker_status(engine)['status'] == 'RUNNING'
    assert worker_status(engine)['status'] == 'NOT_RUNNING'
    with worker_ownership(engine):
        assert worker_status(engine)['status'] == 'RUNNING'


def test_restart_fails_uncertain_run_retry_without_replaying_or_touching_optimization_waits(scene, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.models import BrowserMonitorRun, BrowserMonitorTask
    from scripts import release_worker

    db, optimization, _, _ = scene
    task = db.query(BrowserMonitorTask).first()
    run = db.query(BrowserMonitorRun).filter_by(task_id=task.id).first()
    task.schedule_type = 'single_prompt_v2_run_retry'
    task.status = 'running'
    run.status = 'running'
    run.stage = 'running'
    db.commit()
    preserved_runs = {
        row.id: (row.status, row.stage, row.answer_text)
        for row in db.query(BrowserMonitorRun).filter(
            BrowserMonitorRun.task_id == task.id, BrowserMonitorRun.id != run.id,
        )
    }
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(release_worker, 'ReleaseSessionLocal', factory)
    monkeypatch.setattr(release_worker, 'MonitoringTaskExecutor',
                        lambda: pytest.fail('recovery must not replay browser work'))
    frozen = (optimization.input_json, optimization.input_hash,
              optimization.authorization_json, optimization.progress_json,
              optimization.revision)

    assert optimization.status == 'QUEUED'
    release_worker.recover_owned_tasks()
    db.expire_all()
    assert task.status == 'failed'
    assert (run.status, run.stage, run.error_type) == (
        'failed', 'failed', 'worker_restart_interrupted',
    )
    assert '未自动重试' in run.error_message
    assert {
        row.id: (row.status, row.stage, row.answer_text)
        for row in db.query(BrowserMonitorRun).filter(
            BrowserMonitorRun.task_id == task.id, BrowserMonitorRun.id != run.id,
        )
    } == preserved_runs
    assert optimization.status == 'QUEUED'
    assert (optimization.input_json, optimization.input_hash,
            optimization.authorization_json, optimization.progress_json,
            optimization.revision) == frozen

    task.status = 'queued'
    run.status = 'queued'
    run.stage = 'queued'
    run.error_type = ''
    run.error_message = ''
    optimization.status = 'WAITING_AUTHORIZATION'
    db.commit()
    waiting = (optimization.input_json, optimization.input_hash,
               optimization.authorization_json, optimization.progress_json,
               optimization.revision)
    release_worker.recover_owned_tasks()
    db.expire_all()
    assert (task.status, run.status, run.stage, run.error_type) == (
        'queued', 'queued', 'queued', '',
    )
    assert optimization.status == 'WAITING_AUTHORIZATION'
    assert (optimization.input_json, optimization.input_hash,
            optimization.authorization_json, optimization.progress_json,
            optimization.revision) == waiting


def test_actual_process_crash_restart_and_explicit_resume_preserve_scope_and_budget(scene):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    from app.modules.single_prompt_v2.automatic_delivery import resume_task, task_view
    from scripts.release_upgrade_check import business_fingerprint

    db, task, _, tmp = scene
    database = Path(db.get_bind().url.database).absolute()
    original = (task.input_json, task.input_hash, task.authorization_json)
    env = {**os.environ, 'GEO_RELEASE_DATABASE_URL': f'sqlite:///{database}',
        'DATABASE_URL': f'sqlite:///{database}', 'DEEPSEEK_API_KEY': '', 'SILICONFLOW_API_KEY': '',
        'DEEPSEEK_MODEL': json.loads(task.input_json)['requested_model'],
        'EVIDENCE_ARTIFACT_DIR': str(tmp / 'evidence'), 'MONITORING_ARTIFACT_DIR': str(tmp / 'monitoring')}
    code = '''
import os, socket, sys
def no_network(*args, **kwargs):
    print('UNEXPECTED_NETWORK_ATTEMPT', flush=True)
    raise RuntimeError('OFFLINE_PROCESS_TEST')
socket.socket.connect = no_network
from app.modules.single_prompt_v2 import automatic_delivery
from scripts.release_worker import main
if os.environ.get('CRASH_AT_ANSWER') == '1':
    checkpoint = automatic_delivery.checkpoint
    def crash(*args, **kwargs):
        checkpoint(*args, **kwargs)
        if kwargs.get('stage') == 'ANSWER':
            os._exit(73)
    automatic_delivery.checkpoint = crash
sys.argv = ['release_worker.py', '--once']
main()
'''
    def worker(crash=False):
        result = subprocess.run([sys.executable, '-c', code],
            cwd=Path(__file__).resolve().parents[1], env={**env, 'CRASH_AT_ANSWER': '1' if crash else '0'},
            capture_output=True, text=True, timeout=40)
        assert 'UNEXPECTED_NETWORK_ATTEMPT' not in result.stdout
        assert result.returncode == (73 if crash else 0), result.stderr[-2000:]
        return result.stdout

    worker(crash=True)
    db.expire_all()
    assert task.status == 'RUNNING'
    objects = dict(task_view(task)['objects'])
    assert objects['completion_manifest_id'] and task_view(task)['stage'] == 'ANSWER'
    assert worker_status(db.get_bind())['status'] == 'NOT_RUNNING'

    worker()
    db.expire_all()
    assert task.status == 'INTERRUPTED'
    assert (task.input_json, task.input_hash, task.authorization_json) == original
    assert task_view(task)['objects'] == objects
    assert task_view(task)['usage']['external_requests'] == 0
    assert worker_status(db.get_bind())['status'] == 'NOT_RUNNING'

    resume_task(db, task, task.revision)
    worker()
    db.expire_all()
    assert task.status == 'WAITING_AUTHORIZATION', (task.blocker_code, task.blocker_detail)
    assert (task.input_json, task.input_hash, task.authorization_json) == original
    assert task_view(task)['objects']['completion_manifest_id'] == objects['completion_manifest_id']
    assert task_view(task)['usage']['external_requests'] == 0
    before = business_fingerprint(database)
    assert "'completed': 'IDLE'" in worker()
    assert business_fingerprint(database) == before
