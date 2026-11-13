import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { brandAssociationContent } from '../src/brandAssociationContext.ts';
import { aggregateObservationSummary, savedResultLabel, splitAgentResult } from '../src/agentResultPresentation.ts';

test('business result parser keeps the six delivery sections separate', () => {
  const markdown = `## GEO 诊断与依据\n诊断\n\n## 品牌表现与证据缺口\n品牌缺口\n\n## 优化策略与渠道\n策略\n\n## 完整正文\n# 标题\n\n正文\n\n### 子标题\n内容\n\n## QA 与事实限制\nVERIFY_FIRST\n\n## 复测计划\n复测`;
  const sections = splitAgentResult(markdown);
  assert.equal(sections['GEO 诊断与依据'], '诊断');
  assert.equal(sections['品牌表现与证据缺口'], '品牌缺口');
  assert.match(sections['完整正文'], /### 子标题/);
  assert.equal(sections['QA 与事实限制'], 'VERIFY_FIRST');
  assert.equal(sections['复测计划'], '复测');
});

test('historical result is never presented as a newly completed task', () => {
  assert.equal(savedResultLabel(1, 'SUCCEEDED'), '已保存的真实模型结果');
  assert.equal(savedResultLabel(0, 'WAITING_AUTHORIZATION'), '等待服务启动的新任务');
  assert.equal(savedResultLabel(0, 'SUCCEEDED'), '已保存结果（来源待核对）');
});

test('v5 aggregate observation is shown in business language without backfilling old results', () => {
  assert.equal(aggregateObservationSummary({ result: { evidence_pack: {} } }), null);
  const summary = aggregateObservationSummary({
    result: {
      evidence_pack: {
        aggregate_evidence_sets: [{
          evidence_set_id: 'private-set-hash',
          observation_status: 'SERVER_VERIFIED_ABSENCE',
          members: [{ run_id: 1 }, { run_id: 2 }],
          excluded_members: [{ run_id: 3 }],
        }],
        verified_brand_observations: [{
          observation_id: 'private-observation-hash',
          canonical_text: '本次冻结的 2 条有效回答中，未检测到目标品牌的字面出现。',
        }],
      },
    },
  });
  assert.equal(summary?.status, 'VERIFIED_ABSENCE');
  assert.equal(summary?.includedCount, 2);
  assert.equal(summary?.excludedCount, 1);
  assert.match(summary?.observationText || '', /2 条有效回答/);
  assert.doesNotMatch(JSON.stringify(summary), /private-set-hash|private-observation-hash/);
  assert.match(summary?.limitation || '', /不证明推荐、产品能力、排名或因果关系/);
});

test('brand association input explicitly separates goals from facts', () => {
  const content = brandAssociationContent({
    association_goals: '希望在某类问题中被考虑',
    verified_capabilities: '项目组声明的能力',
    verified_sources: '官网资料 V2',
    pending_capabilities: '尚待产品确认',
    prohibited_claims: '不得保证平台收录',
  });
  assert.match(content, /仅为优化目标，不是产品事实/);
  assert.match(content, /仍须通过 Product Truth 与来源资格校验/);
  assert.match(content, /不得保证平台收录/);
});

test('AI optimization is the default lane and feedback uses actual APIs', () => {
  const panel = readFileSync(new URL('../src/AgentExperimentPanel.tsx', import.meta.url), 'utf8');
  const optimize = readFileSync(new URL('../src/AutomaticOptimizePanel.tsx', import.meta.url), 'utf8');
  assert.match(optimize, /useState<"workflow" \| "agent">\("agent"\)/);
  assert.match(panel, /agent-experiments\/\$\{encodeURIComponent\(selectedRun\.run_id\)\}\/feedback/);
  assert.match(panel, /agent-experiments\/capabilities/);
  assert.match(panel, /结果历史版本/);
  assert.match(panel, /复制完整正文/);
  assert.match(panel, /内容已经生成并保存，但没有通过证据校验/);
  assert.match(panel, /复制未通过草稿/);
  assert.match(panel, /result\?\.result\?\.delivery_markdown \|\| result\?\.result\?\.raw_markdown/);
  assert.match(panel, /result\?\.deliverable_markdown/);
  assert.match(panel, /download\(reportMarkdown, result\.result_version\)/);
  assert.match(panel, /引用来源渠道观察（不是渠道效果结论）/);
  assert.match(panel, /BusinessMarkdown/);
  assert.match(panel, /runCount\} 条回答/);
  assert.match(panel, /引用次数高不等于该渠道最适合发布/);
  assert.match(panel, /formatBeijingDateTime/);
  assert.doesNotMatch(panel, /管理员设置本任务额度|管理员授权当前冻结任务|保守单价|AI 优化计费依据|InputNumber/);
  assert.match(panel, /AI 优化任务已创建并开始运行/);
  assert.match(panel, /AI 优化运行中…/);
  assert.match(panel, /正在整理所选回答、引用与品牌资料/);
  assert.match(panel, /无需手动刷新页面/);
  assert.match(panel, /EVIDENCE_PACK_CORE_EXCEEDS_BUDGET/);
  assert.match(panel, /restartWithServerPolicy/);
});
