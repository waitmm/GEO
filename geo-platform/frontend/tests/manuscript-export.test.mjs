import assert from 'node:assert/strict';
import test from 'node:test';
import { manuscriptFile } from '../src/manuscriptExport.ts';

test('export keeps exact saved body, Unicode, whitespace and version-specific filename', () => {
  const body = '# 标题\r\n\r\n正文😀  \n[来源](https://example.com/doc)\n';
  const result = manuscriptFile('我的稿件', 'execution-v2:1234abcd', body);
  assert.equal(result.body, body);
  assert.equal(result.filename, '我的稿件-execution-v2_1234abcd.md');
  assert.notEqual(result.filename, manuscriptFile('我的稿件', 'execution-v3:5678abcd', body).filename);
  assert.equal(Buffer.from(result.body, 'utf8').toString('utf8'), body);
});

test('untrusted titles cannot add paths, control characters or misleading extensions', () => {
  const result = manuscriptFile('../秘密\\路径\u202e.exe\n', 'execution-v1:abcd', 'safe body');
  assert.ok(result.filename.endsWith('.md'));
  assert.ok(!/[\/\\\u0000-\u001f\u202e]/.test(result.filename));
  assert.ok(!result.filename.startsWith('.'));
  assert.ok(Array.from(manuscriptFile('长'.repeat(500), 'v1', 'body').filename).length <= 134);
  assert.ok(manuscriptFile('   ', 'v1', 'body').filename.startsWith('稿件-'));
});

test('missing saved version or empty body never produces a successful empty export', () => {
  assert.throws(() => manuscriptFile('Title', '', 'body'));
  assert.throws(() => manuscriptFile('Title', 'v1', ' \n'));
});
