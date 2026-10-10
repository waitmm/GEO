import assert from 'node:assert/strict';
import test from 'node:test';
import { readOptimizationSelection, resolveOptimizationSelection } from '../src/optimizationSelection.ts';

const old = { task_id: 'old', objects: { deliveries: [{ proposal_id: 'proposal', result_version: 'v2' }] } };
const current = { task_id: 'current', objects: { deliveries: [{ proposal_id: 'proposal', result_version: 'v4' }] } };
const tasks = [current, old];

test('explicit historical task remains selected after reload or new task arrival', () => {
  const selection = readOptimizationSelection('?v2_analysis=a&optimization_task=old', 'a');
  assert.equal(resolveOptimizationSelection(tasks, selection), old);
  assert.equal(resolveOptimizationSelection([{ task_id: 'newer', objects: {} }, ...tasks], selection), old);
});

test('unknown, empty and foreign task identities never silently select newest', () => {
  for (const id of ['missing', '', 'foreign']) {
    const selection = readOptimizationSelection(`?v2_analysis=a&optimization_task=${id}`, 'a');
    assert.equal(resolveOptimizationSelection(tasks, selection), undefined);
  }
  assert.equal(readOptimizationSelection('?v2_analysis=other&optimization_task=old', 'a'), null);
});

test('existing exact delivery link resolves both proposal and version, never latest', () => {
  const prefix = '?v2_analysis=a&v2_execution_proposal=proposal&v2_execution_result=';
  assert.equal(resolveOptimizationSelection(tasks, readOptimizationSelection(prefix + 'v2', 'a')), old);
  for (const suffix of ['missing', '']) {
    assert.equal(resolveOptimizationSelection(tasks, readOptimizationSelection(prefix + suffix, 'a')), undefined);
  }
  assert.equal(resolveOptimizationSelection(tasks, readOptimizationSelection('?v2_analysis=a&v2_execution_result=v2', 'a')), undefined);
});

test('only a link with no explicit selection may initially choose the first task', () => {
  assert.equal(resolveOptimizationSelection(tasks, readOptimizationSelection('?v2_analysis=a', 'a')), current);
  assert.equal(resolveOptimizationSelection([], null), undefined);
});
