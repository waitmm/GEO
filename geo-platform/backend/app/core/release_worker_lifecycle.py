"""Single-host worker ownership; API restarts never recover an active worker's tasks."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import threading
import time


def worker_paths(engine):
    database = Path(engine.url.database).resolve()
    return database.with_suffix(database.suffix + '.worker.lock'), database.with_suffix(database.suffix + '.worker.json')


def worker_status(engine):
    lock_path, heartbeat = worker_paths(engine)
    if not lock_path.exists():
        return {'status': 'NOT_RUNNING', 'concurrency': 1}
    try:
        with lock_path.open('r') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return {'status': 'NOT_RUNNING', 'concurrency': 1}
            except BlockingIOError:
                pass
        data = json.loads(heartbeat.read_text())
        age = max(0, time.time() - float(data['heartbeat_at']))
        return {'status': 'RUNNING' if age < 30 else 'HEARTBEAT_STALE', 'heartbeat_age_seconds': round(age, 1), 'concurrency': 1}
    except (OSError, ValueError, KeyError):
        return {'status': 'HEARTBEAT_UNAVAILABLE', 'concurrency': 1}


@contextmanager
def worker_ownership(engine):
    lock_path, heartbeat = worker_paths(engine)
    lock = lock_path.open('a+')
    os.chmod(lock_path, 0o600)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('A release worker already owns this database') from None
        stop = threading.Event()
        def write_heartbeat():
            temporary = heartbeat.with_suffix('.tmp')
            temporary.write_text(json.dumps({'pid': os.getpid(), 'heartbeat_at': time.time()}))
            os.chmod(temporary, 0o600)
            temporary.replace(heartbeat)
        write_heartbeat()
        def pulse():
            while not stop.wait(5):
                write_heartbeat()
        thread = threading.Thread(target=pulse, name='release-worker-heartbeat', daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=6)
            heartbeat.unlink(missing_ok=True)
    finally:
        lock.close()
