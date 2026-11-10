import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const panel = readFileSync(new URL("../src/AgentExperimentPanel.tsx", import.meta.url), "utf8");
const children = readFileSync(new URL("../src/DraftArtifactPanel.tsx", import.meta.url), "utf8");

test("AI 优化允许选择 HELP_DOC 和 FAQ 且不暴露费用输入", () => {
  assert.match(panel, /requested_artifact_types/);
  assert.match(panel, /帮助文档/);
  assert.match(panel, /常见问题 FAQ/);
  assert.doesNotMatch(panel, /人民币硬上限|保守单价|Token 上限/);
});

test("子稿件分别展示状态、证据、QA、导出、反馈和重生成", () => {
  for (const text of ["每份内容独立保存和校验", "证据与 QA", "导出 Markdown", "只重新生成这份", "保存这份稿件的反馈"]) {
    assert.match(children, new RegExp(text));
  }
  assert.match(children, /artifact_version/);
  assert.match(children, /parent_result_version/);
  assert.match(children, /稿件已保存，但未通过独立校验/);
  assert.match(children, /failureSummary/);
  assert.doesNotMatch(children, /artifact\.failure\.code.*artifact\.failure\.detail/);
  assert.match(children, /disabled=\{artifact.status !== "SUCCESS"\}/);
  assert.match(children, /单篇重新生成尚未启用/);
  assert.match(children, /disabled=\{!regenerationEnabled\}/);
  assert.match(children, /历史版本只读保留，不会被重新生成覆盖/);
  assert.match(children, /selectedVersions/);
});

test("父部分成功不会伪装成全部完成", () => {
  assert.match(children, /PARTIAL_SUCCESS: "部分完成"/);
  assert.match(children, /单篇失败不会删除另一篇成果/);
  assert.match(panel, /部分内容已经保存并可使用/);
  assert.match(panel, /agent-history-table/);
});

test("多内容结果不再把父报告伪装成第三份稿件", () => {
  assert.match(panel, /hasDraftArtifacts/);
  assert.match(panel, /导出本次优化完整报告/);
  assert.match(panel, /!hasDraftArtifacts && <Button/);
  assert.match(panel, /各内容资产/);
});

test("结构化品牌观察以业务文案展示且不暴露内部 hash", () => {
  assert.match(panel, /本次品牌观察与证据范围/);
  assert.match(panel, /纳入 \{aggregateObservation\.includedCount\} 条完整回答/);
  assert.match(panel, /aggregateObservationSummary/);
  assert.doesNotMatch(panel, /evidence_set_id|observation_id/);
});
