from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import RunArtifact


class ArtifactService:
    def __init__(self) -> None:
        self.base_dir = Path(get_settings().monitoring_artifact_dir)

    def run_dir(self, run_id: int) -> Path:
        path = self.base_dir / str(run_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_text(self, db: Session, run_id: int, artifact_type: str, filename: str, content: str, mime_type: str = "text/plain") -> str:
        path = self.run_dir(run_id) / filename
        path.write_text(content, encoding="utf-8")
        self._record(db, run_id, artifact_type, path, mime_type)
        return str(path)

    def save_json(self, db: Session, run_id: int, artifact_type: str, filename: str, payload: Any) -> str:
        return self.save_text(
            db,
            run_id,
            artifact_type,
            filename,
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            "application/json",
        )

    def save_bytes(self, db: Session, run_id: int, artifact_type: str, filename: str, content: bytes, mime_type: str) -> str:
        path = self.run_dir(run_id) / filename
        path.write_bytes(content)
        self._record(db, run_id, artifact_type, path, mime_type)
        return str(path)

    def _record(self, db: Session, run_id: int, artifact_type: str, path: Path, mime_type: str) -> None:
        db.add(
            RunArtifact(
                run_id=run_id,
                artifact_type=artifact_type,
                storage_path=str(path),
                mime_type=mime_type,
                size_bytes=path.stat().st_size if path.exists() else 0,
            )
        )
        db.flush()


def append_log(lines: list[str], message: str) -> None:
    lines.append(message)
