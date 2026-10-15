import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { projectConfigurationVersionPath } from '../src/projectConfiguration.ts';

const history = new URL('../src/ProjectConfigurationHistory.tsx', import.meta.url);

test('configuration history uses the frozen list and exact-version read endpoints', async () => {
  const source = await readFile(history, 'utf8');
  assert.match(source, /\/api\/projects\/\$\{projectId\}\/configuration-versions/);
  assert.match(source, /configuration_version_id/);
  assert.match(source, /projectConfigurationVersionPath\(projectId, configurationVersionId\)/);
  assert.match(source, /value: version\.configuration_version_id/);
  assert.equal(
    projectConfigurationVersionPath(41, 'project-config-20261015-v2'),
    '/api/projects/41/configuration-versions/project-config-20261015-v2',
  );
  assert.doesNotMatch(source, /method:\s*["'](?:POST|PUT|PATCH|DELETE)/);
});

test('configuration history exposes frozen identity and never presents superseded versions as current', async () => {
  const source = await readFile(history, 'utf8');
  for (const text of ['version_number', 'status', 'snapshot_hash', 'created_at', '冻结品牌', '品牌别名', '品牌官网', '地区 / 语言', '竞品', '项目配置历史（只读）', 'SUPERSEDED']) {
    assert.ok(source.includes(text));
  }
  assert.match(source, /selected\.status === "EFFECTIVE"/);
  assert.doesNotMatch(source, /selected\.status === "SUPERSEDED"\s*\?\s*["']green/);
  assert.doesNotMatch(source, /<Input|<Form|<Popconfirm/);
});

test('project editing mounts the read-only history only for an existing project', async () => {
  const app = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8');
  assert.match(app, /import \{ ProjectConfigurationHistory \} from ['"]\.\/ProjectConfigurationHistory['"]/);
  assert.match(app, /\{editingProjectId && <ProjectConfigurationHistory projectId=\{editingProjectId\} \/>\}/);
});
