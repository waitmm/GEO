import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { summarizeArtifactEvidenceQa } from "../src/draftArtifactPresentation.ts";

test("draft artifact evidence and QA have Chinese operator-facing summaries", () => {
  const summary = summarizeArtifactEvidenceQa({
    action_evidence_refs: [{ kind: "truth", section: "帮助文档" }],
    result_evidence_references: [{ kind: "source", source_title: "官方说明" }],
  }, {
    result_qa: "发布前 VERIFY_FIRST",
    artifact_validation: { status: "FAIL", issues: [{ code: "FAQ_STRUCTURE_REQUIRED", detail: "问题数量不足" }] },
  }, "FAILED", { code: "ARTIFACT_VALIDATION_FAILED", detail: "未通过内容校验" });
  assert.equal(summary.evidenceCount, 2);
  assert.deepEqual(summary.evidenceTypes, ["已确认事实", "来源资料"]);
  assert.deepEqual(summary.evidenceLocations, ["帮助文档", "官方说明"]);
  assert.equal(summary.qualification, "未通过独立校验");
  assert.equal(summary.verifyFirst, true);
  assert.match(summary.issues.join("；"), /至少需要两个明确问题/);
});

test("VERIFY_FIRST warning requires an explicit value, not just a field name", () => {
  const base = { artifact_validation: { status: "PASS", issues: [] } };
  assert.equal(summarizeArtifactEvidenceQa({}, { ...base, verify_first: false }, "SUCCESS").verifyFirst, false);
  assert.equal(summarizeArtifactEvidenceQa({}, { ...base, verify_first: null }, "SUCCESS").verifyFirst, false);
  assert.equal(summarizeArtifactEvidenceQa({}, { ...base, verification_note: "无需核验" }, "SUCCESS").verifyFirst, false);
  assert.equal(summarizeArtifactEvidenceQa({}, { ...base, verify_first: true }, "SUCCESS").verifyFirst, true);
  assert.equal(summarizeArtifactEvidenceQa({}, { ...base, issues: ["L3_VERIFY_FIRST_REQUIRED"] }, "SUCCESS").verifyFirst, true);
});

test("panel keeps raw JSON secondary and translates feedback history", () => {
  const panel = readFileSync(new URL("../src/DraftArtifactPanel.tsx", import.meta.url), "utf8");
  for (const text of ["证据数量", "证据类型", "证据定位", "QA 资格", "需先核实（VERIFY_FIRST）", "技术详情（原始数据）", "feedbackRatingLabel"]) {
    assert.match(panel, new RegExp(text));
  }
  assert.match(panel, /JSON\.stringify\(artifact\.evidence/);
});
