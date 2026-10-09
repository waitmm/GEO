import { useEffect, useState } from "react";
import { Alert, Button, Checkbox, Collapse, Form, Input, InputNumber, Popconfirm, Space, Table, Typography } from "antd";
import { CalendarClock, Pause } from "lucide-react";
import { request } from "./api/client";
import { BrandContextSelect } from "./BrandContextSelect";

const labels: Record<string, string> = { ACTIVE: "已开启", PAUSED: "已暂停", BLOCKED: "需恢复", EXHAUSTED: "次数已用完" };

export function SamplingSchedulePanel({ projectId, promptId }: { projectId: number; promptId: number }) {
  const [rows, setRows] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [form] = Form.useForm();
  const optimizeEnabled = Form.useWatch("optimize_enabled", form);
  const tasks = Form.useWatch(["optimization", "max_tasks"], form) || 0;
  const perCost = Form.useWatch(["optimization", "authorization", "max_cost_cny"], form) || 0;
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
      { title: "自动优化", render: (_, r) => !r.plan.optimization ? "未开启" : <>
        <div>每 {r.plan.optimization.every_batches} 批 · 最多 {r.plan.optimization.max_tasks} 次 · 总预算 ¥{r.plan.optimization.total_authorization.max_cost_cny}</div>
        <div>{r.optimization.status === "BLOCKED" ? r.optimization.last_error : r.optimization.status === "EXHAUSTED" ? "优化任务额度用完" : "按固定配置交接"}</div>
        {(r.optimization.batches || []).filter((b: any) => b.task_id).map((b: any) => <div key={b.analysis_id}><a href={`/?release_view=coreV2&v2_project=${projectId}&v2_prompt=${promptId}&v2_analysis=${b.analysis_id}`}>查看本批优化任务</a></div>)}
      </> },
      { title: "操作", render: (_, r) => r.status === "ACTIVE" && <Popconfirm title="暂停新采样和排队的自动优化；已开始的任务保留结果，可在任务页单独停止。" okText="确认暂停" cancelText="保留计划" onConfirm={() => post(`/${r.schedule_id}/pause`, { expected_revision: r.revision })}><Button disabled={busy} icon={<Pause size={14} />}>暂停</Button></Popconfirm> },
    ]} />
    <Form form={form} layout="vertical" initialValues={{ timezone_name: "Asia/Shanghai", local_time: "09:00", sample_count: 1, max_attempts: 7,
      optimize_enabled: false, optimization: { every_batches: 1, max_tasks: 1 } }} onFinish={({ optimize_enabled, optimization, ...v }) => post("", { ...v, optimization: optimize_enabled ? optimization : null })} style={{ marginTop: 16 }}>
      <Space wrap align="start">
        <Form.Item label="时区" name="timezone_name" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item label="每日时间" name="local_time" rules={[{ required: true }]}><Input type="time" /></Form.Item>
        <Form.Item label="每次独立会话数" name="sample_count" rules={[{ required: true }]}><InputNumber min={1} max={10} /></Form.Item>
        <Form.Item label="授权总尝试上限" name="max_attempts" rules={[{ required: true }]}><InputNumber min={1} max={300} /></Form.Item>
      </Space>
      <Form.Item label="采样授权说明" name="authorization_note" rules={[{ required: true, whitespace: true }]}><Input maxLength={1000} /></Form.Item>
      <Form.Item name="optimize_enabled" valuePropName="checked"><Checkbox>采样完成后自动生成优化建议与稿件</Checkbox></Form.Item>
      {optimizeEnabled && <section aria-label="计划自动优化授权">
        <Alert type="warning" showIcon message={`整份计划模型预算上限 ¥${(tasks * perCost).toFixed(2)}；失败计入，自动重试为 0。`} description="品牌、事实、问题或模型配置变化后停止自动交接；价格依据过期时保留采样，优化等待处理。" />
        <Space wrap align="start" style={{ marginTop: 16 }}>
          <Form.Item label="每几批采样触发优化" name={["optimization", "every_batches"]} rules={[{ required: true }]}><InputNumber min={1} max={30} precision={0} /></Form.Item>
          <Form.Item label="最多自动优化任务数" name={["optimization", "max_tasks"]} rules={[{ required: true }]}><InputNumber min={1} max={30} precision={0} /></Form.Item>
        </Space>
        <Form.Item name={["optimization", "brand_context_version_id"]}><BrandContextSelect projectId={projectId} onChange={v => form.setFieldValue(["optimization", "brand_context_version_id"], v)} /></Form.Item>
        <Form.Item name={["optimization", "source_fetch_authorized"]} valuePropName="checked"><Checkbox>允许获取各批实际引用正文，每个 URL 最多 2 次，不扩站</Checkbox></Form.Item>
        <Space wrap align="start">
          <Form.Item label="每任务模型请求上限" name={["optimization", "authorization", "max_requests"]} rules={[{ required: true }]}><InputNumber min={1} max={1000} precision={0} /></Form.Item>
          <Form.Item label="每任务 token 上限" name={["optimization", "authorization", "max_tokens"]} rules={[{ required: true }]}><InputNumber min={1} max={10000000} precision={0} /></Form.Item>
          <Form.Item label="每任务费用上限（元）" name={["optimization", "authorization", "max_cost_cny"]} rules={[{ required: true }]}><InputNumber min={0.01} max={1000} precision={2} /></Form.Item>
        </Space>
        <Collapse defaultActiveKey={["pricing"]} items={[{ key: "pricing", label: "模型计费与授权记录（必填）", forceRender: true, children: <>
          <Form.Item label="输入/输出较高单价（元/百万token）" name={["optimization", "authorization", "conservative_cny_per_million_tokens"]} rules={[{ required: true }]}><InputNumber min={0.01} max={1000} /></Form.Item>
          <Form.Item label="已核实计费依据" name={["optimization", "authorization", "pricing_source"]} rules={[{ required: true, min: 8 }]}><Input maxLength={2000} /></Form.Item>
          <Form.Item label="计费核实日期" name={["optimization", "authorization", "pricing_checked_at"]} rules={[{ required: true }]}><Input type="date" /></Form.Item>
          <Form.Item label="授权人" name={["optimization", "authorization", "authorized_by"]} rules={[{ required: true, whitespace: true }]}><Input maxLength={240} /></Form.Item>
        </> }]} />
      </section>}
      <Button htmlType="submit" type="primary" loading={busy} disabled={rows.some(r => r.status === "ACTIVE")} icon={<CalendarClock size={16} />}>授权并开启每日采样</Button>
    </Form>
  </section>;
}
