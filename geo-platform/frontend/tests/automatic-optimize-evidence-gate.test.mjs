import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { draftRequestBlocked } from '../src/draftEvidenceGate.ts';

const panel = new URL('../src/AutomaticOptimizePanel.tsx', import.meta.url);
const gate = new URL('../src/draftEvidenceGate.ts', import.meta.url);

test('draft evidence eligibility is rendered without inventing readiness for legacy tasks', async () => {
  const [source, gateSource] = await Promise.all([readFile(panel, 'utf8'), readFile(gate, 'utf8')]);

  assert.match(gateSource, /objects\?\.draft_eligibility/);
  assert.match(source, /该历史任务未返回结构化证据缺口；保留原始失败记录，不能据此推断证据数量或准入状态。/);
  assert.match(source, /当前校验集合/);
  assert.match(source, /待补齐：/);
  assert.match(source, /下一步：/);
  assert.match(source, /NO_ELIGIBLE_EVIDENCE: "策略尚未引用可用于正文的证据"/);
  assert.match(source, /证据条件未满足（\$\{value\}）/);
});

test('known draft evidence blockers cannot resume or authorize another model request', async () => {
  const [source, gateSource] = await Promise.all([readFile(panel, 'utf8'), readFile(gate, 'utf8')]);

  assert.match(gateSource, /DRAFT_EVIDENCE_NOT_QUALIFIED/);
  assert.match(gateSource, /INVALID_DRAFT_EVIDENCE/);
  assert.match(source, /未发送新的模型请求，尚未生成稿件。/);
  assert.match(source, /disabled=\{draftBlocked\}/);
  assert.match(source, /disabled=\{!!task\.usage\.unsettled_requests \|\| draftBlocked\}/);
  assert.match(source, /证据不足，不能恢复生成/);
  assert.match(source, /正文生成尚不具备合格证据条件；请查看上方的待补齐和下一步。/);
  assert.doesNotMatch(source, /Run #\{l\.run_id\}：/);
});

test('historical E1 parse wrapper blocks only the exact invalid draft evidence failure', () => {
  assert.equal(draftRequestBlocked({
    blocker_code: 'FAILED_PARSE',
    blocker_detail: 'generation rejected: INVALID_DRAFT_EVIDENCE',
    objects: {},
  }), true);
  assert.equal(draftRequestBlocked({
    blocker_code: 'FAILED_PARSE',
    blocker_detail: 'other structured output parse failure',
    objects: {},
  }), false);
});
