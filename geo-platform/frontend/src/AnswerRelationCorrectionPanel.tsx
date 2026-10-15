import { useEffect, useState } from "react";
import { Alert, Button, Checkbox, Collapse, Descriptions, Empty, Form, Input, Modal, Select, Space, Spin, Tag, Typography } from "antd";
import { Pencil, Search } from "lucide-react";
import { api, request } from "./api/client";
import type { AnswerRelationCorrectionImpact, AnswerRelationCorrectionStatus } from "./types";

const valueLabels: Record<string, string> = {
  RECOMMEND: "推荐", INCLUDE_AS_OPTION: "纳入候选", PRAISE: "正面评价", COMPARE: "比较",
  MENTION: "仅提及", DISCOURAGE: "不建议", REJECT: "排除",
  SOURCE_SUPPORTS_REASON: "来源支持理由", SOURCE_CONTRADICTS_REASON: "来源反驳理由",
  RELATED: "仅相关", NONE: "无关系",
};

function IdentityList({ title, values }: { title: string; values: string[] }) {
  return <Descriptions.Item label={title}>{values.length ? values.map(value => <Tag key={value}>{value}</Tag>) : "无"}</Descriptions.Item>;
}

function ImpactView({ impact }: { impact: AnswerRelationCorrectionImpact }) {
  return <Descriptions size="small" column={1} bordered>
    <IdentityList title="受影响理由" values={impact.affected_reason_ids} />
    <IdentityList title="不受影响理由" values={impact.unaffected_reason_ids} />
    <IdentityList title="受影响策略方向" values={impact.affected_strategy_ids} />
    <IdentityList title="不受影响策略方向" values={impact.unaffected_strategy_ids} />
    <Descriptions.Item label="受影响稿件">{impact.affected_deliveries.length ? impact.affected_deliveries.map(row =>
      <Typography.Text key={row.result_version} code>{row.proposal_id} / {row.result_version}</Typography.Text>) : "无"}</Descriptions.Item>
    <Descriptions.Item label="不受影响稿件">{impact.unaffected_deliveries.length ? impact.unaffected_deliveries.map(row =>
      <Typography.Text key={row.result_version} code>{row.proposal_id} / {row.result_version}</Typography.Text>) : "无"}</Descriptions.Item>
    <Descriptions.Item label="明确保持不变">{impact.unchanged_objects.join("、")}</Descriptions.Item>
  </Descriptions>;
}

type ReprojectionTask = {
  task_id: string;
  status: string;
  revision?: number;
  expected_revision?: number | string;
  new_strategy_result_version?: string;
  strategy_result_version?: string;
  new_strategy_result_hash?: string;
  strategy_result_hash?: string;
  affected_delivery_set_hash?: string;
  result_version?: string;
  objects?: {
    answer_relation_reprojection?: {
      new_strategy_result_version?: string;
      strategy_result_version?: string;
      new_strategy_result_hash?: string;
      strategy_result_hash?: string;
      affected_delivery_set_hash?: string;
      pending_delivery_updates?: unknown[];
      unchanged_deliveries?: unknown[];
    };
  };
};

type DeliveryRegenerationManifest = Partial<Record<"affected" | "regenerated" | "pending" | "failed" | "unchanged", unknown[]>>;

type DeliveryRegenerationTask = {
  task_id: string;
  status: string;
  manifest?: DeliveryRegenerationManifest;
  delivery_manifest?: DeliveryRegenerationManifest;
};

type SavedCorrection = { result_version: string; result_hash: string } & Record<string, string>;

function reprojectionResult(reprojection: ReprojectionTask) {
  const manifest = reprojection.objects?.answer_relation_reprojection;
  const expectedRevision = reprojection.revision ?? reprojection.expected_revision;
  const strategyResultVersion = manifest?.new_strategy_result_version || manifest?.strategy_result_version ||
    reprojection.new_strategy_result_version || reprojection.strategy_result_version;
  const strategyResultHash = manifest?.new_strategy_result_hash || manifest?.strategy_result_hash ||
    reprojection.new_strategy_result_hash || reprojection.strategy_result_hash;
  const affectedDeliverySetHash = manifest?.affected_delivery_set_hash || reprojection.affected_delivery_set_hash;
  if (!reprojection.status.startsWith("COMPLETED") || expectedRevision === undefined ||
      !strategyResultVersion || !strategyResultHash || !affectedDeliverySetHash) return undefined;
  return {
    expected_revision: expectedRevision,
    strategy_result_version: strategyResultVersion,
    strategy_result_hash: strategyResultHash,
    affected_delivery_set_hash: affectedDeliverySetHash,
  };
}

function ManifestList({ title, values }: { title: string; values?: unknown[] }) {
  if (!values) return null;
  return <Descriptions.Item label={title}>{values.length ? values.map((value, index) =>
    <Typography.Text key={index} code>{typeof value === "string" ? value : JSON.stringify(value)}</Typography.Text>) : "无"}</Descriptions.Item>;
}

function DeliveryRegenerationManifestView({ task }: { task: DeliveryRegenerationTask }) {
  const manifest = task.manifest || task.delivery_manifest;
  if (!manifest) return null;
  return <Descriptions size="small" column={1} bordered>
    <ManifestList title="affected" values={manifest.affected} />
    <ManifestList title="regenerated" values={manifest.regenerated} />
    <ManifestList title="pending" values={manifest.pending} />
    <ManifestList title="failed" values={manifest.failed} />
    <ManifestList title="unchanged" values={manifest.unchanged} />
  </Descriptions>;
}

export function AnswerRelationCorrectionPanel({ taskId, projectId, promptId }: {
  taskId: string; projectId: number; promptId: number;
}) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<AnswerRelationCorrectionStatus>();
  const [selectedKey, setSelectedKey] = useState<string>();
  const [preview, setPreview] = useState<Record<string, any>>();
  const [previewInput, setPreviewInput] = useState<Record<string, any>>();
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<SavedCorrection>();
  const [reprojection, setReprojection] = useState<ReprojectionTask>();
  const [deliveryRegeneration, setDeliveryRegeneration] = useState<DeliveryRegenerationTask>();
  const [form] = Form.useForm();
  const selected = data?.targets.find(row => `${row.target_type}:${row.target_id}` === selectedKey);
  const reprojectionCompleted = reprojection?.status.startsWith("COMPLETED");

  async function load() {
    setBusy(true); setError("");
    try { setData(await api.getAnswerRelationCorrections(taskId, projectId, promptId)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  useEffect(() => { if (open) void load(); }, [open, taskId, projectId, promptId]);

  function choose(key: string) {
    const target = data?.targets.find(row => `${row.target_type}:${row.target_id}` === key);
    setSelectedKey(key); setPreview(undefined); setPreviewInput(undefined); setConfirmed(false); setSaved(undefined); setReprojection(undefined); setDeliveryRegeneration(undefined);
    form.setFieldsValue({ value: undefined, reason: "" });
    if (!target?.can_correct) setError(target?.blocked_reason || "该对象不能纠正"); else setError("");
  }

  async function inspect(values: { value: string; reason: string }) {
    if (!data || !selected?.can_correct) return;
    const input = {
      project_id: projectId, prompt_id: promptId, base_result_version: data.base_result_version,
      base_result_hash: data.base_result_hash, reviewable_set_hash: data.reviewable_set_hash,
      target_type: selected.target_type, target_id: selected.target_id, target_hash: selected.target_hash,
      value: values.value, reason: values.reason,
    };
    setBusy(true); setError(""); setPreview(undefined); setConfirmed(false);
    try { setPreview(await api.previewAnswerRelationCorrection(taskId, input)); setPreviewInput(input); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function save() {
    if (!preview || !previewInput || !confirmed) return;
    setBusy(true); setError("");
    try {
      const result = await api.saveAnswerRelationCorrection(taskId, {
        ...previewInput, preview_hash: preview.preview_hash, human_confirmed: true,
      });
      setSaved(result as SavedCorrection); setReprojection(undefined); setDeliveryRegeneration(undefined); setPreview(undefined); setPreviewInput(undefined); setConfirmed(false); setSelectedKey(undefined);
      form.resetFields(); await load();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function reproject(correction: { result_version: string; result_hash: string }) {
    setBusy(true); setError(""); setReprojection(undefined); setDeliveryRegeneration(undefined);
    try {
      const result = await request<ReprojectionTask>(
        `/api/v2/single-prompt/optimization-tasks/${encodeURIComponent(taskId)}/answer-relation-reprojections`,
        {
          method: "POST",
          body: JSON.stringify({
            project_id: projectId,
            prompt_id: promptId,
            correction_result_version: correction.result_version,
            correction_result_hash: correction.result_hash,
            idempotency_key: `answer-relation-reprojection:${taskId}:${correction.result_version}`,
          }),
        },
      );
      setReprojection(result);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function regenerateAffectedDeliveries(task: ReprojectionTask) {
    const result = reprojectionResult(task);
    if (!result) return;
    setBusy(true); setError(""); setDeliveryRegeneration(undefined);
    try {
      const regeneration = await request<DeliveryRegenerationTask>(
        `/api/v2/single-prompt/optimization-tasks/${encodeURIComponent(task.task_id)}/affected-draft-regenerations`,
        {
          method: "POST",
          body: JSON.stringify({
            project_id: projectId,
            prompt_id: promptId,
            expected_revision: result.expected_revision,
            strategy_result_version: result.strategy_result_version,
            strategy_result_hash: result.strategy_result_hash,
            affected_delivery_set_hash: result.affected_delivery_set_hash,
            idempotency_key: `affected-draft-regeneration:${taskId}:${result.strategy_result_version}:${result.affected_delivery_set_hash}`,
          }),
        },
      );
      setDeliveryRegeneration(regeneration);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function refreshReprojection() {
    if (!reprojection) return;
    setBusy(true); setError("");
    try {
      setReprojection(await request<ReprojectionTask>(
        `/api/v2/single-prompt/optimization-tasks/${encodeURIComponent(reprojection.task_id)}?project_id=${projectId}&prompt_id=${promptId}`,
      ));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function refreshDeliveryRegeneration() {
    if (!deliveryRegeneration) return;
    setBusy(true); setError("");
    try {
      setDeliveryRegeneration(await request<DeliveryRegenerationTask>(
        `/api/v2/single-prompt/optimization-tasks/${encodeURIComponent(deliveryRegeneration.task_id)}?project_id=${projectId}&prompt_id=${promptId}`,
      ));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return <>
    <Button icon={<Pencil size={16} />} onClick={() => setOpen(true)}>纠正答案或证据关系</Button>
    <Modal open={open} title="答案与证据关系纠错" footer={null} width={760} onCancel={() => setOpen(false)} destroyOnHidden>
      {error && <Alert type="error" showIcon message="纠错操作未完成" description={error} />}
      {busy && !data ? <Spin><div style={{ minHeight: 120 }} /></Spin> : data && <Space direction="vertical" style={{ width: "100%" }}>
        <Alert type="info" showIcon message={`固定诊断 ${data.frozen_result_version}；当前纠错基线 ${data.base_result_version}`}
          description="只新增诊断纠错版本；不会修改原回答、引用贡献、既有策略或稿件，也不会创建重算任务。" />
        {data.targets.length ? <Select aria-label="选择答案或证据关系" value={selectedKey} onChange={choose}
          placeholder="选择待纠正对象" style={{ width: "100%" }} options={data.targets.map(row => ({
            value: `${row.target_type}:${row.target_id}`, disabled: !row.can_correct,
            label: `${row.target_type === "RECOMMENDATION_EVENT" ? "答案行为" : "证据关系"} · ${row.label} · ${valueLabels[row.current_value || ""] || row.alignment_evaluation || "未判断"}${row.can_correct ? "" : "（不可纠正）"}`,
          }))} /> : <Empty description="本任务没有可纠正的答案行为或证据关系" />}
        {selected?.can_correct && <Form form={form} layout="vertical" onFinish={inspect} disabled={busy}
          onValuesChange={() => { setPreview(undefined); setConfirmed(false); }}>
          <Descriptions size="small" column={1}>
            <Descriptions.Item label="机器判断">{valueLabels[selected.machine_value || ""] || selected.machine_value}</Descriptions.Item>
            <Descriptions.Item label="当前判断">{valueLabels[selected.current_value || ""] || selected.current_value}</Descriptions.Item>
            <Descriptions.Item label="绑定理由">{selected.reason_ids.join("、") || "无"}</Descriptions.Item>
          </Descriptions>
          <Form.Item name="value" label="纠正后判断" rules={[{ required: true }]}><Select options={selected.allowed_values
            .filter(value => value !== selected.current_value).map(value => ({ value, label: valueLabels[value] || value }))} /></Form.Item>
          <Form.Item name="reason" label="纠错依据" rules={[{ required: true, whitespace: true }]}><Input.TextArea rows={3} maxLength={2000} /></Form.Item>
          <Button htmlType="submit" icon={<Search size={16} />} loading={busy}>预览影响范围</Button>
        </Form>}
        {preview && <>
          <ImpactView impact={preview.impact} />
          <Checkbox checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)}>
            我已核对对象、依据和影响清单，确认保存独立纠错版本
          </Checkbox>
          <Button type="primary" disabled={!confirmed} loading={busy} onClick={() => void save()}>保存纠错版本</Button>
        </>}
        {saved && <Alert type="success" showIcon message={`纠错版本 ${saved.result_version} 已保存`}
          description={`操作者：${saved.actor}；保存时间：${saved.created_at}。既有策略与稿件尚未按本次纠错重算或升级。`}
          action={saved.result_hash && <Button type="primary" loading={busy} onClick={() => void reproject(saved)}>更新受影响策略</Button>} />}
        {reprojection && <Alert type={reprojectionCompleted ? "success" : "info"} showIcon
          message={reprojectionCompleted ? "策略已重新投影，稿件尚未重新生成" : reprojection.status === "QUEUED" ? "策略重投影任务已创建，稿件尚未重新生成" : "策略重投影任务处理中，稿件尚未重新生成"}
          description={<Space direction="vertical" size={0}>
            {reprojectionCompleted
              ? <span>任务：{reprojection.task_id}；新策略版本：{reprojection.new_strategy_result_version || reprojection.strategy_result_version || reprojection.result_version || "未返回"}；状态：{reprojection.status}</span>
              : <span>任务：{reprojection.task_id}；状态：{reprojection.status}</span>}
            {reprojectionCompleted && <span>受影响稿件待更新；未受影响稿件保持不变。</span>}
          </Space>}
          action={<Space><Button loading={busy} onClick={() => void refreshReprojection()}>刷新重投影状态</Button>
            {reprojectionResult(reprojection) && <Button type="primary" loading={busy} onClick={() => void regenerateAffectedDeliveries(reprojection)}>重新生成受影响稿件</Button>}</Space>} />}
        {deliveryRegeneration && <Alert type={deliveryRegeneration.status.startsWith("COMPLETED") ? "success" : deliveryRegeneration.status === "WAITING_AUTHORIZATION" ? "warning" : "info"} showIcon
          message={deliveryRegeneration.status === "QUEUED" ? "局部稿件再生成任务已创建" :
            deliveryRegeneration.status === "RUNNING" ? "正在重新生成受影响稿件" :
            deliveryRegeneration.status === "WAITING_AUTHORIZATION" ? "缺少已授权生成能力" :
            deliveryRegeneration.status.startsWith("COMPLETED") ? "受影响稿件已生成新版本；未受影响稿件保持不变" : "局部稿件再生成任务处理中"}
          description={<Space direction="vertical" size={8} style={{ width: "100%" }}>
            <span>任务：{deliveryRegeneration.task_id}；状态：{deliveryRegeneration.status}</span>
            <span>历史稿件保持不变；未受影响稿件保持不变。</span>
            <DeliveryRegenerationManifestView task={deliveryRegeneration} />
          </Space>}
          action={<Button loading={busy} onClick={() => void refreshDeliveryRegeneration()}>刷新局部再生成状态</Button>} />}
        {!!data.history.length && <Collapse items={data.history.slice().reverse().map(row => ({
          key: row.result_version, label: `${row.result_version} · ${row.actor} · ${row.created_at}`,
          children: <Space direction="vertical" style={{ width: "100%" }}>
            <Typography.Paragraph>{valueLabels[row.summary.before] || row.summary.before} → {valueLabels[row.summary.after] || row.summary.after}</Typography.Paragraph>
            <Typography.Paragraph>依据：{row.summary.reason}</Typography.Paragraph>
            <ImpactView impact={row.impact} />
            <Alert type="warning" showIcon message="本纠错版本尚未重算或升级既有策略与稿件" />
            <Button type="primary" loading={busy} onClick={() => void reproject(row)}>更新受影响策略</Button>
          </Space>,
        }))} />}
      </Space>}
    </Modal>
  </>;
}
