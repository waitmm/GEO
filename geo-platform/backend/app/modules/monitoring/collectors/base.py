from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CollectorResult:
    answer_text: str = ""
    answer_html: str = ""
    platform_reported_search: dict[str, Any] = field(default_factory=dict)
    answer_content_boundary: dict[str, Any] = field(default_factory=dict)
    references: list[dict[str, Any]] = field(default_factory=list)
    retrieval_candidates: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    # COMPLETE and CONFIRMED_NONE are positive observations.  UNKNOWN and
    # PARSE_FAILED must never be inferred as a confirmed zero merely because
    # the collector returned no reference rows.
    reference_observation_status: str = ""


class CollectorError(Exception):
    """Platform-neutral collector failure consumed by the shared executor."""

    error_type = "unknown_error"


@dataclass
class CollectorHealth:
    healthy: bool
    status: str
    message: str = ""


class BaseCollector(ABC):
    @abstractmethod
    async def collect(self, run: Any) -> CollectorResult:
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> CollectorHealth:
        raise NotImplementedError
