import assert from 'node:assert/strict';
import test from 'node:test';
import { isRateLimited, RATE_LIMIT_LABEL, RATE_LIMIT_RECOVERY_GUIDANCE } from '../src/rateLimitFeedback.ts';

test('only a blocked structured rate_limited signal receives rate-limit feedback', () => {
  assert.equal(isRateLimited({ status: 'blocked', errorType: 'rate_limited' }), true);
  assert.equal(isRateLimited({ status: 'blocked', blockedType: 'RATE_LIMITED' }), true);
  assert.equal(isRateLimited({ status: 'failed', errorType: 'rate_limited' }), false);
  assert.equal(isRateLimited({ status: 'blocked', errorType: 'timeout' }), false);
  assert.equal(RATE_LIMIT_LABEL, '平台限流/配额受限');
  assert.match(RATE_LIMIT_RECOVERY_GUIDANCE, /不会自动重试/);
  assert.match(RATE_LIMIT_RECOVERY_GUIDANCE, /正式 V2 样本池/);
});

test('Run pool and legacy Monitor UI preserve the rate-limit recovery boundary', async () => {
  const source = await (await import('node:fs/promises')).readFile(new URL('../src/App.tsx', import.meta.url), 'utf8');
  assert.match(source, /RateLimitAlert/);
  assert.match(source, /恢复后重试/);
  assert.match(source, /不作为品牌未提及处理/);
  assert.match(source, /旧监测页不提供另一套重试入口/);
});
