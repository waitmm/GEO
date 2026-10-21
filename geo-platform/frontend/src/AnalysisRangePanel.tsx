import { useState } from "react";
import { Alert, Button, Checkbox, Form, Input, Select, Space, Table, Typography } from "antd";
import { CalendarRange, LockKeyhole } from "lucide-react";
import { request } from "./api/client";

export function AnalysisRangePanel({ projectId, promptId }: { projectId: number; promptId: number }) {
  const [form] = Form.useForm();
  const mode = Form.useWatch("mode", form) || "LAST_7_DAYS";
  const [preview, setPreview] = useState<any>();
  const [groupHash, setGroupHash] = useState("");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const base = `/api/v2/projects/${projectId}/prompts/${promptId}/analysis-ranges`;

  async function loadPreview(values: any) {
    setBusy(true); setError(""); setPreview(undefined); setGroupHash(""); setSelectedIds([]);
    try {
      const payload: any = { mode: values.mode, run_ids: [] };
      if (values.mode === "CUSTOM") {
        payload.start_at = new Date(values.start_at).toISOString(); payload.end_at = new Date(values.end_at).toISOString();
      } else if (values.mode === "RUN_IDS") {
        payload.run_ids = String(values.run_ids_text || "").split(/[，,\s]+/).filter(Boolean).map(Number);
        if (payload.run_ids.some((value: number) => !Number.isInteger(value) || value <= 0)) throw new Error("Run IDs 必须是正整数");
      }
      const value = await request<any>(base + "/preview", { method: "POST", body: JSON.stringify(payload) });
      setPreview(value);
      const first = value.groups.find((item: any) => item.prompt_version?.binding_status === "BOUND" && item.selected_run_ids.length);
      if (first) { setGroupHash(first.group_hash); setSelectedIds(first.selected_run_ids); }
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function freeze() {
    const group = preview?.groups.find((item: any) => item.group_hash === groupHash);
    if (!group || !selectedIds.length) return;
    setBusy(true); setError("");
    try {
      const result = await request<any>(base + "/freeze", { method: "POST", body: JSON.stringify({
        selector: preview.selector, preview_hash: preview.preview_hash, group_hash: groupHash, selected_run_ids: selectedIds,
      }) });
      const params = new URLSearchParams({ release_view: "coreV2", v2_project: String(projectId), v2_prompt: String(promptId), v2_analysis: result.analysis.analysis_id });
      window.location.assign(`/?${params}`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return <section aria-label="按时间范围选择分析数据">
    <Typography.Title level={4}>选择 GEO 分析范围</Typography.Title>
    <Alert type="info" showIcon message="先预览，再冻结"
      description="时间范围只用于找到候选采样。提交时服务端会再次校验并冻结明确 Run IDs、原始哈希和 Prompt 版本；以后新增采样不会改变这份分析。" />
    {error && <Alert style={{ marginTop: 12 }} type="error" showIcon message={error} />}
    <Form form={form} layout="vertical" initialValues={{ mode: "LAST_7_DAYS" }} onFinish={loadPreview} style={{ marginTop: 16 }}>
      <Space wrap align="start">
        <Form.Item label="分析时间范围" name="mode" rules={[{ required: true }]}><Select style={{ width: 190 }} options={[
          { value: "LAST_7_DAYS", label: "最近 7 天" }, { value: "LAST_14_DAYS", label: "最近 14 天" },
          { value: "LAST_30_DAYS", label: "最近 30 天" }, { value: "CUSTOM", label: "自定义日期" }, { value: "RUN_IDS", label: "指定 Run" },
        ]} /></Form.Item>
        {mode === "CUSTOM" && <><Form.Item label="开始" name="start_at" rules={[{ required: true }]}><Input type="datetime-local" /></Form.Item><Form.Item label="结束" name="end_at" rules={[{ required: true }]}><Input type="datetime-local" /></Form.Item></>}
      </Space>
      {mode === "RUN_IDS" && <Form.Item label="Run IDs" name="run_ids_text" rules={[{ required: true, whitespace: true }]} extra="使用逗号或空格分隔"><Input placeholder="例如：101, 102, 108" /></Form.Item>}
      <Button htmlType="submit" loading={busy} icon={<CalendarRange size={16} />}>预览范围</Button>
    </Form>

    {preview && <section style={{ marginTop: 20 }}>
      <Alert type={preview.mixed_groups ? "warning" : "success"} showIcon
        message={`找到 ${preview.total_count} 条采样，其中 ${preview.valid_count} 条可分析、${preview.invalid_count} 条失败或无正文`}
        description={preview.mixed_groups ? "范围含多个 Prompt 版本、平台或采集配置，请选择一个兼容分组，不会静默混合。" : "失败采样保留在监控记录中，但不会当作品牌未提及或零引用。"} />
      <Table style={{ marginTop: 12 }} size="small" rowKey="group_hash" pagination={false} scroll={{ x: 780 }} dataSource={preview.groups} rowSelection={{
        type: "radio", selectedRowKeys: groupHash ? [groupHash] : [],
        getCheckboxProps: (row: any) => ({ disabled: row.prompt_version?.binding_status !== "BOUND" || !row.selected_run_ids.length }),
        onChange: keys => { const hash = String(keys[0] || ""); setGroupHash(hash); const group = preview.groups.find((item: any) => item.group_hash === hash); setSelectedIds(group?.selected_run_ids || []); },
      }} columns={[
        { title: "平台 / 采集方式", render: (_, row: any) => <>{row.identity.platform} / {row.identity.adapter === "manual_import" ? "人工导入" : row.identity.adapter}{row.identity.source_assertion_status && <><br /><Typography.Text type="warning">人工声明，平台未独立核实</Typography.Text></>}</> },
        { title: "Prompt 版本", render: (_, row: any) => row.prompt_version?.binding_status === "BOUND" ? row.prompt_version.prompt_version_id : `不可证明：${row.prompt_version?.reason || row.identity.binding_reason || "历史未绑定"}` },
        { title: "Run", render: (_, row: any) => `${row.selected_run_ids.length} 可分析 / ${row.run_ids.length} 总数` },
        { title: "状态", render: (_, row: any) => Object.entries(row.status_counts).map(([key, value]) => `${key} ${value}`).join("；") },
      ]} />
      {groupHash && <section style={{ marginTop: 12 }}>
        <Typography.Text strong>本次进入分析的 Run</Typography.Text>
        <Checkbox.Group style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }} value={selectedIds} onChange={values => setSelectedIds(values.map(Number))}
          options={(preview.groups.find((item: any) => item.group_hash === groupHash)?.selected_run_ids || []).map((id: number) => ({ label: `Run ${id}`, value: id }))} />
      </section>}
      <Button style={{ marginTop: 16 }} type="primary" loading={busy} disabled={!groupHash || !selectedIds.length} icon={<LockKeyhole size={16} />} onClick={freeze}>冻结这 {selectedIds.length} 条 Run 并进入分析</Button>
    </section>}
  </section>;
}
