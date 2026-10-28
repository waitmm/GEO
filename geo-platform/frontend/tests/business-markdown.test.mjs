import assert from 'node:assert/strict';
import test from 'node:test';
import { parseBusinessMarkdown } from '../src/businessMarkdownParser.ts';

test('business markdown turns generated prose into readable blocks', () => {
  const blocks = parseBusinessMarkdown('### 标题\n\n正文 **重点** [[answer:10:0:1]]\n\n- 一\n- 二\n\n| 表述 | 资格 |\n|---|---|\n| 能力 | VERIFY_FIRST |');
  assert.deepEqual(blocks.map(block => block.type), ['heading', 'paragraph', 'list', 'table']);
  assert.equal(blocks[2].type === 'list' && blocks[2].items.length, 2);
  assert.equal(blocks[3].type === 'table' && blocks[3].rows.length, 1);
});
