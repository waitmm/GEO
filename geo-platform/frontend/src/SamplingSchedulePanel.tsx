import { useEffect, useState } from "react";
import { Alert, Button, Form, Input, InputNumber, Popconfirm, Space, Table, Typography } from "antd";
import { CalendarClock, Pause } from "lucide-react";
import { request } from "./api/client";

const labels: Record<string, string> = { ACTIVE: "已开启", PAUSED: "已暂停", BLOCKED: "需恢复", EXHAUSTED: "次数已用完" };

export function SamplingSchedulePanel({ projectId, promptId }: { projectId: number; promptId: number }) {
  const [rows, setRows] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const base = `/api/v2/projects/${projectId}/prompts/${promptId}/sampling-schedules`;
  useEffect(() => {
    const c = new AbortController(); setBusy(true);
    request<any[]>(base, { signal: c.signal }).then(setRows).catch(e => { if (!c.signal.aborted) setError(e.message); }).finally(() => { if (!c.signal.aborted) setBusy(false); });
    return () => c.abort();
  }, [base, reload]);
  async function post(path: string, value: unknown) {
    setBusy(true); setError("");
    try { await request(base + path, { method: "POST", body: JSON.stringify(value) }); setReload(n => n + 1); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <section>
    <Typography.Title level={4}>每日采样计划</Typography.Title>
    {error && <Alert type="error" message={error} />}
    <Table rowKey="schedule_id" dataSource={rows} pagination={false} scroll={{ x: 680 }} columns={[
      { title: "状态", render: (_, r) => labels[r.status] || r.status },
      { title: "执行时间", render: (_, r) => `${r.local_time} · ${r.timezone}` },
      { title: "下一次", render: (_, r) => r.status === "ACTIVE" ? new Date(r.next_due_at).toLocaleString() : "已停止" },
      { title: "剩余尝试", dataIndex: "remaining_attempts" },
      { title: "情况", dataIndex: "pause_reason" },
      { title: "操作", render: (_, r) => r.status === "ACTIVE" && <Popconfirm title="暂停后不再启动新采样，已经运行的会话将保留结果。" onConfirm={() => post(`/${r.schedule_id}/pause`, { expected_revision: r.revision })}><Button icon={<Pause size={14} />}>暂停</Button></Popconfirm> },
    ]} />
    <Form layout="vertical" initialValues={{ timezone_name: "Asia/Shanghai", local_time: "09:00", sample_count: 1, max_attempts: 7 }} onFinish={v => post("", v)} style={{ marginTop: 16 }}>
      <Space wrap align="start">
        <Form.Item label="时区" name="timezone_name" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item label="每日时间" name="local_time" rules={[{ required: true }]}><Input type="time" /></Form.Item>
        <Form.Item label="每次独立会话数" name="sample_count" rules={[{ required: true }]}><InputNumber min={1} max={10} /></Form.Item>
        <Form.Item label="授权总尝试上限" name="max_attempts" rules={[{ required: true }]}><InputNumber min={1} max={300} /></Form.Item>
      </Space>
      <Form.Item label="采样授权说明" name="authorization_note" rules={[{ required: true, whitespace: true }]}><Input maxLength={1000} /></Form.Item>
      <Button htmlType="submit" type="primary" loading={busy} disabled={rows.some(r => r.status === "ACTIVE")} icon={<CalendarClock size={16} />}>授权并开启每日采样</Button>
    </Form>
  </section>;
}
