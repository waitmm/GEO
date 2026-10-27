import assert from 'node:assert/strict';
import test from 'node:test';
import {
  beijingDateTimeLocalValue,
  beijingLocalDateTimeToIso,
  formatBeijingDateTime,
  parseApiDateTime,
} from '../src/time.ts';

test('API UTC timestamps are always displayed in Beijing time', () => {
  const naiveUtc = formatBeijingDateTime('2026-10-27T08:15:30');
  const explicitUtc = formatBeijingDateTime('2026-10-27T08:15:30Z');
  const explicitBeijing = formatBeijingDateTime('2026-10-27T16:15:30+08:00');
  assert.equal(naiveUtc, explicitUtc);
  assert.equal(explicitUtc, explicitBeijing);
  assert.match(explicitUtc, /2026\/10\/27 16:15:30（北京时间）/);
});

test('Beijing datetime-local values round-trip independently of machine timezone', () => {
  assert.equal(beijingLocalDateTimeToIso('2026-10-27T16:15'), '2026-10-27T08:15:00.000Z');
  assert.equal(
    beijingDateTimeLocalValue(new Date('2026-10-27T08:15:00.000Z')),
    '2026-10-27T16:15',
  );
});

test('invalid and missing API timestamps fail visibly', () => {
  assert.equal(parseApiDateTime('not-a-time'), null);
  assert.equal(formatBeijingDateTime('not-a-time'), 'not-a-time');
  assert.equal(formatBeijingDateTime(null), '时间未知');
  assert.throws(() => beijingLocalDateTimeToIso('2026-99-99T99:99'));
});
