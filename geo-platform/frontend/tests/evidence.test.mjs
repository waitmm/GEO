import assert from 'node:assert/strict';
import test from 'node:test';
import { locateAnswer, evidenceLink } from '../src/api/evidence.ts';

const answers = [{ run_id: 4, text: '开头😀甲工具有条件支持。结尾', text_hash: 'fixed' }];
test('source navigation preserves code-point offsets, complete answer and Run identity', () => {
  const selected = locateAnswer(answers, { run_id: 4, raw_start: 3, raw_end: 6, raw_text: '甲工具' });
  assert.deepEqual(selected, { before: '开头😀', text: '甲工具', after: '有条件支持。结尾' });
  assert.equal(Object.values(selected).join(''), answers[0].text);
});
test('wrong Run, stale offsets and fabricated text never receive a highlighted position', () => {
  const unit = { run_id: 4, raw_start: 3, raw_end: 6, raw_text: '甲工具' };
  for (const change of [{ run_id: 5 }, { raw_start: -1 }, { raw_end: 99 }, { raw_text: '目标品牌' }, { raw_start: 3.5 }]) {
    assert.equal(locateAnswer(answers, { ...unit, ...change }), null);
  }
});
test('source links cannot execute scripts or expose credentials', () => {
  for (const value of ['javascript:alert(1)', 'data:text/html,test', 'file:///private', '/relative', 'https://user:secret@example.com']) {
    assert.equal(evidenceLink(value), undefined);
  }
  assert.equal(evidenceLink('https://example.com/page'), 'https://example.com/page');
});
