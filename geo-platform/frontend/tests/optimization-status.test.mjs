import test from 'node:test';
import assert from 'node:assert/strict';
import { optimizationStatus } from '../src/optimizationStatus.ts';

test('fact reprojection without a new manuscript does not claim manuscript delivery', () => {
  for (const status of ['COMPLETED', 'COMPLETED_WITH_LIMITATIONS']) {
    assert.equal(optimizationStatus({ task_kind: 'TRUTH_REPROJECTION', status, objects: {} }), '纠错已应用，无新增稿件');
  }
});

test('pending reprojection and an actual delivery remain distinct', () => {
  assert.equal(optimizationStatus({ task_kind: 'TRUTH_REPROJECTION', status: 'WAITING_AUTHORIZATION', objects: {} }), '等待调用授权');
  assert.equal(optimizationStatus({ task_kind: 'TRUTH_REPROJECTION', status: 'COMPLETED_WITH_LIMITATIONS',
    objects: { deliveries: [{ result_version: 'execution-v2' }] } }), '稿件已交付，有范围限制');
  assert.equal(optimizationStatus({ task_kind: 'AUTOMATIC', status: 'BLOCKED', objects: {} }), '需要处理');
});
