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
  assert.match(children, /disabled=\{artifact.status !== "SUCCESS"\}/);
  assert.match(children, /单篇重新生成尚未启用/);
  assert.match(children, /disabled=\{!regenerationEnabled\}/);
});

test("父部分成功不会伪装成全部完成", () => {
  assert.match(children, /PARTIAL_SUCCESS: "部分完成"/);
  assert.match(children, /单篇失败不会删除另一篇成果/);
});
