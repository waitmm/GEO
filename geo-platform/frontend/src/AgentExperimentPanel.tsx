import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, App as AntApp, Button, Card, Collapse, Descriptions, InputNumber, Space, Spin, Table, Tag, Typography } from "antd";
import { Copy, Download, Play, RefreshCw, ShieldCheck, Square } from "lucide-react";
import { request } from "./api/client";
import { BrandContextSelect } from "./BrandContextSelect";

type AgentRun = {
  run_id: string; project_id: number; prompt_id: number; analysis_id: string; context_id: string;
  input_scope_hash: string; agent_execution_hash: string; qualification_hash: string;
  status: string; revision: number; blocker?: { code: string; detail: string } | null;
  usage: { model_calls: number; tool_calls: number; input_tokens: number; output_tokens: number; cost_cny: number;
    reserved_requests: number; reserved_tokens: number; reserved_cost_cny: number };
  budget: { max_model_calls: number; max_tool_calls: number; max_total_tokens: number; max_cost_cny: number };
  authorization: { mode: string }; progress: Record<string, unknown>; allowed_operations: string[];
  result?: { result_version: string; evidence_grade: string; public_claim_eligibility: string;
    publication_eligibility: string; deliverable_markdown: string; result: any; validation: any } | null;
  events?: Array<{ event_id: string; sequence_number: number; event_type: string; payload: any; payload_hash: string }>;
};

type Completion = { manifest_id: string; payload_hash: string; version_number: number };

const statusLabel: Record<string, string> = {
  QUEUED: "排队中", RUNNING: "运行中", WAITING_AUTHORIZATION: "等待模型授权",
  SUCCEEDED: "已完成", PARTIAL: "部分完成", NEEDS_INPUT: "需要新输入",
  BLOCKED: "已阻塞", FAILED: "失败", CANCELLED: "已取消",
};

export function AgentExperimentPanel({ projectId, promptId, analysisId, contextId, completion }: {
  projectId: number; promptId: number; analysisId: string; contextId: string; completion?: Completion | null;
}) {
  const { message, modal } = AntApp.useApp();
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [detail, setDetail] = useState<AgentRun>();
  const [comparison, setComparison] = useState<any>();
  const [contextVersion, setContextVersion] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const active = detail || runs.find(row => row.run_id === selectedId);
  const query = `project_id=${projectId}&prompt_id=${promptId}`;
  const base = "/api/v2/single-prompt";

  const refresh = useCallback(async () => {
    const epoch = generation.current;
    try {
      const rows = await request<AgentRun[]>(`${base}/analyses/${encodeURIComponent(analysisId)}/agent-experiments?${query}`);
      if (generation.current !== epoch) return;
      setRuns(rows); setError("");
      const id = selectedId && rows.some(row => row.run_id === selectedId) ? selectedId : rows[0]?.run_id;
      setSelectedId(id);
      if (id) {
        const [next, compared] = await Promise.all([
          request<AgentRun>(`${base}/agent-experiments/${encodeURIComponent(id)}?${query}`),
          request<any>(`${base}/agent-experiments/${encodeURIComponent(id)}/comparison?${query}`),
        ]);
        if (generation.current === epoch) { setDetail(next); setComparison(compared); }
      } else { setDetail(undefined); setComparison(undefined); }
    } catch (e) { if (generation.current === epoch) setError((e as Error).message); }
    finally { if (generation.current === epoch) setLoading(false); }
  }, [analysisId, projectId, promptId, query, selectedId]);

  useEffect(() => {
    generation.current += 1; setRuns([]); setDetail(undefined); setSelectedId(undefined); setLoading(true); setError("");
  }, [projectId, promptId, analysisId, contextId]);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { generation.current += 1; window.clearInterval(timer); };
  }, [refresh]);

  async function start() {
    setBusy(true); setError("");
    try {
      const saved = await request<AgentRun>(`${base}/analyses/${encodeURIComponent(analysisId)}/agent-experiments`, {
        method: "POST", body: JSON.stringify({
          project_id: projectId, prompt_id: promptId, context_id: contextId,
          idempotency_key: `agent:${crypto.randomUUID()}`, brand_context_version_id: contextVersion || null,
          completion_manifest_id: completion?.manifest_id || null,
          completion_manifest_hash: completion?.payload_hash || null,
        }),
      });
      setSelectedId(saved.run_id); setDetail(saved); await refresh();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function post(action: "cancel" | "authorization", extra: Record<string, unknown> = {}) {
    if (!active) return;
    setBusy(true); setError("");
    try {
      const saved = await request<AgentRun>(`${base}/agent-experiments/${encodeURIComponent(active.run_id)}/${action}`, {
        method: "POST", body: JSON.stringify({ project_id: projectId, prompt_id: promptId, ...extra }),
      });
      setDetail(saved); await refresh();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  function authorize() {
    let amount = Math.min(1, active?.budget.max_cost_cny || 1);
    let requests = Math.min(3, active?.budget.max_model_calls || 1);
    let tokens = Math.min(16000, active?.budget.max_total_tokens || 1);
    let price = 0;
    let pricingSource = "";
    let pricingDate = "";
    modal.confirm({ title: "授权当前 Agent Run 使用外部模型", okText: "确认授权", cancelText: "取消",
      content: <Space direction="vertical" style={{ width: "100%" }}>
        <Alert type="warning" showIcon message="仅授权当前冻结 Run；不会授权采样、抓取、发布或正式库写入。" />
        <Typography.Text>请求次数上限</Typography.Text>
        <InputNumber min={1} max={active?.budget.max_model_calls || 1} precision={0} defaultValue={requests}
          onChange={value => { requests = Number(value || 0); }} />
        <Typography.Text>总 Token 上限</Typography.Text>
        <InputNumber min={2048} max={active?.budget.max_total_tokens || 2048} precision={0} defaultValue={tokens}
          onChange={value => { tokens = Number(value || 0); }} />
        <Typography.Text>人民币硬上限（不得超过冻结预算 {active?.budget.max_cost_cny} 元）</Typography.Text>
        <InputNumber min={0.01} max={active?.budget.max_cost_cny || 0.01} precision={2} defaultValue={amount}
          onChange={value => { amount = Number(value || 0); }} />
        <Typography.Text>输入 / 输出每百万 Token 的保守单价（人民币）</Typography.Text>
        <InputNumber min={0.01} max={10000} onChange={value => { price = Number(value || 0); }} />
        <Typography.Text>已核实计费依据</Typography.Text>
        <input aria-label="Agent 计费依据" maxLength={2000} onChange={event => { pricingSource = event.target.value; }} />
        <Typography.Text>计费核实日期</Typography.Text>
        <input aria-label="Agent 计费核实日期" type="date" onChange={event => { pricingDate = event.target.value; }} />
      </Space>,
      onOk: () => {
        if (!price || pricingSource.trim().length < 8 || !/^\d{4}-\d{2}-\d{2}$/.test(pricingDate)) {
          message.error("请填写保守单价、可核对的计费依据和核实日期");
          return Promise.reject(new Error("pricing evidence required"));
        }
        return post("authorization", { revision: active!.revision, max_requests: requests,
          max_total_tokens: tokens, max_cost_cny: amount, conservative_cny_per_million_tokens: price,
          pricing_source: pricingSource.trim(), pricing_checked_at: pricingDate });
      },
    });
  }

  function copy(text: string) {
    void navigator.clipboard.writeText(text).then(() => message.success("Agent 稿件已复制"))
      .catch(() => message.error("复制失败，请检查浏览器权限"));
  }
  function download(text: string, version: string) {
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `${version}.md`; anchor.click();
    URL.revokeObjectURL(url);
  }

  return <section aria-label="GEO Agent 实验">
    <Alert type="info" showIcon message="独立实验线路"
      description="与正式 Workflow 共用同一冻结 Analysis / Run 输入，但只写 Agent 实验表；模型不能批准 Truth、Review、WAIVE 或发布。默认只读缓存，真实模型调用需单独授权。" />
    <Card size="small" style={{ marginTop: 12 }} title="启动新的 Agent 对照 Run"
      extra={<Button aria-label="刷新 Agent 实验" icon={<RefreshCw size={16} />} onClick={() => void refresh()} />}>
      <Space direction="vertical" style={{ width: "100%" }}>
        <BrandContextSelect projectId={projectId} value={contextVersion} onChange={setContextVersion} />
        <Typography.Text type="secondary">固定 Context：{contextId}；正文版本：{completion ? `V${completion.version_number}` : "未选择"}</Typography.Text>
        <Button type="primary" icon={<Play size={16} />} loading={busy} onClick={() => void start()}>启动 Agent 实验</Button>
      </Space>
    </Card>
    {error && <Alert style={{ marginTop: 12 }} type="error" showIcon message="Agent 实验操作未完成" description={error} />}
    {loading ? <Spin tip="正在读取 Agent 实验"><div style={{ minHeight: 100 }} /></Spin> : runs.length === 0
      ? <Typography.Paragraph type="secondary" style={{ marginTop: 16 }}>当前冻结分析还没有 Agent 实验 Run。</Typography.Paragraph>
      : <>
        <Table style={{ marginTop: 12 }} size="small" pagination={false} rowKey="run_id" dataSource={runs}
          rowSelection={{ type: "radio", selectedRowKeys: selectedId ? [selectedId] : [],
            onChange: keys => { setSelectedId(String(keys[0])); setDetail(undefined); } }}
          columns={[{ title: "Agent Run", dataIndex: "run_id", render: value => <Typography.Text code>{String(value).slice(-12)}</Typography.Text> },
            { title: "状态", dataIndex: "status", render: value => <Tag>{statusLabel[value] || value}</Tag> },
            { title: "模型 / 工具", render: (_, row) => `${row.usage.model_calls} / ${row.usage.tool_calls}` },
            { title: "费用", render: (_, row) => `¥${row.usage.cost_cny.toFixed(4)}` }]} />
        {active && <Card style={{ marginTop: 12 }} title={<Space><span>Agent 结果</span><Tag>{statusLabel[active.status] || active.status}</Tag></Space>}>
          {active.blocker && <Alert type={active.status === "WAITING_AUTHORIZATION" ? "warning" : "error"} showIcon
            message={active.blocker.code} description={active.blocker.detail} />}
          <Descriptions size="small" column={{ xs: 1, md: 2 }} style={{ marginTop: 12 }}>
            <Descriptions.Item label="模型调用">{active.usage.model_calls} / {active.budget.max_model_calls}</Descriptions.Item>
            <Descriptions.Item label="工具调用">{active.usage.tool_calls} / {active.budget.max_tool_calls}</Descriptions.Item>
            <Descriptions.Item label="Token">{active.usage.input_tokens + active.usage.output_tokens} / {active.budget.max_total_tokens}</Descriptions.Item>
            <Descriptions.Item label="实际记录费用">¥{active.usage.cost_cny.toFixed(4)} / ¥{active.budget.max_cost_cny.toFixed(2)}</Descriptions.Item>
            <Descriptions.Item label="外部请求预留">{active.usage.reserved_requests || 0} 次 / ¥{(active.usage.reserved_cost_cny || 0).toFixed(4)}</Descriptions.Item>
            <Descriptions.Item label="输入 hash"><Typography.Text code>{active.input_scope_hash.slice(0, 16)}</Typography.Text></Descriptions.Item>
            <Descriptions.Item label="执行 hash"><Typography.Text code>{active.agent_execution_hash.slice(0, 16)}</Typography.Text></Descriptions.Item>
          </Descriptions>
          <Space wrap>
            {active.status === "WAITING_AUTHORIZATION" && <Button icon={<ShieldCheck size={16} />} onClick={authorize}>授权当前 Run 模型调用</Button>}
            {["QUEUED", "RUNNING", "WAITING_AUTHORIZATION"].includes(active.status) && <Button danger icon={<Square size={16} />} onClick={() => void post("cancel")}>取消</Button>}
            {active.result?.deliverable_markdown && <Button icon={<Copy size={16} />} onClick={() => copy(active.result!.deliverable_markdown)}>复制完整稿件</Button>}
            {active.result?.deliverable_markdown && <Button icon={<Download size={16} />} onClick={() => download(active.result!.deliverable_markdown, active.result!.result_version)}>导出 Markdown</Button>}
          </Space>
          {active.result && <>
            <Alert style={{ marginTop: 12 }} type={active.result.validation?.status === "PASS" ? "success" : "warning"} showIcon
              message={`服务端校验 ${active.result.validation?.status || "未知"} · 证据等级 ${active.result.evidence_grade}`}
              description={`公开主张：${active.result.public_claim_eligibility}；发布资格：${active.result.publication_eligibility}`} />
            <Typography.Title level={5} style={{ marginTop: 16 }}>观察与诊断</Typography.Title>
            <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{active.result.result?.summary}</Typography.Paragraph>
            {active.result.deliverable_markdown && <Typography.Paragraph><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{active.result.deliverable_markdown}</pre></Typography.Paragraph>}
          </>}
          {comparison && <Collapse style={{ marginTop: 12 }} items={[{ key: "compare", label: `同输入 Workflow 对照（${comparison.same_input_workflow_count}）`, children: <>
            <Alert type="info" message={comparison.limitations?.[0]} />
            <Table size="small" pagination={false} rowKey="task_id" dataSource={comparison.workflow || []}
              columns={[{ title: "Workflow Task", dataIndex: "task_id" }, { title: "状态", dataIndex: "status" },
                { title: "同冻结输入", dataIndex: "same_frozen_input", render: value => value ? <Tag color="green">是</Tag> : <Tag>否</Tag> }]} />
          </> }]} />}
          <Collapse style={{ marginTop: 12 }} items={[{ key: "trace", label: `运行 Trace（${active.events?.length || 0}）`, children:
            <Space direction="vertical" style={{ width: "100%" }}>{(active.events || []).map(event => <Card size="small" key={event.event_id}
              title={`#${event.sequence_number} ${event.event_type}`}><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(event.payload, null, 2)}</pre></Card>)}</Space> }]} />
        </Card>}
      </>}
  </section>;
}
