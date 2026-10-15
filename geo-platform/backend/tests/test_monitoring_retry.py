from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, BrowserMonitorRun, Project, Prompt, RunArtifact
from app.modules.monitoring import executor as executor_module
from app.modules.monitoring.api import claim_run_for_retry, retry_run
from app.modules.monitoring.artifacts import ArtifactService
from app.modules.monitoring.collectors.wenxin.exceptions import AnswerTimeoutError
from app.modules.monitoring.executor import MonitoringTaskExecutor


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _seed_failed_run(db, run_id: int = 1, error_type: str = "answer_timeout") -> None:
    project = Project(id=1, organization_id=1, name="Retry", brand_name="Brand")
    prompt = Prompt(id=1, project_id=1, prompt_text="抖音跳转链接", title="抖音跳转链接")
    run = BrowserMonitorRun(
        id=run_id,
        task_id=1,
        project_id=1,
        prompt_id=1,
        status="failed",
        error_type=error_type,
        error_message="boom",
        adapter="wenxin_web_audit",
    )
    db.add_all([project, prompt, run])
    db.commit()


def test_legacy_retry_is_gone_and_never_mutates_the_run(db):
    _seed_failed_run(db)
    before = db.get(BrowserMonitorRun, 1)
    original = (before.status, before.stage, before.retry_count, before.error_type, before.error_message)

    with pytest.raises(HTTPException) as excinfo:
        claim_run_for_retry(db, 1)
    assert excinfo.value.status_code == 410
    assert excinfo.value.detail == {
        "code": "LEGACY_IN_PLACE_RETRY_RETIRED",
        "message": "原地重试入口已停用，请使用正式 V2 样本池的追加式 Run 重试接口",
        "replacement": "/api/v2/single-prompt/runs/{run_id}/retry",
    }
    with pytest.raises(HTTPException) as route_excinfo:
        retry_run(1, db)
    assert route_excinfo.value.status_code == 410
    assert route_excinfo.value.detail == excinfo.value.detail
    db.expire_all()
    unchanged = db.get(BrowserMonitorRun, 1)
    assert (unchanged.status, unchanged.stage, unchanged.retry_count,
            unchanged.error_type, unchanged.error_message) == original


class _FakeCollector:
    async def collect(self, run):
        raise AnswerTimeoutError("回答超时")

    async def close(self) -> None:
        return None


def _executor_with_tmp_artifacts(tmp_path: Path) -> MonitoringTaskExecutor:
    executor = MonitoringTaskExecutor()
    artifacts = ArtifactService()
    artifacts.base_dir = tmp_path
    executor.artifacts = artifacts
    return executor


def test_failed_retry_does_not_duplicate_artifact_rows(db, tmp_path, monkeypatch):
    """failed -> failed 重试不能产生重复的 collector.log artifact 行。"""
    _seed_failed_run(db)
    # 第一次失败残留的 collector.log artifact
    db.add(
        RunArtifact(
            id=1,
            run_id=1,
            artifact_type="collector_log",
            storage_path=str(tmp_path / "1" / "collector.log"),
            mime_type="text/plain",
        )
    )
    db.commit()

    fake = _FakeCollector()
    monkeypatch.setattr(executor_module, "get_collector", lambda adapter: fake)

    executor = _executor_with_tmp_artifacts(tmp_path)
    try:
        run = executor.execute_run(db, 1)
    finally:
        executor.close()

    assert run.status == "failed"
    assert run.error_type == "answer_timeout"
    artifacts = db.query(RunArtifact).filter(RunArtifact.run_id == 1).all()
    assert len(artifacts) == 1
    assert artifacts[0].artifact_type == "collector_log"


def test_success_retry_leaves_single_result_artifact(db, tmp_path, monkeypatch):
    """成功 retry 后旧 artifact 被清理，仅保留本轮写入的 artifact。"""
    _seed_failed_run(db)
    db.add(
        RunArtifact(
            id=1,
            run_id=1,
            artifact_type="collector_log",
            storage_path=str(tmp_path / "1" / "collector.log"),
            mime_type="text/plain",
        )
    )
    db.commit()

    class _SucceedCollector(_FakeCollector):
        async def collect(self, run):
            run.answer_text = "这是一个足够长的正常回答内容用于通过校验"
            return type(
                "Result",
                (),
                {
                    "answer_text": run.answer_text,
                    "answer_html": "",
                    "references": [],
                    "retrieval_candidates": [],
                    "artifacts": [],
                    "environment": {},
                    "metrics": {},
                },
            )()

    monkeypatch.setattr(executor_module, "get_collector", lambda adapter: _SucceedCollector())

    executor = _executor_with_tmp_artifacts(tmp_path)
    try:
        run = executor.execute_run(db, 1)
    finally:
        executor.close()

    assert run.status == "success"
    artifacts = db.query(RunArtifact).filter(RunArtifact.run_id == 1).all()
    # 成功路径写入 result.json + collector.log，旧 artifact 已清理，不应有重复路径
    paths = [item.storage_path for item in artifacts]
    assert len(paths) == len(set(paths))
    assert {item.artifact_type for item in artifacts} == {"raw_result", "collector_log"}
