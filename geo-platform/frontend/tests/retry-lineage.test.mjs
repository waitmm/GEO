import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const app = new URL('../src/App.tsx', import.meta.url);
const client = new URL('../src/api/client.ts', import.meta.url);
const types = new URL('../src/types.ts', import.meta.url);

test('Run pool presents retry lineage without turning retries into independent samples', async () => {
  const [appSource, clientSource, typeSource] = await Promise.all([
    readFile(app, 'utf8'), readFile(client, 'utf8'), readFile(types, 'utf8'),
  ]);

  for (const field of ['logical_run_id: string', 'attempt_id: string', 'attempt_no: number', 'retry_of_run_id: number | null']) {
    assert.match(typeSource, new RegExp(field.replace(/[|]/g, '\\$&')));
    assert.match(clientSource, new RegExp(field.replace(/[|]/g, '\\$&')));
  }
  assert.match(appSource, /逻辑样本 ID/);
  assert.match(appSource, /尝试 #\{row\.attempt_no\}/);
  assert.match(appSource, /父 Run/);
  assert.match(appSource, /不增加独立样本分母，并保留旧 Run/);
  assert.match(appSource, /追加新的尝试/);
});
