import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const history = new URL('../src/PromptVersionHistory.tsx', import.meta.url);

test('prompt history uses only the frozen list and exact-version GET endpoints', async () => {
  const source = await readFile(history, 'utf8');
  assert.match(source, /\/api\/projects\/\$\{projectId\}\/prompts\/\$\{promptId\}\/versions/);
  assert.match(source, /versions\/\$\{encodeURIComponent\(promptVersionId\)\}/);
  assert.match(source, /prompt_version_id/);
  assert.doesNotMatch(source, /method:\s*["'](?:POST|PUT|PATCH|DELETE)/);
});

test('prompt history shows frozen identity and keeps superseded versions read-only', async () => {
  const source = await readFile(history, 'utf8');
  for (const text of ['version_number', 'status', 'snapshot_hash', 'created_at', '冻结问题内容', '标题', '意图类型', '问题组', '启用状态', 'SUPERSEDED', '只读不可修改']) {
    assert.ok(source.includes(text));
  }
  assert.match(source, /selected\.status === "EFFECTIVE"/);
  assert.doesNotMatch(source, /<Input|<Form|<Popconfirm/);
});

test('existing prompt rows mount the read-only history entry', async () => {
  const app = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8');
  assert.match(app, /import \{ PromptVersionHistory \} from ['"]\.\/PromptVersionHistory['"]/);
  assert.match(app, /<PromptVersionHistory projectId=\{projectId!\} promptId=\{row\.id\} \/>/);
});
