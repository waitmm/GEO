import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const app = new URL('../src/App.tsx', import.meta.url);
const client = new URL('../src/api/client.ts', import.meta.url);
const types = new URL('../src/types.ts', import.meta.url);

test('new sampling and selected-run analyses submit an exact PromptVersion binding', async () => {
  const [appSource, clientSource] = await Promise.all([readFile(app, 'utf8'), readFile(client, 'utf8')]);
  for (const field of ['prompt_version_id: v2SelectedPromptVersion.prompt_version_id', 'snapshot_hash: v2SelectedPromptVersion.snapshot_hash']) {
    assert.equal((appSource.match(new RegExp(field, 'g')) || []).length, 2, `${field} belongs to both create paths`);
  }
  assert.match(clientSource, /listPromptVersions:/);
  assert.match(clientSource, /getPromptVersion:/);
  assert.match(clientSource, /createSinglePromptV2Analysis: \(payload: \{[^}]*prompt_version_id: string; snapshot_hash: string;/);
  assert.match(clientSource, /createSinglePromptV2AnalysisFromRuns: \(payload: \{[\s\S]*prompt_version_id: string; snapshot_hash: string;/);
});

test('the UI obtains the selected version by exact ID and exposes immutable/legacy identity', async () => {
  const [appSource, typeSource] = await Promise.all([readFile(app, 'utf8'), readFile(types, 'utf8')]);
  assert.match(appSource, /api\.getPromptVersion\(projectId, activePromptId, promptVersionId\)/);
  assert.match(appSource, /不会隐式使用 latest/);
  assert.match(appSource, /LEGACY_UNBOUND：历史 Analysis 未绑定 Prompt 版本/);
  assert.match(appSource, /不会被当前 Prompt 重新解释，也不会伪造版本归属/);
  assert.match(typeSource, /binding: "BOUND"/);
  assert.match(typeSource, /binding: "LEGACY_UNBOUND"/);
});
