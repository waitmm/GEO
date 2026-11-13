import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const range = new URL("../src/AnalysisRangePanel.tsx", import.meta.url);
const observation = new URL("../src/ObservationPanel.tsx", import.meta.url);

test("range previews show the observation-time project configuration version and block unbound groups", async () => {
  const source = await readFile(range, "utf8");
  assert.match(source, /title: "观察时项目配置"/);
  assert.match(source, /项目配置 V\$\{configuration\.version_number\}/);
  assert.match(source, /历史回答缺少观察时项目配置版本/);
  assert.match(source, /row\.project_configuration\?\.binding_status !== "BOUND"/);
  assert.match(source, /group\.project_configuration\?\.binding_status !== "BOUND"/);
  assert.match(source, /group\.prompt_version\?\.binding_status !== "BOUND"/);
});

test("project Monitor direct analysis also blocks an unbound observation-time configuration", async () => {
  const source = await readFile(observation, "utf8");
  assert.match(source, /monitorAnalysisConfigurationReason/);
  assert.match(source, /row\.analysis_selection\.project_configuration\?\.binding_status !== "BOUND"/);
  assert.match(source, /这些回答缺少观察时项目配置版本，无法安全用于新分析。/);
  assert.match(source, /prompt_version\?\.binding_status !== "BOUND"/);
});
