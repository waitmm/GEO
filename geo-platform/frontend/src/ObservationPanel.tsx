import { useEffect, useRef, useState } from "react";
import { Alert, Button, Collapse, Empty, Form, Input, Select, Space, Table, Typography } from "antd";
import { BarChart3, RefreshCw, Save } from "lucide-react";
import { request } from "./api/client";
import type { Project } from "./types";
import { SamplingSchedulePanel } from "./SamplingSchedulePanel";

const names: Record<string, string> = { brand_mention_rate: "正文提及", brand_option_rate: "列为选项", brand_recommendation_rate: "明确推荐", target_brand_official_reference_rate: "官方来源引用", published_url_reference_rate: "目标 URL 引用" };
const ratio = (m: any) => m?.value == null ? "不可计算" : `${m.hit_count}/${m.evaluable_count} (${(m.value * 100).toFixed(1)}%)`;
const runStates: Record<string, string> = { success: "采样成功", partial_success: "部分成功", failed: "采样失败", blocked: "采样受阻", cancelled: "未执行" };

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
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [form] = Form.useForm();
  const generation = useRef(0);
  const base = `/api/v2/projects/${project.id}/prompts/${promptId}`;
  useEffect(() => {
    const epoch = ++generation.current;
    const controller = new AbortController();
    setResult(undefined); setPool(undefined); setScopes([]); setHistory([]); setContexts([]);
    setLeft(undefined); setRight(undefined); setLeftAnswer(undefined); setRightAnswer(undefined);
    setBusy(true); setError("");
    const queries = mode === "context"
      ? [request<any[]>(`/api/v2/projects/${project.id}/brand-contexts`, { signal: controller.signal })]
      : promptId ? [request<any[]>(`${base}/observation-scopes`, { signal: controller.signal }), request<any[]>(`${base}/observation-comparisons`, { signal: controller.signal }),
        ...(mode === "monitor" ? [request<any>(`${base}/monitor`, { signal: controller.signal })] : [])] : [];
    Promise.all(queries).then(([first, second, current]) => {
      if (controller.signal.aborted) return;
      if (mode === "context") setContexts(first || []);
      else {
        setScopes(first || []); setHistory(second || []); setPool(current);
        const selected = new URLSearchParams(window.location.search).get("observation_result");
        if (selected && mode === "compare") setResult((second || []).find((r: any) => r.result_version === selected));
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
  const options = scopes.map(s => ({ value: s.context_id, label: `Runs ${(s.run_scope.run_ids || []).join("、")} · ${s.created_at}` }));
  const output = result?.output || result || (mode === "monitor" && pool?.runs?.length ? pool : undefined);
  const rows = Object.entries(output?.metrics || {}).map(([key, value]) => ({ key, name: names[key] || key, data: value as any }));
  const choose = (label: string, value: string | undefined, change: (v: string) => void, answer: string | undefined, answerChange: (v: string | undefined) => void) => <Space direction="vertical" style={{ width: "100%" }}>
    <label>{label}</label><Select aria-label={label} style={{ width: "100%" }} placeholder="选择明确的样本范围" value={value} options={options} onChange={v => { change(v); answerChange(undefined); setResult(undefined); }} />
    <Select aria-label={`${label}回答版本`} allowClear style={{ width: "100%" }} placeholder="可选：已保存的回答语义版本" value={answer} onChange={answerChange}
      options={(scopes.find(s => s.context_id === value)?.answer_results || []).map((r: any) => ({ value: r.result_version, label: r.result_version }))} />
  </Space>;
  return <section className="observation-panel">
    <Space style={{ marginBottom: 16 }}><Button aria-label="刷新当前页面" icon={<RefreshCw size={16} />} loading={busy} onClick={() => setReload(n => n + 1)} /></Space>
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
    {mode === "context" ? <>
      <Alert type="info" message="资料可选，不自动成为已核实品牌事实" />
      <Form form={form} layout="vertical" onFinish={save} style={{ marginTop: 16 }}>
        <Form.Item label="资料标题" name="title" rules={[{ required: true, whitespace: true }]}><Input maxLength={240} /></Form.Item>
        <Form.Item label="品牌资料正文" name="content" rules={[{ required: true, whitespace: true }]}><Input.TextArea rows={8} maxLength={100000} /></Form.Item>
        <Form.Item label="资料出处或维护说明" name="source_reference"><Input maxLength={1000} /></Form.Item>
        <Button htmlType="submit" type="primary" loading={busy} icon={<Save size={16} />}>保存新资料版本</Button>
      </Form>
      <Collapse style={{ marginTop: 24 }} items={contexts.map(c => ({ key: c.context_version_id, label: `版本 ${c.version_number} · ${c.title}`, children: <><Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{c.content}</Typography.Paragraph><Typography.Text type="secondary">{c.source_reference || "未填写出处"}</Typography.Text></> }))} />
    </> : !promptId ? <Empty description="请先选择一个问题" /> : <>
      {mode === "monitor" && <Collapse style={{ marginBottom: 24 }} items={[{ key: "schedule", label: "持续采样计划", children: <SamplingSchedulePanel key={`${project.id}:${promptId}`} projectId={project.id} promptId={promptId} /> }]} />}
      {!busy && !scopes.length && !pool?.runs?.length && <Empty description="尚无采样记录，请开启采样计划或进入分析与稿件开始首次采样" />}
      {mode === "monitor" && !result && pool?.pool_count > 0 && <Typography.Paragraph>累计采样尝试 {pool.pool_count} 条，当前问题原文 {pool.runs.length} 条；候选与推荐指标需选择已计算的准确回答版本。</Typography.Paragraph>}
      {mode === "monitor" && pool?.historical_query_runs?.length > 0 && <Collapse items={[{ key: "old-query", label: `历史问题版本的回答（${pool.historical_query_runs.length}），不混入当前问题指标`, children: <AnswerDetails measurement={{ runs: pool.historical_query_runs }} /> }]} />}
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        {choose(mode === "monitor" ? "观察范围" : "基线范围", left, setLeft, leftAnswer, setLeftAnswer)}
        {mode === "compare" && choose("对照范围", right, setRight, rightAnswer, setRightAnswer)}
        <label>目标页面 URL（可选，不要求已发布）<Input value={target} onChange={e => setTarget(e.target.value)} /></label>
        <Button type="primary" icon={<BarChart3 size={16} />} loading={busy} disabled={!left || (mode === "compare" && (!right || right === left))} onClick={run}>{mode === "monitor" ? "查看指标" : "生成变化比较"}</Button>
        {mode === "compare" && <Select aria-label="历史比较" style={{ width: "100%" }} placeholder="查看已保存的比较" value={result?.result_version} onChange={id => {
          setResult(history.find(x => x.result_version === id)); const params = new URLSearchParams(window.location.search); params.set("observation_result", id); window.history.replaceState(null, "", `?${params}`);
        }} options={history.map(r => ({ value: r.result_version, label: `${r.created_at} · ${r.result_version}` }))} />}
      </Space>
      {output && <>
        <Table style={{ marginTop: 24 }} rowKey="key" pagination={false} scroll={{ x: 650 }} dataSource={rows} columns={[
          { title: "指标", dataIndex: "name" },
          { title: mode === "monitor" ? "命中 / 可评估" : "基线", render: (_, r) => ratio(mode === "monitor" ? r.data : r.data.baseline) },
          ...(mode === "compare" ? [{ title: "对照", render: (_: any, r: any) => ratio(r.data.comparison) }, { title: "差值（百分点）", render: (_: any, r: any) => r.data.delta_percentage_points ?? "不可比/不可计算" }] : []),
          { title: "可评估 / 有效原始 / 计划", render: (_, r) => { const m = mode === "monitor" ? r.data : r.data.baseline; return `${m.evaluable_count} / ${m.valid_raw_count} / ${m.planned_count}`; } },
        ]} />
        <Alert style={{ marginTop: 16 }} type="warning" message="仅报告观察变化，不证明优化效果或生成因果" description={output.conflicts?.length ? `条件冲突：${output.conflicts.join("、")}` : "未知条件及未计算语义不按零结果处理。"} />
        {output.citation_changes && <Collapse style={{ marginTop: 16 }} items={[
          ["newly_observed", "本范围首次观察到"], ["continuing", "持续观察到"], ["not_observed_again", "对照范围未再观察到"],
        ].map(([key, label]) => ({ key, label: `${label}（${output.citation_changes[key].length}）`, children: output.citation_changes[key].length ? output.citation_changes[key].map((r: any) => <Typography.Paragraph key={r.url} style={{ overflowWrap: "anywhere" }}>{r.url}</Typography.Paragraph>) : "无可确定项目" }))} />}
        <Typography.Title level={5}>回答与引用原文</Typography.Title>
        {mode === "compare" ? <div className="v2-output-columns"><div><Typography.Title level={5}>基线</Typography.Title><AnswerDetails measurement={output.baseline} /></div><div><Typography.Title level={5}>对照</Typography.Title><AnswerDetails measurement={output.comparison} /></div></div> : <AnswerDetails measurement={output} />}
        <Collapse style={{ marginTop: 16 }} items={[{ key: "details", label: "技术审计：指标条件、身份和未评估原因", children: <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(output, null, 2)}</pre> }]} />
      </>}
    </>}
  </section>;
}
