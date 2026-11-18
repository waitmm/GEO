import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { ObservationRequestEpoch } from '../src/observationRequestEpoch.ts';

const panel = new URL('../src/ObservationPanel.tsx', import.meta.url);

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((nextResolve, nextReject) => { resolve = nextResolve; reject = nextReject; });
  return { promise, resolve, reject };
}

async function runGuardedRequest(epoch, request, state) {
  const token = epoch.begin();
  state.busy = true;
  try {
    const result = await request;
    if (epoch.isCurrent(token)) state.result = result;
  } catch (error) {
    if (epoch.isCurrent(token)) state.error = error.message;
  } finally {
    if (epoch.isCurrent(token)) state.busy = false;
  }
}

test('T23 delayed comparison request cannot overwrite a changed frozen selection', async () => {
  const epoch = new ObservationRequestEpoch();
  const state = { busy: false, result: undefined, error: '' };
  const oldRequest = deferred();
  const oldRun = runGuardedRequest(epoch, oldRequest.promise, state);

  assert.equal(state.busy, true);
  epoch.invalidate(); // baseline, comparison, answer version, URL, or history selection changed.
  state.busy = false; // the panel immediately leaves the old request's loading state.
  oldRequest.resolve({ result_version: 'old-selection' });
  await oldRun;

  assert.deepEqual(state, { busy: false, result: undefined, error: '' });
});

test('T23 delayed old failure cannot replace a newer comparison result or loading state', async () => {
  const epoch = new ObservationRequestEpoch();
  const state = { busy: false, result: undefined, error: '' };
  const oldRequest = deferred();
  const oldRun = runGuardedRequest(epoch, oldRequest.promise, state);

  epoch.invalidate();
  const newRequest = deferred();
  const newRun = runGuardedRequest(epoch, newRequest.promise, state);
  newRequest.resolve({ result_version: 'current-selection' });
  await newRun;
  oldRequest.reject(new Error('old request failed'));
  await oldRun;

  assert.deepEqual(state, { busy: false, result: { result_version: 'current-selection' }, error: '' });
});

test('T23 unmount cleanup blocks an old project response from changing the new page URL', async () => {
  const epoch = new ObservationRequestEpoch();
  const oldRequest = deferred();
  let currentUrl = '?release_view=releaseValidate&v2_project=1&v2_prompt=1';
  const token = epoch.begin();
  const oldRun = oldRequest.promise.then(result => {
    if (!epoch.isCurrent(token)) return;
    currentUrl = `?release_view=releaseValidate&v2_project=1&v2_prompt=1&observation_result=${result.result_version}`;
  });

  // React effect cleanup runs while navigating to another Project/Prompt.
  epoch.invalidate();
  currentUrl = '?release_view=releaseMonitor&v2_project=2&v2_prompt=9';
  oldRequest.resolve({ result_version: 'old-project-comparison' });
  await oldRun;

  assert.equal(currentUrl, '?release_view=releaseMonitor&v2_project=2&v2_prompt=9');
});

test('T23 panel invalidates an active request for every mutable comparison input', async () => {
  const source = await readFile(panel, 'utf8');

  assert.match(source, /function invalidateObservationRequest\(\)/);
  assert.match(source, /function restoreComparison\(saved: any\) \{\s*invalidateObservationRequest\(\);/);
  assert.match(source, /function clearComparisonSelection\(\) \{\s*invalidateObservationRequest\(\);/);
  assert.match(source, /const epoch = observationRequestEpoch\.current\.begin\(\);/);
  assert.match(source, /observationRequestEpoch\.current\.isCurrent\(epoch\)/);
  assert.match(source, /change\(v\); answerChange\(undefined\); clearComparisonSelection\(\);/);
  assert.match(source, /answerChange\(v\); clearComparisonSelection\(\);/);
  assert.match(source, /setTarget\(e\.target\.value\); clearComparisonSelection\(\);/);
  assert.match(source, /onClick=\{\(\) => \{ invalidateObservationRequest\(\); setReload\(n => n \+ 1\); \}\}/);
  assert.match(source, /return \(\) => \{\s*observationRequestEpoch\.current\.invalidate\(\);\s*observationRequestActive\.current = false;/);
});
