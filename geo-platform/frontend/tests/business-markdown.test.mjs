import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { parseBusinessMarkdown } from '../src/businessMarkdownParser.ts';

test('business markdown turns generated prose into readable blocks', () => {
  const blocks = parseBusinessMarkdown('### 标题\n\n正文 **重点** [[answer:10:0:1]]\n\n- 一\n- 二\n\n| 表述 | 资格 |\n|---|---|\n| 能力 | VERIFY_FIRST |');
  assert.deepEqual(blocks.map(block => block.type), ['heading', 'paragraph', 'list', 'table']);
  assert.equal(blocks[2].type === 'list' && blocks[2].items.length, 2);
  assert.equal(blocks[3].type === 'table' && blocks[3].rows.length, 1);
});

test('structured observation locator is rendered as a safe business label', () => {
  const component = readFileSync(new URL('../src/BusinessMarkdown.tsx', import.meta.url), 'utf8');
  assert.match(component, /parts\[0\] === "observation"/);
  assert.match(component, /return "已验证范围观察"/);
  assert.match(component, /answer\|truth\|citation\|source\|observation/);
});
