from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CollectorResult:
    answer_text: str = ""
    answer_html: str = ""
    references: list[dict[str, Any]] = field(default_factory=list)
    retrieval_candidates: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)


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
