import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, App as AntApp, Button, Card, Collapse, Descriptions, Form, Input, InputNumber, Select, Space, Spin, Table, Tag, Typography } from "antd";
import { Copy, Download, MessageSquare, Play, RefreshCw, ShieldCheck, Square } from "lucide-react";
import { request } from "./api/client";
import { BrandContextSelect } from "./BrandContextSelect";
import { savedResultLabel, splitAgentResult } from "./agentResultPresentation";

type AgentResult = {
  result_version: string; version_number: number; evidence_grade: string;
  public_claim_eligibility: string; publication_eligibility: string;
  deliverable_markdown: string; result: any; validation: any; created_at: string;
};

type AgentRun = {
  run_id: string; project_id: number; prompt_id: number; analysis_id: string; context_id: string;
  input_scope_hash: string; agent_execution_hash: string; qualification_hash: string;
  execution_mode: "TOOL_LOOP" | "EVIDENCE_PACK";
  status: string; revision: number; blocker?: { code: string; detail: string } | null;
  usage: { model_calls: number; tool_calls: number; input_tokens: number; output_tokens: number; cost_cny: number;
    reserved_requests: number; reserved_tokens: number; reserved_cost_cny: number };
  budget: { max_model_calls: number; max_tool_calls: number; max_total_tokens: number; max_cost_cny: number };
  authorization: { mode: string }; progress: Record<string, unknown>; allowed_operations: string[];
  result?: AgentResult | null; created_at: string; finished_at?: string | null;
  events?: Array<{ event_id: string; sequence_number: number; event_type: string; payload: any; payload_hash: string }>;
};

type Feedback = {
  feedback_id: string; result_version: string; submitted_by: string; rating: string;
  reason_tags: string[]; suggestion: string; adoption_status: string;
  modification_level: string; modification_summary: string; created_at: string;
};

type Completion = { manifest_id: string; payload_hash: string; version_number: number };
type Capabilities = { new_generation_enabled: boolean; authorization_scope: string; message: string };

const statusLabel: Record<string, string> = {
  QUEUED: "待运行", RUNNING: "生成中", WAITING_AUTHORIZATION: "等待管理员授权",
  SUCCEEDED: "已完成", PARTIAL: "部分完成", NEEDS_INPUT: "需要补充资料",
  BLOCKED: "已阻塞", FAILED: "失败", CANCELLED: "已取消",
};
const ratingLabel: Record<string, string> = { USABLE: "可用", NEEDS_CHANGES: "需修改", UNUSABLE: "不可用" };
const reasonLabel: Record<string, string> = {
  BRAND_ASSOCIATION: "品牌关联不足", FACTUAL_ACCURACY: "事实准确性", STRATEGY_TOO_GENERIC: "策略过于泛化",
  DRAFT_QUALITY: "正文质量", EVIDENCE_LIMITATION: "证据不足", OPERABILITY: "操作体验", OTHER: "其他",
};
const adoptionLabel: Record<string, string> = {
  ADOPTED: "已采用", PARTIALLY_ADOPTED: "部分采用", NOT_ADOPTED: "未采用", UNKNOWN: "尚未决定",
};
const modificationLabel: Record<string, string> = {
  NONE: "无需修改", LIGHT: "少量修改", MEDIUM: "中等修改", HEAVY: "大量修改", NOT_RECORDED: "未记录",
};

function humanTime(value?: string | null) {
  if (!value) return "时间未知";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

export function AgentExperimentPanel({ projectId, promptId, analysisId, contextId, completion }: {
  projectId: number; promptId: number; analysisId: string; contextId: string; completion?: Completion | null;
}) {
  const { message, modal } = AntApp.useApp();
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [detail, setDetail] = useState<AgentRun>();
  const [results, setResults] = useState<AgentResult[]>([]);
  const [selectedResultVersion, setSelectedResultVersion] = useState<string>();
  const [feedback, setFeedback] = useState<Feedback[]>([]);
  const [comparison, setComparison] = useState<any>();
  const [capabilities, setCapabilities] = useState<Capabilities>();
  const [contextVersion, setContextVersion] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [feedbackForm] = Form.useForm();
  const generation = useRef(0);
  const active = detail || runs.find(row => row.run_id === selectedId);
  const result = results.find(row => row.result_version === selectedResultVersion) || results[0] || active?.result || undefined;
  const reportMarkdown = result?.result?.raw_markdown || result?.deliverable_markdown || "";
  const sections = splitAgentResult(reportMarkdown);
  const query = `project_id=${projectId}&prompt_id=${promptId}`;
  const base = "/api/v2/single-prompt";

  const refresh = useCallback(async () => {
    const epoch = generation.current;
    try {
      const [rows, nextCapabilities] = await Promise.all([
        request<AgentRun[]>(`${base}/analyses/${encodeURIComponent(analysisId)}/agent-experiments?${query}`),
        request<Capabilities>(`${base}/agent-experiments/capabilities?project_id=${projectId}`),
      ]);
      if (generation.current !== epoch) return;
      setRuns(rows); setCapabilities(nextCapabilities); setError("");
      const id = selectedId && rows.some(row => row.run_id === selectedId) ? selectedId : rows[0]?.run_id;
      setSelectedId(id);
      if (!id) { setDetail(undefined); setResults([]); setFeedback([]); setComparison(undefined); return; }
      const [next, compared, versions, notes] = await Promise.all([
        request<AgentRun>(`${base}/agent-experiments/${encodeURIComponent(id)}?${query}`),
        request<any>(`${base}/agent-experiments/${encodeURIComponent(id)}/comparison?${query}`),
        request<AgentResult[]>(`${base}/agent-experiments/${encodeURIComponent(id)}/results?${query}`),
        request<Feedback[]>(`${base}/agent-experiments/${encodeURIComponent(id)}/feedback?${query}`),
      ]);
      if (generation.current !== epoch) return;
      setDetail(next); setComparison(compared); setResults(versions); setFeedback(notes);
      setSelectedResultVersion(current => versions.some(row => row.result_version === current)
        ? current : versions[0]?.result_version);
    } catch (e) { if (generation.current === epoch) setError((e as Error).message); }
    finally { if (generation.current === epoch) setLoading(false); }
  }, [analysisId, projectId, query, selectedId]);

  useEffect(() => {
    generation.current += 1; setRuns([]); setDetail(undefined); setResults([]); setFeedback([]);
    setSelectedId(undefined); setSelectedResultVersion(undefined); setLoading(true); setError("");
  }, [projectId, promptId, analysisId, contextId]);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => { generation.current += 1; window.clearInterval(timer); };
  }, [refresh]);

  async function start() {
    setBusy(true); setError("");
    try {
      const nonce = crypto.randomUUID();
      const saved = await request<AgentRun>(`${base}/analyses/${encodeURIComponent(analysisId)}/agent-experiments`, {
        method: "POST", body: JSON.stringify({
          project_id: projectId, prompt_id: promptId, context_id: contextId,
          idempotency_key: `beta:${nonce}`, regenerate_nonce: nonce,
          brand_context_version_id: contextVersion || null, execution_mode: "EVIDENCE_PACK",
          completion_manifest_id: completion?.manifest_id || null,
          completion_manifest_hash: completion?.payload_hash || null,
        }),
      });
      setSelectedId(saved.run_id); setDetail(saved); setSelectedResultVersion(undefined);
      message.success("新的冻结优化任务已创建；它不会复用历史结果冒充新生成。等待管理员按独立日常额度授权。" );
      await refresh();
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
    const requests = 1;
    let tokens = Math.min(300000, active?.budget.max_total_tokens || 1);
    let price = 0; let pricingSource = ""; let pricingDate = "";
    modal.confirm({ title: "管理员授权当前冻结任务", okText: "确认授权", cancelText: "取消", width: 620,
      content: <Space direction="vertical" style={{ width: "100%" }}>
        <Alert type="warning" showIcon message="本授权只覆盖当前任务"
          description="不包含新采样、抓取、发布或正式库写入；历史实验余额不会转为日常额度。" />
        <Typography.Text>请求次数上限（Evidence Pack 固定为 1）</Typography.Text>
        <InputNumber value={requests} disabled />
        <Typography.Text>总 Token 上限</Typography.Text>
        <InputNumber min={2048} max={active?.budget.max_total_tokens || 2048} precision={0} defaultValue={tokens}
          onChange={value => { tokens = Number(value || 0); }} />
        <Typography.Text>人民币硬上限</Typography.Text>
        <InputNumber min={0.01} max={active?.budget.max_cost_cny || 0.01} precision={2} defaultValue={amount}
          onChange={value => { amount = Number(value || 0); }} />
        <Typography.Text>保守单价（人民币 / 百万 Token）</Typography.Text>
        <InputNumber min={0.01} max={10000} onChange={value => { price = Number(value || 0); }} />
        <Input aria-label="AI 优化计费依据" placeholder="可核对的计费依据" maxLength={2000} onChange={event => { pricingSource = event.target.value; }} />
        <Input aria-label="AI 优化计费核实日期" type="date" onChange={event => { pricingDate = event.target.value; }} />
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

  async function submitFeedback(values: any) {
    if (!active || !result) return;
    setBusy(true); setError("");
    try {
      await request(`${base}/agent-experiments/${encodeURIComponent(active.run_id)}/feedback`, {
        method: "POST", body: JSON.stringify({
          project_id: projectId, prompt_id: promptId, result_version: result.result_version, ...values,
        }),
      });
      feedbackForm.resetFields(); message.success("反馈已追加保存，原结果与此前反馈均未被覆盖"); await refresh();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  function copy(text: string) {
    void navigator.clipboard.writeText(text).then(() => message.success("正文已复制"))
      .catch(() => message.error("复制失败，请检查浏览器权限"));
  }
  function download(text: string, version: string) {
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
    const anchor = document.createElement("a"); anchor.href = url;
    anchor.download = `GEO优化稿-${version.replace(/[^a-zA-Z0-9._-]+/g, "_")}.md`; anchor.click(); URL.revokeObjectURL(url);
  }

  return <section aria-label="AI 优化">
    <Alert type="info" showIcon message="内部 Beta · AI 优化"
      description="系统把当前项目、问题、明确 Run 范围、引用、来源快照和品牌资料冻结后生成诊断、策略与稿件。结果独立保存，不会覆盖正式 Workflow、Product Truth 或审核状态。" />
    <Card size="small" style={{ marginTop: 12 }} title="为当前问题准备新的优化任务"
      extra={<Button aria-label="刷新 AI 优化" icon={<RefreshCw size={16} />} onClick={() => void refresh()} />}>
      <Space direction="vertical" style={{ width: "100%" }}>
        <Typography.Text>选择要随本次任务冻结的品牌资料版本</Typography.Text>
        <BrandContextSelect projectId={projectId} value={contextVersion} onChange={setContextVersion} />
        <Alert type={capabilities?.new_generation_enabled ? "success" : "warning"} showIcon
          message={capabilities?.new_generation_enabled ? "日常模型调用已启用" : "当前仅开放历史结果使用"}
          description={capabilities?.message || "正在检查运行授权"} />
        <Typography.Text type="secondary">当前范围：Analysis {analysisId.slice(-10)} · Context {contextId.slice(-10)} · {completion ? `来源资料 V${completion.version_number}` : "未选择来源完成版本"}</Typography.Text>
        <Button type="primary" icon={<Play size={16} />} loading={busy}
          disabled={!capabilities?.new_generation_enabled} onClick={() => void start()}>创建并运行 AI 优化</Button>
      </Space>
    </Card>
    {error && <Alert style={{ marginTop: 12 }} type="error" showIcon message="AI 优化操作未完成" description={error} />}
    {loading ? <Spin tip="正在读取优化历史"><div style={{ minHeight: 100 }} /></Spin> : runs.length === 0
      ? <Alert style={{ marginTop: 16 }} type="info" message="当前冻结分析还没有优化历史"
          description={capabilities?.new_generation_enabled ? "选择品牌资料后即可创建第一条任务。" : "配置独立的日常模型额度后才可创建新生成；历史实验额度不会自动沿用。"} />
      : <>
        <Typography.Title level={4} style={{ marginTop: 20 }}>优化历史</Typography.Title>
        <Table size="small" pagination={{ pageSize: 8 }} rowKey="run_id" dataSource={runs}
          rowSelection={{ type: "radio", selectedRowKeys: selectedId ? [selectedId] : [],
            onChange: keys => { setSelectedId(String(keys[0])); setDetail(undefined); setSelectedResultVersion(undefined); } }}
          columns={[
            { title: "创建时间", dataIndex: "created_at", render: humanTime },
            { title: "状态", dataIndex: "status", render: (value, row) => <Space><Tag>{statusLabel[value] || value}</Tag><Typography.Text type="secondary">{savedResultLabel(row.usage.model_calls, value)}</Typography.Text></Space> },
            { title: "结果", render: (_, row) => row.status === "SUCCEEDED" ? "可查看" : row.blocker?.detail || "尚未生成" },
            { title: "用量", render: (_, row) => `${row.usage.model_calls} 次 · ¥${row.usage.cost_cny.toFixed(4)}` },
          ]} />
        {active && <Card style={{ marginTop: 16 }} title={<Space wrap><span>优化结果</span><Tag>{statusLabel[active.status] || active.status}</Tag><Tag color={active.usage.model_calls ? "blue" : undefined}>{savedResultLabel(active.usage.model_calls, active.status)}</Tag></Space>}>
          {active.blocker && <Alert type={active.status === "WAITING_AUTHORIZATION" ? "warning" : "error"} showIcon
            message={statusLabel[active.status] || active.blocker.code} description={active.blocker.detail} />}
          <Space wrap style={{ marginTop: 12 }}>
            {active.status === "WAITING_AUTHORIZATION" && capabilities?.new_generation_enabled && <Button icon={<ShieldCheck size={16} />} onClick={authorize}>管理员设置本任务额度</Button>}
            {active.status === "WAITING_AUTHORIZATION" && !capabilities?.new_generation_enabled && <Tag color="orange">需要部署级日常额度授权</Tag>}
            {['QUEUED', 'RUNNING', 'WAITING_AUTHORIZATION'].includes(active.status) && <Button danger icon={<Square size={16} />} onClick={() => void post("cancel")}>停止任务</Button>}
          </Space>
          {results.length > 0 && <Select aria-label="结果历史版本" style={{ width: "100%", marginTop: 16 }} value={result?.result_version}
            onChange={setSelectedResultVersion} options={results.map(item => ({ value: item.result_version,
              label: `结果 V${item.version_number} · ${humanTime(item.created_at)} · ${item.evidence_grade}` }))} />}
          {result && <>
            <Alert style={{ marginTop: 12 }} type={result.validation?.status === "PASS" ? "success" : "warning"} showIcon
              message={`服务端校验 ${result.validation?.status || "未知"} · ${result.evidence_grade}`}
              description={`公开主张：${result.public_claim_eligibility}；发布资格：${result.publication_eligibility}。VERIFY_FIRST 表示必须先由员工核实，不是允许直接发布。`} />
            <Space wrap style={{ marginTop: 12 }}>
              <Button icon={<Copy size={16} />} onClick={() => copy(sections["完整正文"] || result.deliverable_markdown)}>复制完整正文</Button>
              <Button icon={<Download size={16} />} onClick={() => download(reportMarkdown, result.result_version)}>导出完整报告</Button>
            </Space>
            <Descriptions size="small" column={{ xs: 1, md: 3 }} style={{ marginTop: 16 }}>
              <Descriptions.Item label="当前样本">{result.result?.evidence_pack?.coverage?.run_count ?? "按冻结范围"} 个 Run</Descriptions.Item>
              <Descriptions.Item label="引用观察">{result.result?.evidence_pack?.coverage?.citation_occurrence_count ?? 0}</Descriptions.Item>
              <Descriptions.Item label="来源快照">{result.result?.evidence_pack?.coverage?.source_snapshot_count ?? 0}</Descriptions.Item>
            </Descriptions>
            {(["GEO 诊断与依据", "品牌表现与证据缺口", "优化策略与渠道", "完整正文", "QA 与事实限制", "复测计划"] as const).map(title =>
              <Card size="small" key={title} title={title} style={{ marginTop: 12 }}>
                <Typography.Paragraph style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", marginBottom: 0 }}>{sections[title] || "本结果未提供该部分。"}</Typography.Paragraph>
              </Card>)}
            <Card size="small" title={<Space><MessageSquare size={16} />提交使用反馈</Space>} style={{ marginTop: 16 }}>
              <Form form={feedbackForm} layout="vertical" initialValues={{ adoption_status: "UNKNOWN", modification_level: "NOT_RECORDED" }} onFinish={submitFeedback}>
                <Form.Item name="rating" label="这份结果是否可用" rules={[{ required: true }]}><Select options={Object.entries(ratingLabel).map(([value, label]) => ({ value, label }))} /></Form.Item>
                <Form.Item name="reason_tags" label="主要原因"><Select mode="multiple" options={Object.entries(reasonLabel).map(([value, label]) => ({ value, label }))} /></Form.Item>
                <Form.Item name="adoption_status" label="是否实际采用"><Select options={Object.entries(adoptionLabel).map(([value, label]) => ({ value, label }))} /></Form.Item>
                <Form.Item name="modification_level" label="人工修改量"><Select options={Object.entries(modificationLabel).map(([value, label]) => ({ value, label }))} /></Form.Item>
                <Form.Item name="suggestion" label="建议或问题"><Input.TextArea rows={3} maxLength={4000} /></Form.Item>
                <Form.Item name="modification_summary" label="主要修改内容（可选）"><Input.TextArea rows={2} maxLength={4000} /></Form.Item>
                <Button type="primary" htmlType="submit" loading={busy}>保存反馈</Button>
              </Form>
              {feedback.filter(item => item.result_version === result.result_version).length > 0 && <Collapse style={{ marginTop: 12 }} items={[{
                key: "feedback-history", label: `该版本历史反馈（${feedback.filter(item => item.result_version === result.result_version).length}）`,
                children: feedback.filter(item => item.result_version === result.result_version).map(item => <Card size="small" key={item.feedback_id} style={{ marginBottom: 8 }}>
                  <Space wrap><Tag>{ratingLabel[item.rating] || item.rating}</Tag><Tag>{adoptionLabel[item.adoption_status] || item.adoption_status}</Tag><Tag>{modificationLabel[item.modification_level] || item.modification_level}</Tag><Typography.Text type="secondary">{item.submitted_by} · {humanTime(item.created_at)}</Typography.Text></Space>
                  <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0 }}>{item.reason_tags.map(value => reasonLabel[value] || value).join("、") || "未选择原因"}{item.suggestion ? `：${item.suggestion}` : ""}</Typography.Paragraph>
                </Card>),
              }]} />}
            </Card>
            <Collapse style={{ marginTop: 12 }} items={[
              { key: "evidence", label: "证据详情与资料限制", children: <>
                <Typography.Paragraph>已反查证据 {result.result?.evidence_references?.length || 0} 条；省略材料 {result.result?.evidence_pack?.coverage?.source_passage_omitted ?? 0} 条。</Typography.Paragraph>
                <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify({ limitations: result.result?.limitations || [], evidence_references: result.result?.evidence_references || [] }, null, 2)}</pre>
              </> },
              { key: "workflow", label: `正式流程对照（严格同输入 ${comparison?.same_input_workflow_count || 0} 条）`, children: <>
                <Alert type="info" message={comparison?.limitations?.[0] || "仅比较同一冻结输入，不把差异解释为因果效果。"} />
                <Table size="small" pagination={false} rowKey="task_id" dataSource={comparison?.workflow || []}
                  columns={[{ title: "正式任务", dataIndex: "task_id" }, { title: "状态", dataIndex: "status" },
                    { title: "同冻结输入", dataIndex: "same_frozen_input", render: value => value ? <Tag color="green">是</Tag> : <Tag>否</Tag> }]} />
              </> },
              { key: "audit", label: "技术审计信息", children: <>
                <Descriptions size="small" column={{ xs: 1, md: 2 }}>
                  <Descriptions.Item label="模型调用">{active.usage.model_calls} / {active.budget.max_model_calls}</Descriptions.Item>
                  <Descriptions.Item label="Token">{active.usage.input_tokens + active.usage.output_tokens} / {active.budget.max_total_tokens}</Descriptions.Item>
                  <Descriptions.Item label="费用">¥{active.usage.cost_cny.toFixed(4)} / ¥{active.budget.max_cost_cny.toFixed(2)}</Descriptions.Item>
                  <Descriptions.Item label="结果版本"><Typography.Text code>{result.result_version}</Typography.Text></Descriptions.Item>
                  <Descriptions.Item label="输入身份"><Typography.Text code>{active.input_scope_hash.slice(0, 16)}</Typography.Text></Descriptions.Item>
                  <Descriptions.Item label="执行身份"><Typography.Text code>{active.agent_execution_hash.slice(0, 16)}</Typography.Text></Descriptions.Item>
                </Descriptions>
                <Collapse style={{ marginTop: 8 }} items={[{ key: "trace", label: `运行记录（${active.events?.length || 0}）`, children:
                  <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(active.events || [], null, 2)}</pre> }]} />
              </> },
            ]} />
          </>}
        </Card>}
      </>}
  </section>;
}
