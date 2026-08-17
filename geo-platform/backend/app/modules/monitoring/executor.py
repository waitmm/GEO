from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import BrandMention, BrowserMonitorRun, ReferenceSource, RetrievalCandidate, Project, RunArtifact
from app.modules.monitoring.analysis import analyze_brand
from app.modules.monitoring.artifacts import ArtifactService
from app.modules.monitoring.collectors.base import CollectorResult
from app.modules.monitoring.collectors.registry import get_collector
from app.modules.monitoring.collectors.wenxin.exceptions import WenxinCollectorError
from app.services.serialization import dumps


class MonitoringTaskExecutor:
    def __init__(self) -> None:
        self.artifacts = ArtifactService()
        self._event_loop = asyncio.new_event_loop()
        self._collectors = {}

    def close(self) -> None:
        for collector in self._collectors.values():
            close = getattr(collector, "close", None)
            if close:
                self._event_loop.run_until_complete(close())
        self._collectors.clear()
        self._event_loop.close()

    def execute_queued_runs(self, db: Session, task_id: int) -> int:
        runs = (
            db.query(BrowserMonitorRun)
            .filter(BrowserMonitorRun.task_id == task_id, BrowserMonitorRun.status.in_(["queued", "pending"]))
            .order_by(BrowserMonitorRun.run_sequence.asc(), BrowserMonitorRun.id.asc())
            .all()
        )
        if not runs:
            return 0

        # 按 run_sequence 分组；single_independent 模式会在组内每条 Prompt 前
        # 强制开启新对话，避免同批次 Prompt 共用历史上下文。
        groups: dict[int, list[BrowserMonitorRun]] = {}
        for run in runs:
            seq = run.run_sequence
            if seq not in groups:
                groups[seq] = []
            groups[seq].append(run)

        completed = 0
        for sequence, group_runs in groups.items():
            completed += self._execute_run_group(db, group_runs)
        return completed

    def _execute_run_group(self, db: Session, runs: list[BrowserMonitorRun]) -> int:
        if not runs:
            return 0

        collector = None
        try:
            first_run = runs[0]
            project = db.get(Project, first_run.project_id)
            if not project:
                raise ValueError(f"Project not found: {first_run.project_id}")

            collector = get_collector(first_run.adapter)
            # 启动浏览器会话（每个 Sample 组一次）；独立模式是否真正切换为新
            # 对话，由 collector 在每条 Run 开始前强校验。
            has_session = callable(getattr(collector, "start_session", None))
            if has_session:
                self._event_loop.run_until_complete(collector.start_session())

            completed = 0
            for run in runs:
                try:
                    logs = []
                    started = time.perf_counter()
                    self._stage(db, run, "launching_browser", "running")
                    if has_session:
                        result = self._event_loop.run_until_complete(collector.collect_in_session(run))
                    else:
                        result = self._event_loop.run_until_complete(collector.collect(run))
                    self.apply_result(db, run, project, result)
                    logs.append(f"run {run.id} finished with status={run.status}")
                    self.artifacts.save_json(db, run.id, "raw_result", "result.json", result.__dict__)
                    run.finished_at = datetime.utcnow()
                    run.duration_ms = int((time.perf_counter() - started) * 1000)
                    self.artifacts.save_text(db, run.id, "collector_log", "collector.log", "\n".join(logs) + "\n")
                    db.commit()
                    completed += 1
                except WenxinCollectorError as exc:
                    self._fail_run(run, exc.error_type, str(exc))
                    logs.append(f"collector failed: {exc.error_type} {exc}")
                    run.finished_at = datetime.utcnow()
                    run.duration_ms = int((time.perf_counter() - started) * 1000)
                    self.artifacts.save_text(db, run.id, "collector_log", "collector.log", "\n".join(logs) + "\n")
                    db.commit()
                except Exception as exc:
                    self._fail_run(run, "unknown_error", str(exc))
                    logs.append(f"unknown failed: {exc}")
                    run.finished_at = datetime.utcnow()
                    run.duration_ms = int((time.perf_counter() - started) * 1000)
                    self.artifacts.save_text(db, run.id, "collector_log", "collector.log", "\n".join(logs) + "\n")
                    db.commit()
            return completed
        finally:
            if collector and hasattr(collector, "end_session") and callable(getattr(collector, "end_session")):
                self._event_loop.run_until_complete(collector.end_session())
            if collector:
                self._cleanup_collector(collector)

    def execute_run(self, db: Session, run_id: int) -> BrowserMonitorRun:
        run = db.get(BrowserMonitorRun, run_id)
        if not run:
            raise ValueError(f"Run not found: {run_id}")
        project = db.get(Project, run.project_id)
        if not project:
            raise ValueError(f"Project not found: {run.project_id}")

        started = time.perf_counter()
        logs = []
        self._stage(db, run, "launching_browser", "running")
        collector = None
        try:
            collector = get_collector(run.adapter)
            result = self._event_loop.run_until_complete(collector.collect(run))
            self.apply_result(db, run, project, result)
            logs.append(f"run {run.id} finished with status={run.status}")
            self.artifacts.save_json(db, run.id, "raw_result", "result.json", result.__dict__)
        except WenxinCollectorError as exc:
            self._fail_run(run, exc.error_type, str(exc))
            logs.append(f"collector failed: {exc.error_type} {exc}")
        except Exception as exc:
            self._fail_run(run, "unknown_error", str(exc))
            logs.append(f"unknown failed: {exc}")
        finally:
            # 每个 Run 结束后清理 Collector，确保下一 Run 使用全新浏览器上下文
            self._cleanup_collector(collector)
            run.finished_at = datetime.utcnow()
            run.duration_ms = int((time.perf_counter() - started) * 1000)
            self.artifacts.save_text(db, run.id, "collector_log", "collector.log", "\n".join(logs) + "\n")
            db.commit()
            db.refresh(run)
        return run

    def _cleanup_collector(self, collector) -> None:
        if collector is None:
            return
        try:
            close = getattr(collector, "close", None)
            if close:
                self._event_loop.run_until_complete(close())
        except Exception:
            pass
        # 清除缓存的 collector，防止下一 Run 复用旧的浏览器会话
        adapter_keys = list(self._collectors.keys())
        for key in adapter_keys:
            if self._collectors[key] is collector:
                del self._collectors[key]

    def apply_result(self, db: Session, run: BrowserMonitorRun, project: Project, result: CollectorResult) -> BrowserMonitorRun:
        self._stage(db, run, "analyzing", "running")
        self._clear_run_outputs(db, run.id)
        answer_text = (result.answer_text or "").strip()
        brand = analyze_brand(answer_text, project)
        db.add(
            BrandMention(
                run_id=run.id,
                brand_name=brand["brand_name"],
                alias_matched=brand["alias_matched"],
                mention_count=brand["mention_count"],
                first_char_position=brand["first_char_position"],
                first_paragraph_index=brand["first_paragraph_index"],
                recommendation_level=brand["recommendation_level"],
                context_snippets_json=dumps(brand["context_snippets"]),
            )
        )

        run.answer_text = answer_text
        run.answer_html = result.answer_html
        run.answer_char_count = len(answer_text)
        run.brand_mentioned = brand["brand_mentioned"]
        run.brand_mention_count = brand["mention_count"]
        run.brand_first_position = brand["first_char_position"]
        run.brand_recommendation_level = brand["recommendation_level"]
        ui_count = int(result.metrics.get("ui_declared_count", len(result.references)))
        dom_count = int(result.metrics.get("dom_reference_count", len(result.references)))
        parsed_count = int(result.metrics.get("parsed_reference_count", len(result.references)))
        resolved_count = int(
            result.metrics.get(
                "resolved_url_count",
                sum(1 for item in result.references if item.get("url")),
            )
        )
        run.expected_reference_count = ui_count
        run.detected_reference_count = dom_count
        run.resolved_reference_count = resolved_count
        run.unresolved_reference_count = max(0, parsed_count - resolved_count)
        run.reference_complete = ui_count == 0 or (
            ui_count == dom_count == parsed_count
            and resolved_count / max(1, parsed_count) >= 0.95
        )
        field_values = {
            **result.environment,
            "ui_declared_count": ui_count,
            "dom_reference_count": dom_count,
            "parsed_reference_count": parsed_count,
            "resolved_url_count": resolved_count,
        }
        for field, value in field_values.items():
            if hasattr(run, field):
                setattr(run, field, value)
        self._save_references(db, run.id, result.references)
        self._save_candidates(db, run.id, result.retrieval_candidates)
        self._save_result_artifacts(db, run.id, result.artifacts)
        if not answer_text:
            run.status = "failed"
            run.error_type = "empty_answer"
            run.error_message = "未采集到回答正文"
        elif len(re.sub(r"\s+", "", answer_text)) < 20:
            run.answer_text = ""
            run.answer_char_count = 0
            run.status = "failed"
            run.error_type = "empty_answer"
            run.error_message = "回答正文过短，疑似仅采集到生成前占位内容"
        else:
            run.status = "success" if run.reference_complete else "partial_success"
        run.stage = run.status
        if hasattr(run, "outcome_category"):
            run.outcome_category = run.status
        if hasattr(run, "blocked_type"):
            run.blocked_type = ""
        if hasattr(run, "blocked_reason"):
            run.blocked_reason = ""
        if run.status != "failed":
            run.error_stage = ""
            run.error_type = ""
            run.error_message = ""
        return run

    def _stage(self, db: Session, run: BrowserMonitorRun, stage: str, status: str) -> None:
        run.stage = stage
        run.status = status
        if run.started_at is None:
            run.started_at = datetime.utcnow()
        db.commit()
        db.refresh(run)

    def _fail_run(self, run: BrowserMonitorRun, error_type: str, error_message: str) -> None:
        is_blocked = error_type in {"login_required", "captcha_required"}
        run.status = "blocked" if is_blocked else "failed"
        run.error_stage = run.stage
        run.stage = "failed"
        run.error_type = error_type
        run.error_message = error_message
        if hasattr(run, "outcome_category"):
            run.outcome_category = "blocked" if is_blocked else "collector_failed"
        if hasattr(run, "blocked_type"):
            run.blocked_type = error_type if is_blocked else ""
        if hasattr(run, "blocked_reason"):
            run.blocked_reason = error_message if is_blocked else ""

    def _clear_run_outputs(self, db: Session, run_id: int) -> None:
        db.query(BrandMention).filter(BrandMention.run_id == run_id).delete()
        db.query(ReferenceSource).filter(ReferenceSource.run_id == run_id).delete()
        db.query(RetrievalCandidate).filter(RetrievalCandidate.run_id == run_id).delete()
        db.query(RunArtifact).filter(RunArtifact.run_id == run_id).delete()

    def _save_references(self, db: Session, run_id: int, references: list[dict]) -> None:
        for index, item in enumerate(references, start=1):
            db.add(
                ReferenceSource(
                    run_id=run_id,
                    reference_index=item.get("reference_index") or index,
                    display_title=item.get("display_title") or "",
                    matched_title=item.get("matched_title") or item.get("display_title") or "",
                    url=item.get("url") or "",
                    canonical_url=item.get("canonical_url") or item.get("url") or "",
                    domain=item.get("domain") or "",
                    platform_name="文心助手",
                    resolution_method=item.get("resolution_method") or "unresolved",
                    match_confidence=item.get("match_confidence") or 0,
                    evidence_path=item.get("evidence_path") or "",
                    relevance_label=item.get("relevance_label") or "unreviewed",
                    quality_label=item.get("quality_label") or "unknown",
                    is_official_domain=bool(item.get("is_official_domain")),
                    is_competitor_domain=bool(item.get("is_competitor_domain")),
                )
            )

    def _save_candidates(self, db: Session, run_id: int, candidates: list[dict]) -> None:
        for index, item in enumerate(candidates, start=1):
            db.add(
                RetrievalCandidate(
                    run_id=run_id,
                    retrieval_query=item.get("retrieval_query") or "",
                    rank=item.get("rank") or index,
                    title=item.get("title") or "",
                    url=item.get("url") or "",
                    canonical_url=item.get("canonical_url") or item.get("url") or "",
                    domain=item.get("domain") or "",
                    snippet=item.get("snippet") or "",
                    evidence_path=item.get("evidence_path") or "",
                )
            )

    def _save_result_artifacts(self, db: Session, run_id: int, artifacts: list[dict]) -> None:
        for item in artifacts:
            artifact_type = item.get("artifact_type") or "raw_result"
            filename = item.get("filename") or f"{artifact_type}.txt"
            mime_type = item.get("mime_type") or "text/plain"
            if "content_bytes" in item:
                self.artifacts.save_bytes(db, run_id, artifact_type, filename, item["content_bytes"], mime_type)
            else:
                self.artifacts.save_text(db, run_id, artifact_type, filename, item.get("content") or "", mime_type)
