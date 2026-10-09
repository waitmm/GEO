from sqlalchemy import create_engine
import pytest

from app.core.release_worker_lifecycle import worker_ownership, worker_status


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
