import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, App as AntApp, Button, Checkbox, Collapse, Descriptions, Form, Input, InputNumber, Modal, Select, Space, Spin, Steps, Table, Tag, Tooltip, Typography } from "antd";
import { Copy, Download, Play, RefreshCw, ShieldCheck, Square } from "lucide-react";
import { request } from "./api/client";
import { BrandContextSelect } from "./BrandContextSelect";
import { SupplementalSources } from "./SupplementalSources";
import { ManuscriptEditor } from "./ManuscriptEditor";
import { TruthCorrectionPanel } from './TruthCorrectionPanel';
import { AnswerRelationCorrectionPanel } from './AnswerRelationCorrectionPanel';
import { DeliveryEvidence } from "./DeliveryEvidence";
import { ManuscriptPreview } from "./ManuscriptPreview";
import { downloadManuscript } from "./manuscriptExport";
import { readOptimizationSelection, resolveOptimizationSelection } from "./optimizationSelection";
import { optimizationStatus as statusLabel } from './optimizationStatus';
import type { OptimizationSelection } from "./optimizationSelection";

type Task = {
  task_kind: string; pending_draft?: { sections: { heading: string; blocks: { text: string }[] }[] };
  task_id: string; revision: number; status: string; stage: string; input_hash: string;
  brand_context_label: string; supplemental_source_count: number;
  scope: number[]; provider: string; requested_model: string; effective_request_model: string;
  blocker_detail: string; authorization: { policy: string; max_cost_cny: number };
  objects: Record<string, any>; limitations: any[];
  usage: { external_requests: number; cache_hits: number; reserved_tokens: number; reserved_cost_cny: number; actual_tokens: number; unsettled_requests: number };
};
const stages = [{ key: "SOURCES", title: "正文准备" }, { key: "ANSWER", title: "回答分析" }, { key: "CITATION", title: "引用分析" }, { key: "STRATEGY", title: "优化建议" }, { key: "TRUTH", title: "品牌资料核实" }, { key: "DRAFT", title: "具体稿件" }, { key: "TEXT_QA", title: "文本检查" }];
const assetNames: Record<string, string> = { HELP_DOC: "帮助文档", FEATURE_PAGE: "功能说明页", PRODUCT_PAGE: "产品页", ARTICLE: "文章", VIDEO: "视频稿" };
const answerRelationCorrectionReady = (task: Task) => task.task_kind === "AUTOMATIC_OPTIMIZE"
  && ["COMPLETED", "COMPLETED_WITH_LIMITATIONS"].includes(task.status)
  && Array.isArray(task.objects.deliveries) && task.objects.deliveries.length > 0;

export function AutomaticOptimizePanel({ projectId, promptId, analysisId, rawHash, completion }: { projectId: number; promptId: number; analysisId: string; rawHash: string; completion?: { manifest_id: string; payload_hash: string; version_number: number } | null }) {
  const { message } = AntApp.useApp();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selected, setSelected] = useState<OptimizationSelection>(() => readOptimizationSelection(window.location.search, analysisId));
  const selectedRef = useRef(selected);
  const [contextVersion, setContextVersion] = useState<string>();
  const [supplementalSourceIds, setSupplementalSourceIds] = useState<string[]>([]);
  const [fetchAllowed, setFetchAllowed] = useState(false);
  const [sourceVersion, setSourceVersion] = useState<string>();
  const [initial, setInitial] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [readError, setReadError] = useState("");
  const [authOpen, setAuthOpen] = useState(false);
  const [loadedDeliveries, setLoadedDeliveries] = useState<{ taskId: string; rows: any[] }>();
  const [copiedVersion, setCopiedVersion] = useState<string>();
  const [exportedVersion, setExportedVersion] = useState<string>();
  const [form] = Form.useForm();
  const alive = useRef(true);
  const sequence = useRef(0);
  const readInFlight = useRef(false);
  const task = resolveOptimizationSelection(tasks, selected);
  const deliveries = loadedDeliveries?.taskId === task?.task_id ? loadedDeliveries?.rows || [] : [];
  const query = `project_id=${projectId}&prompt_id=${promptId}`;
  const base = "/api/v2/single-prompt";
  const selectTask = useCallback((taskId: string) => {
    const choice: OptimizationSelection = { kind: "TASK", taskId };
    selectedRef.current = choice; setSelected(choice);
    const params = new URLSearchParams(window.location.search);
    if (params.get("v2_analysis") === analysisId) {
      params.set("optimization_task", taskId);
      window.history.replaceState(null, "", `${window.location.pathname}?${params}${window.location.hash}`);
    }
  }, [analysisId]);
  const refresh = useCallback(async () => {
    if (readInFlight.current) return;
    readInFlight.current = true;
    const seq = ++sequence.current;
    try {
      const rows = await request<Task[]>(`${base}/analyses/${encodeURIComponent(analysisId)}/optimization-tasks?project_id=${projectId}&prompt_id=${promptId}`);
      if (alive.current && seq === sequence.current) {
        setTasks(rows); setReadError("");
        if (!selectedRef.current && rows.length) selectTask(rows[0].task_id);
      }
    } catch (e) { if (alive.current && seq === sequence.current) setReadError((e as Error).message); }
    finally {
      readInFlight.current = false;
      if (alive.current && seq === sequence.current) setInitial(false);
    }
  }, [analysisId, projectId, promptId, selectTask]);
  useEffect(() => {
    alive.current = true; void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { alive.current = false; ++sequence.current; window.clearInterval(timer); };
  }, [refresh]);
  const resultKey = JSON.stringify(task?.objects.deliveries || []);
  useEffect(() => {
    setLoadedDeliveries(undefined);
    if (!task?.task_id || resultKey === "[]") return;
    const c = new AbortController();
    request<any[]>(`${base}/optimization-tasks/${encodeURIComponent(task.task_id)}/deliveries?${query}`, { signal: c.signal })
      .then(rows => { if (!c.signal.aborted) setLoadedDeliveries({ taskId: task.task_id, rows }); })
      .catch(e => { if (!c.signal.aborted) setError(e.message); });
    return () => c.abort();
  }, [task?.task_id, resultKey, query]);
  async function mutate(action: string, values?: any) {
    setBusy(true); setError("");
    try {
      const identity = { project_id: projectId, prompt_id: promptId };
      if (action === "create" && sourceVersion && sourceVersion !== completion?.manifest_id) throw new Error("正文版本已变化，请重新选择，不会自动替换输入");
      const value = action === "create" ? { ...identity, raw_output_hash: rawHash,
        idempotency_key: `optimize:${crypto.randomUUID()}`, brand_context_version_id: contextVersion || null,
        supplemental_source_ids: supplementalSourceIds,
        source_fetch_authorized: !sourceVersion && fetchAllowed,
        ...(sourceVersion && completion?.manifest_id === sourceVersion ? { completion_manifest_id: sourceVersion, completion_manifest_hash: completion.payload_hash } : {}) }
        : { ...identity, expected_revision: task!.revision, ...(action === "authorization" ? { ...values, input_hash: task!.input_hash } : {}) };
      const uri = action === "create" ? `${base}/analyses/${encodeURIComponent(analysisId)}/optimization-tasks`
        : `${base}/optimization-tasks/${encodeURIComponent(task!.task_id)}/${action}`;
      const saved = await request<Task>(uri, { method: "POST", body: JSON.stringify(value) });
      if (alive.current) { ++sequence.current; selectTask(saved.task_id); setTasks(old => [saved, ...old.filter(t => t.task_id !== saved.task_id)]); setAuthOpen(false); }
      await refresh();
    } catch (e) { if (alive.current) setError((e as Error).message); }
    finally { if (alive.current) setBusy(false); }
  }
  async function regenerate(delivery: any) {
    setBusy(true); setError("");
    try {
      const saved = await request<Task>(`${base}/optimization-tasks/${encodeURIComponent(task!.task_id)}/draft-regenerations`, {
        method: "POST", body: JSON.stringify({ project_id: projectId, prompt_id: promptId,
          proposal_id: delivery.proposal_id, result_version: delivery.result_version, result_hash: delivery.result_hash,
          idempotency_key: `regenerate:${crypto.randomUUID()}` }) });
      if (alive.current) { ++sequence.current; selectTask(saved.task_id); setTasks(old => [saved, ...old.filter(t => t.task_id !== saved.task_id)]); }
      await refresh();
    } catch (e) { if (alive.current) setError((e as Error).message); }
    finally { if (alive.current) setBusy(false); }
  }
  function href(delivery: any) {
    const o = task!.objects;
    const params = new URLSearchParams({ v2_project: String(projectId), v2_prompt: String(promptId), v2_analysis: analysisId, optimization_task: task!.task_id,
      v2_diagnosis: o.diagnosis_id, v2_diagnosis_result: o.answer_result_version, v2_strategy: o.strategy_id,
      v2_strategy_result: o.strategy_result_version, v2_execution_proposal: delivery.proposal_id, v2_execution_result: delivery.result_version });
    return `${window.location.pathname}?${params}#v2-execution`;
  }
  const active = task && ["QUEUED", "RUNNING"].includes(task.status);
  return <section className="automatic-optimize" aria-label="自动优化交付">
    <Space wrap style={{ justifyContent: "space-between", width: "100%" }}><Typography.Title level={4}>自动优化交付</Typography.Title>
      <Tooltip title="刷新任务"><Button aria-label="刷新自动优化任务" icon={<RefreshCw size={16} />} disabled={busy} onClick={() => void refresh()} /></Tooltip></Space>
    {(error || readError) && <Alert type="error" showIcon message="自动优化操作未完成" description={error || readError} />}
    {initial ? <Spin tip="正在读取任务"><div style={{ minHeight: 80 }} /></Spin> : <>
      <Space direction="vertical" style={{ width: "100%", maxWidth: 620 }}>
        <Typography.Text strong>新任务输入</Typography.Text>
        <BrandContextSelect projectId={projectId} value={contextVersion} onChange={setContextVersion} />
        <SupplementalSources key={`sources:${projectId}`} projectId={projectId} selection={supplementalSourceIds} onChange={setSupplementalSourceIds} disabled={!!active} />
        {completion && <Select aria-label="本次优化正文版本" value={sourceVersion || "prepare"} disabled={!!active} style={{ width: "100%" }}
          onChange={v => setSourceVersion(v === "prepare" ? undefined : v)} options={[
            { value: "prepare", label: "准备正文后固定本次版本" },
            { value: completion.manifest_id, label: `使用已保存正文版本 ${completion.version_number}` },
          ]} />}
        <Checkbox checked={!sourceVersion && fetchAllowed} disabled={!!active || !!sourceVersion} onChange={e => setFetchAllowed(e.target.checked)}>允许获取本次引用正文，每个 URL 最多两次</Checkbox>
        <Space wrap><Button type="primary" icon={<Play size={16} />} disabled={!!active || !rawHash} loading={busy} onClick={() => void mutate("create")}>开始自动优化</Button>
          {task && <Tag color={active ? "processing" : task.status.startsWith("COMPLETED") ? "success" : "default"}>{statusLabel(task)}</Tag>}
        </Space>
      </Space>
      {selected && !task && !readError && <Alert type="warning" showIcon message="当前链接未匹配本分析的自动任务" description="未替换为其他稿件。可重新选择任务；旧入口保存的稿件仍可在原方案详情中查看。" />}
      {tasks.length > 0 && <Select aria-label="优化任务版本" value={task?.task_id} onChange={selectTask} placeholder="选择当前分析的任务" style={{ width: "100%", marginTop: 12 }} options={tasks.map((t, i) => ({ value: t.task_id, label: `任务 ${tasks.length - i} · ${statusLabel(t)} · Run ${t.scope.join("、")}` }))} />}
      {task && <>
        {task.task_kind === "TEXT_REVISION" && <Alert type="info" message="正文修改复检：沿用原始分析与证据，只检查本次修改稿" />}
        {task.task_kind === "TEXT_REGENERATION" && <Alert type="info" message="正文重新生成：保留原稿，沿用冻结分析与证据，仅生成和检查新正文" />}
        {task.task_kind === 'TRUTH_REPROJECTION' && <Alert type="info" message="事实纠错局部更新：只更新受影响方向；回答与引用仅复用兼容缓存，其他稿件保留在原任务" />}
        {task.objects.truth_reprojection && <Button onClick={() => selectTask(task.objects.truth_reprojection.parent_task_id)}>查看原任务与历史稿件</Button>}
        <Steps size="small" responsive current={task.stage === "COMPLETE" ? stages.length : Math.max(0, stages.findIndex(s => s.key === task.stage))} items={stages.map(s => ({ title: s.title }))} style={{ margin: "20px 0" }} />
        {task.blocker_detail && <Alert type="warning" showIcon message={statusLabel(task)} description={task.blocker_detail} />}
        <Descriptions size="small" column={{ xs: 1, md: 3 }}>
          <Descriptions.Item label="固定样本">{task.scope.map(r => `Run #${r}`).join("、")}</Descriptions.Item>
          <Descriptions.Item label="本任务冻结资料">{task.brand_context_label}；额外公开资料 {task.supplemental_source_count} 份</Descriptions.Item>
          <Descriptions.Item label="模型请求 / 缓存">{task.usage.external_requests} / {task.usage.cache_hits}</Descriptions.Item>
          <Descriptions.Item label="预算预占上界">¥{task.usage.reserved_cost_cny.toFixed(4)} / ¥{task.authorization.max_cost_cny}</Descriptions.Item>
          <Descriptions.Item label="已记录 token">{task.usage.actual_tokens}</Descriptions.Item>
          <Descriptions.Item label="待核实用量">{task.usage.unsettled_requests}</Descriptions.Item>
          <Descriptions.Item label="模型">{task.provider} / {task.requested_model}</Descriptions.Item>
        </Descriptions>
        <Space wrap>
          {!['TEXT_REVISION', 'TEXT_REGENERATION'].includes(task.task_kind) && task.objects.strategy_id && <TruthCorrectionPanel
            key={`truth:${task.task_id}`} taskId={task.task_id} projectId={projectId} promptId={promptId}
            onQueued={saved => { if (!alive.current) return; ++sequence.current; selectTask(saved.task_id); setTasks(old => [saved, ...old.filter(t => t.task_id !== saved.task_id)]); void refresh(); }} />}
          {answerRelationCorrectionReady(task) && <AnswerRelationCorrectionPanel
            key={`answer-relation:${task.task_id}`} taskId={task.task_id} projectId={projectId} promptId={promptId} />}
          {task.authorization.policy === "CACHE_ONLY" && !active && !task.status.startsWith("COMPLETED") && task.status !== "CANCELLED" && <Button icon={<ShieldCheck size={16} />} onClick={() => setAuthOpen(true)}>授权本任务模型调用</Button>}
          {["INTERRUPTED", "BLOCKED"].includes(task.status) && <Button disabled={!!task.usage.unsettled_requests} loading={busy} icon={<Play size={16} />} onClick={() => void mutate("resume")}>恢复未完成步骤</Button>}
          {!task.status.startsWith("COMPLETED") && task.status !== "CANCELLED" && <Button danger icon={<Square size={16} />} loading={busy} onClick={() => void mutate("cancel")}>停止后续步骤</Button>}
        </Space>
        {!!task.limitations.length && <Collapse style={{ marginTop: 12 }} items={[{ key: "limits", label: `分析限制（${task.limitations.length}）`, children: <ul>{task.limitations.map((l, i) => <li key={i}>Run #{l.run_id}：{l.code === "CITATION_PARTIAL_EVALUATION" ? "部分引用未完成判断，不能当作不支持" : "当前引用资料未完成有效评估"}</li>)}</ul> }]} />}
        {task.pending_draft && <Collapse items={[{ key: "submitted", label: "本次提交的修改原文（不继承旧稿资格）", children: task.pending_draft.sections.map((s, i) => <section key={i}>
          <Typography.Title level={5}>{s.heading}</Typography.Title>{s.blocks.map((b, j) => <Typography.Paragraph key={j} style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{b.text}</Typography.Paragraph>)}
        </section>) }]} />}
      </>}
      {deliveries.map(delivery => <section key={delivery.result_version} style={{ marginTop: 24 }}>
        <Typography.Title level={4}>{delivery.output.publication_draft.title}</Typography.Title>
        <Typography.Paragraph>{delivery.output.direction.intervention_goal}</Typography.Paragraph>
        <Descriptions size="small" column={1}>
          <Descriptions.Item label="内容形式">{assetNames[delivery.output.asset_resolution.recommended_asset_type] || "按当前方案确定"}</Descriptions.Item>
          <Descriptions.Item label="选择理由">{delivery.output.asset_resolution.selection_reason}</Descriptions.Item>
          <Descriptions.Item label="建议承载位置">{delivery.output.channel_resolution.reason}</Descriptions.Item>
          <Descriptions.Item label="新建 / 更新判断">{delivery.output.asset_resolution.reason}</Descriptions.Item>
          <Descriptions.Item label="文本检查">{delivery.output.automatic_qa.status === "READY" ? "通过当前文本检查" : "需要修正"}</Descriptions.Item>
        </Descriptions>
        <Space wrap><Button icon={<Copy size={16} />} onClick={() => {
          setCopiedVersion(undefined);
          void navigator.clipboard.writeText(delivery.output.publication_draft.body_markdown)
            .then(() => setCopiedVersion(delivery.result_version)).catch(() => message.error("复制失败，请检查浏览器权限"));
        }}>复制完整正文</Button>
          {copiedVersion === delivery.result_version && <Typography.Text role="status">正文已复制</Typography.Text>}
          <Button icon={<Download size={16} />} onClick={() => {
            setExportedVersion(undefined);
            try {
              downloadManuscript(delivery.output.publication_draft.title, delivery.result_version,
                delivery.output.publication_draft.body_markdown);
              setExportedVersion(delivery.result_version);
            } catch { message.error("正文导出未完成，请检查当前稿件或浏览器下载权限"); }
          }}>导出 Markdown</Button>
          {exportedVersion === delivery.result_version && <Typography.Text role="status">正文下载已发起</Typography.Text>}
          <DeliveryEvidence key={`evidence:${delivery.result_version}`} frozen={delivery.output.delivery_input} resultVersion={delivery.result_version}
            officialFacts={delivery.output.generation_receipt?.official_facts} />
          <ManuscriptEditor key={delivery.result_version} delivery={delivery} taskId={task!.task_id} projectId={projectId} promptId={promptId}
            onQueued={saved => { if (!alive.current) return; ++sequence.current; selectTask(saved.task_id); setTasks(old => [saved, ...old.filter(t => t.task_id !== saved.task_id)]); void refresh(); }} />
          <Button icon={<RefreshCw size={16} />} loading={busy} disabled={!!active}
            onClick={() => void regenerate(delivery)}>重新生成正文</Button>
          <Button href={href(delivery)}>方案详情与可选发布记录</Button></Space>
        <ManuscriptPreview output={delivery.output} />
        <Collapse items={[{ key: "qa", label: `质量问题与实际修复（${delivery.output.automatic_qa.findings.length}）`, children: <>
          <Table size="small" pagination={false} rowKey="segment_id" scroll={{ x: 780 }} dataSource={delivery.output.automatic_qa.findings.map((finding: any) => ({ ...finding,
            repair: delivery.output.automatic_qa.repairs.find((r: any) => r.segment_id === finding.segment_id) }))} columns={[
            { title: "发现的问题", dataIndex: "rationale" }, { title: "原文", dataIndex: "original_text" },
            { title: "实际修改", render: (_, r: any) => r.repair ? r.repair.after || "已删除不成立陈述" : "没有修改记录" },
            { title: "复检", render: (_, r: any) => r.repair?.recheck === "PASS" ? "通过" : r.repair ? "未通过" : "未发生修复" },
          ]} locale={{ emptyText: "本次检查未发现问题，未进行修复" }} />
          {(delivery.output.automatic_qa.limitations || []).map((item: string) => <Typography.Paragraph key={item} type="secondary">{item}</Typography.Paragraph>)}
        </> }]} />
      </section>)}
    </>}
    <Modal title="本任务独立调用授权" open={authOpen} onCancel={() => setAuthOpen(false)} footer={null} destroyOnHidden>
      <Alert type="warning" showIcon message="失败请求计入预算；自动重试为 0。刷新、恢复和新结果不重置额度。" />
      {task?.task_kind === "TEXT_REGENERATION" ? <Typography.Paragraph>本次只允许正文生成和文本检查各最多一次；不重新计算回答、引用或品牌事实，不继承旧任务额度。</Typography.Paragraph>
        : task?.task_kind === 'TRUTH_REPROJECTION' ? <Typography.Paragraph>本次只允许受影响稿件的正文生成和文本检查；回答、引用和资料核实不允许新增模型请求，不重新抓取来源。</Typography.Paragraph>
        : task?.task_kind !== "TEXT_REVISION" && <Typography.Paragraph>范围包括本任务的回答、引用分析、合格官方资料的主张提取与核实、正文生成及文本检查；不包含其他项目或重新采样。</Typography.Paragraph>}
      <Form form={form} layout="vertical" onFinish={v => void mutate("authorization", v)} style={{ marginTop: 16 }}>
        <Form.Item label="请求次数上限" name="max_requests" rules={[{ required: true }]}><InputNumber min={1} max={task?.task_kind === "TEXT_REVISION" ? 1 : task?.task_kind === "TEXT_REGENERATION" ? 2 : 1000} precision={0} /></Form.Item>
        <Form.Item label="总 token 上限" name="max_tokens" rules={[{ required: true }]}><InputNumber min={1} max={10000000} precision={0} /></Form.Item>
        <Form.Item label="人民币硬预算" name="max_cost_cny" rules={[{ required: true }]}><InputNumber min={0.01} max={1000} precision={2} /></Form.Item>
        <Form.Item label="输入 / 输出每百万 token 的较高保守单价（人民币）" name="conservative_cny_per_million_tokens" rules={[{ required: true }]}><InputNumber min={0.01} max={1000} /></Form.Item>
        <Form.Item label="已核实计费依据" name="pricing_source" rules={[{ required: true, min: 8 }]}><Input maxLength={2000} /></Form.Item>
        <Form.Item label="计费核实日期" name="pricing_checked_at" rules={[{ required: true }]}><Input type="date" /></Form.Item>
        <Button type="primary" htmlType="submit" loading={busy} icon={<ShieldCheck size={16} />}>确认授权并继续</Button>
      </Form>
    </Modal>
  </section>;
}
