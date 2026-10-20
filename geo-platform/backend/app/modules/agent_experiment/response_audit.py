"""Restricted local archive for complete rejected provider responses."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat
from typing import Any

from app.modules.single_prompt_v2.delivery_text import digest


class SecureResponseAuditArchive:
    """Persist response-only evidence with strict permissions and finite retention."""

    def __init__(self, root: Path, *, retention_days: int = 7) -> None:
        self.root = root.resolve()
        if not self.root.is_absolute() or retention_days < 1 or retention_days > 30:
            raise ValueError("AGENT_RESPONSE_AUDIT_CONFIG_INVALID")
        self.retention_days = retention_days

    def prepare(self) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)
        if stat.S_IMODE(self.root.stat().st_mode) != 0o700:
            raise RuntimeError("AGENT_RESPONSE_AUDIT_DIRECTORY_PERMISSIONS_INVALID")
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        for path in self.root.glob("agent-response-*.json"):
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if modified < cutoff:
                path.unlink()

    def record_rejected_response(self, *, run_id: str, event: dict[str, Any]) -> Path | None:
        if (
            event.get("response_source") != "EXTERNAL_LLM"
            or event.get("validation_status") != "REJECTED"
            or not isinstance(event.get("raw_provider_response"), dict)
        ):
            return None
        self.prepare()
        now = datetime.now(timezone.utc)
        identity = event.get("request_identity") or {}
        safe_identity = {
            key: identity.get(key) for key in (
                "provider", "effective_request_model", "prompt_version", "schema_version",
                "input_hash", "call_identity_hash", "endpoint_path", "transport_kind",
                "attempt", "max_attempts",
            )
        }
        record = {
            "contract_version": "geo.agent.rejected-provider-response-audit.v1",
            "run_id": run_id,
            "recorded_at": now.isoformat(),
            "expires_at": (now + timedelta(days=self.retention_days)).isoformat(),
            "request_identity": safe_identity,
            "validation_status": "REJECTED",
            "rejection_code": event.get("rejection_code"),
            "rejection_reason": event.get("rejection_reason"),
            "finish_reason": event.get("finish_reason"),
            "response_model": event.get("response_model"),
            "provider_output_kind": event.get("provider_output_kind"),
            "raw_response_hash": event.get("raw_response_hash"),
            "token_usage": event.get("token_usage") or {},
            "raw_provider_response": event["raw_provider_response"],
        }
        record["record_hash"] = digest(record)
        encoded = (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        input_hash = str(safe_identity.get("input_hash") or digest(safe_identity))
        raw_hash = str(event.get("raw_response_hash") or digest(event["raw_provider_response"]))
        path = self.root / (
            f"agent-response-{digest(run_id)[:12]}-{input_hash[:16]}-{raw_hash[:16]}.json"
        )
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if stat.S_IMODE(path.stat().st_mode) != 0o600:
                raise RuntimeError("AGENT_RESPONSE_AUDIT_FILE_PERMISSIONS_INVALID")
            return path
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise RuntimeError("AGENT_RESPONSE_AUDIT_FILE_PERMISSIONS_INVALID")
        return path
