"""LLM Call Cache — 数据库层缓存。

相同 input_hash + model + prompt_version + schema_version 不重复调用 API。
依赖 models/db.py 中的 llm_call_cache 表（由 alembic migration 创建）。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session


class LLMCallCache:
    @staticmethod
    def get(
        db: Session,
        *,
        provider: str,
        model: str,
        prompt_version: str,
        schema_version: str,
        input_hash: str,
    ) -> dict[str, Any] | None:
        from app.models import LLMCallCache as Row

        row = (
            db.query(Row)
            .filter(
                Row.provider == provider,
                Row.model == model,
                Row.prompt_version == prompt_version,
                Row.schema_version == schema_version,
                Row.input_hash == input_hash,
            )
            .order_by(Row.id.desc())
            .first()
        )
        if not row:
            return None
        return {
            "parsed_payload": json.loads(row.parsed_payload_json or "{}"),
            "token_usage": row.token_usage,
        }

    @staticmethod
    def put(
        db: Session,
        *,
        provider: str,
        model: str,
        prompt_version: str,
        schema_version: str,
        input_hash: str,
        raw_response_hash: str,
        parsed_payload: dict[str, Any],
        token_usage: int,
    ) -> None:
        from app.models import LLMCallCache as Row

        row = Row(
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            schema_version=schema_version,
            input_hash=input_hash,
            raw_response_hash=raw_response_hash,
            parsed_payload_json=json.dumps(parsed_payload, ensure_ascii=False),
            token_usage=token_usage,
            created_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
