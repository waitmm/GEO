import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, App as AntApp, Button, Card, Checkbox, Collapse, Descriptions, Form, Input, Select, Space, Spin, Table, Tag, Typography } from "antd";
import { Copy, Download, MessageSquare, Play, RefreshCw, Square } from "lucide-react";
import { request } from "./api/client";
import { BrandContextSelect } from "./BrandContextSelect";
import { savedResultLabel, splitAgentResult } from "./agentResultPresentation";
import { formatBeijingDateTime } from "./time";
import { BusinessMarkdown } from "./BusinessMarkdown";
import { DraftArtifactPanel, type DraftArtifact } from "./DraftArtifactPanel";

type AgentResult = {
  result_version: string; version_number: number; evidence_grade: string;
  public_claim_eligibility: string; publication_eligibility: string;
  deliverable_markdown: string; result: any; validation: any; created_at: string;
  draft_delivery_status?: "SUCCESS" | "PARTIAL_SUCCESS" | "FAILED" | "LEGACY_SINGLE_DRAFT";
  draft_artifacts?: DraftArtifact[]; legacy_single_draft?: boolean;
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
type Capabilities = { new_generation_enabled: boolean; draft_regeneration_enabled?: boolean; authorization_scope: string; message: string };

const statusLabel: Record<string, string> = {
  QUEUED: "待运行", RUNNING: "生成中", WAITING_AUTHORIZATION: "等待服务启动",
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
const progressLabel: Record<string, string> = {
  QUEUED: "任务已排队，等待后台开始", BUILDING_EVIDENCE_PACK: "正在整理所选回答、引用与品牌资料",
  GENERATING_CONTENT: "正在生成诊断、策略与正文", VALIDATING_CONTENT: "正在校验证据、事实与正文完整性",
};

function humanTime(value?: string | null) {
  return formatBeijingDateTime(value);
}

function validationIssueText(validation?: any) {
  const issues = Array.isArray(validation?.issues) ? validation.issues : [];
  return issues.map((item: any) => {
    if (item?.code === "SECTION_EVIDENCE_REQUIRED") return `${item.detail}缺少可反查证据标记`;
    return item?.detail ? `${item.code || "校验问题"}：${item.detail}` : String(item?.code || "校验问题");
  }).join("；");
}

function blockerText(run: AgentRun) {
  if (run.status === "PARTIAL") {
    return "部分内容已经保存并可使用；另有内容未通过独立校验。请打开结果，按稿件查看状态和具体问题。";
  }
  if (run.blocker?.code?.startsWith("EVIDENCE_PACK_CORE_EXCEEDS_BUDGET")) {
    return "所选回答中的重复引用资料超过旧版输入容量；本次未调用模型、未产生费用。请使用已升级的输入整理重新创建任务。";
  }
  if (run.blocker?.code === "EVIDENCE_PACK_OUTPUT_VALIDATION_FAILED") {
    return "内容已经生成并保存，但没有通过证据校验；请打开该结果查看草稿和具体缺口。";
  }
  return run.blocker?.detail || "尚未生成";
}

export function AgentExperimentPanel({ projectId, promptId, analysisId, contextId, runCount, completion }: {
  projectId: number; promptId: number; analysisId: string; contextId: string; runCount: number; completion?: Completion | null;
}) {
  const { message } = AntApp.useApp();
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [detail, setDetail] = useState<AgentRun>();
  const [results, setResults] = useState<AgentResult[]>([]);
  const [selectedResultVersion, setSelectedResultVersion] = useState<string>();
  const [feedback, setFeedback] = useState<Feedback[]>([]);
  const [comparison, setComparison] = useState<any>();
  const [capabilities, setCapabilities] = useState<Capabilities>();
  const [contextVersion, setContextVersion] = useState<string>();
  const [requestedArtifactTypes, setRequestedArtifactTypes] = useState<string[]>(["HELP_DOC", "FAQ"]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [feedbackForm] = Form.useForm();
  const generation = useRef(0);
  const active = detail || runs.find(row => row.run_id === selectedId);
  const activeIsRunning = Boolean(active && ["QUEUED", "RUNNING"].includes(active.status));
  const result = results.find(row => row.result_version === selectedResultVersion) || results[0] || active?.result || undefined;
  const reportMarkdown = result?.result?.raw_markdown || result?.deliverable_markdown || "";
  const sections = splitAgentResult(reportMarkdown);
  const hasDraftArtifacts = Boolean(result?.draft_artifacts?.length);
  const displayedSectionTitles = hasDraftArtifacts
    ? (["GEO 诊断与依据", "品牌表现与证据缺口", "优化策略与渠道", "QA 与事实限制", "复测计划"] as const)
    : (["GEO 诊断与依据", "品牌表现与证据缺口", "优化策略与渠道", "完整正文", "QA 与事实限制", "复测计划"] as const);
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
          requested_artifact_types: requestedArtifactTypes,
          completion_manifest_id: completion?.manifest_id || null,
          completion_manifest_hash: completion?.payload_hash || null,
        }),
      });
      setSelectedId(saved.run_id); setDetail(saved); setSelectedResultVersion(undefined);
      message.success("AI 优化任务已创建并开始运行；历史结果不会被冒充为本次生成。" );
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

  function restartWithServerPolicy() {
    if (!active) return;
    void post("authorization", { revision: active.revision });
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
          message={capabilities?.new_generation_enabled ? "AI 生成已启用" : "当前仅开放历史结果使用"}
          description={capabilities?.message || "正在检查运行授权"} />
        <Typography.Text type="secondary">当前范围：已冻结 {runCount} 条回答 · {completion ? `来源资料 V${completion.version_number}` : "未选择来源资料版本"}</Typography.Text>
        <div>
          <Typography.Text strong>本次生成的内容资产</Typography.Text>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
            两份内容共享同一次诊断、策略和证据，但分别服务“操作说明”和“问题解答”，不会把同一篇文章换标题重复交付。
          </Typography.Paragraph>
          <Checkbox.Group value={requestedArtifactTypes} onChange={values => setRequestedArtifactTypes(values.map(String))}
            options={[{ label: "帮助文档", value: "HELP_DOC" }, { label: "常见问题 FAQ", value: "FAQ" }]} />
          {requestedArtifactTypes.length === 0 && <Typography.Text type="danger">请至少选择一种内容资产</Typography.Text>}
        </div>
        <Button type="primary" icon={<Play size={16} />} loading={busy || activeIsRunning}
          disabled={!capabilities?.new_generation_enabled || activeIsRunning || requestedArtifactTypes.length === 0} onClick={() => void start()}>
          {busy || activeIsRunning ? "AI 优化运行中…" : "创建并运行 AI 优化"}
        </Button>
        {activeIsRunning && <Alert type="info" showIcon message="AI 优化正在运行"
          description={`${progressLabel[String(active?.progress?.phase || active?.status || "")] || "后台正在处理"}。系统会自动刷新；完成或失败后会直接显示结果和原因，无需手动刷新页面。`} />}
      </Space>
    </Card>
    {error && <Alert style={{ marginTop: 12 }} type="error" showIcon message="AI 优化操作未完成" description={error} />}
    {loading ? <Spin tip="正在读取优化历史"><div style={{ minHeight: 100 }} /></Spin> : runs.length === 0
      ? <Alert style={{ marginTop: 16 }} type="info" message="当前冻结分析还没有优化历史"
          description={capabilities?.new_generation_enabled ? "选择品牌资料后即可创建第一条任务。" : "AI 生成尚未由服务端启用；历史结果仍可正常查看和使用。"} />
      : <>
        <Typography.Title level={4} style={{ marginTop: 20 }}>优化历史</Typography.Title>
        <Table className="agent-history-table" size="small" pagination={{ pageSize: 8 }} rowKey="run_id" dataSource={runs}
          rowSelection={{ type: "radio", selectedRowKeys: selectedId ? [selectedId] : [],
            onChange: keys => { setSelectedId(String(keys[0])); setDetail(undefined); setSelectedResultVersion(undefined); } }}
          columns={[
            { title: "创建时间", dataIndex: "created_at", render: humanTime },
            { title: "状态", dataIndex: "status", render: (value, row) => <Space><Tag>{statusLabel[value] || value}</Tag><Typography.Text type="secondary">{savedResultLabel(row.usage.model_calls, value)}</Typography.Text></Space> },
            { title: "结果", render: (_, row) => row.status === "SUCCEEDED" ? "可查看" : blockerText(row) },
          ]} />
        {active && <Card className="agent-result-card" style={{ marginTop: 16 }} title={<Space wrap><span>优化结果</span><Tag>{statusLabel[active.status] || active.status}</Tag><Tag color={active.usage.model_calls ? "blue" : undefined}>{savedResultLabel(active.usage.model_calls, active.status)}</Tag></Space>}>
          {active.blocker && <Alert type={active.status === "WAITING_AUTHORIZATION" ? "warning" : "error"} showIcon
            message={active.blocker.code === "EVIDENCE_PACK_OUTPUT_VALIDATION_FAILED" ? "内容已生成，但未通过证据校验" : statusLabel[active.status] || active.blocker.code}
            description={blockerText(active)} />}
          <Space wrap style={{ marginTop: 12 }}>
            {active.status === "WAITING_AUTHORIZATION" && capabilities?.new_generation_enabled && <Button onClick={restartWithServerPolicy}>重新尝试启动</Button>}
            {active.status === "WAITING_AUTHORIZATION" && !capabilities?.new_generation_enabled && <Tag color="orange">AI 生成服务暂未启用</Tag>}
            {['QUEUED', 'RUNNING', 'WAITING_AUTHORIZATION'].includes(active.status) && <Button danger icon={<Square size={16} />} onClick={() => void post("cancel")}>停止任务</Button>}
          </Space>
          {results.length > 0 && <Select className="agent-result-version-select" aria-label="结果历史版本" style={{ width: "100%", marginTop: 16 }} value={result?.result_version}
            onChange={setSelectedResultVersion} options={results.map(item => ({ value: item.result_version,
              label: `结果 V${item.version_number} · ${humanTime(item.created_at)} · ${item.evidence_grade}` }))} />}
          {result && <>
            <Alert style={{ marginTop: 12 }} type={result.validation?.status === "PASS" ? "success" : "warning"} showIcon
              message={result.validation?.status === "PASS" ? `服务端校验通过 · ${result.evidence_grade}` : `草稿已保存，服务端校验未通过 · ${result.evidence_grade}`}
              description={result.validation?.status === "PASS"
                ? `公开主张：${result.public_claim_eligibility}；发布资格：${result.publication_eligibility}。VERIFY_FIRST 表示必须先由员工核实，不是允许直接发布。`
                : `${validationIssueText(result.validation) || "存在未通过的内容校验项"}。这份草稿可查看和导出排查，但不是合格交付。`} />
            {(result.draft_artifacts || []).length > 0 && <DraftArtifactPanel
              artifacts={result.draft_artifacts || []} projectId={projectId} promptId={promptId}
              parentStatus={result.draft_delivery_status || "FAILED"}
              regenerationEnabled={Boolean(capabilities?.draft_regeneration_enabled)} onChanged={refresh} />}
            <Space wrap style={{ marginTop: 12 }}>
              {!hasDraftArtifacts && <Button icon={<Copy size={16} />} onClick={() => copy(sections["完整正文"] || result.deliverable_markdown)}>{result.validation?.status === "PASS" ? "复制完整正文" : "复制未通过草稿"}</Button>}
              <Button icon={<Download size={16} />} onClick={() => download(reportMarkdown, result.result_version)}>
                {hasDraftArtifacts ? "导出本次优化完整报告" : "导出完整报告"}
              </Button>
            </Space>
            <Descriptions size="small" column={{ xs: 1, md: 3 }} style={{ marginTop: 16 }}>
              <Descriptions.Item label="当前样本">{result.result?.evidence_pack?.coverage?.run_count ?? runCount} 条回答</Descriptions.Item>
              <Descriptions.Item label="引用观察">{result.result?.evidence_pack?.coverage?.citation_occurrence_count ?? 0}</Descriptions.Item>
              <Descriptions.Item label="来源快照">{result.result?.evidence_pack?.coverage?.source_snapshot_count ?? 0}</Descriptions.Item>
            </Descriptions>
            <Alert style={{ marginTop: 12 }} type="info" showIcon
              message={hasDraftArtifacts
                ? "建议阅读顺序：诊断依据 → 优化策略 → 各内容资产 → QA"
                : "建议阅读顺序：诊断依据 → 优化策略 → 完整正文 → QA"}
              description="蓝色“回答 #”标签表示结论可以回查到冻结回答；VERIFY_FIRST 表示相关品牌事实仍需员工核实后使用。" />
            {(result.result?.evidence_pack?.citation_channel_observations?.platforms || []).length > 0 &&
              <Card size="small" title="引用来源渠道观察（不是渠道效果结论）" style={{ marginTop: 12 }}>
                <Space wrap>{result.result.evidence_pack.citation_channel_observations.platforms.map((item: any) =>
                  <Tag key={item.platform_key}>{item.platform_label} · {item.citation_occurrence_count} 条 · {item.run_ids.length} 个 Run</Tag>)}</Space>
                <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
                  这里统计的是冻结回答实际出现的引用平台、来源域名和内容形态。引用次数高不等于该渠道最适合发布；竞品来源也不构成目标品牌能力证明。
                </Typography.Paragraph>
              </Card>}
            {displayedSectionTitles.map(title =>
              <Card size="small" key={title} title={title} style={{ marginTop: 12 }}>
                <BusinessMarkdown markdown={sections[title] || "本结果未提供该部分。"} />
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
                  <Descriptions.Item label="模型调用">{active.usage.model_calls} 次</Descriptions.Item>
                  <Descriptions.Item label="Token">{active.usage.input_tokens + active.usage.output_tokens}</Descriptions.Item>
                  <Descriptions.Item label="费用">¥{active.usage.cost_cny.toFixed(4)}</Descriptions.Item>
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
