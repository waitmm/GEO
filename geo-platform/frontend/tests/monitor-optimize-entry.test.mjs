import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const observation = new URL("../src/ObservationPanel.tsx", import.meta.url);

test("project Monitor gives a prompt-local next step when direct analysis is unavailable", async () => {
  const source = await readFile(observation, "utf8");
  assert.match(source, /function openPromptMonitor\(targetPromptId: number\)/);
  assert.match(source, /v2_project: String\(project\.id\), v2_prompt: String\(targetPromptId\)/);
  assert.match(source, /查看这个问题/);
  assert.match(source, /当前没有可安全分析的回答。请先打开这个问题/);
  assert.match(source, /可人工导入或配置采集计划/);
  assert.match(source, /请点击“查看这个问题”/);
});
