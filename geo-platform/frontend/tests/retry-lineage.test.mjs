import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const app = new URL('../src/App.tsx', import.meta.url);
const client = new URL('../src/api/client.ts', import.meta.url);
const types = new URL('../src/types.ts', import.meta.url);

test('Run pool presents one business Run while keeping retry attempts as internal audit', async () => {
  const [appSource, clientSource, typeSource] = await Promise.all([
    readFile(app, 'utf8'), readFile(client, 'utf8'), readFile(types, 'utf8'),
  ]);

  for (const field of ['logical_run_id: string', 'attempt_id: string', 'attempt_no: number', 'retry_of_run_id: number | null']) {
    assert.match(typeSource, new RegExp(field.replace(/[|]/g, '\\$&')));
    assert.match(clientSource, new RegExp(field.replace(/[|]/g, '\\$&')));
  }
  assert.match(appSource, /业务样本 ID/);
  assert.match(appSource, /第 \{row\.attempt_no\} 次/);
  assert.match(appSource, /失败过程保留在内部执行日志/);
  assert.match(appSource, /成功后更新同一条业务 Run/);
  assert.doesNotMatch(appSource, /父 Run/);
  assert.match(typeSource, /logical_sample_total: number/);
  assert.match(typeSource, /attempt_total: number/);
  assert.match(appSource, /个业务样本 · \{v2RunPool\?\.attempt_total \|\| 0\} 次采集尝试/);
  assert.match(appSource, /total: v2RunPool\?\.logical_sample_total \|\| 0/);
  assert.match(appSource, /\["retrying", "queued", "running"\]/);
  assert.match(appSource, /refreshV2RunPool\(v2RunPool\?\.page \|\| 1\)/);
});

test('Run pool selection still protects against duplicate legacy business samples', async () => {
  const appSource = await readFile(app, 'utf8');

  assert.match(appSource, /const \[v2SelectedRuns, setV2SelectedRuns\]/);
  assert.match(appSource, /new Map<string, SinglePromptV2RunPoolItem>\(\)/);
  assert.match(appSource, /newestByLogicalRun\.set\(row\.logical_run_id, row\)/);
  assert.match(appSource, /检测到旧数据中的同一业务样本重复记录/);
  assert.match(appSource, /onSelectAll: \(selected, _selectedRows, changeRows\) => selectV2Runs\(changeRows, selected\)/);
  assert.match(appSource, /个业务样本/);
});

test('legacy monitoring does not expose a second retry implementation and redirects operators to V2', async () => {
  const [appSource, clientSource] = await Promise.all([readFile(app, 'utf8'), readFile(client, 'utf8')]);

  assert.match(appSource, /失败 Run 请在正式 V2 采样记录池中重试/);
  assert.match(appSource, /旧监测页不提供另一套重试入口/);
  assert.match(appSource, /前往正式 V2 采样记录池/);
  assert.doesNotMatch(appSource, /retryBrowserAuditRun/);
  assert.doesNotMatch(clientSource, /retryBrowserAuditRun/);
  assert.doesNotMatch(clientSource, /\/api\/monitoring\/runs\/\$\{runId\}\/retry/);
});
