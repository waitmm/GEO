import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  beginAgentHistorySelection,
  completeAgentHistorySelection,
  failAgentHistorySelection,
  isCurrentAgentHistoryLoad,
  isCurrentAgentHistoryRequest,
  isCurrentAgentHistoryResult,
} from "../src/agentHistorySelection.ts";

test("switching A to B immediately makes A's frozen result ineligible for rendering", () => {
  const aLoaded = completeAgentHistorySelection(beginAgentHistorySelection("A"), "A");
  assert.equal(isCurrentAgentHistoryResult(aLoaded, "A"), true);

  const bLoading = beginAgentHistorySelection("B");
  assert.equal(bLoading.loadedRunId, undefined);
  assert.equal(bLoading.loading, true);
  assert.equal(isCurrentAgentHistoryResult(bLoading, "A"), false);
  assert.equal(isCurrentAgentHistoryResult(bLoading, "B"), false);

  const bLoaded = completeAgentHistorySelection(bLoading, "B");
  assert.equal(isCurrentAgentHistoryResult(bLoaded, "A"), false);
  assert.equal(isCurrentAgentHistoryResult(bLoaded, "B"), true);
});

test("a failed B load never re-enables A assets, QA, feedback, or comparison", () => {
  const failed = failAgentHistorySelection(beginAgentHistorySelection("B"), "B", "B read failed");
  assert.equal(failed.loading, false);
  assert.equal(failed.loadedRunId, undefined);
  assert.equal(failed.error, "B read failed");
  assert.equal(isCurrentAgentHistoryResult(failed, "A"), false);
  assert.equal(isCurrentAgentHistoryResult(failed, "B"), false);
});

test("a stale A failure after selecting B cannot be surfaced as B's failure", () => {
  const bLoading = beginAgentHistorySelection("B");
  assert.equal(isCurrentAgentHistoryLoad(bLoading.selectedRunId, "A"), false);
  assert.equal(isCurrentAgentHistoryLoad(bLoading.selectedRunId, "B"), true);
  assert.deepEqual(failAgentHistorySelection(bLoading, "A", "A read failed"), bLoading);
});

test("a list-stage failure from A is invalidated before B becomes selected", () => {
  const aListRequestEpoch = 7;
  const bSelectionEpoch = 8;
  assert.equal(isCurrentAgentHistoryRequest(aListRequestEpoch, bSelectionEpoch), false);
  assert.equal(isCurrentAgentHistoryRequest(bSelectionEpoch, bSelectionEpoch), true);
});

test("the history panel clears all A-specific projections and renders only a selected-and-loaded B", async () => {
  const source = await readFile(new URL("../src/AgentExperimentPanel.tsx", import.meta.url), "utf8");
  assert.match(source, /setDetail\(undefined\); setResults\(\[\]\); setFeedback\(\[\]\); setComparison\(undefined\); setSelectedResultVersion\(undefined\);/);
  assert.match(source, /isCurrentAgentHistoryResult\(historySelection, active\?\.run_id\)/);
  assert.match(source, /isCurrentAgentHistoryLoad\(selectedRunRef\.current, attemptedRunId\)/);
  assert.match(source, /\+\+generation\.current;\n    selectedRunRef\.current = runId/);
  assert.match(source, /所选优化历史读取失败/);
  assert.match(source, /未显示其他任务的结果/);
});
