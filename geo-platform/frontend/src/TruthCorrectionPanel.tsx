import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Checkbox, Collapse, Descriptions, Empty, Form, Input, Modal, Select, Space, Spin, Typography } from 'antd';
import { Pencil, Play, Search } from 'lucide-react';
import { request } from './api/client';

const labels: Record<string, string> = { SUPPORTED: '已确认支持', PARTIALLY_SUPPORTED: '在限定条件下支持',
  NOT_SUPPORTED: '已确认不支持', UNKNOWN: '尚无法确认' };
type Fact = { truth_id: number; capability_label: string; product_truth_status: string; source_reference: string; note: string };
type Impact = { parent_task_id: string; affected_reason_ids: string[]; affected_direction_ids: string[]; unaffected_direction_ids: string[] };
type Correction = { correction_id: string; version_number: number; base: Fact; output: Fact; impact: Impact; actor: string; created_at: string };
type Facts = { current_set_hash: string; truths: { frozen: Fact; current: Fact | null; base_hash: string; can_correct: boolean }[]; history: Correction[] };
type Preview = { preview_hash: string; impact: Impact };

export function TruthCorrectionPanel({ taskId, projectId, promptId, onQueued }: {
  taskId: string; projectId: number; promptId: number; onQueued: (task: any) => void;
}) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<Facts>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<number>();
  const [preview, setPreview] = useState<{ result: Preview; values: Record<string, any> }>();
  const [confirmed, setConfirmed] = useState(false);
  const [saved, setSaved] = useState<Correction>();
  const [form] = Form.useForm();
  const alive = useRef(true);
  const identity = useRef(crypto.randomUUID());
  const base = `/api/v2/single-prompt/optimization-tasks/${encodeURIComponent(taskId)}`;
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  async function load() {
    setBusy(true); setError('');
    try {
      const result = await request<Facts>(`${base}/truths?project_id=${projectId}&prompt_id=${promptId}`);
      if (alive.current) setData(result);
    } catch (e) { if (alive.current) setError((e as Error).message); }
    finally { if (alive.current) setBusy(false); }
  }
  function choose(id: number) {
    const item = data?.truths.find(t => t.frozen.truth_id === id);
    if (!item?.can_correct || !item.current) return;
    setSelected(id); setPreview(undefined); setConfirmed(false); setSaved(undefined);
    identity.current = crypto.randomUUID();
    form.setFieldsValue({ capability_label: item.current.capability_label, product_truth_status: item.current.product_truth_status,
      source_reference: item.current.source_reference, reason: '' });
  }
  async function inspect(values: Record<string, any>) {
    const item = data?.truths.find(t => t.frozen.truth_id === selected);
    if (!item?.can_correct) return;
    setBusy(true); setError(''); setPreview(undefined); setConfirmed(false);
    try {
      const input = { ...values, source_reference: values.source_reference || '', project_id: projectId, prompt_id: promptId,
        truth_id: selected, base_hash: item.base_hash, expected_set_hash: data!.current_set_hash };
      const result = await request<Preview>(`${base}/truth-corrections/preview`, { method: 'POST', body: JSON.stringify(input) });
      if (alive.current) setPreview({ result, values: input });
    } catch (e) { if (alive.current) setError((e as Error).message); }
    finally { if (alive.current) setBusy(false); }
  }
  async function save() {
    if (!preview || !confirmed) return;
    setBusy(true); setError('');
    try {
      const result = await request<Correction>(`${base}/truth-corrections`, { method: 'POST', body: JSON.stringify({
        ...preview.values, preview_hash: preview.result.preview_hash, human_confirmed: true,
        idempotency_key: `truth-correction:${identity.current}` }) });
      if (alive.current) { setSaved(result); setPreview(undefined); setConfirmed(false); setSelected(undefined); }
      await load();
    } catch (e) { if (alive.current) setError((e as Error).message); }
    finally { if (alive.current) setBusy(false); }
  }
  async function reproject(correction: Correction) {
    setBusy(true); setError('');
    try {
      const task = await request<any>(`${base}/truth-reprojections`, { method: 'POST', body: JSON.stringify({
        project_id: projectId, prompt_id: promptId, correction_id: correction.correction_id,
        idempotency_key: `truth-reproject:${correction.correction_id}` }) });
      if (alive.current) { setOpen(false); onQueued(task); }
    } catch (e) { if (alive.current) setError((e as Error).message); }
    finally { if (alive.current) setBusy(false); }
  }
  const affected = (impact: Impact) => impact.affected_reason_ids.length > 0 || impact.affected_direction_ids.length > 0;
  const relatedHistory = data?.history.filter(c => c.impact.parent_task_id === taskId) || [];
  return <>
    <Button icon={<Pencil size={16} />} onClick={() => { setOpen(true); void load(); }}>纠正品牌事实</Button>
    <Modal open={open} title="品牌事实纠错" footer={null} width={680} onCancel={() => setOpen(false)} destroyOnHidden>
      {error && <Alert type="error" showIcon message="纠错操作未完成" description={error} />}
      {busy && !data ? <Spin><div style={{ minHeight: 100 }} /></Spin> : data && <Space direction="vertical" style={{ width: '100%' }}>
        {data.truths.length === 0 ? <Empty description="本任务没有冻结的品牌事实。可在品牌资料中补充资料，现有稿件仍可查看。" /> : <>
          <Select aria-label="选择待纠正事实" value={selected} placeholder="选择待纠正事实" style={{ width: '100%' }} disabled={busy}
            onChange={choose} options={data.truths.map(t => ({ value: t.frozen.truth_id, disabled: !t.can_correct,
              label: `${t.frozen.capability_label} · ${labels[t.frozen.product_truth_status]}${t.can_correct ? '' : '（已有后续版本）'}` }))} />
          {selected && <Form form={form} layout="vertical" onFinish={inspect} disabled={busy} onValuesChange={() => { setPreview(undefined); setConfirmed(false); }}>
            <Form.Item name="capability_label" label="单项事实及适用条件" rules={[{ required: true, whitespace: true }]}><Input maxLength={160} /></Form.Item>
            <Form.Item name="product_truth_status" label="人工判断" rules={[{ required: true }]}><select className="release-intent-select">
              {Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select></Form.Item>
            <Form.Item name="source_reference" label="事实出处"><Input.TextArea rows={2} maxLength={2000} /></Form.Item>
            <Form.Item name="reason" label="纠错原因与依据" rules={[{ required: true, whitespace: true }]}><Input.TextArea rows={3} maxLength={2000} /></Form.Item>
            <Button htmlType="submit" loading={busy} icon={<Search size={16} />}>预览影响范围</Button>
          </Form>}
        </>}
        {preview && <>
          <Descriptions size="small" column={1}>
            <Descriptions.Item label="受影响理由">{preview.result.impact.affected_reason_ids.length}</Descriptions.Item>
            <Descriptions.Item label="受影响方向">{preview.result.impact.affected_direction_ids.length}</Descriptions.Item>
            <Descriptions.Item label="保持不变的方向">{preview.result.impact.unaffected_direction_ids.length}</Descriptions.Item>
          </Descriptions>
          <Checkbox checked={confirmed} disabled={busy} onChange={e => setConfirmed(e.target.checked)}>我已核对事实与依据，确认保存独立纠错版本</Checkbox>
          <Button type="primary" loading={busy} disabled={!confirmed} onClick={() => void save()}>保存事实纠错</Button>
        </>}
        {saved && <Alert type="success" showIcon message={`事实纠错第 ${saved.version_number} 版已保存；原稿和原判断保持不变`} />}
        {relatedHistory.length > 0 && <Collapse items={relatedHistory.map(c => ({ key: c.correction_id,
          label: `纠错 ${c.version_number} · ${c.output.capability_label} · ${labels[c.output.product_truth_status]}`,
          children: <Space direction="vertical" style={{ width: '100%' }}>
            <Typography.Paragraph>原判断：{labels[c.base.product_truth_status]}；纠正后：{labels[c.output.product_truth_status]}</Typography.Paragraph>
            <Typography.Paragraph style={{ overflowWrap: 'anywhere' }}>依据：{c.output.note}</Typography.Paragraph>
            <Typography.Paragraph style={{ overflowWrap: 'anywhere' }}>出处：{c.output.source_reference || '尚无可确认出处'}</Typography.Paragraph>
            <Typography.Text type="secondary">保存时间：{c.created_at}</Typography.Text>
            <Typography.Text type="secondary">操作者：{c.actor}；受影响方向 {c.impact.affected_direction_ids.length} 个，未受影响 {c.impact.unaffected_direction_ids.length} 个</Typography.Text>
            {affected(c.impact) ? <Button icon={<Play size={16} />} loading={busy} onClick={() => void reproject(c)}>更新受影响内容</Button>
              : <Typography.Text>本次未影响该任务的理由或方向，无需重算。</Typography.Text>}
          </Space> }))} />}
      </Space>}
    </Modal>
  </>;
}
