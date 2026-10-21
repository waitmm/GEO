import { useEffect, useState } from "react";
import { Alert, Button, Collapse, Form, Input, InputNumber, Popconfirm, Select, Space, Table, Tag, Typography } from "antd";
import { CalendarClock, Pause, Play, RefreshCw } from "lucide-react";
import { api, request } from "./api/client";
import type { PromptVersion } from "./types";

const labels: Record<string, string> = { ACTIVE: "运行中", PAUSED: "已暂停", BLOCKED: "需恢复", EXHAUSTED: "次数已用完", SUPERSEDED: "已替换" };
const executionLabels: Record<string, string> = { SUCCESS: "成功", PARTIAL: "部分成功", FAILED: "失败", BLOCKED: "受阻", CANCELLED: "已取消", MISSED: "设备离线，已跳过", QUEUED: "排队中", RUNNING: "采集中" };

export function SamplingSchedulePanel({ projectId, promptId }: { projectId: number; promptId: number }) {
  const [rows, setRows] = useState<any[]>([]);
  const [executions, setExecutions] = useState<Record<string, any[]>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [versions, setVersions] = useState<PromptVersion[]>([]);
  const [selected, setSelected] = useState<PromptVersion | null>(null);
  const [form] = Form.useForm();
  const cadence = Form.useWatch("cadence_type", form) || "DAILY";
  const base = `/api/v2/projects/${projectId}/prompts/${promptId}/sampling-schedules`;

  useEffect(() => {
    const controller = new AbortController(); setBusy(true); setError("");
    request<any[]>(base, { signal: controller.signal }).then(async data => {
      if (controller.signal.aborted) return;
      setRows(data);
      const history = await Promise.all(data.filter(row => row.automation_policy === "COLLECTION_ONLY")
        .map(async row => [row.schedule_id, await request<any[]>(`${base}/${row.schedule_id}/executions`, { signal: controller.signal })] as const));
      if (!controller.signal.aborted) setExecutions(Object.fromEntries(history));
    }).catch(e => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [base, reload]);

  useEffect(() => {
    let cancelled = false; setSelected(null);
    api.listPromptVersions(projectId, promptId).then(value => { if (!cancelled) setVersions(value); })
      .catch((e: Error) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [projectId, promptId]);

  async function chooseVersion(id: string) {
    setBusy(true); setError("");
    try { setSelected(await api.getPromptVersion(projectId, promptId, id)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function post(path: string, value: unknown) {
    setBusy(true); setError("");
    try { await request(base + path, { method: "POST", body: JSON.stringify(value) }); setReload(value => value + 1); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  const cadenceText = (row: any) => row.cadence?.type === "INTERVAL" ? `每 ${row.cadence.every_hours} 小时`
    : row.cadence?.type === "WEEKLY" ? `每周 ${["一", "二", "三", "四", "五", "六", "日"][row.cadence.weekday]} ${row.cadence.local_time}`
      : `每天 ${row.cadence?.local_time || row.local_time}`;

  return <section aria-label="定时采集管理">
    <Typography.Title level={4}>定时采集</Typography.Title>
    <Alert type="info" showIcon message="采集自动化，分析手动化"
      description="计划只积累真实回答、引用和运行状态，不自动分析、生成策略或写稿。设备离线期间错过的时段会记录并跳过，不批量补采。" />
    {error && <Alert style={{ marginTop: 12 }} type="error" showIcon message={error} />}
    <Table style={{ marginTop: 16 }} rowKey="schedule_id" dataSource={rows} loading={busy} pagination={false} scroll={{ x: 980 }} columns={[
      { title: "状态", render: (_, row) => <><Tag color={row.status === "ACTIVE" ? "green" : row.status === "BLOCKED" ? "red" : "default"}>{labels[row.status] || row.status}</Tag>{!row.external_collection_authorized && row.automation_policy === "COLLECTION_ONLY" && <Tag color="orange">待外部采样授权</Tag>}</> },
      { title: "频率", render: (_, row) => cadenceText(row) },
      { title: "下一次", render: (_, row) => row.status === "ACTIVE" ? new Date(row.next_due_at).toLocaleString() : "—" },
      { title: "剩余次数", dataIndex: "remaining_attempts" },
      { title: "最近执行", render: (_, row) => row.last_execution ? `${executionLabels[row.last_execution.status] || row.last_execution.status} · ${new Date(row.last_execution.due_at).toLocaleString()}` : "尚未执行" },
      { title: "成功率", render: (_, row) => row.execution_summary?.success_rate == null ? "暂无" : `${(row.execution_summary.success_rate * 100).toFixed(0)}%` },
      { title: "说明", dataIndex: "pause_reason" },
      { title: "操作", render: (_, row) => <Space wrap>
        {row.status === "ACTIVE" ? <>
          <Button disabled={busy || !row.external_collection_authorized} icon={<Play size={14} />} onClick={() => post(`/${row.schedule_id}/run-now`, { expected_revision: row.revision, idempotency_key: `manual-${Date.now()}` })}>立即采集</Button>
          <Popconfirm title="暂停后不会启动新的采集，正在执行的任务保留真实结果。" onConfirm={() => post(`/${row.schedule_id}/pause`, { expected_revision: row.revision })}><Button disabled={busy} icon={<Pause size={14} />}>暂停</Button></Popconfirm>
        </> : row.status === "PAUSED" && <Button disabled={busy || !row.external_collection_authorized} icon={<Play size={14} />} onClick={() => post(`/${row.schedule_id}/resume`, { expected_revision: row.revision })}>恢复</Button>}
      </Space> },
    ]} />
    {!!rows.length && <Collapse style={{ marginTop: 12 }} items={rows.filter(row => row.automation_policy === "COLLECTION_ONLY").map(row => ({
      key: row.schedule_id, label: `执行记录 · ${cadenceText(row)}`,
      children: <Table size="small" rowKey="execution_id" pagination={false} dataSource={executions[row.schedule_id] || []} columns={[
        { title: "时间", render: (_, item) => new Date(item.due_at).toLocaleString() },
        { title: "触发", render: (_, item) => item.trigger_type === "MANUAL" ? "手动" : "计划" },
        { title: "状态", render: (_, item) => executionLabels[item.status] || item.status },
        { title: "成功 / 部分 / 失败", render: (_, item) => `${item.success_count} / ${item.partial_count} / ${item.failure_count}` },
        { title: "原因", render: (_, item) => Object.values(item.error_summary || {}).map((value: any) => value.message || value.reason || value.type).filter(Boolean).join("；") || "—" },
      ]} />
    }))} />}

    <Typography.Title level={5} style={{ marginTop: 24 }}>新建采集计划</Typography.Title>
    <Form form={form} layout="vertical" initialValues={{ timezone_name: "Asia/Shanghai", local_time: "09:00", cadence_type: "DAILY", weekday: 0, interval_hours: 6, sample_count: 3, max_attempts: 90 }}
      onFinish={value => {
        if (!selected) { setError("请选择明确的 Prompt 冻结版本。"); return; }
        return post("", { ...value, collection_only: true, optimization: null,
          prompt_version_id: selected.prompt_version_id, snapshot_hash: selected.snapshot_hash });
      }}>
      <Form.Item label="绑定 Prompt 冻结版本" required><Select aria-label="采集计划绑定的 Prompt 冻结版本" value={selected?.prompt_version_id} placeholder="选择当前有效版本"
        onChange={value => void chooseVersion(value)} options={versions.filter(item => item.status === "EFFECTIVE").map(item => ({ value: item.prompt_version_id, label: `V${item.version_number} · ${item.snapshot_hash.slice(0, 12)}` }))} /></Form.Item>
      <Space wrap align="start">
        <Form.Item label="采集频率" name="cadence_type" rules={[{ required: true }]}><Select style={{ width: 150 }} options={[{ value: "DAILY", label: "每天" }, { value: "WEEKLY", label: "每周" }, { value: "INTERVAL", label: "固定间隔" }]} /></Form.Item>
        {cadence !== "INTERVAL" && <Form.Item label="执行时间" name="local_time" rules={[{ required: true }]}><Input type="time" /></Form.Item>}
        {cadence === "WEEKLY" && <Form.Item label="星期" name="weekday" rules={[{ required: true }]}><Select style={{ width: 120 }} options={["一", "二", "三", "四", "五", "六", "日"].map((label, index) => ({ value: index, label: `周${label}` }))} /></Form.Item>}
        {cadence === "INTERVAL" && <Form.Item label="每隔几小时" name="interval_hours" rules={[{ required: true }]}><InputNumber min={1} max={168} /></Form.Item>}
        <Form.Item label="时区" name="timezone_name" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item label="每次采样数" name="sample_count" rules={[{ required: true }]}><InputNumber min={1} max={10} /></Form.Item>
        <Form.Item label="累计授权次数" name="max_attempts" rules={[{ required: true }]}><InputNumber min={1} max={300} /></Form.Item>
      </Space>
      <Form.Item label="采样授权说明" name="authorization_note" rules={[{ required: true, whitespace: true }]}><Input maxLength={1000} placeholder="记录本计划的用途和授权范围" /></Form.Item>
      <Space><Button htmlType="submit" type="primary" loading={busy} disabled={!selected || rows.some(row => row.status === "ACTIVE")} icon={<CalendarClock size={16} />}>保存采集计划</Button><Button icon={<RefreshCw size={16} />} onClick={() => setReload(value => value + 1)}>刷新状态</Button></Space>
    </Form>
  </section>;
}
