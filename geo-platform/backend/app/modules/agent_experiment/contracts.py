"""Strict model-facing contracts for GEO Agent Experiment V1."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EvidenceKind(str, Enum):
    ANSWER_SPAN = "answer_span"
    CITATION_OCCURRENCE = "citation_occurrence"
    SOURCE_PASSAGE = "source_passage"
    TRUTH_FACT = "truth_fact"
    KNOWLEDGE_PASSAGE = "knowledge_passage"
    TOOL_OBSERVATION = "tool_observation"


class EvidenceRef(StrictModel):
    kind: Literal["answer_span", "citation_occurrence", "source_passage", "truth_fact", "knowledge_passage", "tool_observation"]
    run_id: str | None = None
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=1)
    citation_occurrence_id: str | None = None
    snapshot_id: str | None = None
    passage_id: str | None = None
    truth_fact_id: str | None = None
    truth_version_id: str | None = None
    knowledge_version_id: str | None = None
    knowledge_passage_id: str | None = None
    observation_id: str | None = None

    @model_validator(mode="after")
    def required_locator(self):
        required = {
            "answer_span": ("run_id", "start", "end"),
            "citation_occurrence": ("citation_occurrence_id",),
            "source_passage": ("snapshot_id", "passage_id"),
            "truth_fact": ("truth_fact_id", "truth_version_id"),
            "knowledge_passage": ("knowledge_version_id", "knowledge_passage_id"),
            "tool_observation": ("observation_id",),
        }[self.kind]
        if any(getattr(self, name) is None for name in required):
            raise ValueError(f"{self.kind} 缺少定位字段")
        if self.kind == "answer_span" and self.end <= self.start:
            raise ValueError("answer_span end 必须大于 start")
        return self


class Assertion(StrictModel):
    statement: str = Field(min_length=1)
    classification: Literal["OBSERVED", "VERIFIED_FACT", "INFERENCE", "HYPOTHESIS", "UNKNOWN"]
    reasoning: str
    evidence_refs: list[EvidenceRef]

    @model_validator(mode="after")
    def verified_requires_evidence(self):
        if self.classification in {"OBSERVED", "VERIFIED_FACT"} and not self.evidence_refs:
            raise ValueError("观察或已验证事实必须有证据指针")
        return self


class AgentAction(StrictModel):
    id: str = Field(min_length=1)
    priority: Literal["HIGH", "MEDIUM", "LOW"]
    what: str = Field(min_length=1)
    why: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    channel_role: Literal["PRIMARY", "SECONDARY", "EXPERIMENTAL", "OBSERVE", "UNDETERMINED"]
    readiness: Literal["READY", "VERIFY_FIRST", "EXPERIMENTAL"]
    required_asset: str = Field(min_length=1)
    next_step: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef]


class Deliverable(StrictModel):
    id: str = Field(min_length=1)
    action_ids: list[str] = Field(min_length=1)
    asset_type: Literal["HELP_DOC", "WEB_PAGE_UPDATE", "FAQ", "ARTICLE", "COMPARISON_GUIDE", "OTHER"]
    title: str = Field(min_length=1)
    body_markdown: str = Field(min_length=1)
    editorial_notes: list[str]


class QASelfCheck(StrictModel):
    checked: list[str]
    identified_issues: list[str]
    suggested_repairs: list[str]


class ValidationPlan(StrictModel):
    questions: list[str] = Field(min_length=1)
    metrics: list[str] = Field(min_length=1)
    comparison_prerequisites: list[str]
    non_causality_note: str = Field(min_length=1)


class AgentArtifact(StrictModel):
    schema_version: Literal["geo.agent.result.v1"]
    summary: str = Field(min_length=1)
    observations: list[Assertion]
    diagnosis: list[Assertion] = Field(min_length=1)
    actions: list[AgentAction] = Field(min_length=1)
    deliverables: list[Deliverable] = Field(min_length=1)
    qa_self_check: QASelfCheck
    validation_plan: ValidationPlan
    limitations: list[str]

    @model_validator(mode="after")
    def relationships_exist(self):
        action_ids = {row.id for row in self.actions}
        if len(action_ids) != len(self.actions):
            raise ValueError("action id 不能重复")
        if len({row.id for row in self.deliverables}) != len(self.deliverables):
            raise ValueError("deliverable id 不能重复")
        missing = sorted({value for row in self.deliverables for value in row.action_ids} - action_ids)
        if missing:
            raise ValueError(f"deliverable 引用了不存在的 action: {missing}")
        return self


class AgentDecision(StrictModel):
    action_type: Literal["TOOL_CALL", "FINAL_ARTIFACT", "STOP"]
    reasoning: str = Field(min_length=1)
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    artifact: AgentArtifact | None = None
    stop_reason: str | None = None

    @model_validator(mode="after")
    def match_action(self):
        if self.action_type == "TOOL_CALL" and (not self.tool_name or self.arguments is None):
            raise ValueError("TOOL_CALL 必须提供 tool_name 和 arguments")
        if self.action_type == "FINAL_ARTIFACT" and self.artifact is None:
            raise ValueError("FINAL_ARTIFACT 必须提供 artifact")
        if self.action_type == "STOP" and not self.stop_reason:
            raise ValueError("STOP 必须提供 stop_reason")
        return self


TOOL_NAMES = frozenset({
    "get_scope_summary", "list_runs", "read_answer", "list_citations", "read_source",
    "read_brand_context", "read_product_truth", "read_monitor_metrics", "save_working_note",
})
