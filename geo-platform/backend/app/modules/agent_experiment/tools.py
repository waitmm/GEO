"""Strict read-only tools exposed to the model-driven Agent loop."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.modules.single_prompt_v2.delivery_text import digest

from .contracts import TOOL_NAMES
from .scope import revalidate_frozen_scope


class ToolRegistry:
    def __init__(self, db: Session, run):
        self.db = db
        self.run = run

    def prepare(self, name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
        if name not in TOOL_NAMES:
            raise HTTPException(422, {"code": "AGENT_TOOL_NOT_ALLOWED", "tool_name": name})
        scope = revalidate_frozen_scope(self.db, self.run)
        normalized = self._normalize_arguments(name, scope, arguments)
        observation_key = digest({
            "contract_version": "geo.agent.observation-key.v1",
            "input_scope_hash": self.run.input_scope_hash,
            "tool_name": name,
            "arguments": normalized,
        })
        return scope, normalized, observation_key

    def call_prepared(self, name: str, arguments: dict[str, Any], scope: dict[str, Any],
                      observation_key: str) -> dict[str, Any]:
        method = getattr(self, f"_{name}")
        data = method(scope, arguments)
        return {
            "observation_id": f"obs-{digest({'run_id': self.run.run_id, 'tool': name, 'arguments': arguments, 'data': data})[:24]}",
            "observation_key": observation_key, "tool_name": name, "arguments": arguments,
            "data": data,
        }

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        scope, normalized, observation_key = self.prepare(name, arguments)
        return self.call_prepared(name, normalized, scope, observation_key)

    @staticmethod
    def _require_only(arguments: dict[str, Any], allowed: set[str]) -> None:
        extra = sorted(set(arguments) - allowed)
        if extra:
            raise HTTPException(422, {"code": "AGENT_TOOL_ARGUMENT_NOT_ALLOWED", "fields": extra})

    def _normalize_arguments(self, name: str, scope: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
        """Canonicalize defaults and scalar identities before deduplication."""
        if name in {"get_scope_summary", "list_runs", "read_brand_context",
                    "read_product_truth", "read_monitor_metrics"}:
            self._require_only(arguments, set())
            return {}
        if name == "list_citations":
            self._require_only(arguments, {"run_id"})
            return ({"run_id": str(arguments["run_id"])}
                    if arguments.get("run_id") is not None else {})
        if name == "read_answer":
            self._require_only(arguments, {"run_id", "start", "end"})
            run_id = str(arguments.get("run_id", ""))
            row = next((item for item in scope["runs"] if str(item["run_id"]) == run_id), None)
            if not row:
                raise HTTPException(422, {"code": "AGENT_RUN_OUT_OF_SCOPE", "run_id": run_id})
            text = str(row.get("answer_text") or "")
            start = int(arguments.get("start", 0))
            return {"run_id": run_id, "start": start,
                    "end": int(arguments.get("end", min(len(text), start + 4000)))}
        if name == "read_source":
            self._require_only(arguments, {"snapshot_id", "passage_id", "start", "end"})
            snapshot_id = str(arguments.get("snapshot_id", ""))
            row = next((item for item in scope["source_snapshots"] if item["snapshot_id"] == snapshot_id), None)
            if not row:
                raise HTTPException(422, {"code": "AGENT_SOURCE_OUT_OF_SCOPE", "snapshot_id": snapshot_id})
            if arguments.get("passage_id") is not None:
                return {"snapshot_id": snapshot_id, "passage_id": str(arguments["passage_id"])}
            text = str(row.get("clean_text") or "")
            start = int(arguments.get("start", 0))
            return {"snapshot_id": snapshot_id, "start": start,
                    "end": int(arguments.get("end", min(len(text), start + 4000)))}
        if name == "save_working_note":
            self._require_only(arguments, {"note", "evidence_refs"})
            refs = arguments.get("evidence_refs") or []
            if not isinstance(refs, list):
                raise HTTPException(422, {"code": "AGENT_NOTE_REFS_INVALID"})
            return {"note": str(arguments.get("note") or "").strip(), "evidence_refs": refs}
        raise HTTPException(422, {"code": "AGENT_TOOL_NOT_ALLOWED", "tool_name": name})

    def _get_scope_summary(self, scope, arguments):
        self._require_only(arguments, set())
        return {
            "identity": scope["identity"], "prompt": scope["prompt"],
            "monitor_metrics": scope["monitor_metrics"],
            "brand_context_mode": scope["brand_context"].get("mode"),
            "truth_set_hash": scope["product_truth"]["set_hash"],
            "source_completion": ({key: scope["source_completion"].get(key) for key in ("manifest_id", "payload_hash", "status")}
                                  if scope.get("source_completion") else None),
        }

    def _list_runs(self, scope, arguments):
        self._require_only(arguments, set())
        return [{"run_id": str(row["run_id"]), "status": row.get("status"),
                 "answer_char_count": len(str(row.get("answer_text") or "")),
                 "reference_count": len(row.get("references") or []),
                 "brand_mentioned": bool(row.get("brand_mentioned"))} for row in scope["runs"]]

    def _read_answer(self, scope, arguments):
        self._require_only(arguments, {"run_id", "start", "end"})
        run_id = str(arguments.get("run_id", ""))
        row = next((item for item in scope["runs"] if str(item["run_id"]) == run_id), None)
        if not row:
            raise HTTPException(422, {"code": "AGENT_RUN_OUT_OF_SCOPE", "run_id": run_id})
        text = str(row.get("answer_text") or "")
        start = int(arguments.get("start", 0))
        end = int(arguments.get("end", min(len(text), start + 4000)))
        if start < 0 or end <= start or end > len(text) or end - start > 4000:
            raise HTTPException(422, {"code": "AGENT_ANSWER_RANGE_INVALID"})
        return {"run_id": run_id, "start": start, "end": end, "text": text[start:end],
                "answer_hash": digest(text)}

    def _list_citations(self, scope, arguments):
        self._require_only(arguments, {"run_id"})
        requested = str(arguments.get("run_id")) if arguments.get("run_id") is not None else None
        output = []
        for row in scope["runs"]:
            if requested is not None and str(row["run_id"]) != requested:
                continue
            for ref in row.get("references") or []:
                output.append({"citation_occurrence_id": f"run:{row['run_id']}:reference:{ref['reference_id']}",
                               "run_id": str(row["run_id"]), **ref})
        if requested is not None and not any(str(row["run_id"]) == requested for row in scope["runs"]):
            raise HTTPException(422, {"code": "AGENT_RUN_OUT_OF_SCOPE", "run_id": requested})
        return output

    def _read_source(self, scope, arguments):
        self._require_only(arguments, {"snapshot_id", "passage_id", "start", "end"})
        snapshot_id = str(arguments.get("snapshot_id", ""))
        row = next((item for item in scope["source_snapshots"] if item["snapshot_id"] == snapshot_id), None)
        if not row:
            raise HTTPException(422, {"code": "AGENT_SOURCE_OUT_OF_SCOPE", "snapshot_id": snapshot_id})
        passage_id = arguments.get("passage_id")
        if passage_id:
            passage = next((item for item in row["passages"] if str(item.get("passage_id")) == str(passage_id)), None)
            if not passage:
                raise HTTPException(422, {"code": "AGENT_PASSAGE_OUT_OF_SCOPE", "passage_id": passage_id})
            return {"snapshot_id": snapshot_id, "passage": passage, "title": row["title"],
                    "canonical_url": row["canonical_url"]}
        text = row["clean_text"]
        start = int(arguments.get("start", 0))
        end = int(arguments.get("end", min(len(text), start + 4000)))
        if start < 0 or end <= start or end > len(text) or end - start > 4000:
            raise HTTPException(422, {"code": "AGENT_SOURCE_RANGE_INVALID"})
        return {"snapshot_id": snapshot_id, "start": start, "end": end, "text": text[start:end],
                "title": row["title"], "canonical_url": row["canonical_url"]}

    def _read_brand_context(self, scope, arguments):
        self._require_only(arguments, set())
        return scope["brand_context"]

    def _read_product_truth(self, scope, arguments):
        self._require_only(arguments, set())
        return scope["product_truth"]

    def _read_monitor_metrics(self, scope, arguments):
        self._require_only(arguments, set())
        return scope["monitor_metrics"]

    def _save_working_note(self, scope, arguments):
        self._require_only(arguments, {"note", "evidence_refs"})
        note = str(arguments.get("note") or "").strip()
        if not note or len(note) > 4000:
            raise HTTPException(422, {"code": "AGENT_NOTE_INVALID"})
        refs = arguments.get("evidence_refs") or []
        if not isinstance(refs, list):
            raise HTTPException(422, {"code": "AGENT_NOTE_REFS_INVALID"})
        return {"saved": True, "note": note, "evidence_refs": refs,
                "warning": "工作笔记不是原始证据"}
