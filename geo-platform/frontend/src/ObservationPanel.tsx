import { useEffect, useRef, useState } from "react";
import { Alert, Button, Collapse, Empty, Form, Input, Select, Space, Table, Typography } from "antd";
import { BarChart3, RefreshCw, Save } from "lucide-react";
import { request } from "./api/client";
import type { Project } from "./types";
import { SamplingSchedulePanel } from "./SamplingSchedulePanel";
import { SupplementalSources } from "./SupplementalSources";

const names: Record<string, string> = { brand_mention_rate: "正文提及", brand_option_rate: "列为选项", brand_recommendation_rate: "明确推荐", target_brand_official_reference_rate: "官方来源引用", published_url_reference_rate: "目标 URL 引用" };
const ratio = (m: any) => m?.value == null ? "不可计算" : `${m.hit_count}/${m.evaluable_count} (${(m.value * 100).toFixed(1)}%)`;
const coverage = (m: any) => `${m.evaluable_count} / ${m.valid_raw_count} / ${m.planned_count}`;
const runStates: Record<string, string> = { success: "采样成功", partial_success: "部分成功", failed: "采样失败", blocked: "采样受阻", cancelled: "未执行" };
const unknownReasons: Record<string, string> = {
  BRAND_ALIAS_AMBIGUOUS: "只出现别名，尚不能确定是否指向目标品牌",
  ANSWER_SEMANTIC_NOT_EVALUATED: "回答语义尚未完成有效计算",
  ANSWER_SEMANTIC_UNCERTAIN: "回答中的主体或选择行为尚不确定",
  OFFICIAL_IDENTITY_NOT_PROVIDED: "尚未配置官方域名或页面",
  REFERENCE_OBSERVATION_INCOMPLETE: "引用采集不完整，不能判断未出现",
  PUBLISHED_URL_IDENTITY_UNAVAILABLE: "未指定要观察的目标页面",
};

function UnknownMembers({ metric }: { metric: any }) {
  if (!metric?.unevaluated?.length) return <span>无未评估样本</span>;
  return <>{metric.unevaluated.map((item: any) => <div key={`${item.run_id}:${item.reason}`}>
    Run {item.run_id}：{unknownReasons[item.reason] || (String(item.reason).startsWith("FAILED") ? "回答计算失败，未按零计入" : "尚未获得有效判断，未按零计入")}
  </div>)}</>;
}

function AnswerDetails({ measurement }: { measurement: any }) {
  return <Collapse items={(measurement?.runs || []).map((run: any) => ({
    key: run.run_id,
    label: `Run ${run.run_id} · ${runStates[run.status] || "未完成"} · ${(run.references || []).length} 条引用`,
    children: <>
      {(run.error?.message || run.error_message) && <Alert type="warning" message={run.error?.message || run.error_message} />}
      <Typography.Paragraph style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{run.answer_text || "没有可消费的回答正文，不计为品牌缺席。"}</Typography.Paragraph>
      {!run.reference_complete && <Typography.Paragraph type="warning">引用范围不完整，不能据此判断来源消失。</Typography.Paragraph>}
      {(run.references || []).map((source: any, i: number) => <Typography.Paragraph key={i} style={{ overflowWrap: "anywhere" }}>
        {i + 1}. {source.title || "未提供标题"}<br />
        {/^https?:\/\//i.test(source.url || "") ? <a href={source.url} target="_blank" rel="noopener noreferrer">{source.url}</a> : "未取得可访问 URL"}
      </Typography.Paragraph>)}
    </>,
  }))} />;
}

export function ObservationPanel({ project, promptId, mode }: { project: Project; promptId: number | null; mode: "monitor" | "compare" | "context" }) {
  const [scopes, setScopes] = useState<any[]>([]);
  const [contexts, setContexts] = useState<any[]>([]);
  const [history, setHistory] = useState<any[]>([]);
  const [left, setLeft] = useState<string>();
  const [right, setRight] = useState<string>();
  const [leftAnswer, setLeftAnswer] = useState<string>();
  const [rightAnswer, setRightAnswer] = useState<string>();
  const [target, setTarget] = useState("");
  const [result, setResult] = useState<any>();
  const [pool, setPool] = useState<any>();
  const [overview, setOverview] = useState<any>();
  const [intent, setIntent] = useState<string>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [openingPrompt, setOpeningPrompt] = useState<number>();
  const [reload, setReload] = useState(0);
  const [form] = Form.useForm();
  const generation = useRef(0);
  const base = `/api/v2/projects/${project.id}/prompts/${promptId}`;
  function restoreComparison(saved: any) {
    setResult(saved);
    if (!saved) return;
    setLeft(saved.input.baseline.context_id); setRight(saved.input.comparison.context_id);
    setLeftAnswer(saved.input.baseline.answer_result_version || undefined);
    setRightAnswer(saved.input.comparison.answer_result_version || undefined);
    setTarget(saved.input.target_url || "");
  }
  function clearComparisonSelection() {
    setResult(undefined);
    if (mode !== "compare") return;
    const params = new URLSearchParams(window.location.search);
    params.delete("observation_result");
    window.history.replaceState(null, "", params.toString() ? `?${params}` : window.location.pathname);
  }
  useEffect(() => {
    const epoch = ++generation.current;
    const controller = new AbortController();
    setResult(undefined); setPool(undefined); setOverview(undefined); setScopes([]); setHistory([]); setContexts([]);
    setLeft(undefined); setRight(undefined); setLeftAnswer(undefined); setRightAnswer(undefined);
    setBusy(true); setError(""); setOpeningPrompt(undefined);
    const queries = mode === "context"
      ? [request<any[]>(`/api/v2/projects/${project.id}/brand-contexts`, { signal: controller.signal })]
      : promptId ? [request<any[]>(`${base}/observation-scopes`, { signal: controller.signal }), request<any[]>(`${base}/observation-comparisons`, { signal: controller.signal }),
        ...(mode === "monitor" ? [request<any>(`${base}/monitor`, { signal: controller.signal }), request<any>(`/api/v2/projects/${project.id}/monitor`, { signal: controller.signal })] : [])]
        : mode === "monitor" ? [Promise.resolve([]), Promise.resolve([]), Promise.resolve(undefined), request<any>(`/api/v2/projects/${project.id}/monitor`, { signal: controller.signal })] : [];
    Promise.all(queries).then(([first, second, current, aggregate]) => {
      if (controller.signal.aborted) return;
      if (mode === "context") setContexts(first || []);
      else {
        setScopes(first || []); setHistory(second || []); setPool(current); setOverview(aggregate);
        const selected = new URLSearchParams(window.location.search).get("observation_result");
        if (selected && mode === "compare") {
          const saved = (second || []).find((r: any) => r.result_version === selected);
          if (saved) restoreComparison(saved);
          else {
            clearComparisonSelection();
            setError("指定的历史比较不存在或不属于当前问题，未替换为其他范围。");
          }
        }
      }
    }).catch(e => { if (!controller.signal.aborted) setError(e.message); }).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => { if (generation.current === epoch) generation.current++; controller.abort(); };
  }, [base, mode, reload, project.id, promptId]);
  const ref = (id: string | undefined, answer: string | undefined) => {
    const s = scopes.find(x => x.context_id === id);
    const a = s?.answer_results.find((x: any) => x.result_version === answer);
    return { context_id: s.context_id, raw_output_hash: s.raw_output_hash, ...(a ? { answer_result_version: a.result_version, answer_result_hash: a.output_hash } : {}) };
  };
  async function run() {
    const epoch = generation.current;
    setBusy(true); setError("");
    try {
      let domain = "";
      try { domain = new URL(project.website_url || "").hostname; } catch { /* Unconfigured official identity stays unknown. */ }
      const identity = { canonical_brand_name: project.brand_name, accepted_aliases: project.brand_aliases || [], official_domains: domain ? [domain] : [], official_urls: project.website_url ? [project.website_url] : [] };
      const payload = mode === "monitor" ? { scope: ref(left, leftAnswer), identity, target_url: target } : { baseline: ref(left, leftAnswer), comparison: ref(right, rightAnswer), identity, target_url: target };
      const next = await request<any>(`${base}/${mode === "monitor" ? "measurements" : "observation-comparisons"}`, { method: "POST", body: JSON.stringify(payload) });
      if (generation.current !== epoch) return;
      setResult(next);
      if (mode === "compare") {
        setHistory(current => [next, ...current.filter(x => x.result_version !== next.result_version)]);
        const params = new URLSearchParams(window.location.search); params.set("observation_result", next.result_version);
        window.history.replaceState(null, "", `?${params}`);
      }
    } catch (e) { if (generation.current === epoch) setError((e as Error).message); }
    finally { if (generation.current === epoch) setBusy(false); }
  }
  async function save(values: any) {
    const epoch = generation.current;
    setBusy(true); setError("");
    try {
      await request(`/api/v2/projects/${project.id}/brand-contexts`, { method: "POST", body: JSON.stringify({ ...values, expected_version: contexts[0]?.version_number || 0 }) });
      if (generation.current === epoch) { form.resetFields(); setReload(n => n + 1); }
    } catch (e) { if (generation.current === epoch) setError((e as Error).message); }
    finally { if (generation.current === epoch) setBusy(false); }
  }
  async function openAnalysis(row: any) {
    const epoch = generation.current;
    const selection = row.analysis_selection;
    const promptVersion = selection?.prompt_version;
    if (promptVersion?.binding_status !== "BOUND" || !promptVersion.prompt_version_id || !promptVersion.snapshot_hash) {
      setError(monitorAnalysisBindingReason(selection));
      return;
    }
    setOpeningPrompt(row.prompt.id); setError("");
    try {
      const next = await request<any>(`/api/v2/projects/${project.id}/prompts/${row.prompt.id}/monitor-analysis`, {
        method: "POST", body: JSON.stringify({ scope_hash: selection.scope_hash }),
      });
      if (epoch !== generation.current) return;
      const params = new URLSearchParams({ release_view: "coreV2", v2_project: String(project.id),
        v2_prompt: String(row.prompt.id), v2_analysis: next.analysis.analysis_id });
      window.location.assign(`/?${params}`);
    } catch (e) { if (epoch === generation.current) setError((e as Error).message); }
    finally { if (epoch === generation.current) setOpeningPrompt(undefined); }
  }
  const options = scopes.map(s => ({ value: s.context_id, label: `范围 ${s.context_id} · Runs ${(s.run_scope.run_ids || []).join("、")} · ${s.created_at}` }));
  const monitorAnalysisBindingReason = (selection: any) => {
    const status = selection?.prompt_version?.binding_status;
    if (status === "LEGACY_UNBOUND") return "这些历史回答未绑定 Prompt 冻结版本，不能用当前或 latest Prompt 替代建立分析。";
    if (status) return `这些回答的 Prompt 版本绑定为 ${status}，不是可证明的单一冻结版本，不能建立分析。`;
    return "后端未提供这些回答可证明的 Prompt 冻结版本，不能建立分析。";
  };
  const output = result?.output || result || (mode === "monitor" && pool?.runs?.length ? pool : undefined);
  const measuredIdentity = result?.input?.identity || output?.identity;
  const measuredTarget = result?.input?.target_url ?? output?.target_url;
  const comparisonInput = mode === "compare" ? result?.input : undefined;
  const rows = Object.entries(output?.metrics || {}).map(([key, value]) => ({ key, name: names[key] || key, data: value as any }));
  const choose = (label: string, value: string | undefined, change: (v: string) => void, answer: string | undefined, answerChange: (v: string | undefined) => void) => <Space direction="vertical" style={{ width: "100%" }}>
    <label>{label}</label><Select aria-label={label} style={{ width: "100%" }} placeholder="选择明确的样本范围" value={value} options={options} onChange={v => { change(v); answerChange(undefined); clearComparisonSelection(); }} />
    <Select aria-label={`${label}回答版本`} allowClear style={{ width: "100%" }} placeholder="可选：已保存的回答语义版本" value={answer} onChange={v => { answerChange(v); clearComparisonSelection(); }}
      options={(scopes.find(s => s.context_id === value)?.answer_results || []).map((r: any) => ({ value: r.result_version, label: r.result_version }))} />
  </Space>;
  return <section className="observation-panel">
    <Space style={{ marginBottom: 16 }}><Button aria-label="刷新当前页面" icon={<RefreshCw size={16} />} loading={busy} onClick={() => setReload(n => n + 1)} /></Space>
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
    {mode === "context" ? <>
      <SupplementalSources key={project.id} projectId={project.id} />
      <Typography.Title level={4}>内部补充上下文</Typography.Title>
      <Alert type="info" message="资料可选，不自动成为已核实品牌事实" />
      <Form form={form} layout="vertical" onFinish={save} style={{ marginTop: 16 }}>
        <Form.Item label="资料标题" name="title" rules={[{ required: true, whitespace: true }]}><Input maxLength={240} /></Form.Item>
        <Form.Item label="品牌资料正文" name="content" rules={[{ required: true, whitespace: true }]}><Input.TextArea rows={8} maxLength={100000} /></Form.Item>
        <Form.Item label="资料出处或维护说明" name="source_reference"><Input maxLength={1000} /></Form.Item>
        <Button htmlType="submit" type="primary" loading={busy} icon={<Save size={16} />}>保存新资料版本</Button>
      </Form>
      <Collapse style={{ marginTop: 24 }} items={contexts.map(c => ({ key: c.context_version_id, label: `版本 ${c.version_number} · ${c.title}`, children: <><Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{c.content}</Typography.Paragraph><Typography.Text type="secondary">{c.source_reference || "未填写出处"}</Typography.Text></> }))} />
    </> : !promptId && mode !== "monitor" ? <Empty description="请先选择一个问题" /> : <>
      {mode === "monitor" && overview && <section aria-label="项目监控概览" style={{ marginBottom: 24 }}>
        <Typography.Title level={4}>项目监控概览</Typography.Title>
        <Table size="small" rowKey="key" pagination={false} scroll={{ x: 680 }} dataSource={Object.entries(overview.metrics).map(([key, data]) => ({ key, data: data as any }))} columns={[
          { title: "指标", render: (_, row) => names[row.key] },
          { title: "按问题平均", render: (_, row) => row.data.prompt_macro_average == null ? "不可计算" : `${(row.data.prompt_macro_average * 100).toFixed(1)}%` },
          { title: "参与 / 全部问题", render: (_, row) => `${row.data.participating_prompt_count} / ${row.data.total_prompt_count}` },
          { title: "按样本加权", render: (_, row) => row.data.run_weighted_average == null ? "不可计算" : `${(row.data.run_weighted_average * 100).toFixed(1)}% (${row.data.hit_count}/${row.data.evaluable_count})` },
        ]} />
        <Select aria-label="按意图筛选问题" allowClear placeholder="全部意图" value={intent} onChange={setIntent} style={{ width: 220, margin: "16px 0" }} options={[
          { value: "category_awareness", label: "概念与知识" }, { value: "supplier_recommendation", label: "方案与工具选择" }, { value: "usage_instruction", label: "使用与操作" },
        ]} />
        <Table size="small" rowKey={r => r.prompt.id} scroll={{ x: 700 }} dataSource={overview.prompts.filter((r: any) => !intent || r.prompt.intent_type === intent)} columns={[
          { title: "问题 / 分组", render: (_, row: any) => <><Typography.Text>{row.prompt.text}</Typography.Text><br /><Typography.Text type="secondary">{row.prompt.group || "未分组"}</Typography.Text></> },
          { title: "正文提及", render: (_, row: any) => ratio(row.metrics.brand_mention_rate) },
          { title: "下一步", render: (_, row: any) => <><Typography.Text>{row.opportunity.label}</Typography.Text><br /><Typography.Text type="secondary">{row.opportunity.reason}</Typography.Text></> },
          { title: "采样范围", render: (_, row: any) => `${row.run_ids.length} 条当前问题回答 / ${row.pool_count} 条历史尝试` },
          { title: "操作", render: (_, row: any) => <>
            <Button loading={openingPrompt === row.prompt.id} disabled={openingPrompt !== undefined || !row.analysis_selection.selected_run_ids.length || row.analysis_selection.prompt_version?.binding_status !== "BOUND" || !row.analysis_selection.prompt_version?.prompt_version_id || !row.analysis_selection.prompt_version?.snapshot_hash}
              onClick={() => openAnalysis(row)}>分析这 {row.analysis_selection.selected_run_ids.length} 条回答</Button>
            {row.analysis_selection.prompt_version?.binding_status !== "BOUND" && <Typography.Paragraph type="warning">
              {monitorAnalysisBindingReason(row.analysis_selection)}
            </Typography.Paragraph>}
            {row.analysis_selection.excluded_run_ids.length > 0 && <Typography.Paragraph type="warning">
              Run {row.analysis_selection.excluded_run_ids.join("、")} 没有可分析正文，不进入该分析；监测统计仍保留这些尝试。
            </Typography.Paragraph>}
          </> },
        ]} />
      </section>}
      {!promptId && !busy && <Empty description={overview?.prompts.length ? "选择问题查看原文、采样计划和详细指标" : "尚无可用问题，请先在问题配置中创建"} />}
      {mode === "monitor" && promptId && <Collapse style={{ marginBottom: 24 }} items={[{ key: "schedule", label: "持续采样计划", children: <SamplingSchedulePanel key={`${project.id}:${promptId}`} projectId={project.id} promptId={promptId} /> }]} />}
      {promptId && !busy && !scopes.length && !pool?.runs?.length && <Empty description="尚无采样记录，请开启采样计划或进入分析与稿件开始首次采样" />}
      {mode === "monitor" && !result && pool?.pool_count > 0 && <Typography.Paragraph>累计采样尝试 {pool.pool_count} 条，当前问题原文 {pool.runs.length} 条；候选与推荐指标需选择已计算的准确回答版本。</Typography.Paragraph>}
      {mode === "monitor" && pool?.historical_query_runs?.length > 0 && <Collapse items={[{ key: "old-query", label: `历史问题版本的回答（${pool.historical_query_runs.length}），不混入当前问题指标`, children: <AnswerDetails measurement={{ runs: pool.historical_query_runs }} /> }]} />}
      {promptId && <Space direction="vertical" size={16} style={{ width: "100%" }}>
        {choose(mode === "monitor" ? "观察范围" : "基线范围", left, setLeft, leftAnswer, setLeftAnswer)}
        {mode === "compare" && choose("对照范围", right, setRight, rightAnswer, setRightAnswer)}
        <label>目标页面 URL（可选，不要求已发布）<Input value={target} onChange={e => { setTarget(e.target.value); clearComparisonSelection(); }} /></label>
        <Button type="primary" icon={<BarChart3 size={16} />} loading={busy} disabled={!left || (mode === "compare" && (!right || right === left))} onClick={run}>{mode === "monitor" ? "查看指标" : "生成变化比较"}</Button>
        {mode === "compare" && <Alert type="info" showIcon message="历史结果隔离" description="选择历史比较只恢复该结果保存时的基线、对照和回答版本；修改任一范围或目标页面会退出该历史结果，不会用新范围覆盖它。" />}
        {mode === "compare" && <Select aria-label="历史比较" style={{ width: "100%" }} placeholder="查看已保存的比较" value={result?.result_version} onChange={id => {
          restoreComparison(history.find(x => x.result_version === id)); const params = new URLSearchParams(window.location.search); params.set("observation_result", id); window.history.replaceState(null, "", `?${params}`);
        }} options={history.map(r => ({ value: r.result_version, label: `${r.created_at} · ${r.result_version}` }))} />}
      </Space>}
      {output && <>
        {measuredIdentity && <section aria-label="本结果测量身份" style={{ marginTop: 20, overflowWrap: "anywhere" }}>
          <Typography.Text strong>本结果测量身份：{measuredIdentity.canonical_brand_name}</Typography.Text>
          <Typography.Paragraph style={{ margin: "4px 0" }}>别名：{measuredIdentity.accepted_aliases?.join("、") || "未设置"}；官方域名：{measuredIdentity.official_domains?.join("、") || "未设置，官方引用不可计算"}</Typography.Paragraph>
          {measuredTarget && <Typography.Paragraph>目标页面：{measuredTarget}</Typography.Paragraph>}
          {mode === "compare" && <Typography.Paragraph type="secondary">当前展示的是保存时的测量身份；项目配置更新不会改写此结果。</Typography.Paragraph>}
        </section>}
        {comparisonInput && <section aria-label="固定范围身份" style={{ marginTop: 12, overflowWrap: "anywhere" }}>
          <Typography.Text strong>固定范围身份（保存比较）</Typography.Text>
          <Typography.Paragraph style={{ margin: "4px 0" }}>基线：{comparisonInput.baseline?.context_id || "未提供"} · 回答版本：{comparisonInput.baseline?.answer_result_version || "未绑定"} · 原始哈希：{comparisonInput.baseline?.raw_output_hash || "未提供"}</Typography.Paragraph>
          <Typography.Paragraph style={{ margin: "4px 0" }}>对照：{comparisonInput.comparison?.context_id || "未提供"} · 回答版本：{comparisonInput.comparison?.answer_result_version || "未绑定"} · 原始哈希：{comparisonInput.comparison?.raw_output_hash || "未提供"}</Typography.Paragraph>
        </section>}
        {mode === "monitor" && output.opportunity && <Alert style={{ marginTop: 16 }} type="info" message={output.opportunity.label} description={output.opportunity.reason} />}
        <Table style={{ marginTop: 24 }} rowKey="key" pagination={false} scroll={{ x: 650 }} dataSource={rows} columns={[
          { title: "指标", dataIndex: "name" },
          { title: mode === "monitor" ? "命中 / 可评估" : "基线", render: (_, r) => ratio(mode === "monitor" ? r.data : r.data.baseline) },
          ...(mode === "compare" ? [{ title: "对照", render: (_: any, r: any) => ratio(r.data.comparison) }, { title: "差值（百分点）", render: (_: any, r: any) => r.data.delta_percentage_points ?? "不可比/不可计算" }] : []),
          { title: mode === "monitor" ? "可评估 / 有效原始 / 计划" : "基线覆盖（可评估 / 有效 / 固定范围）", render: (_, r) => coverage(mode === "monitor" ? r.data : r.data.baseline) },
          ...(mode === "compare" ? [{ title: "对照覆盖（可评估 / 有效 / 固定范围）", render: (_: any, r: any) => coverage(r.data.comparison) }] : []),
        ]} />
        <Collapse style={{ marginTop: 12 }} items={[{ key: "unknown", label: "哪些样本未计入，为什么", children:
          <Table size="small" rowKey="key" pagination={false} dataSource={rows} scroll={{ x: 520 }} columns={[
            { title: "指标", dataIndex: "name" },
            { title: mode === "monitor" ? "未评估原因" : "基线未评估原因", render: (_, r) => <UnknownMembers metric={mode === "monitor" ? r.data : r.data.baseline} /> },
            ...(mode === "compare" ? [{ title: "对照未评估原因", render: (_: any, r: any) => <UnknownMembers metric={r.data.comparison} /> }] : []),
          ]} /> }]} />
        <Alert style={{ marginTop: 16 }} type="warning" message="仅报告观察变化，不证明优化效果或生成因果" description={output.conflicts?.length ? `条件不可比：${output.conflicts.map((code: string) => {
          const [field, state] = code.split(":");
          const label = ({ platform: "采样平台", source_type: "采样来源类型", adapter: "采集器", original_query: "问题原文", collection_mode: "采样模式" } as Record<string, string>)[field] || "采样条件";
          return `${label}${state === "CONFLICT" ? "不一致" : "未知或不完整"}`;
        }).join("、")}` : "未知条件及未计算语义不按零结果处理。"} />
        {mode === "monitor" && <>
          <Typography.Title level={5}>按日期观察（UTC）</Typography.Title>
          <Table size="small" rowKey="date" scroll={{ x: 650 }} pagination={false} dataSource={output.trend?.points || []} columns={[
            { title: "日期", dataIndex: "date" }, { title: "样本数", render: (_, row: any) => row.run_ids.length },
            { title: "提及", render: (_, row: any) => ratio(row.metrics.brand_mention_rate) },
            { title: "候选", render: (_, row: any) => ratio(row.metrics.brand_option_rate) },
            { title: "推荐", render: (_, row: any) => ratio(row.metrics.brand_recommendation_rate) },
          ]} />
          {!!output.trend?.unknown_date_run_ids?.length && <Typography.Paragraph type="warning">{output.trend.unknown_date_run_ids.length} 条记录缺少可靠时间，未排入日期趋势。</Typography.Paragraph>}
          {!!pool?.competitor_observations?.length && !result && <><Typography.Title level={5}>已配置竞品的正文提及</Typography.Title>
            <Table size="small" rowKey="competitor_id" pagination={false} dataSource={pool.competitor_observations} columns={[
              { title: "竞品", dataIndex: "name" }, { title: "命中 / 可评估", render: (_, row: any) => ratio(row.measurement) },
            ]} /></>}
        </>}
        {output.citation_changes && <Collapse style={{ marginTop: 16 }} items={[
          ["newly_observed", "本范围首次观察到"], ["continuing", "持续观察到"], ["not_observed_again", "对照范围未再观察到"],
        ].map(([key, label]) => ({ key, label: `${label}（${output.citation_changes[key].length}）`, children: output.citation_changes[key].length ? output.citation_changes[key].map((r: any) => <Typography.Paragraph key={r.url} style={{ overflowWrap: "anywhere" }}>{r.url}</Typography.Paragraph>) : "无可确定项目" }))} />}
        {output.citation_changes && (!output.citation_changes.baseline_complete || !output.citation_changes.comparison_complete) && <Alert style={{ marginTop: 12 }} type="warning" showIcon message="引用采集范围不完整" description={`基线侧 ${output.citation_changes.unclassified_baseline.length} 个、对照侧 ${output.citation_changes.unclassified_comparison.length} 个来源差异尚不能判为新增或消失。`} />}
        <Typography.Title level={5}>回答与引用原文</Typography.Title>
        {mode === "compare" ? <div className="v2-output-columns"><div><Typography.Title level={5}>基线</Typography.Title><AnswerDetails measurement={output.baseline} /></div><div><Typography.Title level={5}>对照</Typography.Title><AnswerDetails measurement={output.comparison} /></div></div> : <AnswerDetails measurement={output} />}
        <Collapse style={{ marginTop: 16 }} items={[{ key: "details", label: "技术审计：指标条件、身份和未评估原因", children: <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(output, null, 2)}</pre> }]} />
      </>}
    </>}
  </section>;
}
