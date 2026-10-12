import { test } from 'node:test';
import assert from 'node:assert/strict';
import { projectConfigurationPayload } from '../src/projectConfiguration.ts';

test('preview and save share payload with explicit locale and complete competitor URL', () => {
  const input = { name: ' Project ', brand_name: 'Brand', brand_aliases: ' B, B, , Other ',
    region: 'US', language: 'en-US', competitors: ' Other: X;Y:https://other.example:8443/help\n\nThird::' };
  const copy = structuredClone(input);
  const payload = projectConfigurationPayload(input);
  assert.deepEqual(payload.brand_aliases, ['B', 'B', 'Other']);
  assert.deepEqual(payload.competitors, [
    { name: 'Other', aliases: ['X', 'Y'], website_url: 'https://other.example:8443/help' },
    { name: 'Third', aliases: [], website_url: '' },
  ]);
  assert.equal(payload.region, 'US');
  assert.equal(payload.language, 'en-US');
  assert.deepEqual(input, copy);
});

test('optional fields remain empty and invalid names are not silently discarded', () => {
  assert.deepEqual(projectConfigurationPayload({}).brand_aliases, []);
  assert.deepEqual(projectConfigurationPayload({}).competitors, []);
  assert.equal(projectConfigurationPayload({ competitors: ':alias:https://example.com' }).competitors[0].name, '');
});
